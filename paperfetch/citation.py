from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from typing import Any

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
REFERENCE_INDEX_PATTERN = re.compile(r"^\[(\d+)\]\s+")


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _authors_text(paper: dict[str, Any]) -> str:
    authors = paper.get("authors") or []
    names = [str(author.get("name") or "").strip() for author in authors if author]
    names = [name for name in names if name]
    if not names:
        return "Unknown Author"
    if len(names) <= 3:
        return ", ".join(names)

    head = names[:3]
    if any(_contains_cjk(name) for name in head):
        return ", ".join(head) + ", 等"
    return ", ".join(head) + ", et al"


def _document_type(paper: dict[str, Any], doi: str | None = None) -> str:
    valid_types = {"J", "C", "M", "A", "D", "R", "N", "S", "P", "DB", "EB/OL", "Z"}
    value = str(paper.get("documentType") or "").strip().upper()
    if value in valid_types and value != "Z":
        return value

    venue = str(paper.get("venue") or "").lower()
    title = str(paper.get("title") or "").lower()
    external_ids = paper.get("externalIds") if isinstance(paper.get("externalIds"), dict) else {}
    doi_text = str(doi or "").lower()
    if not doi_text and isinstance(external_ids, dict):
        doi_text = str(external_ids.get("DOI") or external_ids.get("doi") or "").lower()

    if "ArXiv" in external_ids or "arxiv" in venue or "arxiv" in title or "arxiv" in doi_text:
        return "EB/OL"
    if any(hint in venue for hint in CONFERENCE_HINTS):
        return "C"
    if any(hint in title for hint in CONFERENCE_HINTS):
        return "C"
    if any(hint in doi_text for hint in CONFERENCE_HINTS):
        return "C"
    if any(hint in venue for hint in JOURNAL_HINTS):
        return "J"

    if value in valid_types:
        return value
    return "Z"


def _format_year(paper: dict[str, Any]) -> str:
    year = _clean_text(paper.get("year"))
    if year:
        return year
    publication_date = _clean_text(paper.get("publicationDate"))
    if publication_date:
        return publication_date.split("-", 1)[0]
    return "n.d."


def _format_date(value: Any) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    text = text.replace("/", "-")
    if re.fullmatch(r"\d{4}", text):
        return text
    if re.fullmatch(r"\d{4}-\d{2}", text):
        return text
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except ValueError:
        return None


def _journal_segment(paper: dict[str, Any], year: str) -> str:
    venue = _clean_text(paper.get("venue")) or "Unknown Journal"
    volume = _clean_text(paper.get("volume"))
    issue = _clean_text(paper.get("issue"))
    pages = _clean_text(paper.get("pages"))

    segment = f"{venue}, {year}"
    if volume:
        segment += f", {volume}"
    if issue:
        segment += f"({issue})" if volume else f", ({issue})"
    if pages:
        segment += f": {pages}"
    return segment


def _conference_segment(paper: dict[str, Any], year: str) -> str:
    venue = _clean_text(paper.get("venue")) or "Unknown Conference"
    pages = _clean_text(paper.get("pages"))
    segment = f"//{venue}, {year}"
    if pages:
        segment += f": {pages}"
    return segment


def _generic_segment(paper: dict[str, Any], year: str) -> str:
    venue = _clean_text(paper.get("venue")) or "Unknown Source"
    pages = _clean_text(paper.get("pages"))
    segment = f"{venue}, {year}"
    if pages:
        segment += f": {pages}"
    return segment


def _book_like_segment(paper: dict[str, Any], year: str) -> str:
    place = _clean_text(paper.get("publisherPlace")) or "[S.l.]"
    publisher = _clean_text(paper.get("publisher")) or _clean_text(paper.get("venue")) or "[s.n.]"
    segment = f"{place}: {publisher}, {year}"
    pages = _clean_text(paper.get("pages"))
    if pages:
        segment += f": {pages}"
    return segment


def _thesis_segment(paper: dict[str, Any], year: str) -> str:
    place = _clean_text(paper.get("publisherPlace")) or "[S.l.]"
    school = _clean_text(paper.get("publisher")) or _clean_text(paper.get("venue")) or "[s.n.]"
    return f"{place}: {school}, {year}"


