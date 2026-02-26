from __future__ import annotations

from typing import Any

import requests

OPENALEX_BASE = "https://api.openalex.org/works"
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
JOURNAL_HINTS = (
    "journal",
    "transactions",
    "letters",
    "review",
)


def _normalize_arxiv_id(value: str) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = text.removeprefix("https://arxiv.org/abs/").removeprefix("http://arxiv.org/abs/")
    text = text.removeprefix("arXiv:").removeprefix("arxiv:")
    return text or None


def _extract_external_ids(work: dict[str, Any], doi: str | None) -> dict[str, str]:
    external_ids: dict[str, str] = {}
    if doi:
        external_ids["DOI"] = doi

    ids = work.get("ids") or {}
    arxiv_id = _normalize_arxiv_id(str((ids if isinstance(ids, dict) else {}).get("arxiv") or ""))
    if arxiv_id:
        external_ids["ArXiv"] = arxiv_id
    return external_ids


def _extract_pdf_urls(work: dict[str, Any], external_ids: dict[str, str]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    def add_url(value: Any) -> None:
        url = str(value or "").strip()
        if not url or not url.startswith("http"):
            return
        lowered = url.lower()
        if lowered in seen:
            return
        seen.add(lowered)
        urls.append(url)

    best_oa = work.get("best_oa_location")
    if isinstance(best_oa, dict):
        add_url(best_oa.get("pdf_url"))
        add_url(best_oa.get("landing_page_url"))

    primary_location = work.get("primary_location")
    if isinstance(primary_location, dict):
        add_url(primary_location.get("pdf_url"))
        add_url(primary_location.get("landing_page_url"))

    open_access = work.get("open_access")
    if isinstance(open_access, dict):
        add_url(open_access.get("oa_url"))

    locations = work.get("locations")
    if isinstance(locations, list):
        for location in locations:
            if not isinstance(location, dict):
                continue
            add_url(location.get("pdf_url"))
            add_url(location.get("landing_page_url"))

    arxiv_id = external_ids.get("ArXiv")
    if arxiv_id:
        add_url(f"https://arxiv.org/pdf/{arxiv_id}.pdf")

    return urls


def _extract_venue(work: dict[str, Any]) -> str:
    primary_location = work.get("primary_location") or {}
    source = primary_location.get("source") or {}
    display_name = str(source.get("display_name") or "").strip()
    if display_name:
        return display_name

    locations = work.get("locations") or []
    if isinstance(locations, list):
        for location in locations:
            if not isinstance(location, dict):
                continue
            source_item = location.get("source") or {}
            candidate = str((source_item if isinstance(source_item, dict) else {}).get("display_name") or "").strip()
            if candidate:
                return candidate

    host_venue = work.get("host_venue") or {}
    if isinstance(host_venue, dict):
        candidate = str(host_venue.get("display_name") or "").strip()
        if candidate:
            return candidate
    return ""


def _map_openalex_type_to_gbt_tag(
    work_type: str,
    *,
    venue: str = "",
    title: str = "",
    doi: str | None = None,
    external_ids: dict[str, str] | None = None,
) -> str:
    mapping = {
        "journal-article": "J",
        "proceedings-article": "C",
        "book": "M",
        "book-chapter": "A",
        "dissertation": "D",
        "report": "R",
        "dataset": "DB",
        "posted-content": "EB/OL",
        "reference-entry": "Z",
    }
    mapped = mapping.get(work_type)
    if mapped:
        return mapped

    external = external_ids or {}
    venue_l = venue.lower()
    title_l = title.lower()
    doi_l = str(doi or "").lower()
    if "ArXiv" in external or "arxiv" in venue_l or "arxiv" in title_l or "arxiv" in doi_l:
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


def _extract_authors(work: dict[str, Any]) -> list[dict[str, str]]:
    names: list[dict[str, str]] = []
    for authorship in work.get("authorships") or []:
        author = (authorship or {}).get("author") or {}
        name = str(author.get("display_name") or "").strip()
        if name:
            names.append({"name": name})
    return names


def _restore_openalex_abstract(work: dict[str, Any]) -> str:
    inverted = work.get("abstract_inverted_index")
    if not isinstance(inverted, dict):
        return ""

    positions: list[tuple[int, str]] = []
    for token, indexes in inverted.items():
        if not isinstance(token, str) or not isinstance(indexes, list):
            continue
        for index in indexes:
            if isinstance(index, int):
                positions.append((index, token))
    if not positions:
        return ""

    positions.sort(key=lambda item: item[0])
    return " ".join(token for _, token in positions).strip()


def _to_common_paper(work: dict[str, Any]) -> dict[str, Any]:
    doi_url = str(work.get("doi") or "").strip()
    doi = doi_url.removeprefix("https://doi.org/").removeprefix("http://doi.org/")
    doi = doi.strip() or None

    paper_url = str(work.get("id") or "").strip()
    work_type = str(work.get("type") or "").strip().lower()
    title = str(work.get("display_name") or "").strip()
    venue = _extract_venue(work)
    primary_location = work.get("primary_location") if isinstance(work.get("primary_location"), dict) else {}
    source_item = primary_location.get("source") if isinstance(primary_location.get("source"), dict) else {}
    publisher = str(source_item.get("host_organization_name") or "").strip() or None
    external_ids = _extract_external_ids(work, doi)
    pdf_urls = _extract_pdf_urls(work, external_ids)
    biblio = work.get("biblio") if isinstance(work.get("biblio"), dict) else {}
    volume = str((biblio or {}).get("volume") or "").strip()
    issue = str((biblio or {}).get("issue") or "").strip()
    first_page = str((biblio or {}).get("first_page") or "").strip()
    last_page = str((biblio or {}).get("last_page") or "").strip()
    pages = ""
    if first_page and last_page:
        pages = f"{first_page}-{last_page}"
    elif first_page:
        pages = first_page
    elif last_page:
        pages = last_page

    return {
        "paperId": paper_url or None,
        "title": title,
        "abstract": _restore_openalex_abstract(work),
        "authors": _extract_authors(work),
        "year": work.get("publication_year"),
        "publicationDate": str(work.get("publication_date") or "").strip() or None,
        "venue": venue,
        "publisher": publisher,
        "publisherPlace": None,
        "documentType": _map_openalex_type_to_gbt_tag(
            work_type,
            venue=venue,
            title=title,
            doi=doi,
            external_ids=external_ids,
        ),
        "rawType": work_type or None,
        "volume": volume or None,
        "issue": issue or None,
        "pages": pages or None,
        "citationCount": int(work.get("cited_by_count") or 0),
        "externalIds": external_ids,
        "pdfUrl": pdf_urls[0] if pdf_urls else None,
        "pdfUrls": pdf_urls,
        "url": paper_url,
    }


def search_papers(keyword: str, limit: int = 25, contact_email: str | None = None) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "search": keyword,
        "per-page": max(1, min(limit, 200)),
    }
    if contact_email:
        params["mailto"] = contact_email

    response = requests.get(OPENALEX_BASE, params=params, timeout=30)
    response.raise_for_status()

    works = response.json().get("results", [])
    if not isinstance(works, list):
        return []
    return [_to_common_paper(work) for work in works if isinstance(work, dict)]


def get_paper_by_doi(doi: str, contact_email: str | None = None) -> dict[str, Any] | None:
    normalized = str(doi or "").strip()
    if not normalized:
        return None

    candidate_filters = [
        f"doi:{normalized}",
        f"doi:https://doi.org/{normalized}",
    ]
    for filter_value in candidate_filters:
        params: dict[str, Any] = {"filter": filter_value, "per-page": 3}
        if contact_email:
            params["mailto"] = contact_email
        response = requests.get(OPENALEX_BASE, params=params, timeout=30)
        response.raise_for_status()
        works = response.json().get("results", [])
        if not isinstance(works, list):
            continue
        for work in works:
            if isinstance(work, dict):
                return _to_common_paper(work)
    return None
