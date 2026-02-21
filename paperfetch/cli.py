from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from paperfetch.citation import append_daily_citation, build_citation_text
from paperfetch.config import load_app_config
from paperfetch.arxiv import search_papers as arxiv_search_papers
from paperfetch.openalex import get_paper_by_doi as openalex_get_paper_by_doi
from paperfetch.openalex import search_papers as openalex_search_papers
from paperfetch.s2 import (
    SemanticScholarRateLimitError,
    get_paper_by_doi as s2_get_paper_by_doi,
    search_papers as s2_search_papers,
)
from paperfetch.select import (
    get_doi,
    normalize_text,
    pick_best_candidate,
    score_paper,
    title_similarity,
)
from paperfetch.title_llm import LLMTitleError, load_llm_config, propose_titles
from paperfetch.pdf import PDFDownloadError, download_pdf_for_paper
from paperfetch.rerank_llm import LLMPoolError, select_from_pool


def _search_candidates(
    keyword: str,
    limit: int,
    provider: str,
    s2_key: str | None,
    contact_email: str | None,
) -> tuple[list[dict], str]:
    if provider == "all":
        merged: list[dict] = []
        try:
            merged.extend(s2_search_papers(keyword=keyword, limit=limit, api_key=s2_key))
        except SemanticScholarRateLimitError:
            pass
        merged.extend(openalex_search_papers(keyword=keyword, limit=limit, contact_email=contact_email))
        merged.extend(arxiv_search_papers(keyword=keyword, limit=limit))
        return _merge_and_dedupe_papers(merged), "all"
    if provider == "s2":
        return s2_search_papers(keyword=keyword, limit=limit, api_key=s2_key), "s2"
    if provider == "arxiv":
        return arxiv_search_papers(keyword=keyword, limit=limit), "arxiv"
    if provider == "openalex":
        return openalex_search_papers(keyword=keyword, limit=limit, contact_email=contact_email), "openalex"

    try:
        papers = s2_search_papers(keyword=keyword, limit=limit, api_key=s2_key)
        return papers, "s2"
    except SemanticScholarRateLimitError:
        papers = openalex_search_papers(keyword=keyword, limit=limit, contact_email=contact_email)
        return papers, "openalex"


def _search_titles_pool(
    titles: list[str],
    limit: int,
    provider: str,
    s2_key: str | None,
    contact_email: str | None,
) -> tuple[list[dict[str, Any]], str]:
    if not titles:
        return [], provider if provider != "auto" else "openalex"

    title_query_limit = max(10, min(limit, 30))
    merged: list[dict[str, Any]] = []

    if provider == "all":
        for title in titles:
            try:
                merged.extend(
                    s2_search_papers(keyword=title, limit=title_query_limit, api_key=s2_key)
                )
            except SemanticScholarRateLimitError:
                pass
            merged.extend(
                openalex_search_papers(
                    keyword=title,
                    limit=title_query_limit,
                    contact_email=contact_email,
                )
            )
            merged.extend(arxiv_search_papers(keyword=title, limit=title_query_limit))
        return _merge_and_dedupe_papers(merged), "all"

    if provider == "auto":
        try:
            for title in titles:
                merged.extend(
                    s2_search_papers(keyword=title, limit=title_query_limit, api_key=s2_key)
                )
            return _merge_and_dedupe_papers(merged), "s2"
        except SemanticScholarRateLimitError:
            merged = []
            for title in titles:
                merged.extend(
                    openalex_search_papers(
                        keyword=title,
                        limit=title_query_limit,
                        contact_email=contact_email,
                    )
                )
            return _merge_and_dedupe_papers(merged), "openalex"

    if provider == "arxiv":
        for title in titles:
            merged.extend(arxiv_search_papers(keyword=title, limit=title_query_limit))
        return _merge_and_dedupe_papers(merged), "arxiv"

    if provider == "s2":
        for title in titles:
            merged.extend(
                s2_search_papers(keyword=title, limit=title_query_limit, api_key=s2_key)
            )
        return _merge_and_dedupe_papers(merged), "s2"

    for title in titles:
        merged.extend(
            openalex_search_papers(
                keyword=title,
                limit=title_query_limit,
                contact_email=contact_email,
            )
        )
    return _merge_and_dedupe_papers(merged), "openalex"