def _news_segment(paper: dict[str, Any], year: str) -> str:
    venue = _clean_text(paper.get("venue")) or "Unknown Newspaper"
    publication_date = _format_date(paper.get("publicationDate")) or year
    return f"{venue}, {publication_date}"


def _web_segment(paper: dict[str, Any], year: str, doi: str | None) -> str:
    publication_date = _format_date(paper.get("publicationDate"))
    if not publication_date and year != "n.d.":
        publication_date = year
    reference_date = datetime.now().strftime("%Y-%m-%d")

    url = _clean_text(paper.get("url"))
    if not url and doi:
        url = f"https://doi.org/{doi}"
    if not url:
        external_ids = paper.get("externalIds") if isinstance(paper.get("externalIds"), dict) else {}
        arxiv_id = _clean_text((external_ids or {}).get("ArXiv"))
        if arxiv_id:
            url = f"https://arxiv.org/abs/{arxiv_id}"
    if not url:
        url = "N/A"

    date_part = ""
    if publication_date:
        date_part = f"({publication_date})"
    date_part += f"[{reference_date}]"
    segment = f"{date_part}. {url}"
    if doi:
        segment += f". DOI:{doi}"
    return segment


def _source_segment(paper: dict[str, Any], year: str, doc_type: str) -> str:
    if doc_type == "J":
        return _journal_segment(paper, year)
    if doc_type == "C":
        return _conference_segment(paper, year)
    if doc_type in {"M", "A", "R", "S", "P"}:
        return _book_like_segment(paper, year)
    if doc_type == "D":
        return _thesis_segment(paper, year)
    if doc_type == "N":
        return _news_segment(paper, year)
    return _generic_segment(paper, year)


def build_citation_text(
    paper: dict[str, Any],
    doi: str | None,
    keyword: str,
    search_provider: str,
    selected_by: str,
    llm_reason: str | None = None,
    llm_confidence: float | None = None,
    llm_proposed_titles: list[str] | None = None,
    matched_title: str | None = None,
    match_similarity: float | None = None,
    validation_score: float | None = None,
) -> str:
    del keyword, search_provider, selected_by
    del llm_reason, llm_confidence, llm_proposed_titles
    del matched_title, match_similarity, validation_score

    title = _clean_text(paper.get("title")) or "Unknown Title"
    year = _format_year(paper)
    authors = _authors_text(paper)
    doc_type = _document_type(paper, doi=doi)

    if doc_type == "EB/OL":
        source_info = _web_segment(paper, year, doi)
        return f"{authors}. {title}[{doc_type}]. {source_info}.\n"

    source_info = _source_segment(paper, year, doc_type)
    citation = f"{authors}. {title}[{doc_type}]. {source_info}."
    if doi:
        citation += f" DOI:{doi}."
    return citation + "\n"


def _daily_citation_path(output_dir: Path) -> Path:
    date_name = datetime.now().strftime("%Y-%m-%d")
    return output_dir / f"{date_name}.txt"


def _next_reference_index(citation_path: Path) -> int:
    if not citation_path.exists():
        return 1

    max_index = 0
    with citation_path.open("r", encoding="utf-8") as file_obj:
        for line in file_obj:
            match = REFERENCE_INDEX_PATTERN.match(line.strip())
            if not match:
                continue
            max_index = max(max_index, int(match.group(1)))
    return max_index + 1


def _with_reference_index(citation_text: str, index: int) -> str:
    text = citation_text.strip()
    if not text:
        return ""
    if REFERENCE_INDEX_PATTERN.match(text):
        return text + "\n"
    return f"[{index}] {text}\n"


def append_daily_citation(output_dir: Path, citation_text: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    citation_path = _daily_citation_path(output_dir)
    next_index = _next_reference_index(citation_path)
    numbered = _with_reference_index(citation_text, next_index)
    if not numbered:
        return citation_path

    needs_newline = False
    if citation_path.exists() and citation_path.stat().st_size > 0:
        with citation_path.open("rb") as file_obj:
            file_obj.seek(-1, 2)
            needs_newline = file_obj.read(1) != b"\n"

    with citation_path.open("a", encoding="utf-8") as file_obj:
        if needs_newline:
            file_obj.write("\n")
        file_obj.write(numbered)
    return citation_path
