from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from paperfetch.config import load_app_config


class ConfigMergeTests(unittest.TestCase):
    def test_local_overrides_example_and_inherits_missing_fields(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            example_path = tmp_path / "config.example.json"
            local_path = tmp_path / "config.local.json"

            example_path.write_text(
                json.dumps(
                    {
                        "llm": {
                            "base_url": "https://example-llm.test/v1/",
                            "api_key": "YOUR_LLM_API_KEY",
                            "model": "glm-5",
                            "disable_reasoning": True,
                            "system_prompt": "Prefer canonical papers.",
                        },
                        "providers": {
                            "s2_api_key": "YOUR_S2_API_KEY",
                            "openalex_email": "you@example.com",
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            local_path.write_text(
                json.dumps(
                    {
                        "llm": {
                            "api_key": "real-key-123",
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            prev_cwd = os.getcwd()
            prev_env = os.getenv("PAPERFETCH_CONFIG_FILE")
            os.chdir(tmp_path)
            os.environ.pop("PAPERFETCH_CONFIG_FILE", None)
            try:
                cfg = load_app_config()
            finally:
                os.chdir(prev_cwd)
                if prev_env is None:
                    os.environ.pop("PAPERFETCH_CONFIG_FILE", None)
                else:
                    os.environ["PAPERFETCH_CONFIG_FILE"] = prev_env

        self.assertEqual(cfg.llm_base_url, "https://example-llm.test/v1/")
        self.assertEqual(cfg.llm_api_key, "real-key-123")
        self.assertEqual(cfg.llm_model, "glm-5")
        self.assertTrue(cfg.llm_disable_reasoning)
        self.assertEqual(cfg.llm_system_prompt, "Prefer canonical papers.")
        self.assertEqual(cfg.s2_api_key, "")
        self.assertEqual(cfg.openalex_email, "")
        self.assertIn("config.example.json", cfg.source_path)
        self.assertIn("config.local.json", cfg.source_path)


if __name__ == "__main__":
    unittest.main()