def _merge_and_dedupe_papers(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for paper in papers:
        paper_id = str(paper.get("paperId") or "").strip()
        title = str(paper.get("title") or "").strip().lower()
        year = str(paper.get("year") or "").strip()
        key = paper_id or f"{title}::{year}"
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(paper)
    return deduped


def _build_validation_pool(
    keyword: str,
    papers: list[dict[str, Any]],
    validation_candidates: int,
    proposed_titles: list[str],
) -> list[dict[str, Any]]:
    size = max(1, validation_candidates)
    keep: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_paper(paper: dict[str, Any]) -> None:
        paper_id = str(paper.get("paperId") or "").strip()
        title = normalize_text(str(paper.get("title") or ""))
        year = str(paper.get("year") or "").strip()
        key = paper_id or f"{title}::{year}"
        if not key or key in seen:
            return
        seen.add(key)
        keep.append(paper)

    for target_title in proposed_titles:
        target_norm = normalize_text(target_title)
        if not target_norm:
            continue
        exact_hits = [
            paper
            for paper in papers
            if normalize_text(str(paper.get("title") or "")) == target_norm
        ]
        for hit in sorted(
            exact_hits,
            key=lambda paper: int(paper.get("citationCount") or 0),
            reverse=True,
        ):
            add_paper(hit)

    ranked = sorted(
        papers,
        key=lambda paper: score_paper(keyword, paper),
        reverse=True,
    )
    for paper in ranked:
        add_paper(paper)
        if len(keep) >= size:
            break
    return keep[:size]


def _build_pool_candidates(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for index, paper in enumerate(papers, start=1):
        external_ids = paper.get("externalIds") if isinstance(paper.get("externalIds"), dict) else {}
        doi = ""
        if isinstance(external_ids, dict):
            doi = str(external_ids.get("DOI") or external_ids.get("doi") or "").strip()
        abstract = str(paper.get("abstract") or "").strip()
        if len(abstract) > 800:
            abstract = abstract[:800].rstrip()
        candidates.append(
            {
                "candidate_id": f"C{index}",
                "title": str(paper.get("title") or "").strip(),
                "year": paper.get("year"),
                "venue": str(paper.get("venue") or "").strip(),
                "doi": doi or None,
                "citationCount": int(paper.get("citationCount") or 0),
                "abstract": abstract,
                "url": str(paper.get("url") or "").strip(),
            }
        )
    return candidates


def _pick_best_backup_match(primary: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not candidates:
        return None

    primary_title = normalize_text(str(primary.get("title") or ""))
    primary_year = int(primary.get("year") or 0)
    primary_doi = get_doi(primary)

    best_item: dict[str, Any] | None = None
    best_key: tuple[float, int, int] | None = None
    for candidate in candidates:
        score = 0.0
        candidate_doi = get_doi(candidate)
        if primary_doi and candidate_doi and primary_doi.lower() == candidate_doi.lower():
            score += 100.0

        candidate_title = normalize_text(str(candidate.get("title") or ""))
        if primary_title and candidate_title:
            if candidate_title == primary_title:
                score += 50.0
            elif primary_title in candidate_title or candidate_title in primary_title:
                score += 20.0

        candidate_year = int(candidate.get("year") or 0)
        if primary_year and candidate_year:
            if candidate_year == primary_year:
                score += 8.0
            elif abs(candidate_year - primary_year) <= 1:
                score += 3.0

        citations = int(candidate.get("citationCount") or 0)
        rank_key = (score, citations, -candidate_year if candidate_year else 0)
        if best_key is None or rank_key > best_key:
            best_key = rank_key
            best_item = candidate

    if not best_item:
        return None
    if best_key and best_key[0] < 20:
        return None
    return best_item


def _merge_with_backup(primary: dict[str, Any], backup: dict[str, Any] | None) -> dict[str, Any]:
    if not backup:
        return primary

    merged = dict(primary)
    for field in ("title", "year", "venue", "volume", "issue", "pages", "url", "rawType", "pdfUrl", "openAccessPdf"):
        current = merged.get(field)
        incoming = backup.get(field)
        if (not current or str(current).strip() == "") and incoming:
            merged[field] = incoming

    current_type = str(merged.get("documentType") or "").strip().upper()
    incoming_type = str(backup.get("documentType") or "").strip().upper()
    if incoming_type and incoming_type != "Z" and (not current_type or current_type == "Z"):
        merged["documentType"] = incoming_type

    primary_ids = merged.get("externalIds") if isinstance(merged.get("externalIds"), dict) else {}
    backup_ids = backup.get("externalIds") if isinstance(backup.get("externalIds"), dict) else {}
    if primary_ids or backup_ids:
        combined = dict(backup_ids)
        combined.update(primary_ids)
        merged["externalIds"] = combined

    if not merged.get("authors") and backup.get("authors"):
        merged["authors"] = backup.get("authors")

    combined_pdf_urls: list[str] = []
    seen_pdf_urls: set[str] = set()
    for source in (primary.get("pdfUrls"), backup.get("pdfUrls")):
        if not isinstance(source, list):
            continue
        for value in source:
            url = str(value or "").strip()
            if not url or not url.startswith("http"):
                continue
            lowered = url.lower()
            if lowered in seen_pdf_urls:
                continue
            seen_pdf_urls.add(lowered)
            combined_pdf_urls.append(url)
    if combined_pdf_urls:
        merged["pdfUrls"] = combined_pdf_urls
        if not merged.get("pdfUrl"):
            merged["pdfUrl"] = combined_pdf_urls[0]

    merged["citationCount"] = max(
        int(primary.get("citationCount") or 0),
        int(backup.get("citationCount") or 0),
    )
    return merged


def _enrich_selected_metadata(
    selected: dict[str, Any],
    search_source: str,
    s2_key: str | None,
    contact_email: str | None,
) -> dict[str, Any]:
    primary_doi = get_doi(selected)
    primary_title = str(selected.get("title") or "").strip()

    if search_source == "openalex":
        backup: dict[str, Any] | None = None
        try:
            if primary_doi:
                backup = s2_get_paper_by_doi(primary_doi, api_key=s2_key)
            if not backup and primary_title:
                backup_candidates = s2_search_papers(keyword=primary_title, limit=8, api_key=s2_key)
                backup = _pick_best_backup_match(selected, backup_candidates)
        except Exception:
            backup = None
        return _merge_with_backup(selected, backup)

    if search_source == "s2":
        backup = None
        try:
            if primary_doi:
                backup = openalex_get_paper_by_doi(primary_doi, contact_email=contact_email)
            if not backup and primary_title:
                backup_candidates = openalex_search_papers(
                    keyword=primary_title,
                    limit=8,
                    contact_email=contact_email,
                )
                backup = _pick_best_backup_match(selected, backup_candidates)
        except Exception:
            backup = None
        return _merge_with_backup(selected, backup)

    return selected


def _should_try_arxiv_fallback(error_text: str | None) -> bool:
    if not error_text:
        return True
    lowered = error_text.lower()
    return "418" in lowered or "non-pdf" in lowered or "no pdf" in lowered


def _merge_arxiv_fallback(selected: dict[str, Any], title: str) -> dict[str, Any]:
    try:
        candidates = arxiv_search_papers(keyword=title, limit=3)
    except Exception:
        return selected
    if not candidates:
        return selected
    # Prefer exact title match if exists; otherwise first candidate.
    target_norm = normalize_text(title)
    best = candidates[0]
    for candidate in candidates:
        if normalize_text(str(candidate.get("title") or "")) == target_norm:
            best = candidate
            break
    return _merge_with_backup(selected, best)


def run(
    keyword: str,
    out_dir: str,
    limit: int,
    provider: str,
    selector: str,
    llm_candidates: int,
    llm_timeout: float,
    download_pdf: bool,
    pdf_out_dir: str,
    pdf_timeout: float,
    min_title_similarity: float,
    pdf_arxiv_fallback: bool,
) -> tuple[Path, Path | None, str | None]:
    app_config = load_app_config()
    contact_email = app_config.openalex_email or None
    s2_key = app_config.s2_api_key or None
    selected_by = selector
    llm_reason: str | None = None
    llm_confidence: float | None = None
    llm_proposed_titles: list[str] | None = None
    matched_title: str | None = None
    match_similarity: float | None = None
    validation_score: float | None = None

    if selector == "llm":
        try:
            llm_cfg = load_llm_config(timeout=llm_timeout, app_config=app_config)
            title_proposal = propose_titles(keyword=keyword, client_cfg=llm_cfg)
            llm_proposed_titles = title_proposal.titles

            merged, search_source = _search_titles_pool(
                titles=title_proposal.titles,
                limit=limit,
                provider=provider,
                s2_key=s2_key,
                contact_email=contact_email,
            )
            if not merged:
                raise SystemExit(f"No papers returned from title search provider: {search_source}")
            pool = _build_validation_pool(
                keyword,
                merged,
                llm_candidates,
                title_proposal.titles,
            )
            pool_candidates = _build_pool_candidates(pool)
            pool_selection = select_from_pool(
                keyword=keyword,
                proposed_titles=title_proposal.titles,
                candidates=pool_candidates,
                client_cfg=llm_cfg,
            )
            selected_index = None
            for idx, candidate in enumerate(pool_candidates):
                if candidate["candidate_id"] == pool_selection.candidate_id:
                    selected_index = idx
                    break
            if selected_index is None:
                raise SystemExit(
                    f"LLM selected invalid candidate_id: {pool_selection.candidate_id}"
                )
            selected = pool[selected_index]
            matched_title = title_proposal.titles[0]
            similarity = title_similarity(
                str(selected.get("title") or ""),
                title_proposal.titles[0],
            )
            if similarity < min_title_similarity:
                raise SystemExit(
                    f"Selected title similarity {similarity:.3f} < {min_title_similarity:.3f}"
                )
            match_similarity = similarity
            llm_reason = title_proposal.reason
            llm_confidence = title_proposal.confidence
        except (LLMTitleError, LLMPoolError, ValueError) as error:
            raise SystemExit(str(error)) from error
        selected_by = "llm-title+pool-llm"
    else:
        keyword_papers, search_source = _search_candidates(
            keyword=keyword,
            limit=limit,
            provider=provider,
            s2_key=s2_key,
            contact_email=contact_email,
        )
        if not keyword_papers:
            raise SystemExit(f"No papers returned from search provider: {search_source}")
        selected = pick_best_candidate(keyword, keyword_papers)

    selected = _enrich_selected_metadata(
        selected=selected,
        search_source=search_source,
        s2_key=s2_key,
        contact_email=contact_email,
    )
    pdf_path: Path | None = None
    pdf_error: str | None = None
    if download_pdf:
        try:
            pdf_path = download_pdf_for_paper(
                paper=selected,
                output_dir=Path(pdf_out_dir),
                timeout=pdf_timeout,
            )
        except PDFDownloadError as error:
            pdf_error = str(error)
            if pdf_arxiv_fallback and _should_try_arxiv_fallback(pdf_error):
                selected = _merge_arxiv_fallback(selected, str(selected.get("title") or ""))
                try:
                    pdf_path = download_pdf_for_paper(
                        paper=selected,
                        output_dir=Path(pdf_out_dir),
                        timeout=pdf_timeout,
                    )
                    pdf_error = None
                except PDFDownloadError as followup:
                    pdf_error = str(followup)

    doi = get_doi(selected)
    citation_text = build_citation_text(
        paper=selected,
        doi=doi,
        keyword=keyword,
        search_provider=search_source,
        selected_by=selected_by,
        llm_reason=llm_reason,
        llm_confidence=llm_confidence,
        llm_proposed_titles=llm_proposed_titles,
        matched_title=matched_title,
        match_similarity=match_similarity,
        validation_score=validation_score,
    )
    citation_path = append_daily_citation(Path(out_dir), citation_text)
    return citation_path, pdf_path, pdf_error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch one likely canonical paper citation by keyword."
    )
    parser.add_argument(
        "keyword",
        nargs="+",
        help="Keyword string; supports spaces without quotes (e.g. Focal loss for dense object detection)",
    )
    parser.add_argument("--out", type=str, default="./citations", help="Citation output directory")
    parser.add_argument("--limit", type=int, default=50, help="Search candidates")
    parser.add_argument(
        "--provider",
        type=str,
        choices=["all", "auto", "s2", "openalex", "arxiv"],
        default="all",
        help="Search provider: all (S2+OpenAlex+arXiv), auto (S2 then fallback), s2, openalex, or arxiv",
    )
    parser.add_argument(
        "--selector",
        type=str,
        choices=["llm", "rule"],
        default="llm",
        help="Selection strategy: llm (default) or rule",
    )
    parser.add_argument(
        "--llm-candidates",
        type=int,
        default=10,
        help="Top-N papers kept for strong validation after multi-query retrieval",
    )
    parser.add_argument(
        "--llm-timeout",
        type=float,
        default=90.0,
        help="Timeout (seconds) for LLM API call",
    )
    parser.add_argument(
        "--download-pdf",
        dest="download_pdf",
        action="store_true",
        help="Try to download selected paper PDF (open-access only, default enabled)",
    )
    parser.add_argument(
        "--no-download-pdf",
        dest="download_pdf",
        action="store_false",
        help="Disable PDF download",
    )
    parser.set_defaults(download_pdf=True)
    parser.add_argument(
        "--pdf-out",
        type=str,
        default="./papers",
        help="PDF output directory (used with --download-pdf)",
    )
    parser.add_argument(
        "--pdf-timeout",
        type=float,
        default=45.0,
        help="Timeout (seconds) for each PDF download attempt",
    )
    parser.add_argument(
        "--pdf-arxiv-fallback",
        dest="pdf_arxiv_fallback",
        action="store_true",
        help="If PDF download fails, retry using arXiv search by title (default enabled)",
    )
    parser.add_argument(
        "--no-pdf-arxiv-fallback",
        dest="pdf_arxiv_fallback",
        action="store_false",
        help="Disable arXiv fallback for PDF download",
    )
    parser.set_defaults(pdf_arxiv_fallback=True)
    parser.add_argument(
        "--min-title-sim",
        type=float,
        default=0.6,
        help="Minimum similarity between LLM first title and selected title",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    keyword = " ".join(args.keyword).strip()
    if not keyword:
        raise SystemExit("Keyword cannot be empty.")
    citation_path, pdf_path, pdf_error = run(
        keyword=keyword,
        out_dir=args.out,
        limit=args.limit,
        provider=args.provider,
        selector=args.selector,
        llm_candidates=args.llm_candidates,
        llm_timeout=args.llm_timeout,
        download_pdf=args.download_pdf,
        pdf_out_dir=args.pdf_out,
        pdf_timeout=args.pdf_timeout,
        min_title_similarity=args.min_title_sim,
        pdf_arxiv_fallback=args.pdf_arxiv_fallback,
    )
    print(f"OK: citation appended to {citation_path}")
    if args.download_pdf:
        if pdf_path is not None:
            print(f"OK: pdf downloaded to {pdf_path}")
        else:
            print(f"WARN: pdf download failed. {pdf_error}")


if __name__ == "__main__":
    main()
