from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import requests


class PDFDownloadError(RuntimeError):
    """Raised when PDF download fails."""


def _sanitize_filename(text: str, max_length: int = 120) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "").strip())
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", cleaned)
    cleaned = cleaned.strip(" .")
    if not cleaned:
        return "paper"
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip(" .")
    return cleaned or "paper"


def _collect_pdf_candidate_urls(paper: dict[str, Any]) -> list[str]:
    pdf_like_urls: list[str] = []
    fallback_urls: list[str] = []
    seen: set[str] = set()

    def add_url(value: Any) -> None:
        url = str(value or "").strip()
        if not url or not url.startswith("http"):
            return
        lowered = url.lower()
        if lowered in seen:
            return
        seen.add(lowered)
        if lowered.endswith(".pdf") or "/pdf/" in lowered or "pdf=" in lowered:
            pdf_like_urls.append(url)
        else:
            fallback_urls.append(url)

    # Prefer arXiv if available (open access).
    external_ids = paper.get("externalIds") if isinstance(paper.get("externalIds"), dict) else {}
    arxiv_id = str(external_ids.get("ArXiv") or external_ids.get("arXiv") or "").strip()
    if arxiv_id:
        add_url(f"https://arxiv.org/pdf/{arxiv_id}.pdf")

    add_url(paper.get("pdfUrl"))

    raw_urls = paper.get("pdfUrls")
    if isinstance(raw_urls, list):
        for value in raw_urls:
            add_url(value)

    open_access_pdf = paper.get("openAccessPdf")
    if isinstance(open_access_pdf, dict):
        add_url(open_access_pdf.get("url"))

    landing_url = str(paper.get("url") or "").strip()
    if landing_url.lower().endswith(".pdf"):
        add_url(landing_url)

    return pdf_like_urls + fallback_urls


def _is_pdf_response(response: requests.Response, first_chunk: bytes, source_url: str) -> bool:
    content_type = str(response.headers.get("Content-Type") or "").lower()
    if "application/pdf" in content_type:
        return True
    if first_chunk.startswith(b"%PDF"):
        return True
    final_url = str(response.url or source_url).lower()
    return final_url.endswith(".pdf")


def _target_pdf_path(output_dir: Path, paper: dict[str, Any]) -> Path:
    year = str(paper.get("year") or "").strip()
    title = str(paper.get("title") or "paper").strip()
    stem = _sanitize_filename(f"{year}-{title}" if year else title)
    path = output_dir / f"{stem}.pdf"
    if not path.exists():
        return path

    index = 2
    while True:
        candidate = output_dir / f"{stem}-{index}.pdf"
        if not candidate.exists():
            return candidate
        index += 1


def download_pdf_for_paper(
    paper: dict[str, Any],
    output_dir: Path,
    timeout: float = 45.0,
    session: requests.Session | None = None,
) -> Path:
    if timeout <= 0:
        raise PDFDownloadError("PDF timeout must be > 0.")

    urls = _collect_pdf_candidate_urls(paper)
    if not urls:
        raise PDFDownloadError("No PDF candidate URL found in metadata.")

    output_dir.mkdir(parents=True, exist_ok=True)
    client = session or requests
    last_error: str | None = None

    for url in urls:
        try:
            response = client.get(
                url,
                timeout=(10, timeout),
                allow_redirects=True,
                stream=True,
                headers={"User-Agent": "paperfetch/0.1"},
            )
        except requests.RequestException as error:
            last_error = f"{url} -> {error}"
            continue

        try:
            response.raise_for_status()
            chunk_iter = response.iter_content(chunk_size=8192)
            first_chunk = b""
            for piece in chunk_iter:
                if piece:
                    first_chunk = piece
                    break
            if not first_chunk:
                last_error = f"{url} -> empty body"
                continue
            if not _is_pdf_response(response, first_chunk, url):
                last_error = f"{url} -> non-pdf response"
                continue

            target_path = _target_pdf_path(output_dir, paper)
            with target_path.open("wb") as file_obj:
                file_obj.write(first_chunk)
                for piece in chunk_iter:
                    if piece:
                        file_obj.write(piece)
            return target_path
        except requests.RequestException as error:
            last_error = f"{url} -> {error}"
            continue
        finally:
            response.close()

    detail = f" Last error: {last_error}" if last_error else ""
    raise PDFDownloadError(f"Failed to download PDF from {len(urls)} candidate URL(s).{detail}")
