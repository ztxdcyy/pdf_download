from __future__ import annotations

from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from paperfetch.citation import append_daily_citation, build_citation_text


class CitationFormatTests(unittest.TestCase):
    def test_journal_format(self) -> None:
        paper = {
            "title": "Sample Journal Paper",
            "authors": [
                {"name": "A. One"},
                {"name": "B. Two"},
                {"name": "C. Three"},
                {"name": "D. Four"},
            ],
            "year": 2024,
            "venue": "Journal of Examples",
            "volume": "12",
            "issue": "3",
            "pages": "10-20",
            "documentType": "J",
        }
        text = build_citation_text(paper, "10.1000/xyz", "k", "all", "llm").strip()
        expected = (
            "A. One, B. Two, C. Three, et al. "
            "Sample Journal Paper[J]. Journal of Examples, 2024, 12(3): 10-20. DOI:10.1000/xyz."
        )
        self.assertEqual(text, expected)

    def test_web_format_contains_access_date(self) -> None:
        paper = {
            "title": "Sample Preprint",
            "authors": [{"name": "A. One"}],
            "year": 2024,
            "publicationDate": "2024-03-01",
            "venue": "arXiv",
            "documentType": "EB/OL",
            "url": "https://arxiv.org/abs/1234.56789",
        }
        text = build_citation_text(paper, None, "k", "all", "llm").strip()
        today = datetime.now().strftime("%Y-%m-%d")
        self.assertIn("(2024-03-01)", text)
        self.assertIn(f"[{today}]", text)
        self.assertIn("https://arxiv.org/abs/1234.56789", text)
        self.assertIn("[EB/OL]", text)

    def test_append_daily_citation_adds_index(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            out = Path(tmp_dir)
            first = append_daily_citation(out, "Author A. First[J]. J, 2024.")
            append_daily_citation(out, "Author B. Second[J]. J, 2024.")
            lines = first.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[0], "[1] Author A. First[J]. J, 2024.")
            self.assertEqual(lines[1], "[2] Author B. Second[J]. J, 2024.")


if __name__ == "__main__":
    unittest.main()
