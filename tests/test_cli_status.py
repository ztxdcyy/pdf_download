from __future__ import annotations

from pathlib import Path
import unittest

from paperfetch.cli import _determine_completion_status


class CLICompletionStatusTests(unittest.TestCase):
    def test_success_when_pdf_downloaded(self) -> None:
        status, code = _determine_completion_status(True, Path("papers/a.pdf"))
        self.assertEqual(status, "success")
        self.assertEqual(code, 0)

    def test_failure_when_pdf_required_but_missing(self) -> None:
        status, code = _determine_completion_status(True, None)
        self.assertEqual(status, "failure")
        self.assertEqual(code, 2)

    def test_warning_when_pdf_disabled(self) -> None:
        status, code = _determine_completion_status(False, None)
        self.assertEqual(status, "warning")
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
