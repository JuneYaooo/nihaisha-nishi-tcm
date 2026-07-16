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
    "classics": "倪师推荐补充资料（古籍）",
}

SOURCE_ROLE_LABELS = {
    "ni-recommended-supplement": "倪师推荐补充资料（非倪师本人资料）",
}

WATERMARK_RE = re.compile(
    r"学习资料成本价打印公益流通禁止加价贩卖\s*"
    r"微信公众号\s*[:：]?\s*岐黄圣贤智慧\s*[、,，]?\s*岐黄传承道法自然"
)
MULTIPLE_BLANK_LINES_RE = re.compile(r"\n{3,}")
CJK_INTERCHAR_SPACE_RE = re.compile(
    r"(?<=[\u3400-\u4dbf\u4e00-\u9fff])[ \t\u3000\r\n]+(?=[\u3400-\u4dbf\u4e00-\u9fff])"
)
RESOURCE_WATERMARK_LINE_RE = re.compile(
    r"更多相关资源|相关资源请访问|hbtmxy|[kK][l1]rs999"
)
LABELED_PHONE_RE = re.compile(r"((?:电话|手机|联系电话)\s*[:：]?\s*)[\d\- ]{7,}")
URL_TOKEN_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
OCR_EMPTY_PAGE_TEXT = (
    "[OCR 未识别到正文] 源页为扫描图像，可能是空白页、隔页、图像或少量标题；"
    "需要版式或图像信息时请查看原 PDF。"
)
OCR_LOW_CONFIDENCE_PAGE_TEXT = (
    "[OCR 低置信页] 本页只识别到极少量低置信字符，未作为可检索正文收录；"
    "需要核对时请查看原 PDF。"
)


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
    parser.add_argument(
        "--ocr-cache-root",
        default=Path("output/pdf-ocr-cache"),
        type=Path,
        help="Directory containing resumable <doc_id>.jsonl PaddleOCR output.",
    )
    return parser.parse_args()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def load_existing_cards(cards_path: Path) -> dict[str, dict[str, Any]]:
    cards: dict[str, dict[str, Any]] = {}
    if not cards_path.exists():
        return cards
    with cards_path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            card = json.loads(line)
            cards[card["card_id"]] = card
    return cards


