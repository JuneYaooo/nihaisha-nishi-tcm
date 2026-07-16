from __future__ import annotations

import copy
import json
from collections.abc import Mapping, Sequence


def merge_unique(left: list[object], right: Sequence[object]) -> list[object]:
    seen = {json.dumps(value, ensure_ascii=False, sort_keys=True) for value in left}
    merged = list(left)
    for value in right:
        key = json.dumps(value, ensure_ascii=False, sort_keys=True)
        if key not in seen:
            seen.add(key)
            merged.append(value)
    return merged


def fuse_ranked_channels(
    channels: Mapping[str, Sequence[dict[str, object]]],
    limit: int,
    rank_constant: int = 60,
    channel_weights: Mapping[str, float] | None = None,
) -> list[dict[str, object]]:
    if limit <= 0 or not channels:
        return []

    weights = {
        "vector": 1.0,
        "text": 1.0,
        "knowledge": 1.0,
        **(channel_weights or {}),
    }
    fused: dict[str, dict[str, object]] = {}
    merge_fields = (
        "matched_units",
        "matched_knowledge_units",
        "matched_graph_relations",
        "matched_text_terms",
        "unit_types",
    )

    for channel in sorted(channels):
        seen_paragraph_ids: set[str] = set()
        for rank, result in enumerate(channels[channel], start=1):
            paragraph_id = str(result.get("paragraph_id", ""))
            if not paragraph_id or paragraph_id in seen_paragraph_ids:
                continue
            seen_paragraph_ids.add(paragraph_id)

            contribution = weights.get(channel, 1.0) / (rank_constant + rank)
            current = fused.get(paragraph_id)
            if current is None:
                current = copy.deepcopy(result)
                current["raw_channel_scores"] = {}
                current["channel_ranks"] = {}
                current["fusion_score"] = 0.0
                current["retrieval_sources"] = []
                for field in merge_fields:
                    current[field] = []
                fused[paragraph_id] = current

            raw_channel_scores = current["raw_channel_scores"]
            channel_ranks = current["channel_ranks"]
            assert isinstance(raw_channel_scores, dict)
            assert isinstance(channel_ranks, dict)
            raw_channel_scores[channel] = float(result.get("score", 0.0))
            channel_ranks[channel] = rank
            current["fusion_score"] = float(current["fusion_score"]) + contribution
            current["score"] = current["fusion_score"]

            sources = list(current["retrieval_sources"])
            current["retrieval_sources"] = sorted(
                str(source)
                for source in merge_unique(sources, list(result.get("retrieval_sources", [channel])))
            )
            for field in merge_fields:
                current[field] = merge_unique(
                    list(current[field]),
                    list(result.get(field, [])),
                )
            for score_field in ("vector_score", "text_score", "knowledge_score", "graph_score"):
                if score_field in result:
                    current[score_field] = max(
                        float(current.get(score_field, 0.0)),
                        float(result.get(score_field, 0.0)),
                    )

    ranked = sorted(
        fused.values(),
        key=lambda item: (
            -float(item["fusion_score"]),
            -len(item["channel_ranks"]),
            -max(item["raw_channel_scores"].values(), default=0.0),
            str(item["paragraph_id"]),
        ),
    )
    return ranked[:limit]
