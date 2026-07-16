from __future__ import annotations

import hashlib
import json
import math
import re
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from nihaisha_kg.assets import PRODUCTION_ASSETS
from nihaisha_kg.evaluation import (
    EvalCase,
    aggregate_metrics,
    evaluate_database,
    evaluate_ranked_ids,
    load_eval_cases,
    MAX_EVALUATION_JSONL_LINE_BYTES,
    MAX_EVALUATION_QUERY_CHARS,
    MAX_EVALUATION_ID_LIST_ITEMS,
)
from nihaisha_kg import evaluation


class EvaluationTests(unittest.TestCase):
    def assert_invalid_eval_jsonl(self, content: str, physical_line: int = 1) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "eval.jsonl"
            path.write_text(content, encoding="utf-8")

            with self.assertRaises(ValueError) as caught:
                load_eval_cases(path)

            self.assertIn(f"{path}:{physical_line}:", str(caught.exception))

    def test_load_eval_cases_reads_jsonl_record(self) -> None:
        record = {
            "case_id": "case-1",
            "query": "query",
            "task_type": "source_lookup",
            "relevant_paragraph_ids": ["p2", "p4"],
            "forbidden_paragraph_ids": ["p8"],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "eval.jsonl"
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")

            cases = load_eval_cases(path)

        self.assertEqual(len(cases), 1)
        self.assertIsInstance(cases[0], EvalCase)
        self.assertEqual(cases[0].relevant_paragraph_ids, ("p2", "p4"))
        self.assertEqual(cases[0].forbidden_paragraph_ids, ("p8",))

    def test_evaluate_ranked_ids_reports_retrieval_metrics(self) -> None:
        case = EvalCase(
            case_id="case-1",
            query="query",
            task_type="comparison",
            relevant_paragraph_ids=("p2", "p4"),
            forbidden_paragraph_ids=("p8",),
        )

        metrics = evaluate_ranked_ids(case, ["p8", "p2", "p3", "p4"], k_values=(1, 3, 5))

        self.assertEqual(metrics["hit_at_1"], 0.0)
        self.assertEqual(metrics["recall_at_3"], 0.5)
        self.assertEqual(metrics["recall_at_5"], 1.0)
        self.assertEqual(metrics["reciprocal_rank"], 0.5)
        self.assertEqual(metrics["forbidden_hits_at_5"], 1.0)
        self.assertEqual(metrics["context_precision_at_5"], 0.5)
        expected_ndcg = (1 / math.log2(3) + 1 / math.log2(5)) / (1 + 1 / math.log2(3))
        self.assertAlmostEqual(metrics["ndcg_at_5"], expected_ndcg)

    def test_load_eval_cases_rejects_malformed_or_invalid_records_with_location(self) -> None:
        valid = {
            "case_id": "case-1",
            "query": "query",
            "task_type": "source_lookup",
            "relevant_paragraph_ids": ["p1"],
            "forbidden_paragraph_ids": [],
        }
        invalid_records = {
            "non-object row": [],
            "missing field": {},
            "scalar relevant IDs": {**valid, "relevant_paragraph_ids": "p1"},
            "scalar forbidden IDs": {**valid, "forbidden_paragraph_ids": "p2"},
            "empty relevant IDs": {**valid, "relevant_paragraph_ids": []},
            "duplicate relevant IDs": {**valid, "relevant_paragraph_ids": ["p1", "p1"]},
            "duplicate forbidden IDs": {**valid, "forbidden_paragraph_ids": ["p2", "p2"]},
            "empty relevant ID": {**valid, "relevant_paragraph_ids": [""]},
            "empty forbidden ID": {**valid, "forbidden_paragraph_ids": [""]},
            "overlapping IDs": {
                **valid,
                "relevant_paragraph_ids": ["p1"],
                "forbidden_paragraph_ids": ["p1"],
            },
        }
        for label, record in invalid_records.items():
            with self.subTest(label=label):
                self.assert_invalid_eval_jsonl("\n" + json.dumps(record) + "\n", physical_line=2)

        self.assert_invalid_eval_jsonl('\n{"case_id":\n', physical_line=2)
        self.assert_invalid_eval_jsonl("\n\n", physical_line=1)

    def test_load_eval_cases_rejects_invalid_scalar_fields_with_location(self) -> None:
        valid = {
            "case_id": "case-1",
            "query": "query",
            "task_type": "source_lookup",
            "relevant_paragraph_ids": ["p1"],
        }
        for field in ("case_id", "query", "task_type"):
            for value in (None, 7, ""):
                with self.subTest(field=field, value=value):
                    record = {**valid, field: value}
                    self.assert_invalid_eval_jsonl(
                        "\n" + json.dumps(record) + "\n",
                        physical_line=2,
                    )

    def test_load_eval_cases_rejects_duplicate_case_id_with_location(self) -> None:
        record = {
            "case_id": "case-1",
            "query": "query",
            "task_type": "source_lookup",
            "relevant_paragraph_ids": ["p1"],
        }
        content = json.dumps(record) + "\n\n" + json.dumps(record) + "\n"

        self.assert_invalid_eval_jsonl(content, physical_line=3)

    def test_load_eval_cases_rejects_oversized_line_before_json_decode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "eval.jsonl"
            path.write_bytes(b"{" + b"x" * MAX_EVALUATION_JSONL_LINE_BYTES + b"}\n")

            with self.assertRaisesRegex(ValueError, rf"{re.escape(str(path))}:1:.*line exceeds"):
                load_eval_cases(path)

    def test_load_eval_cases_rejects_invalid_utf8_without_echoing_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "eval.jsonl"
            path.write_bytes(b'{"case_id":"secret-' + b"\xff" + b'"}\n')

            with self.assertRaisesRegex(ValueError, rf"{re.escape(str(path))}:1: invalid UTF-8") as caught:
                load_eval_cases(path)

            self.assertNotIn("secret", str(caught.exception))

    def test_load_eval_cases_bounds_queries_ids_and_id_lists(self) -> None:
        valid = {
            "case_id": "case-1",
            "query": "query",
            "task_type": "source_lookup",
            "relevant_paragraph_ids": ["p1"],
        }
        invalid_records = {
            "query": {**valid, "query": "q" * (MAX_EVALUATION_QUERY_CHARS + 1)},
            "case id": {**valid, "case_id": "c" * 257},
            "task type": {**valid, "task_type": "t" * 257},
            "paragraph id": {**valid, "relevant_paragraph_ids": ["p" * 257]},
            "relevant count": {
                **valid,
                "relevant_paragraph_ids": [f"p-{index}" for index in range(MAX_EVALUATION_ID_LIST_ITEMS + 1)],
            },
            "forbidden count": {
                **valid,
                "forbidden_paragraph_ids": [f"x-{index}" for index in range(MAX_EVALUATION_ID_LIST_ITEMS + 1)],
            },
        }
        for label, record in invalid_records.items():
            with self.subTest(label=label):
                self.assert_invalid_eval_jsonl(json.dumps(record, ensure_ascii=False) + "\n")

    def test_load_eval_cases_enforces_aggregate_file_id_item_and_character_budgets(self) -> None:
        rows = [
            {
                "case_id": f"case-{index}",
                "query": "query",
                "task_type": "source",
                "relevant_paragraph_ids": [f"paragraph-{index}"],
            }
            for index in range(4)
        ]
        content = "".join(json.dumps(row) + "\n" for row in rows)
        cases = (
            ("MAX_EVALUATION_FILE_BYTES", len(content.encode("utf-8")) - 1, "file exceeds"),
            ("MAX_EVALUATION_TOTAL_ID_ITEMS", 3, "cumulative ID item"),
            ("MAX_EVALUATION_TOTAL_ID_CHARS", 20, "cumulative ID character"),
        )
        for constant, budget, message in cases:
            with self.subTest(constant=constant):
                with tempfile.TemporaryDirectory() as tmpdir:
                    path = Path(tmpdir) / "eval.jsonl"
                    path.write_text(content, encoding="utf-8")
                    with patch.object(evaluation, constant, budget):
                        with self.assertRaisesRegex(ValueError, message) as caught:
                            load_eval_cases(path)
                    self.assertIn(str(path), str(caught.exception))

    def test_load_eval_cases_localizes_surrogates_and_huge_integer_errors(self) -> None:
        valid = {
            "case_id": "case-1",
            "query": "query",
            "task_type": "source",
            "relevant_paragraph_ids": ["p1"],
        }
        surrogate = json.dumps({**valid, "query": "bad\ud800value"}) + "\n"
        huge_integer = json.dumps(valid)[:-1] + ', "ignored": ' + "9" * 5000 + "}\n"
        self.assert_invalid_eval_jsonl(surrogate)
        self.assert_invalid_eval_jsonl(huge_integer)

    def test_evaluate_ranked_ids_deduplicates_at_first_occurrence(self) -> None:
        case = EvalCase(
            case_id="case-1",
            query="query",
            task_type="source_lookup",
            relevant_paragraph_ids=("p2",),
        )

        metrics = evaluate_ranked_ids(case, ["p8", "p8", "p2"], k_values=(2,))

        self.assertEqual(metrics["hit_at_2"], 1.0)
        self.assertEqual(metrics["reciprocal_rank"], 0.5)

    def test_evaluate_ranked_ids_treats_empty_relevance_as_vacuously_complete(self) -> None:
        case = EvalCase(
            case_id="case-1",
            query="query",
            task_type="source_lookup",
            relevant_paragraph_ids=(),
        )

        metrics = evaluate_ranked_ids(case, ["p1"], k_values=(5,))

        self.assertEqual(metrics["recall_at_5"], 1.0)
        self.assertEqual(metrics["context_precision_at_5"], 1.0)
        self.assertEqual(metrics["ndcg_at_5"], 1.0)

    def test_aggregate_metrics_handles_empty_and_sparse_rows(self) -> None:
        self.assertEqual(aggregate_metrics([]), {})
        self.assertEqual(
            aggregate_metrics([{"hit_at_1": 1.0}, {"recall_at_5": 0.5}]),
            {"hit_at_1": 0.5, "recall_at_5": 0.25},
        )

    def test_evaluate_database_searches_each_case_and_aggregates(self) -> None:
        cases = [
            EvalCase("one", "first", "lookup", ("p1",)),
            EvalCase("two", "second", "lookup", ("p3",), ("p9",)),
        ]

        class FakeStore:
            def __init__(self) -> None:
                self.calls: list[tuple[str, int, str]] = []

            def search(self, query: str, limit: int, mode: str) -> list[dict[str, object]]:
                self.calls.append((query, limit, mode))
                return {
                    "first": [{"paragraph_id": "p1"}, {"paragraph_id": "p1"}],
                    "second": [{"paragraph_id": "p9"}, {"paragraph_id": "p3"}],
                }[query]

        store = FakeStore()
        original = list(cases)

        payload = evaluate_database(store, cases, mode="text", limit=10)

        self.assertEqual(store.calls, [("first", 10, "text"), ("second", 10, "text")])
        self.assertEqual(payload["cases"], 2)
        self.assertEqual(len(payload["results"]), 2)
        self.assertEqual(payload["results"][0]["ranked_paragraph_ids"], ["p1", "p1"])
        self.assertEqual(payload["results"][0]["metrics"]["reciprocal_rank"], 1.0)
        self.assertEqual(payload["aggregate"]["hit_at_1"], 0.5)
        self.assertEqual(cases, original)
        json.dumps(payload)

    def test_evaluate_database_handles_empty_cases_without_searching(self) -> None:
        class NoSearchStore:
            def search(self, *_args: object, **_kwargs: object) -> list[dict[str, object]]:
                raise AssertionError("empty evaluation must not search")

        self.assertEqual(
            evaluate_database(NoSearchStore(), [], mode="knowledge"),
            {"cases": 0, "aggregate": {}, "results": []},
        )

    def test_evaluate_database_validates_limit_and_mode_before_searching(self) -> None:
        class NoSearchStore:
            def search(self, *_args: object, **_kwargs: object) -> list[dict[str, object]]:
                raise AssertionError("invalid arguments must not search")

        store = NoSearchStore()
        case = EvalCase("one", "query", "lookup", ("p1",))
        for invalid_limit in (True, 0, -1, 1.5, "10", 101, 10**50):
            with self.subTest(limit=invalid_limit):
                with self.assertRaises((TypeError, ValueError)):
                    evaluate_database(store, [case], mode="text", limit=invalid_limit)  # type: ignore[arg-type]
        for invalid_mode in ("", "semantic", None):
            with self.subTest(mode=invalid_mode):
                with self.assertRaises((TypeError, ValueError)):
                    evaluate_database(store, [case], mode=invalid_mode)  # type: ignore[arg-type]

        calls = 0

        class BoundedStore:
            def search(self, *_args: object, **kwargs: object) -> list[dict[str, object]]:
                nonlocal calls
                calls += 1
                self.limit = kwargs["limit"]
                return []

        bounded_store = BoundedStore()
        evaluate_database(bounded_store, [case], mode="text", limit=100)
        self.assertEqual((calls, bounded_store.limit), (1, 100))

    def test_evaluate_database_consumes_at_most_limit_search_rows(self) -> None:
        pulls = 0

        def infinite_results():  # type: ignore[no-untyped-def]
            nonlocal pulls
            index = 0
            while True:
                pulls += 1
                yield {"paragraph_id": f"p{index}"}
                index += 1

        class FakeStore:
            def search(self, *_args: object, **_kwargs: object):  # type: ignore[no-untyped-def]
                return infinite_results()

        case = EvalCase("one", "query", "lookup", ("p0",))
        payload = evaluate_database(FakeStore(), [case], mode="text", limit=1)

        self.assertEqual(pulls, 1)
        self.assertEqual(payload["results"][0]["ranked_paragraph_ids"], ["p0"])

    def test_evaluate_database_skips_hostile_or_invalid_result_rows(self) -> None:
        class HostileMapping(dict[str, object]):
            def get(self, *_args: object, **_kwargs: object) -> object:
                raise RuntimeError("hostile mapping")

            def __getitem__(self, _key: object) -> object:
                raise RuntimeError("hostile mapping")

        class HostileString(str):
            def __str__(self) -> str:
                raise RuntimeError("hostile string")

        rows: list[object] = [
            HostileMapping(paragraph_id="hidden"),
            {"paragraph_id": HostileString("hidden")},
            {"paragraph_id": ""},
            {"paragraph_id": "x" * 257},
            {"paragraph_id": "safe"},
        ]

        class FakeStore:
            def search(self, *_args: object, **_kwargs: object):  # type: ignore[no-untyped-def]
                return iter(rows)

        case = EvalCase("one", "query", "lookup", ("safe",))
        payload = evaluate_database(FakeStore(), [case], mode="text", limit=10)

        self.assertEqual(payload["results"][0]["ranked_paragraph_ids"], ["safe"])
        json.dumps(payload, allow_nan=False)

    def test_evaluate_database_rejects_unbounded_case_iterables_before_search(self) -> None:
        searches = 0

        class FakeStore:
            def search(self, *_args: object, **_kwargs: object) -> list[dict[str, object]]:
                nonlocal searches
                searches += 1
                return []

        case = EvalCase("one", "query", "lookup", ("p1",))

        def infinite_cases():  # type: ignore[no-untyped-def]
            while True:
                yield case

        with self.assertRaisesRegex(ValueError, "evaluation cases exceed maximum"):
            evaluate_database(FakeStore(), infinite_cases(), mode="text", limit=1)
        self.assertEqual(searches, 0)

    def test_golden_v1_loads_seven_unique_cases(self) -> None:
        path = Path(__file__).resolve().parents[1] / "evals" / "golden_v1.jsonl"

        cases = load_eval_cases(path)
        by_id = {case.case_id: case for case in cases}

        self.assertEqual(len(cases), 7)
        self.assertEqual(len(by_id), 7)
        self.assertEqual(
            by_id["acupuncture-four-gates"].relevant_paragraph_ids,
            ("fb1cc40bb9bbb8be",),
        )

    def test_baseline_v1_has_stable_provenance_and_matching_case_count(self) -> None:
        root = Path(__file__).resolve().parents[1]
        baseline = json.loads((root / "evals" / "baseline_v1.json").read_text(encoding="utf-8"))
        provenance = baseline["provenance"]

        self.assertEqual(baseline["cases"], 7)
        self.assertEqual(len(baseline["results"]), 7)
        self.assertEqual(provenance["mode"], "hybrid")
        self.assertEqual(provenance["limit"], 10)
        self.assertEqual(provenance["code_commit"], "b4a71f2573e06259aa1697aacb67d2f9a6169e08")
        self.assertEqual(provenance["embedding"]["provider"], "SiliconFlow")
        self.assertEqual(provenance["embedding"]["model"], "BAAI/bge-m3")
        self.assertEqual(provenance["embedding"]["dimensions"], 1024)
        self.assertEqual(provenance["embedding"]["selection"], "auto_from_db_metadata")
        self.assertEqual(
            provenance["artifacts"]["golden_sha256"],
            "b415d6cfa1aafc951671a44277e5ff103bd46c05b98ac35fe804d34062a57479",
        )
        self.assertEqual(
            provenance["artifacts"]["db_lfs_oid_sha256"],
            "286b2389ed3096f6e378c1f869aecb00445d5335a98720679c647bfd3ca22997",
        )
        self.assertEqual(
            provenance["artifacts"]["faiss_lfs_oid_sha256"],
            "ec5c576af53c56c6a22871ed0ebf8d3346435c200c54be6711a866fcb0a52cba",
        )
        self.assertEqual(
            provenance["artifacts"]["vector_ids_sha256"],
            "dc90ebf490393e87ef998918242e4e8a41423507d260fa8f5afa6c6bc54ebf6f",
        )
        self.assertTrue(re.fullmatch(r"[0-9a-f]{64}", provenance["artifacts"]["golden_sha256"]))
        self.assertEqual(provenance["runtime"]["python"], "3.13.2")
        self.assertEqual(provenance["runtime"]["faiss-cpu"], "1.14.3")
        self.assertEqual(provenance["runtime"]["numpy"], "2.5.1")
        self.assertEqual(provenance["runtime"]["requests"], "2.32.5")
        self.assertEqual(provenance["runtime"]["sqlite"], "3.49.0")
        self.assertEqual(
            hashlib.sha256((root / "evals" / "golden_v1.jsonl").read_bytes()).hexdigest(),
            provenance["artifacts"]["golden_sha256"],
        )
        vector_ids = next(
            asset for asset in PRODUCTION_ASSETS if asset.filename == "vector_ids.jsonl"
        )
        self.assertEqual(vector_ids.sha256, provenance["artifacts"]["vector_ids_sha256"])


if __name__ == "__main__":
    unittest.main()
