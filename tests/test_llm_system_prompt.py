from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from paperfetch.config import load_app_config
from paperfetch.rerank_llm import _build_messages as build_pool_messages
from paperfetch.title_llm import _build_messages as build_title_messages
from paperfetch.title_llm import load_llm_config


class LLMSystemPromptTests(unittest.TestCase):
    def test_custom_system_prompt_loaded_and_injected(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "config.json"
            cfg_path.write_text(
                json.dumps(
                    {
                        "llm": {
                            "base_url": "https://example.com",
                            "api_key": "token",
                            "model": "glm-5",
                            "disable_reasoning": True,
                            "system_prompt": "Prefer papers from CVPR/ICCV/ECCV.",
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            original = os.getenv("PAPERFETCH_CONFIG_FILE")
            os.environ["PAPERFETCH_CONFIG_FILE"] = str(cfg_path)
            try:
                app_cfg = load_app_config()
                llm_cfg = load_llm_config(timeout=30, app_config=app_cfg)
            finally:
                if original is None:
                    os.environ.pop("PAPERFETCH_CONFIG_FILE", None)
                else:
                    os.environ["PAPERFETCH_CONFIG_FILE"] = original

        self.assertEqual(llm_cfg.system_prompt, "Prefer papers from CVPR/ICCV/ECCV.")

        title_system = build_title_messages("DETR", llm_cfg.system_prompt)[0]["content"]
        pool_system = build_pool_messages(
            "DETR",
            ["DETR: End-to-End Object Detection with Transformers"],
            [{"candidate_id": "C1"}],
            llm_cfg.system_prompt,
        )[0]["content"]
        self.assertIn("Additional user preference", title_system)
        self.assertIn("Prefer papers from CVPR/ICCV/ECCV.", title_system)
        self.assertIn("Additional user preference", pool_system)
        self.assertIn("Prefer papers from CVPR/ICCV/ECCV.", pool_system)


if __name__ == "__main__":
    unittest.main()
