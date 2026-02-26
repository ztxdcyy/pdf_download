from __future__ import annotations

import threading
import time
from typing import Any
from urllib.parse import quote

import requests

S2_BASE = "https://api.semanticscholar.org/graph/v1"
CONFERENCE_HINTS = (
    "conference",
    "proceedings",
    "symposium",
    "workshop",
    "cvpr",
    "iccv",
    "eccv",
    "neurips",
    "nips",
    "icml",
    "iclr",
    "aaai",
    "ijcai",
    "acl",
    "emnlp",
    "naacl",
    "coling",
    "kdd",
    "siggraph",
)
JOURNAL_HINTS = ("journal", "transactions", "letters", "review")
MIN_REQUEST_INTERVAL_SECONDS = 1.05

_rate_lock = threading.Lock()
_last_request_at = 0.0

FIELDS = ",".join(
    [
        "paperId",
        "title",
        "abstract",
        "authors",
        "year",
        "venue",
        "publicationTypes",
        "citationCount",
        "openAccessPdf",
        "externalIds",
        "url",
    ]
)


class SemanticScholarRateLimitError(RuntimeError):
    """Raised when Semantic Scholar returns 429."""


def _respect_rate_limit() -> None:
    global _last_request_at
    with _rate_lock:
        now = time.monotonic()
        wait = MIN_REQUEST_INTERVAL_SECONDS - (now - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.monotonic()


def _s2_get(client: Any, url: str, **kwargs: Any) -> requests.Response:
    _respect_rate_limit()
    response = client.get(url, **kwargs)
    if response.status_code == 429:
        raise SemanticScholarRateLimitError("Semantic Scholar rate limited (429).")
    return response


def _map_s2_publication_types_to_gbt_tag(
    publication_types: Any,
    *,
    title: str = "",
    venue: str = "",
    doi: str | None = None,
    external_ids: dict[str, Any] | None = None,
) -> str:
    if not isinstance(publication_types, list):
        normalized: set[str] = set()
    else:
        normalized = {str(item or "").strip().lower() for item in publication_types}
    if "journalarticle" in normalized or "review" in normalized:
        return "J"
    if "conference" in normalized:
        return "C"
    if "book" in normalized:
        return "M"
    if "bookchapter" in normalized:
        return "A"
    if "thesis" in normalized:
        return "D"
    if "report" in normalized:
        return "R"
    if "preprint" in normalized:
        return "EB/OL"

    venue_l = venue.lower()
    title_l = title.lower()
    doi_l = str(doi or "").lower()
    external = external_ids or {}
    if "arxiv" in venue_l or "arxiv" in title_l or "arxiv" in doi_l or "ArXiv" in external:
        return "EB/OL"
    if any(hint in venue_l for hint in CONFERENCE_HINTS):
        return "C"
    if any(hint in title_l for hint in CONFERENCE_HINTS):
        return "C"
    if any(hint in doi_l for hint in CONFERENCE_HINTS):
        return "C"
    if any(hint in venue_l for hint in JOURNAL_HINTS):
        return "J"
    return "Z"


def _to_common_paper(item: dict[str, Any]) -> dict[str, Any]:
    publication_types = item.get("publicationTypes")
    external_ids = item.get("externalIds") if isinstance(item.get("externalIds"), dict) else {}
    doi = None
    if isinstance(external_ids, dict):
        doi = str(external_ids.get("DOI") or external_ids.get("doi") or "").strip() or None
    pdf_urls: list[str] = []
    seen: set[str] = set()

    def add_pdf_url(value: Any) -> None:
        url = str(value or "").strip()
        if not url or not url.startswith("http"):
            return
        lowered = url.lower()
        if lowered in seen:
            return
        seen.add(lowered)
        pdf_urls.append(url)

    open_access_pdf = item.get("openAccessPdf")
    if isinstance(open_access_pdf, dict):
        add_pdf_url(open_access_pdf.get("url"))

    arxiv_id = ""
    if isinstance(external_ids, dict):
        arxiv_id = str(external_ids.get("ArXiv") or external_ids.get("arXiv") or "").strip()
    if arxiv_id:
        add_pdf_url(f"https://arxiv.org/pdf/{arxiv_id}.pdf")

    mapped = dict(item)
    mapped["documentType"] = _map_s2_publication_types_to_gbt_tag(
        publication_types,
        title=str(item.get("title") or ""),
        venue=str(item.get("venue") or ""),
        doi=doi,
        external_ids=external_ids,
    )
    mapped["pdfUrl"] = pdf_urls[0] if pdf_urls else None
    mapped["pdfUrls"] = pdf_urls
    mapped["publicationDate"] = str(item.get("publicationDate") or "").strip() or None
    mapped["publisher"] = None
    mapped["publisherPlace"] = None
    return mapped


def search_papers(
    keyword: str,
    limit: int = 25,
    api_key: str | None = None,
    session: requests.Session | None = None,
) -> list[dict[str, Any]]:
    client = session or requests
    headers = {"User-Agent": "paperfetch/0.1"}
    if api_key:
        headers["x-api-key"] = api_key

    response = _s2_get(
        client,
        f"{S2_BASE}/paper/search",
        params={"query": keyword, "limit": limit, "fields": FIELDS},
        headers=headers,
        timeout=30,
    )
    response.raise_for_status()
    data = response.json().get("data", [])
    if not isinstance(data, list):
        return []

    result: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        result.append(_to_common_paper(item))
    return result


def get_paper_by_doi(
    doi: str,
    api_key: str | None = None,
    session: requests.Session | None = None,
) -> dict[str, Any] | None:
    normalized = str(doi or "").strip()
    if not normalized:
        return None

    client = session or requests
    headers = {"User-Agent": "paperfetch/0.1"}
    if api_key:
        headers["x-api-key"] = api_key

    encoded = quote(f"DOI:{normalized}", safe="")
    response = _s2_get(
        client,
        f"{S2_BASE}/paper/{encoded}",
        params={"fields": FIELDS},
        headers=headers,
        timeout=30,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()

    payload = response.json()
    if not isinstance(payload, dict):
        return None
    return _to_common_paper(payload)
