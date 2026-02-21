from __future__ import annotations

from difflib import SequenceMatcher
import math
import re
from typing import Any


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.lower())).strip()


def get_doi(paper: dict[str, Any]) -> str | None:
    external_ids = paper.get("externalIds") or {}
    doi = external_ids.get("DOI") or external_ids.get("doi")
    if not doi:
        return None
    return str(doi).strip() or None


def is_arxiv_doi(doi: str | None) -> bool:
    if not doi:
        return False
    normalized = doi.lower()
    return normalized.startswith("10.48550/arxiv.") or "arxiv" in normalized


def is_preprint(paper: dict[str, Any]) -> bool:
    external_ids = paper.get("externalIds") or {}
    venue = str(paper.get("venue") or "").lower()
    return "arxiv" in external_ids or venue == "arxiv"


def _query_relevance_score(keyword: str, title: str) -> float:
    title_norm = normalize_text(title)
    keyword_norm = normalize_text(keyword)
    if not title_norm or not keyword_norm:
        return -8.0

    score = 0.0
    if keyword_norm in title_norm:
        score += 20.0

    keyword_tokens = set(keyword_norm.split())
    title_tokens = set(title_norm.split())
    overlap = len(keyword_tokens & title_tokens)
    if overlap > 0:
        score += 15.0 * (overlap / max(1, len(keyword_tokens)))
    else:
        # Do not hard-filter; keep candidate with small penalty.
        score -= 10.0

    # Penalize obvious variant naming around short acronyms, e.g. DN-DETR / DETR-v2.
    if len(keyword_norm) <= 8 and " " not in keyword_norm:
        escaped = re.escape(keyword_norm)
        if re.search(rf"\b[a-z0-9]+-{escaped}\b", title_norm):
            score -= 8.0
        if re.search(rf"\b{escaped}-[a-z0-9]+\b", title_norm):
            score -= 8.0

    return score


def score_paper(keyword: str, paper: dict[str, Any]) -> float:
    title = str(paper.get("title") or "")
    score = _query_relevance_score(keyword, title)

    doi = get_doi(paper)
    if doi and not is_arxiv_doi(doi):
        score += 80.0
    if is_preprint(paper):
        score -= 20.0
    else:
        score += 40.0

    citations = max(0, int(paper.get("citationCount") or 0))
    score += math.log1p(citations) * 14.0

    if re.search(r"\b(survey|review)\b", title.lower()):
        score -= 30.0

    year = int(paper.get("year") or 9999)
    if year < 9999:
        score += max(0.0, (2030 - year) * 0.8)
    return score


def pick_best_candidate(keyword: str, papers: list[dict[str, Any]]) -> dict[str, Any]:
    best_paper: dict[str, Any] | None = None
    best_key: tuple[float, int, int] | None = None

    for paper in papers:
        score = score_paper(keyword, paper)
        citations = max(0, int(paper.get("citationCount") or 0))
        year = int(paper.get("year") or 9999)
        rank_key = (score, citations, -year)
        if best_key is None or rank_key > best_key:
            best_key = rank_key
            best_paper = paper

    if best_paper is None:
        raise ValueError("No candidate was selected from search results.")
    return best_paper


def _title_similarity(left: str, right: str) -> float:
    left_norm = normalize_text(left)
    right_norm = normalize_text(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0

    ratio = SequenceMatcher(None, left_norm, right_norm).ratio()
    left_tokens = set(left_norm.split())
    right_tokens = set(right_norm.split())
    overlap = len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))
    return max(ratio, overlap)


def title_similarity(left: str, right: str) -> float:
    return _title_similarity(left, right)
