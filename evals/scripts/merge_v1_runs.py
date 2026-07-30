from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from v1_common import EVAL_DIR, read_jsonl, write_jsonl


def merge_sample_files(paths: list[Path], *, id_field: str) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    sample_ids: set[str] = set()
    for path in paths:
        rows = read_jsonl(path)
        file_sample_ids = {str(row.get("sample_id", "")) for row in rows}
        if len(file_sample_ids) != 1 or "" in file_sample_ids:
            raise ValueError(f"{path}: expected exactly one non-empty sample_id")
        sample_id = next(iter(file_sample_ids))
        if sample_id in sample_ids:
            raise ValueError(f"duplicate sample_id across files: {sample_id}")
        sample_ids.add(sample_id)
        for row in rows:
            item_id = str(row.get(id_field, ""))
            key = (sample_id, item_id)
            if not item_id or key in seen:
                raise ValueError(f"{path}: invalid or duplicate {sample_id}/{item_id}")
            seen.add(key)
            merged.append(row)
    return merged


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--judgments", type=Path, nargs="+", required=True)
    parser.add_argument("--pairs", type=Path, nargs="+", required=True)
    parser.add_argument(
        "--judgments-output",
        type=Path,
        default=EVAL_DIR / "answer_eval_judgments_v1.jsonl",
    )
    parser.add_argument(
        "--pairs-output",
        type=Path,
        default=EVAL_DIR / "answer_eval_pairs_v1.jsonl",
    )
    args = parser.parse_args()

    judgments = merge_sample_files(args.judgments, id_field="case_id")
    pairs = merge_sample_files(args.pairs, id_field="pair_id")
    judgment_samples = {str(row["sample_id"]) for row in judgments}
    pair_samples = {str(row["sample_id"]) for row in pairs}
    if judgment_samples != pair_samples:
        raise ValueError("judgment and pair sample IDs differ")
    write_jsonl(args.judgments_output, judgments)
    write_jsonl(args.pairs_output, pairs)
    print(f"samples={len(judgment_samples)} judgments={len(judgments)} pairs={len(pairs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
