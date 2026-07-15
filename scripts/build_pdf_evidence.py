#!/usr/bin/env python3
"""Build complete page-level PDF evidence from the local source PDFs."""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
import sys
from typing import Any


MODULE_TITLES = {
    "acupuncture": "针灸",
    "huangdi": "黄帝内经",
    "bencao": "神农本草",
    "shanghan": "伤寒论",
    "jingui": "金匮要略",
    "zhongjing-xinfa": "仲景心法",
}

WATERMARK_RE = re.compile(
    r"学习资料成本价打印公益流通禁止加价贩卖\s*"
    r"微信公众号\s*[:：]?\s*岐黄圣贤智慧\s*[、,，]?\s*岐黄传承道法自然"
)
MULTIPLE_BLANK_LINES_RE = re.compile(r"\n{3,}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build one complete evidence record for every physical page of every manifest PDF."
    )
    parser.add_argument(
        "--source-root",
        required=True,
        type=Path,
        help="Directory containing the source PDFs. Files are resolved recursively by source_name.",
    )
    parser.add_argument(
        "--evidence-dir",
        default=Path("references/pdf-evidence"),
        type=Path,
        help="Evidence output directory.",
    )
    return parser.parse_args()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def load_existing_terms(cards_path: Path) -> dict[str, list[str]]:
    terms: dict[str, list[str]] = {}
    if not cards_path.exists():
        return terms
    with cards_path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            card = json.loads(line)
            terms[card["card_id"]] = card.get("terms", [])
    return terms


def clean_page_text(raw_text: str) -> str:
    text = raw_text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = WATERMARK_RE.sub("", text)
    lines = [line.rstrip() for line in text.splitlines()]
    text = "\n".join(lines).strip()
    return MULTIPLE_BLANK_LINES_RE.sub("\n\n", text)


def resolve_source(source_root: Path, source_name: str) -> Path:
    matches = sorted(source_root.rglob(source_name))
    if not matches:
        raise FileNotFoundError(f"Source PDF not found: {source_name}")
    if len(matches) > 1:
        joined = "\n".join(str(path) for path in matches)
        raise RuntimeError(f"Source PDF is ambiguous: {source_name}\n{joined}")
    return matches[0]


def markdown_fence(text: str) -> str:
    runs = [len(match.group(0)) for match in re.finditer(r"`+", text)]
    return "`" * max(3, (max(runs) + 1) if runs else 3)


