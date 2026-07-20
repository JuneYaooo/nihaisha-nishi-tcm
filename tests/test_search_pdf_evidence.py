from __future__ import annotations

import io
import importlib.util
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "search_pdf_evidence.py"
MODULE_SPEC = importlib.util.spec_from_file_location("nihaisha_search_pdf_evidence", MODULE_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
search_pdf_evidence = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(search_pdf_evidence)


def test_safe_excerpt_keeps_non_actionable_formula_context_visible() -> None:
    text = "桂枝汤与麻黄汤的方证不同。具体煎服方法可见原页。这一段用于课程比较。"

    excerpt = search_pdf_evidence.safe_excerpt(text, show_excerpt=False)

    assert "桂枝汤与麻黄汤的方证不同" in excerpt
    assert "这一段用于课程比较" in excerpt
    assert "煎服方法" not in excerpt
    assert search_pdf_evidence.FOLDED_NOTICE in excerpt


def test_safe_excerpt_full_page_remains_explicit_opt_in() -> None:
    text = "剂量为10克。"

    assert search_pdf_evidence.safe_excerpt(text, show_excerpt=True) == text


def test_cli_prints_excerpt_before_source_metadata(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "pdf"
    text_dir = tmp_path / "text"
    evidence_dir.mkdir()
    text_dir.mkdir()
    card = {
        "card_id": "card-1",
        "citation": "pdf-evidence:test#p1",
        "source_name": "测试课程.pdf",
        "locator": "p1",
        "text": "桂枝汤与麻黄汤用于方证比较。",
        "module": "shanghan",
    }
    (evidence_dir / "evidence-cards.jsonl").write_text(
        json.dumps(card, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (text_dir / "evidence-cards.jsonl").write_text("", encoding="utf-8")
    argv = [
        "search_pdf_evidence.py",
        "桂枝汤",
        "--evidence-dir",
        str(evidence_dir),
        "--text-evidence-dir",
        str(text_dir),
    ]

    stdout = io.StringIO()
    with patch.object(sys, "argv", argv), redirect_stdout(stdout):
        assert search_pdf_evidence.main() == 0

    output = stdout.getvalue()
    assert output.index("原文摘录：") < output.index("来源：")
    assert "桂枝汤与麻黄汤用于方证比较" in output
