from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_skill_defaults_to_lightweight_retrieval() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert "### Default Retrieval Policy" in skill
    assert "The default path is the lightweight bundled Skill" in skill
    assert "Full-corpus RAG is explicit opt-in only" in skill
    assert "A request to use RAG is not permission to download its data" in skill
    assert "Stop without downloading" in skill
    assert "data/pdf_rag_bge_m3/" in skill


def test_ordinary_formula_and_source_queries_do_not_route_to_rag() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    rag_route = next(
        line for line in skill.splitlines() if line.startswith("   - Optional full-corpus RAG:")
    )

    assert "explicit user opt-in" in rag_route
    assert "formula-pattern comparison" not in rag_route
    assert "related-reference lookup" not in rag_route
    assert "Formula queries: `references/formula-patterns.md`" in skill
    assert "use `scripts/search_pdf_evidence.py` first" in skill


def test_missing_rag_modules_stay_on_lightweight_and_evidence_is_inline() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert "Route by corpus capability even after RAG opt-in" in skill
    assert "Tianji, learning-entry, lesson-plan" in skill
    assert "Never fill a missing RAG module" in skill
    assert "show a short, safe original excerpt first" in skill
    assert "Do not return a bare file/page locator" in skill


def test_agent_default_prompt_forbids_automatic_rag_download() -> None:
    agent_config = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")

    assert "默认只使用 references" in agent_config
    assert "不自动安装、下载或调用 RAG" in agent_config
    assert "不得自动下载" in agent_config
    assert "另行明确要求下载 RAG 数据时才可下载" in agent_config


def test_skill_installer_excludes_heavy_and_local_artifacts() -> None:
    installer = (ROOT / "install_as_skill.sh").read_text(encoding="utf-8")
    excluded = set(re.findall(r"--exclude='([^']+)'", installer))

    assert {
        ".env",
        ".venv",
        "*.egg-info",
        "LOCAL_USABILITY_REPORT.md",
        "data",
        "output",
        "tests",
        "evals",
        "docs/local",
        "docs/superpowers",
    } <= excluded
