from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from v1_common import EVAL_DIR, ROOT, read_jsonl, validate_cases

sys.path.insert(0, str(ROOT))

from nihaisha_kg.pdf_vector import LocalVectorStore, create_embedding_backend_for_db  # noqa: E402


def compact_result(row: dict[str, Any], rank: int) -> dict[str, Any]:
    return {
        "rank": rank,
        "paragraph_id": str(row.get("paragraph_id", "")),
        "source_path": str(row.get("source_path", "")),
        "title": str(row.get("title", "")),
        "page_start": row.get("page_start"),
        "page_end": row.get("page_end"),
        "text": str(row.get("text", "")).strip()[:1600],
        "score": row.get("score"),
        "retrieval_sources": row.get("retrieval_sources", []),
        "source_layer": row.get("source_layer", ""),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=EVAL_DIR / "answer_eval_v1.jsonl")
    parser.add_argument("--db", type=Path, default=ROOT / "data/pdf_rag_bge_m3/rag.sqlite")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / ".local-evals/v1/rag_retrieval.jsonl",
    )
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument(
        "--mode", choices=("text", "vector", "knowledge", "graph", "hybrid"), default="hybrid"
    )
    args = parser.parse_args()

    cases = read_jsonl(args.cases)
    validate_cases(cases)
    backend = create_embedding_backend_for_db(args.db)
    store = LocalVectorStore(args.db, embedding_backend=backend)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for index, case in enumerate(cases, start=1):
            rows = store.search(str(case["query"]), limit=args.limit, mode=args.mode)
            payload = {
                "case_id": case["case_id"],
                "query": case["query"],
                "results": [
                    compact_result(dict(row), rank)
                    for rank, row in enumerate(rows[: args.limit], start=1)
                ],
            }
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            print(f"[{index}/{len(cases)}] {case['case_id']} results={len(rows)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
