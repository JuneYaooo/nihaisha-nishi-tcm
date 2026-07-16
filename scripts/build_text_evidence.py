#!/usr/bin/env python3
"""Build section-level evidence cards from a recommended supplemental DOC file."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile


SOURCE_ROLE = "ni-recommended-supplement"
RECOMMENDED_BY = "倪海厦"
MODULE = "shanghan"
ARCHIVE_NAME = "02.大塚敬節傷寒論解說.doc"
SEARCH_ALIASES = [
    "大塚敬節傷寒論解說",
    "大塚敬节伤寒论解说",
    "大塚敬節傷寒論條文",
    "大塚敬节伤寒论条文",
]
HEADING_RE = re.compile(
    r"^(太陽病[上中下]篇|陽明病篇|少陽病篇|太陰病篇|少陰病篇|"
    r"厥陰病篇|辨.+篇)"
)
CLAUSE_RE = re.compile(r"^(\d+)[.．]\s*(.*)$")
PRIVACY_RE = re.compile(
    r"https?://|www\.|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|"
    r"(?:电话|電話|手机|手機|微信|QQ|账号|帳號|身份证|身分證)\s*[:：]?\s*\w+",
    re.IGNORECASE,
)


def extract_doc_text(source: Path, libreoffice: Path) -> str:
    """Extract a legacy Word document through LibreOffice's text filter."""
    with tempfile.TemporaryDirectory(prefix="text-evidence-") as tmp_dir:
        result = subprocess.run(
            [
                str(libreoffice),
                "--headless",
                "--convert-to",
                "txt:Text",
                "--outdir",
                tmp_dir,
                str(source),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        output = Path(tmp_dir) / f"{source.stem}.txt"
        if not output.exists():
            raise RuntimeError(f"LibreOffice did not create {output}: {result.stderr}")
        return output.read_text(encoding="utf-8-sig")


def normalize_text(text: str) -> str:
    """Normalize conversion artifacts without silently rewriting source wording."""
    text = text.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u2028", "\n").replace("\xa0", " ")
    lines = []
    blank = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if re.fullmatch(r"(?:PAGE\s+)?\\?\*?\s*MERGEFORMAT\s*\d*", line):
            continue
        if not line:
            if lines and not blank:
                lines.append("")
            blank = True
            continue
        lines.append(line)
        blank = False
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines) + "\n"


def parse_sections(text: str) -> tuple[str, list[dict]]:
    """Split the source into its preface and one coherent card per numbered clause."""
    lines = text.splitlines()
    if not lines:
        raise ValueError("No text extracted from source")
    internal_title = lines[0]
    sections: list[dict] = []
    preface: list[str] = []
    current_heading = ""
    current_clause: dict | None = None

    def flush_clause() -> None:
        nonlocal current_clause
        if current_clause is None:
            return
        current_clause["text"] = "".join(current_clause.pop("parts")).strip()
        sections.append(current_clause)
        current_clause = None

    for raw_line in lines[1:]:
        line = raw_line.strip()
        if not line:
            continue
        heading_match = HEADING_RE.match(line)
        if heading_match:
            flush_clause()
            if preface:
                preface_title = preface[0]
                sections.append(
                    {
                        "clause_number": None,
                        "heading": preface_title,
                        "locator": preface_title,
                        "text": "\n".join(preface),
                    }
                )
                preface = []
            current_heading = heading_match.group(1)
            continue
        clause_match = CLAUSE_RE.match(line)
        if clause_match:
            flush_clause()
            number = int(clause_match.group(1))
            current_clause = {
                "clause_number": number,
                "heading": current_heading,
                "locator": f"{current_heading} · 第{number}条",
                "parts": [line],
            }
            continue
        if current_clause is not None:
            current_clause["parts"].append(line)
        elif not current_heading:
            preface.append(line)

    flush_clause()
    if preface:
        preface_title = preface[0]
        sections.insert(
            0,
            {
                "clause_number": None,
                "heading": preface_title,
                "locator": preface_title,
                "text": "\n".join(preface),
            },
        )
    return internal_title, sections


def build(source: Path, output_dir: Path, libreoffice: Path) -> dict:
    source_bytes = source.read_bytes()
    doc_id = hashlib.sha256(source_bytes).hexdigest()[:12]
    normalized = normalize_text(extract_doc_text(source, libreoffice))
    privacy_hits = sorted(set(PRIVACY_RE.findall(normalized)))
    if privacy_hits:
        raise ValueError(f"Potential private or promotional data found: {privacy_hits}")
    internal_title, sections = parse_sections(normalized)
    clause_numbers = [section["clause_number"] for section in sections if section["clause_number"]]
    if clause_numbers != list(range(1, 183)):
        raise ValueError("Expected a complete, ordered sequence of clauses 1 through 182")

    output_dir.mkdir(parents=True, exist_ok=True)
    source_text_dir = output_dir / "source-text"
    source_text_dir.mkdir(exist_ok=True)
    (source_text_dir / f"{doc_id}.txt").write_text(normalized, encoding="utf-8")

    cards = []
    for section_number, section in enumerate(sections, start=1):
        section_id = f"s{section_number:03d}"
        cards.append(
            {
                "card_id": f"{doc_id}-{section_id}",
                "doc_id": doc_id,
                "source_name": internal_title,
                "internal_title": internal_title,
                "archive_name": ARCHIVE_NAME,
                "aliases": SEARCH_ALIASES,
                "source_type": "doc",
                "source_role": SOURCE_ROLE,
                "recommended_by": RECOMMENDED_BY,
                "module": MODULE,
                "section_id": section_id,
                "section_number": section_number,
                "clause_number": section["clause_number"],
                "heading": section["heading"],
                "locator": section["locator"],
                "text_method": "libreoffice-text",
                "text": section["text"],
                "terms": [],
                "citation": f"text-evidence:{doc_id}#{section_id}",
            }
        )
    with (output_dir / "evidence-cards.jsonl").open("w", encoding="utf-8") as handle:
        for card in cards:
            handle.write(json.dumps(card, ensure_ascii=False, separators=(",", ":")) + "\n")

    manifest = {
        "doc_id": doc_id,
        "source_name": internal_title,
        "archive_name": ARCHIVE_NAME,
        "source_type": "doc",
        "source_role": SOURCE_ROLE,
        "recommended_by": RECOMMENDED_BY,
        "module": MODULE,
        "sections": len(cards),
        "numbered_clauses": len(clause_numbers),
        "characters": len(normalized),
        "text_method": "libreoffice-text",
        "source_text": f"source-text/{doc_id}.txt",
        "sha256": hashlib.sha256(source_bytes).hexdigest(),
        "privacy_scan": "passed",
        "content_note": (
            "压缩包文件名作《大塚敬節傷寒論解說》，内题作《大塚敬節傷寒論條文》；"
            "实质内容为张仲景自序及182条伤寒条文节录/提示，未见系统解说正文。"
        ),
    }
    (output_dir / "source-manifest.json").write_text(
        json.dumps([manifest], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Legacy DOC source to extract")
    parser.add_argument("--output-dir", type=Path, default=Path("references/text-evidence"))
    parser.add_argument(
        "--libreoffice",
        type=Path,
        default=Path("libreoffice"),
    )
    args = parser.parse_args()
    manifest = build(args.source, args.output_dir, args.libreoffice)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
