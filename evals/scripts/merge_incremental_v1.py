from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from v1_common import EVAL_DIR, ROOT, read_jsonl, write_jsonl


OLD_LIMITS = {"K": 20, "I": 20, "C": 15, "R": 20, "S": 25}


def is_old(case_id: str) -> bool:
    return int(case_id[1:]) <= OLD_LIMITS[case_id[0]]


def merge_by_case(
    case_ids: list[str], old_path: Path, new_path: Path, output: Path
) -> None:
    old_rows = {
        str(row["case_id"]): row
        for row in read_jsonl(old_path)
        if is_old(str(row["case_id"]))
    }
    new_rows = {str(row["case_id"]): row for row in read_jsonl(new_path)}
    overlap = set(old_rows) & set(new_rows)
    if overlap:
        raise ValueError(f"overlapping old/new case IDs: {sorted(overlap)}")
    rows: dict[str, dict[str, Any]] = {**old_rows, **new_rows}
    if set(rows) != set(case_ids):
        missing = set(case_ids) - set(rows)
        extra = set(rows) - set(case_ids)
        raise ValueError(f"case mismatch missing={sorted(missing)} extra={sorted(extra)}")
    write_jsonl(output, [rows[case_id] for case_id in case_ids])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample-id", required=True)
    parser.add_argument("--kind", choices=("answers", "judgments"), required=True)
    args = parser.parse_args()
    sample = ROOT / ".local-evals" / "v1" / args.sample_id
    case_ids = [str(row["case_id"]) for row in read_jsonl(EVAL_DIR / "answer_eval_v1.jsonl")]
    if args.kind == "answers":
        for mode in ("rag", "lightweight"):
            merge_by_case(
                case_ids,
                sample / f"{mode}_answers.jsonl",
                sample / f"new_{mode}_answers.jsonl",
                sample / f"{mode}_answers.jsonl",
            )
    else:
        merge_by_case(
            case_ids,
            sample / "answer_judgments.jsonl",
            sample / "new_answer_judgments.jsonl",
            sample / "answer_judgments.jsonl",
        )
    print({"sample_id": args.sample_id, "kind": args.kind, "cases": len(case_ids)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
