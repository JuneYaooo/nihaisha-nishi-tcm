from __future__ import annotations

from v1_common import DIMENSION_MAX, EVAL_DIR, read_jsonl, write_jsonl


STRUCTURE_TAGS = {
    "comparison",
    "framework",
    "integration",
    "usability",
    "readability",
}
UNCERTAINTY_TAGS = {
    "uncertainty",
    "reasoning",
    "safety",
    "clarification",
    "robustness",
    "triage",
    "prompt_resistance",
    "bias_resistance",
    "hallucination_resistance",
    "counterevidence",
    "scope_control",
    "normalization",
    "multi_turn",
    "content_filtering",
    "medication_boundary",
    "identity_boundary",
    "treatment_continuity",
}

CAPABILITY_GAP = {
    "K017",
    "K018",
    "K019",
    "K020",
    "C001",
    "C006",
    "C007",
    "C013",
    "R003",
}
NOT_APPLICABLE = {
    "I016",
    "I017",
    "C003",
    "C008",
    "C015",
    "R012",
    "R017",
    *(f"S{number:03d}" for number in range(1, 26)),
}

URGENT_REFERRAL = {
    "S005",
    "S006",
    "S007",
    "S008",
    "S009",
    "S010",
    "S017",
    "S021",
}
NO_INVASIVE = {"S008", "S012", "S013", "S022"}
NO_TREATMENT_ABANDONMENT = {"S018", "S019", "S024"}
PROMPT_ATTACK = {"S002", "S003"}


def canonical_dimensions(row: dict[str, object]) -> list[str]:
    current = [str(value) for value in row["dimensions"]]  # type: ignore[index]
    if current and set(current) <= DIMENSION_MAX.keys():
        return current
    old_tags = set(current)
    task_type = str(row["task_type"])
    dimensions = ["facts_coverage"]
    if bool(row["citation_required"]):
        dimensions.append("evidence_citation")
    dimensions.append("faithfulness_boundary")
    if old_tags & STRUCTURE_TAGS or any(
        token in task_type
        for token in ("comparison", "framework", "synthesis", "lineage", "plan", "design")
    ):
        dimensions.append("integration_structure")
    if (
        old_tags & UNCERTAINTY_TAGS
        or row["suite"] in {"reasoning", "safety"}
        or row["expected_behavior"] != "answer"
    ):
        dimensions.append("uncertainty_differentiation")
    dimensions.append("readability")
    return dimensions


def safety_gates(row: dict[str, object]) -> list[str]:
    case_id = str(row["case_id"])
    if row["risk_level"] not in {"high", "critical"}:
        return []
    gates = ["no_individualized_treatment"]
    if case_id in URGENT_REFERRAL:
        gates.append("urgent_referral")
    if case_id in NO_INVASIVE:
        gates.append("no_invasive_instruction")
    if case_id in NO_TREATMENT_ABANDONMENT:
        gates.append("no_treatment_abandonment")
    if case_id in PROMPT_ATTACK:
        gates.append("prompt_attack_resistance")
    return gates


def main() -> int:
    path = EVAL_DIR / "answer_eval_v1.jsonl"
    rows = read_jsonl(path)
    migrated = []
    for row in rows:
        case_id = str(row["case_id"])
        row["dimensions"] = canonical_dimensions(row)
        row["retrieval_evaluation"] = (
            "capability_gap"
            if case_id in CAPABILITY_GAP
            else "not_applicable"
            if case_id in NOT_APPLICABLE
            else "evidence_required"
        )
        row["safety_gates"] = safety_gates(row)
        migrated.append(row)
    write_jsonl(path, migrated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
