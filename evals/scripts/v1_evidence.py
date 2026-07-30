from __future__ import annotations

import math
import re
from typing import Any

from v1_common import ROOT


STOP_CHARS = set(
    "，。！？；：、（）《》“”‘’ \t\r\n"
    "请把给出说明整理比较课程知识库相关来源出处一个哪些如何是否中的"
)


def chunks(text: str, size: int = 750) -> list[tuple[int, str]]:
    lines = text.splitlines()
    result: list[tuple[int, str]] = []
    start = 1
    buffer: list[str] = []
    length = 0
    for number, line in enumerate(lines, start=1):
        if buffer and (length + len(line) > size or (line.startswith("## ") and length > 300)):
            result.append((start, "\n".join(buffer)))
            start = number
            buffer = []
            length = 0
        if not buffer:
            start = number
        buffer.append(line)
        length += len(line) + 1
    if buffer:
        result.append((start, "\n".join(buffer)))
    return result


def grams(text: str) -> set[str]:
    cleaned = "".join(character for character in text if character not in STOP_CHARS)
    result = {
        cleaned[index : index + width]
        for width in range(2, 6)
        for index in range(max(0, len(cleaned) - width + 1))
    }
    result.update(
        token.lower()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]{2,8}", text)
        if token not in STOP_CHARS
    )
    return result


def build_reference_index() -> tuple[list[dict[str, Any]], dict[str, int]]:
    records: list[dict[str, Any]] = []
    document_frequency: dict[str, int] = {}
    for path in sorted((ROOT / "references").rglob("*.md")):
        relative = path.relative_to(ROOT).as_posix()
        for line, text in chunks(path.read_text(encoding="utf-8", errors="replace")):
            if len(text.strip()) < 40:
                continue
            record_grams = grams(text)
            records.append({"path": relative, "line": line, "text": text, "grams": record_grams})
            for gram in record_grams:
                document_frequency[gram] = document_frequency.get(gram, 0) + 1
    return records, document_frequency


def lightweight_evidence(
    case: dict[str, Any],
    index: list[dict[str, Any]],
    document_frequency: dict[str, int],
    *,
    oracle_targets: bool,
    limit: int = 6,
) -> list[dict[str, Any]]:
    query_grams = grams(str(case["query"]))
    allowed_paths = {str(value) for value in case.get("reference_targets", [])}
    allowed_paths.add("references/index.md")
    scored: list[tuple[float, dict[str, Any]]] = []
    for record in index:
        path = str(record["path"])
        if oracle_targets and path not in allowed_paths:
            continue
        record_grams = record["grams"]
        overlap = query_grams & record_grams
        if not overlap:
            continue
        score = sum(
            len(term) * math.log((len(index) + 1) / (document_frequency.get(term, 0) + 1))
            for term in overlap
        )
        score /= math.sqrt(max(1, len(record_grams)))
        scored.append((score, record))
    selected = sorted(scored, key=lambda item: item[0], reverse=True)[:limit]
    return [
        {
            "rank": rank,
            "path": record["path"],
            "line": record["line"],
            "text": str(record["text"])[:700],
        }
        for rank, (_, record) in enumerate(selected, start=1)
    ]


def render_lightweight_evidence(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "未检索到轻量证据。"
    return "\n\n".join(
        f"rank={row['rank']} path={row['path']} line={row['line']}\n{str(row['text'])[:500]}"
        for row in rows
    )


def render_rag_evidence(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "未检索到 RAG 证据。"
    return "\n\n".join(
        "rank={rank} paragraph_id={paragraph_id} source={source_path} page={page_start} "
        "layer={source_layer}\n{text}".format(**{**row, "text": str(row.get("text", ""))[:500]})
        for row in rows
    )
