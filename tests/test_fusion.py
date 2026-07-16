from __future__ import annotations

import copy
import unittest

from nihaisha_kg.fusion import fuse_ranked_channels, merge_unique


def hit(paragraph_id: str, raw_score: float, source: str) -> dict[str, object]:
    return {
        "paragraph_id": paragraph_id,
        "title": f"title-{paragraph_id}",
        "score": raw_score,
        "vector_score": raw_score if source == "vector" else 0.0,
        "text_score": raw_score if source == "text" else 0.0,
        "knowledge_score": raw_score if source == "knowledge" else 0.0,
        "retrieval_sources": [source],
        "matched_units": [],
        "matched_knowledge_units": [],
        "matched_text_terms": [],
        "unit_types": [],
    }


class FusionTests(unittest.TestCase):
    def test_merge_unique_handles_nested_json_values_in_stable_order(self) -> None:
        left = [{"b": [2, 1], "a": "值"}, "桂枝"]

        merged = merge_unique(
            left,
            [{"a": "值", "b": [2, 1]}, ["nested", {"x": 1}], "桂枝"],
        )

        self.assertEqual(merged, [left[0], "桂枝", ["nested", {"x": 1}]])

    def test_cross_channel_rank_beats_incomparable_single_channel_raw_scores(self) -> None:
        shared_vector = hit("shared", 0.2, "vector")
        shared_text = hit("shared", 0.1, "text")
        vector_only = hit("vector-only", 99.0, "vector")
        text_only = hit("text-only", 500.0, "text")

        results = fuse_ranked_channels(
            {
                "vector": [shared_vector, vector_only],
                "text": [shared_text, text_only],
            },
            limit=3,
        )

        self.assertEqual(results[0]["paragraph_id"], "shared")
        self.assertEqual(results[0]["channel_ranks"], {"text": 1, "vector": 1})
        self.assertGreater(results[0]["fusion_score"], results[1]["fusion_score"])
        self.assertEqual(results[0]["score"], results[0]["fusion_score"])
        self.assertEqual(results[0]["raw_channel_scores"], {"text": 0.1, "vector": 0.2})

    def test_text_and_knowledge_merge_sources_and_unique_knowledge_unit(self) -> None:
        unit = {"knowledge_unit_id": "ku-1", "unit_type": "dosage", "object": "5克"}
        text_result = hit("shared", 8.0, "text")
        text_result["retrieval_sources"] = ["text", "shared-source"]
        text_result["matched_knowledge_units"] = [unit]
        knowledge_result = hit("shared", 900.0, "knowledge")
        knowledge_result["matched_knowledge_units"] = [dict(unit)]

        results = fuse_ranked_channels(
            {"text": [text_result], "knowledge": [knowledge_result]},
            limit=1,
        )

        self.assertEqual(results[0]["retrieval_sources"], ["knowledge", "shared-source", "text"])
        self.assertEqual(results[0]["matched_knowledge_units"], [unit])
        self.assertEqual(results[0]["text_score"], 8.0)
        self.assertEqual(results[0]["knowledge_score"], 900.0)

    def test_equal_results_use_paragraph_id_as_stable_tie_breaker(self) -> None:
        results = fuse_ranked_channels(
            {"text": [hit("p-b", 1.0, "text"), hit("p-a", 1.0, "text")]},
            limit=2,
        )

        self.assertEqual([item["paragraph_id"] for item in results], ["p-b", "p-a"])

        tied = fuse_ranked_channels(
            {
                "text": [hit("p-b", 1.0, "text")],
                "vector": [hit("p-a", 1.0, "vector")],
            },
            limit=2,
        )
        self.assertEqual([item["paragraph_id"] for item in tied], ["p-a", "p-b"])

    def test_empty_paragraph_ids_are_ignored(self) -> None:
        results = fuse_ranked_channels(
            {"text": [hit("", 9.0, "text"), hit("kept", 1.0, "text")]},
            limit=4,
        )

        self.assertEqual([item["paragraph_id"] for item in results], ["kept"])

    def test_duplicate_paragraph_in_one_channel_contributes_only_its_best_rank(self) -> None:
        results = fuse_ranked_channels(
            {
                "text": [hit("p-a", 1.0, "text"), hit("p-a", 500.0, "text")],
                "vector": [hit("p-b", 1.0, "vector")],
            },
            limit=2,
        )

        self.assertEqual(results[0]["paragraph_id"], "p-a")
        self.assertEqual(results[0]["channel_ranks"], {"text": 1})
        self.assertEqual(results[0]["raw_channel_scores"], {"text": 1.0})
        self.assertEqual(results[0]["fusion_score"], results[1]["fusion_score"])

    def test_duplicate_list_fields_are_merged_once_in_first_seen_order(self) -> None:
        shared_dict = {"b": [2, 1], "a": "值"}
        text_result = hit("shared", 1.0, "text")
        text_result.update(
            {
                "matched_units": [shared_dict, ["nested", {"x": 1}]],
                "matched_knowledge_units": [{"id": "ku-1"}],
                "matched_text_terms": ["桂枝", "桂枝"],
                "unit_types": ["formula", "formula"],
            }
        )
        vector_result = hit("shared", 1.0, "vector")
        vector_result.update(
            {
                "matched_units": [{"a": "值", "b": [2, 1]}, ["nested", {"x": 1}], {"id": 2}],
                "matched_knowledge_units": [{"id": "ku-1"}, {"id": "ku-2"}],
                "matched_text_terms": ["桂枝", "麻黄"],
                "unit_types": ["formula", "clinical"],
            }
        )

        result = fuse_ranked_channels(
            {"vector": [vector_result], "text": [text_result]},
            limit=1,
        )[0]

        self.assertEqual(result["matched_units"], [shared_dict, ["nested", {"x": 1}], {"id": 2}])
        self.assertEqual(result["matched_knowledge_units"], [{"id": "ku-1"}, {"id": "ku-2"}])
        self.assertEqual(result["matched_text_terms"], ["桂枝", "麻黄"])
        self.assertEqual(result["unit_types"], ["formula", "clinical"])

    def test_inputs_are_not_mutated_and_nonpositive_limit_returns_empty(self) -> None:
        channels = {
            "vector": [hit("p-a", 0.9, "vector")],
            "text": [hit("p-a", 7.0, "text")],
        }
        original = copy.deepcopy(channels)

        self.assertEqual(fuse_ranked_channels(channels, limit=0), [])
        self.assertEqual(fuse_ranked_channels({}, limit=3), [])
        fuse_ranked_channels(channels, limit=1)

        self.assertEqual(channels, original)

    def test_channel_weight_override_changes_rank_contribution(self) -> None:
        results = fuse_ranked_channels(
            {
                "text": [hit("text-result", 1.0, "text")],
                "vector": [hit("vector-result", 1.0, "vector")],
            },
            limit=2,
            channel_weights={"text": 2.0},
        )

        self.assertEqual(results[0]["paragraph_id"], "text-result")


if __name__ == "__main__":
    unittest.main()
