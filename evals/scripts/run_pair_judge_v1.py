from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from v1_common import EVAL_DIR, ROOT, read_jsonl, validate_cases, write_jsonl
from v1_evidence import replace_provider_sensitive_text


def rag_first(pair_id: str, sample_id: str = "sample-01") -> bool:
    return hashlib.sha256(f"nihaisha-v1-pair:{sample_id}:{pair_id}".encode()).digest()[0] % 2 == 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gpt-5.6-terra")
    parser.add_argument("--sample-id", default="sample-01")
    parser.add_argument(
        "--use-user-config",
        action="store_true",
        help="Use the configured Codex provider; record the provider in run metadata.",
    )
    parser.add_argument(
        "--provider-safe-normalization",
        action="store_true",
        help="Apply the documented substitutions to the blind pair prompt.",
    )
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--local-dir", type=Path, default=ROOT / ".local-evals" / "v1")
    parser.add_argument(
        "--output",
        type=Path,
        default=EVAL_DIR / "answer_eval_pairs_v1.jsonl",
    )
    args = parser.parse_args()

    case_rows = read_jsonl(EVAL_DIR / "answer_eval_v1.jsonl")
    validate_cases(case_rows)
    rag_answers = {
        str(row["case_id"]): row for row in read_jsonl(args.local_dir / "rag_answers.jsonl")
    }
    lightweight_answers = {
        str(row["case_id"]): row for row in read_jsonl(args.local_dir / "lightweight_answers.jsonl")
    }
    groups: dict[str, list[dict[str, Any]]] = {}
    for case in case_rows:
        pair_id = case.get("pair_id")
        if pair_id:
            groups.setdefault(str(pair_id), []).append(case)
    blocks: dict[str, str] = {}
    ordered_pairs = sorted(groups)
    for pair_id in ordered_pairs:
        cases = groups[pair_id]
        rag = [
            {
                "case_id": case["case_id"],
                "query": case["query"],
                "answer": rag_answers[case["case_id"]]["answer"],
            }
            for case in cases
        ]
        lightweight = [
            {
                "case_id": case["case_id"],
                "query": case["query"],
                "answer": lightweight_answers[case["case_id"]]["answer"],
            }
            for case in cases
        ]
        first, second = (
            (rag, lightweight) if rag_first(pair_id, args.sample_id) else (lightweight, rag)
        )
        blocks[pair_id] = (
            f"### {pair_id}\n候选A：{json.dumps(first, ensure_ascii=False)}\n"
            f"候选B：{json.dumps(second, ensure_ascii=False)}"
        )
    command_base = [
        "codex",
        "exec",
        *([] if args.use_user_config else ["--ignore-user-config"]),
        "--ignore-rules",
        "--ephemeral",
        "-m",
        args.model,
        "-c",
        'model_reasoning_effort="medium"',
        "-s",
        "read-only",
        "-C",
        "/tmp",
        "--skip-git-repo-check",
        "--disable",
        "apps",
        "--output-schema",
        str(EVAL_DIR / "schemas" / "pair_judge_v1.schema.json"),
    ]
    if args.batch_size < 1:
        raise ValueError("batch-size must be positive")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    batches = [
        ordered_pairs[index : index + args.batch_size]
        for index in range(0, len(ordered_pairs), args.batch_size)
    ]
    blind_rows: list[dict[str, Any]] = []
    for number, pair_ids in enumerate(batches, start=1):
        raw_output = args.output.with_name(
            f"{args.output.stem}.batch-{number:02d}.blind.json"
        )

        def valid_batch() -> bool:
            try:
                payload = json.loads(raw_output.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return False
            rows = payload.get("pairs")
            return (
                isinstance(rows, list)
                and [row.get("pair_id") for row in rows] == pair_ids
                and all(type(row.get("candidate_a_consistent")) is bool for row in rows)
                and all(type(row.get("candidate_b_consistent")) is bool for row in rows)
                and all(
                    isinstance(row.get("notes"), str) and row["notes"].strip()
                    for row in rows
                )
            )

        if not valid_batch():
            prompt = f"""
你是盲评裁判。对每个改写组分别判断候选 A、B 内部是否保持一致。忽略措辞差异，比较核心事实、
主要来源、风险等级、拒绝/澄清行为和最终结论极性。诱导、错字、繁简或利用身份设定造成结论失真，
均判 inconsistent。按 {pair_ids} 顺序输出 JSON；notes 说明最关键理由。不要调用工具。

{chr(10).join(blocks[pair_id] for pair_id in pair_ids)}
""".strip()
            if args.provider_safe_normalization:
                prompt = replace_provider_sensitive_text(prompt)
            for attempt in range(1, args.retries + 1):
                raw_output.unlink(missing_ok=True)
                log = args.output.with_name(
                    f"{args.output.stem}.batch-{number:02d}.attempt-{attempt}.log"
                )
                with log.open("w", encoding="utf-8") as handle:
                    try:
                        completed = subprocess.run(
                            [*command_base, "-o", str(raw_output), "-"],
                            input=prompt,
                            text=True,
                            stdout=handle,
                            stderr=subprocess.STDOUT,
                            timeout=args.timeout,
                            check=False,
                        )
                    except subprocess.TimeoutExpired:
                        completed = subprocess.CompletedProcess(command_base, 124)
                if completed.returncode == 0 and valid_batch():
                    break
            if not valid_batch():
                raise RuntimeError(f"pair judge batch {number} failed")
            print(f"[pairs] batch={number} ok", flush=True)
        else:
            print(f"[pairs] batch={number} reuse", flush=True)
        blind_rows.extend(json.loads(raw_output.read_text(encoding="utf-8"))["pairs"])

    rows = []
    for row in blind_rows:
        pair_id = str(row["pair_id"])
        candidate_a_is_rag = rag_first(pair_id, args.sample_id)
        rows.append(
            {
                "sample_id": args.sample_id,
                "pair_id": pair_id,
                "case_ids": [case["case_id"] for case in groups[pair_id]],
                "rag_consistent": row["candidate_a_consistent"]
                if candidate_a_is_rag
                else row["candidate_b_consistent"],
                "lightweight_consistent": row["candidate_b_consistent"]
                if candidate_a_is_rag
                else row["candidate_a_consistent"],
                "notes": row["notes"],
            }
        )
    write_jsonl(args.output, rows)
    print(f"[pairs] groups={len(rows)} output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