def load_ocr_records(
    cache_path: Path,
    doc_id: str,
    existing_cards: dict[str, dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    records: dict[int, dict[str, Any]] = {}
    for card in existing_cards.values():
        if card.get("doc_id") != doc_id or not card.get("text_method", "").startswith("paddleocr"):
            continue
        page_kind = card.get("ocr_status") or {
            "text": "ocr",
            "visual": "ocr-empty",
            "excluded": "excluded",
        }.get(card.get("page_kind"))
        if page_kind:
            records[int(card["page"])] = {
                "doc_id": doc_id,
                "page": int(card["page"]),
                "page_kind": page_kind,
                "text": card.get("text", ""),
                "ocr_model": card.get("text_method", "paddleocr").removeprefix("paddleocr-"),
                "mean_confidence": card.get("ocr_mean_confidence"),
            }

    if cache_path.exists():
        with cache_path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get("doc_id") != doc_id:
                    raise ValueError(f"Unexpected OCR doc_id at {cache_path}:{line_number}")
                records[int(record["page"])] = record
    return records


def clean_page_text(raw_text: str, *, normalize_cjk_spacing: bool = False) -> str:
    text = raw_text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = WATERMARK_RE.sub("", text)
    if normalize_cjk_spacing:
        text = CJK_INTERCHAR_SPACE_RE.sub("", text)
    lines = [
        line.rstrip()
        for line in text.splitlines()
        if not RESOURCE_WATERMARK_LINE_RE.search(line)
    ]
    text = "\n".join(lines).strip()
    return MULTIPLE_BLANK_LINES_RE.sub("\n\n", text)


def redact_ocr_privacy(text: str) -> str:
    text = LABELED_PHONE_RE.sub(r"\1[已隐去]", text)
    return URL_TOKEN_RE.sub("[链接已移除]", text)


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
    excluded_pages = sum(document["excluded_pages"] for document in documents)
    blank_pages = sum(document["blank_pages"] for document in documents)
    lines = [
        f"# {title} PDF 完整页级证据",
        "",
        "> 每个源 PDF 物理页均有记录；文本页保存完整文本层，不做字符截断。",
        "> 重复流通水印会被移除；纯图片页使用人工校阅说明；非正文推广/隐私页和真正空白页明确标记。",
        "",
        "## 覆盖统计",
        "",
        "| PDF | Doc ID | 来源层级 | 文本提取 | 物理页 | 完整文本页 | 纯图片页 | 已排除页 | 空白页 |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for document in documents:
        lines.append(
            f"| `{document['source_name']}` | `{document['doc_id']}` | "
            f"{SOURCE_ROLE_LABELS.get(document.get('source_role'), '-')} | "
            f"{document.get('text_extraction', 'native')} | "
            f"{document['physical_pages']} | {document['pages_with_text']} | "
            f"{document['pages_with_visual']} | {document['excluded_pages']} | "
            f"{document['blank_pages']} |"
        )
    lines.extend(
        [
            f"| **合计** |  |  |  | **{total_pages}** | **{text_pages}** | "
            f"**{visual_pages}** | **{excluded_pages}** | **{blank_pages}** |",
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
                *(
                    [f"- 来源层级: {SOURCE_ROLE_LABELS[document['source_role']]}"]
                    if document.get("source_role") in SOURCE_ROLE_LABELS
                    else []
                ),
                f"- 文本提取: {document.get('text_extraction', 'native')}",
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
        "| Doc ID | Module | Role | Extraction | PDF | Physical pages | Full-text pages | Visual pages | Excluded pages | Blank pages | Characters |",
        "| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for document in documents:
        lines.append(
            f"| `{document['doc_id']}` | `{document['module']}` | "
            f"`{document.get('source_role', '-')}` | `{document.get('text_extraction', 'native')}` | "
            f"`{document['source_name']}` | "
            f"{document['physical_pages']} | {document['pages_with_text']} | "
            f"{document['pages_with_visual']} | {document['excluded_pages']} | "
            f"{document['blank_pages']} | {document['characters']} |"
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
    existing_cards = load_existing_cards(cards_path)
    documents: list[dict[str, Any]] = []
    cards: list[dict[str, Any]] = []
    cards_by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for source_document in source_documents:
        doc_id = source_document["doc_id"]
        source_name = source_document["source_name"]
        source_path = resolve_source(args.source_root, source_name)
        pdf = fitz.open(source_path)
        normalize_cjk_spacing = source_document.get("normalize_cjk_spacing", False)
        source_role = source_document.get("source_role")
        recommended_by = source_document.get("recommended_by")
        text_extraction = source_document.get("text_extraction", "native")
        ocr_model = source_document.get("ocr_model")
        ocr_records = (
            load_ocr_records(
                args.ocr_cache_root / f"{doc_id}.jsonl",
                doc_id,
                existing_cards,
            )
            if text_extraction == "paddleocr"
            else {}
        )
        text_page_numbers: list[int] = []
        visual_page_numbers: list[int] = []
        excluded_page_numbers: list[int] = []
        blank_page_numbers: list[int] = []
        characters = 0

        for page_index, page in enumerate(pdf):
            page_number = page_index + 1
            card_id = f"{doc_id}-p{page_number:04d}"
            text = ""
            ocr_status = None
            ocr_mean_confidence = None
            override = page_overrides.get(card_id)
            if override:
                page_kind = override["page_kind"]
                text = override["text"]
                if page_kind == "visual":
                    visual_page_numbers.append(page_number)
                elif page_kind == "excluded":
                    excluded_page_numbers.append(page_number)
                elif page_kind == "blank":
                    blank_page_numbers.append(page_number)
                else:
                    raise ValueError(f"Unsupported page override kind: {page_kind}")
            elif text_extraction == "paddleocr":
                ocr_record = ocr_records.get(page_number)
                if not ocr_record:
                    raise RuntimeError(
                        f"Missing OCR page {page_number} for {doc_id}; "
                        f"expected cache {args.ocr_cache_root / f'{doc_id}.jsonl'}"
                    )
                text = clean_page_text(
                    ocr_record.get("text", ""),
                    normalize_cjk_spacing=normalize_cjk_spacing,
                )
                text = redact_ocr_privacy(text)
                ocr_page_kind = ocr_record.get("page_kind")
                ocr_mean_confidence = ocr_record.get("mean_confidence")
                if ocr_page_kind == "ocr":
                    if (
                        ocr_mean_confidence is not None
                        and ocr_mean_confidence < 0.75
                        and len(text) < 20
                    ):
                        page_kind = "visual"
                        ocr_status = "ocr-low-confidence"
                        text = OCR_LOW_CONFIDENCE_PAGE_TEXT
                        visual_page_numbers.append(page_number)
                    else:
                        page_kind = "text"
                        ocr_status = "ocr"
                        text_page_numbers.append(page_number)
                        characters += len(text)
                elif ocr_page_kind == "excluded":
                    page_kind = "excluded"
                    ocr_status = "excluded"
                    excluded_page_numbers.append(page_number)
                elif ocr_page_kind in {"ocr-empty", "ocr-low-confidence"}:
                    page_kind = "visual"
                    ocr_status = ocr_page_kind
                    text = (
                        OCR_LOW_CONFIDENCE_PAGE_TEXT
                        if ocr_page_kind == "ocr-low-confidence"
                        else OCR_EMPTY_PAGE_TEXT
                    )
                    visual_page_numbers.append(page_number)
                else:
                    raise ValueError(f"Unsupported OCR page kind: {ocr_page_kind}")
            else:
                text = clean_page_text(
                    page.get_text("text"),
                    normalize_cjk_spacing=normalize_cjk_spacing,
                )
                if text:
                    page_kind = "text"
                    text_page_numbers.append(page_number)
                    characters += len(text)
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
                **({"source_role": source_role} if source_role else {}),
                **({"recommended_by": recommended_by} if recommended_by else {}),
                **(
                    {"text_method": f"paddleocr-{ocr_model or 'unknown'}"}
                    if text_extraction == "paddleocr"
                    else {}
                ),
                **({"ocr_status": ocr_status} if ocr_status else {}),
                **(
                    {"ocr_mean_confidence": ocr_mean_confidence}
                    if ocr_mean_confidence is not None
                    else {}
                ),
                "text": text,
                "terms": existing_cards.get(card_id, {}).get("terms", []),
            }
            cards.append(card)
            cards_by_doc[doc_id].append(card)

        document = {
            "doc_id": doc_id,
            "source_name": source_name,
            "source_type": "pdf",
            "module": source_document["module"],
            **({"source_role": source_role} if source_role else {}),
            **({"recommended_by": recommended_by} if recommended_by else {}),
            **(
                {"text_extraction": text_extraction, "ocr_model": ocr_model}
                if text_extraction == "paddleocr"
                else {}
            ),
            **(
                {"normalize_cjk_spacing": True}
                if normalize_cjk_spacing
                else {}
            ),
            "physical_pages": pdf.page_count,
            "pages_with_text": len(text_page_numbers),
            "pages_with_visual": len(visual_page_numbers),
            "excluded_pages": len(excluded_page_numbers),
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
                "excluded_pages": sum(document["excluded_pages"] for document in documents),
                "blank_pages": sum(document["blank_pages"] for document in documents),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
