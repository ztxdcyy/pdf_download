from __future__ import annotations

from datetime import datetime
from pathlib import Path
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


def _authors_text(paper: dict[str, Any]) -> str:
    authors = paper.get("authors") or []
    names = [str(author.get("name") or "").strip() for author in authors if author]
    names = [name for name in names if name]
    if not names:
        return "Unknown Author"
    if len(names) <= 3:
        return ", ".join(names)
    return ", ".join(names[:3]) + ", et al"


def _document_type(paper: dict[str, Any], doi: str | None = None) -> str:
    valid_types = {"J", "C", "M", "A", "D", "R", "DB", "EB/OL", "Z"}
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


def _journal_segment(paper: dict[str, Any], year: str) -> str:
    venue = str(paper.get("venue") or "Unknown Venue").strip()
    volume = str(paper.get("volume") or "").strip()
    issue = str(paper.get("issue") or "").strip()
    pages = str(paper.get("pages") or "").strip()

    segment = f"{venue}, {year}"
    if volume:
        segment += f", {volume}"
        if issue:
            segment += f"({issue})"
    if pages:
        segment += f": {pages}"
    return segment


def _conference_segment(paper: dict[str, Any], year: str) -> str:
    venue = str(paper.get("venue") or "Unknown Conference").strip()
    pages = str(paper.get("pages") or "").strip()
    segment = f"{venue}, {year}"
    if pages:
        segment += f": {pages}"
    return segment


def _generic_segment(paper: dict[str, Any], year: str) -> str:
    venue = str(paper.get("venue") or "Unknown Source").strip()
    pages = str(paper.get("pages") or "").strip()
    segment = f"{venue}, {year}"
    if pages:
        segment += f": {pages}"
    return segment


def _source_segment(paper: dict[str, Any], year: str, doc_type: str) -> str:
    if doc_type == "J":
        return _journal_segment(paper, year)
    if doc_type == "C":
        return _conference_segment(paper, year)
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
    title = str(paper.get("title") or "Unknown Title").strip()
    year = str(paper.get("year") or "n.d.")
    paper_url = str(paper.get("url") or "").strip()
    authors = _authors_text(paper)
    doc_type = _document_type(paper, doi=doi)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    source_info = _source_segment(paper, year, doc_type)
    citation = f"{authors}. {title}[{doc_type}]. {source_info}."
    if doi:
        citation += f" DOI:{doi}."

    lines = [
        citation,
        f"[meta] keyword={keyword} provider={search_provider} selected_by={selected_by} time={timestamp}",
        f"[meta] doi={doi or 'N/A'} url={paper_url or 'N/A'}",
        f"[meta] llm_confidence={llm_confidence if llm_confidence is not None else 'N/A'} "
        f"matched_title={matched_title or 'N/A'} similarity={match_similarity if match_similarity is not None else 'N/A'} "
        f"score={validation_score if validation_score is not None else 'N/A'}",
        f"[meta] llm_titles={' | '.join(llm_proposed_titles) if llm_proposed_titles else 'N/A'}",
        f"[meta] llm_reason={llm_reason or 'N/A'}",
        "---",
        "",
    ]
    return "\n".join(lines) + "\n"


def append_daily_citation(output_dir: Path, citation_text: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    date_name = datetime.now().strftime("%Y-%m-%d")
    citation_path = output_dir / f"{date_name}.txt"
    with citation_path.open("a", encoding="utf-8") as file_obj:
        file_obj.write(citation_text)
    return citation_path
