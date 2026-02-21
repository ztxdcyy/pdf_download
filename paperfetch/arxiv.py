from __future__ import annotations

from datetime import datetime
from typing import Any
import xml.etree.ElementTree as ET

import requests

ARXIV_BASE = "http://export.arxiv.org/api/query"
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


def _parse_year(value: str) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).year
    except ValueError:
        return None


def _extract_arxiv_id(id_url: str) -> str:
    text = str(id_url or "").strip()
    if not text:
        return ""
    parts = text.split("/")
    return parts[-1] if parts else text


def _entry_text(entry: ET.Element, tag: str) -> str:
    node = entry.find(f"atom:{tag}", ATOM_NS)
    if node is None or node.text is None:
        return ""
    return node.text.strip()


def _entry_authors(entry: ET.Element) -> list[dict[str, str]]:
    authors: list[dict[str, str]] = []
    for author in entry.findall("atom:author", ATOM_NS):
        name_node = author.find("atom:name", ATOM_NS)
        if name_node is not None and name_node.text:
            authors.append({"name": name_node.text.strip()})
    return authors


def _entry_links(entry: ET.Element) -> dict[str, str]:
    links: dict[str, str] = {}
    for link in entry.findall("atom:link", ATOM_NS):
        rel = link.attrib.get("rel", "")
        href = link.attrib.get("href", "")
        if rel and href:
            links[rel] = href
        if link.attrib.get("type") == "application/pdf" and href:
            links["pdf"] = href
    return links


def _to_common_paper(entry: ET.Element) -> dict[str, Any]:
    id_url = _entry_text(entry, "id")
    title = _entry_text(entry, "title").replace("\n", " ").strip()
    abstract = _entry_text(entry, "summary").replace("\n", " ").strip()
    published = _entry_text(entry, "published")
    year = _parse_year(published)
    arxiv_id = _extract_arxiv_id(id_url)
    links = _entry_links(entry)
    pdf_url = links.get("pdf") or (f"https://arxiv.org/pdf/{arxiv_id}.pdf" if arxiv_id else None)

    external_ids: dict[str, str] = {}
    if arxiv_id:
        external_ids["ArXiv"] = arxiv_id

    pdf_urls = [pdf_url] if pdf_url else []
    return {
        "paperId": arxiv_id or id_url or None,
        "title": title,
        "abstract": abstract,
        "authors": _entry_authors(entry),
        "year": year,
        "venue": "arXiv",
        "documentType": "EB/OL",
        "rawType": "preprint",
        "volume": None,
        "issue": None,
        "pages": None,
        "citationCount": 0,
        "externalIds": external_ids,
        "pdfUrl": pdf_url,
        "pdfUrls": pdf_urls,
        "url": id_url,
    }


def search_papers(keyword: str, limit: int = 25) -> list[dict[str, Any]]:
    query = str(keyword or "").strip()
    if not query:
        return []
    max_results = max(1, min(limit, 100))
    params = {
        "search_query": f'all:"{query}"',
        "start": 0,
        "max_results": max_results,
    }
    response = requests.get(ARXIV_BASE, params=params, timeout=30)
    response.raise_for_status()
    root = ET.fromstring(response.text)
    entries = root.findall("atom:entry", ATOM_NS)
    return [_to_common_paper(entry) for entry in entries]