def build_module_markdown(
    module: str,
    documents: list[dict[str, Any]],
    cards_by_doc: dict[str, list[dict[str, Any]]],
) -> str:
    title = MODULE_TITLES[module]
    total_pages = sum(document["physical_pages"] for document in documents)
    text_pages = sum(document["pages_with_text"] for document in documents)
    visual_pages = sum(document["pages_with_visual"] for document in documents)
    blank_pages = sum(document["blank_pages"] for document in documents)
    lines = [
        f"# {title} PDF 完整页级证据",
        "",
        "> 每个源 PDF 物理页均有记录；文本页保存完整文本层，不做字符截断。",
        "> 重复流通水印会被移除；纯图片页使用人工校阅说明；真正空白页明确标记。",
        "",
        "## 覆盖统计",
        "",
        "| PDF | Doc ID | 物理页 | 完整文本页 | 纯图片页 | 空白页 |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for document in documents:
        lines.append(
            f"| `{document['source_name']}` | `{document['doc_id']}` | "
            f"{document['physical_pages']} | {document['pages_with_text']} | "
            f"{document['pages_with_visual']} | {document['blank_pages']} |"
        )
    lines.extend(
        [
            f"| **合计** |  | **{total_pages}** | **{text_pages}** | "
            f"**{visual_pages}** | **{blank_pages}** |",
            "",
            "## 完整页面",
            "",
        ]
    )
    for document in documents:
        doc_id = document["doc_id"]
        lines.extend(
            [
                f"## {document['source_name']}",
                "",
                f"- Doc ID: `{doc_id}`",
                f"- 物理页数: {document['physical_pages']}",
                "",
            ]
        )
        for card in cards_by_doc[doc_id]:
            page = card["page"]
            citation = card["citation"]
            page_kind = card["page_kind"]
            lines.extend(
                [
                    "<details>",
                    f"<summary>第 {page} 页 · <code>{citation}</code> · {page_kind}</summary>",
                    "",
                ]
            )
            if page_kind == "blank":
                lines.append("[空白页：源 PDF 本页没有文本、图片或绘图对象。]")
            else:
                text = card["text"]
                fence = markdown_fence(text)
                lines.extend([f"{fence}text", text, fence])
            lines.extend(["", "</details>", ""])
    return "\n".join(lines).rstrip() + "\n"


def build_sources_markdown(documents: list[dict[str, Any]]) -> str:
    lines = [
        "# PDF Evidence Sources",
        "",
        "| Doc ID | Module | PDF | Physical pages | Full-text pages | Visual pages | Blank pages | Characters |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for document in documents:
        lines.append(
            f"| `{document['doc_id']}` | `{document['module']}` | `{document['source_name']}` | "
            f"{document['physical_pages']} | {document['pages_with_text']} | "
            f"{document['pages_with_visual']} | {document['blank_pages']} | {document['characters']} |"
        )
    return "\n".join(lines) + "\n"


def build_modules_index(documents: list[dict[str, Any]]) -> str:
    modules = []
    seen = set()
    for document in documents:
        module = document["module"]
        if module not in seen:
            modules.append(module)
            seen.add(module)
    lines = [
        "# PDF Evidence Modules",
        "",
        "本目录按课程模块保存完整 PDF 页级文本。每个物理页都有记录，正文不截断；",
        "页面默认折叠，以降低 Markdown 浏览负担。精确检索可使用 `scripts/search_pdf_evidence.py`。",
        "",
        "| Module | File |",
        "| --- | --- |",
    ]
    for module in modules:
        lines.append(f"| {MODULE_TITLES[module]} | `{module}.md` |")
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    evidence_dir = args.evidence_dir
    manifest_path = evidence_dir / "source-manifest.json"
    cards_path = evidence_dir / "evidence-cards.jsonl"
    overrides_path = evidence_dir / "page-overrides.json"

    try:
        import fitz
    except ImportError:
        print("PyMuPDF is required. Install the 'pymupdf' package.", file=sys.stderr)
        return 2

    source_documents = load_json(manifest_path)
    page_overrides = load_json(overrides_path) if overrides_path.exists() else {}
    existing_terms = load_existing_terms(cards_path)
    documents: list[dict[str, Any]] = []
    cards: list[dict[str, Any]] = []
    cards_by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for source_document in source_documents:
        doc_id = source_document["doc_id"]
        source_name = source_document["source_name"]
        source_path = resolve_source(args.source_root, source_name)
        pdf = fitz.open(source_path)
        text_page_numbers: list[int] = []
        visual_page_numbers: list[int] = []
        blank_page_numbers: list[int] = []
        characters = 0

        for page_index, page in enumerate(pdf):
            page_number = page_index + 1
            card_id = f"{doc_id}-p{page_number:04d}"
            text = clean_page_text(page.get_text("text"))
            override = page_overrides.get(card_id)
            if text:
                page_kind = "text"
                text_page_numbers.append(page_number)
                characters += len(text)
            elif override:
                page_kind = override["page_kind"]
                text = override["text"]
                visual_page_numbers.append(page_number)
            else:
                page_kind = "blank"
                blank_page_numbers.append(page_number)

            card = {
                "card_id": card_id,
                "citation": f"pdf-evidence:{doc_id}#p{page_number}",
                "doc_id": doc_id,
                "locator": f"page {page_number}",
                "module": source_document["module"],
                "page": page_number,
                "page_kind": page_kind,
                "source_name": source_name,
                "source_type": "pdf",
                "text": text,
                "terms": existing_terms.get(card_id, []),
            }
            cards.append(card)
            cards_by_doc[doc_id].append(card)

        document = {
            "doc_id": doc_id,
            "source_name": source_name,
            "source_type": "pdf",
            "module": source_document["module"],
            "physical_pages": pdf.page_count,
            "pages_with_text": len(text_page_numbers),
            "pages_with_visual": len(visual_page_numbers),
            "blank_pages": len(blank_page_numbers),
            "first_page": text_page_numbers[0] if text_page_numbers else None,
            "last_page": text_page_numbers[-1] if text_page_numbers else None,
            "characters": characters,
        }
        documents.append(document)

    jsonl = "".join(json.dumps(card, ensure_ascii=False) + "\n" for card in cards)
    atomic_write_text(cards_path, jsonl)
    atomic_write_text(
        manifest_path,
        json.dumps(documents, ensure_ascii=False, indent=2) + "\n",
    )
    atomic_write_text(evidence_dir / "sources.md", build_sources_markdown(documents))
    atomic_write_text(evidence_dir / "modules" / "index.md", build_modules_index(documents))

    documents_by_module: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for document in documents:
        documents_by_module[document["module"]].append(document)
    for module, module_documents in documents_by_module.items():
        atomic_write_text(
            evidence_dir / "modules" / f"{module}.md",
            build_module_markdown(module, module_documents, cards_by_doc),
        )

    print(
        json.dumps(
            {
                "documents": len(documents),
                "physical_page_records": len(cards),
                "full_text_pages": sum(document["pages_with_text"] for document in documents),
                "visual_pages": sum(document["pages_with_visual"] for document in documents),
                "blank_pages": sum(document["blank_pages"] for document in documents),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
