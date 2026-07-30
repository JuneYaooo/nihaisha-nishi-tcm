from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from v1_common import EVAL_DIR, read_jsonl, validate_cases, validate_score


MODES = ("rag", "lightweight")


def validate_pairs(
    rows: list[dict[str, Any]],
    cases: dict[str, dict[str, Any]],
    sample_ids: list[str],
) -> None:
    expected: dict[str, list[str]] = {}
    for case in cases.values():
        if case.get("pair_id"):
            expected.setdefault(str(case["pair_id"]), []).append(str(case["case_id"]))
    actual: dict[str, dict[str, list[str]]] = {sample_id: {} for sample_id in sample_ids}
    for row in rows:
        sample_id = row.get("sample_id")
        pair_id = row.get("pair_id")
        case_ids = row.get("case_ids")
        if sample_id not in actual:
            raise ValueError("invalid pair judgment sample_id")
        if not isinstance(pair_id, str) or not isinstance(case_ids, list):
            raise ValueError("invalid pair judgment row")
        if pair_id in actual[sample_id]:
            raise ValueError(f"duplicate pair judgment {sample_id}/{pair_id}")
        if type(row.get("rag_consistent")) is not bool:
            raise ValueError(f"{pair_id}: rag_consistent must be boolean")
        if type(row.get("lightweight_consistent")) is not bool:
            raise ValueError(f"{pair_id}: lightweight_consistent must be boolean")
        if not isinstance(row.get("notes"), str) or not row["notes"].strip():
            raise ValueError(f"{pair_id}: notes must be non-empty")
        actual[sample_id][pair_id] = [str(value) for value in case_ids]
    for sample_id in sample_ids:
        if actual[sample_id] != expected:
            raise ValueError(f"{sample_id}: pair judgments do not match pair_id groups in cases")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=EVAL_DIR / "answer_eval_v1.jsonl")
    parser.add_argument(
        "--judgments", type=Path, default=EVAL_DIR / "answer_eval_judgments_v1.jsonl"
    )
    parser.add_argument("--pairs", type=Path, default=EVAL_DIR / "answer_eval_pairs_v1.jsonl")
    parser.add_argument("--summary", type=Path, default=EVAL_DIR / "answer_eval_summary_v1.json")
    parser.add_argument("--run", type=Path, default=EVAL_DIR / "answer_eval_run_v1.json")
    parser.add_argument(
        "--protocol-only",
        action="store_true",
        help="Validate cases and pending-run metadata without requiring completed V1.1 judgments.",
    )
    args = parser.parse_args()

    cases = validate_cases(read_jsonl(args.cases))
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    run = json.loads(args.run.read_text(encoding="utf-8"))
    if summary.get("question_count") != len(cases):
        raise ValueError("summary question_count mismatch")
    eligible = summary.get("release_gate", {}).get("eligible")
    if type(eligible) is not bool:
        raise ValueError("summary release eligibility must be boolean")
    if args.protocol_only:
        if run.get("status") != "protocol_ready_results_pending":
            raise ValueError("protocol-only validation expects a pending run")
        if eligible:
            raise ValueError("pending V1 protocol must not be marked release-eligible")
        print(
            json.dumps(
                {"status": "ok", "cases": len(cases), "run_status": run["status"]},
                ensure_ascii=False,
            )
        )
        return 0

    current_run = run.get("current_run")
    if not isinstance(current_run, dict):
        raise ValueError("completed validation requires current_run metadata")
    sample_ids = current_run.get("sample_ids")
    if (
        not isinstance(sample_ids, list)
        or not sample_ids
        or any(not isinstance(value, str) or not value for value in sample_ids)
    ):
        raise ValueError("current_run sample_ids must be a non-empty string list")
    if len(set(sample_ids)) != len(sample_ids):
        raise ValueError("current_run sample_ids must be unique")
    if current_run.get("answer_samples_per_case") != len(sample_ids):
        raise ValueError("answer_samples_per_case does not match sample_ids")

    judgment_rows = read_jsonl(args.judgments)
    judgments: dict[str, dict[str, dict[str, Any]]] = {sample_id: {} for sample_id in sample_ids}
    for row in judgment_rows:
        sample_id = row.get("sample_id")
        case_id = str(row.get("case_id"))
        if sample_id not in judgments:
            raise ValueError(f"invalid judgment sample_id: {sample_id}")
        if case_id in judgments[sample_id]:
            raise ValueError(f"duplicate judgment {sample_id}/{case_id}")
        judgments[sample_id][case_id] = row
    for sample_id, sample in judgments.items():
        if set(sample) != set(cases):
            raise ValueError(f"{sample_id}: judgment case IDs do not match cases")
        for case_id, case in cases.items():
            row = sample[case_id]
            for mode in MODES:
                validate_score(case, row[mode], mode)
                relevance = row.get(f"{mode}_retrieval_relevance")
                if not isinstance(relevance, list) or any(
                    not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 3
                    for value in relevance
                ):
                    raise ValueError(f"{sample_id}/{case_id}/{mode}: invalid retrieval relevance")
    pair_rows = read_jsonl(args.pairs)
    validate_pairs(pair_rows, cases, sample_ids)
    print(
        json.dumps(
            {
                "status": "ok",
                "cases": len(cases),
                "samples": len(sample_ids),
                "judgments": len(judgment_rows),
                "pair_observations": len(pair_rows),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
