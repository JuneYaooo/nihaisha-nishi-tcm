from __future__ import annotations

import math
import os
import traceback
import unittest
from unittest.mock import patch

import requests

from nihaisha_kg.rerank import (
    MAX_RERANK_DOCUMENTS,
    MAX_RERANK_DOCUMENT_CHARS,
    MAX_RERANK_QUERY_CHARS,
    MAX_SANITIZER_INPUT_CHARS,
    MAX_SANITIZER_SECRET_GUARD_CHARS,
    SiliconFlowReranker,
    normalize_rerank_outcome_results,
    normalize_rerank_results,
    snapshot_rerank_outcome,
    sanitize_rerank_error,
)


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.payload


class FakeSession:
    def __init__(self, payload: object = None, error: Exception | None = None) -> None:
        self.payload = {} if payload is None else payload
        self.error = error
        self.calls: list[tuple[str, dict[str, str], dict[str, object], float]] = []

    def post(
        self,
        url: str,
        headers: dict[str, str],
        json: dict[str, object],
        timeout: float,
    ) -> FakeResponse:
        self.calls.append((url, headers, json, timeout))
        if self.error is not None:
            raise self.error
        return FakeResponse(self.payload)


class FakeHttpError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.response = type("Response", (), {"status_code": status_code})()


class RerankTests(unittest.TestCase):
    def test_sanitizer_redacts_structured_credentials_and_url_userinfo(self) -> None:
        cases = (
            ('{"api_key": "unknown-secret"}', "unknown-secret"),
            ('{"api-key": "hyphen-secret"}', "hyphen-secret"),
            ("token='unknown secret'", "unknown secret"),
            ("{'access_token': 'access secret'}", "access secret"),
            ('{"secret" = "quoted secret"}', "quoted secret"),
            ('{"password": "password secret"}', "password secret"),
            ("{'passwd': 'passwd secret'}", "passwd secret"),
            ('client_secret="client secret"', "client secret"),
            ("'client-secret'='hyphen client secret'", "hyphen client secret"),
            ('{"private_key": "private key secret"}', "private key secret"),
            ("private-key='hyphen private key secret'", "hyphen private key secret"),
            ('{"authorization": "Bearer nested-secret"}', "nested-secret"),
            ("https://private-user:private-pass@example.test/path", "private-user"),
            ("https://private-user:private-pass@example.test/path", "private-pass"),
        )

        for message, credential in cases:
            with self.subTest(message=message, credential=credential):
                sanitized = sanitize_rerank_error(message)
                self.assertNotIn(credential, sanitized)
                self.assertIn("[REDACTED]", sanitized)

    def test_sanitizer_redacts_quoted_and_unquoted_authorization_values_atomically(self) -> None:
        messages = (
            "Authorization: Bearer supersecret",
            'Authorization="Bearer supersecret"',
            "Authorization='Bearer supersecret'",
        )

        for message in messages:
            with self.subTest(message=message):
                sanitized = sanitize_rerank_error(message)
                self.assertNotIn("supersecret", sanitized)
                self.assertNotIn("Bearer", sanitized)
                self.assertIn("[REDACTED]", sanitized)

    def test_sanitizer_redacts_entire_authorization_field_across_schemes(self) -> None:
        credential = "credential-sentinel"
        messages = (
            f"Authorization: Basic {credential}",
            f"authorization=Digest username={credential}, realm=private, nonce=value",
            f'Authorization: "Basic {credential}"',
            f"'Authorization'='Digest username={credential}, realm=private'",
            f"Authorization: Bearer {credential}\r\nnext-line: retained",
            f"Authorization=Basic {credential}\x00next-field: retained",
        )

        for message in messages:
            with self.subTest(kind=message.split(maxsplit=1)[0]):
                sanitized = sanitize_rerank_error(message)
                self.assertFalse(credential in sanitized)
                self.assertIn("[REDACTED]", sanitized)
        self.assertIn("next-line: retained", sanitize_rerank_error(messages[-2]))
        self.assertNotIn("next-field: retained", sanitize_rerank_error(messages[-1]))

    def test_sanitizer_removes_control_and_ansi_authorization_bypasses(self) -> None:
        credential = "credential-sentinel"
        messages = (
            f"Auth\x00orization: Basic {credential}",
            f"Authorization:\x00Digest username={credential}, realm=private",
            f"Authorization: Bear\x07er {credential}",
            f"Auth\x1b[31morization: Basic {credential}",
            f"Authorization:\x1b[2m Digest username={credential}",
        )

        for message in messages:
            sanitized = sanitize_rerank_error(message)
            self.assertFalse(credential in sanitized)
            self.assertEqual(sanitized.count("[REDACTED]"), 1)
            self.assertFalse("[REDACTED]]" in sanitized)

        multiline = sanitize_rerank_error(
            f"Authorization:\r\nbenign-line\r\napi_key={credential}"
        )
        self.assertIn("Authorization:", multiline)
        self.assertIn("benign-line", multiline)
        self.assertFalse(credential in multiline)
        self.assertEqual(multiline.count("[REDACTED]"), 1)

    def test_sanitizer_strips_c1_ansi_sequences_before_authorization_matching(self) -> None:
        credential = "credential-sentinel"
        messages = (
            f"Auth\x9b31morization: Basic {credential}",
            f"Authorization\x9b2K:\x9b0mDigest username={credential}",
            f"Authorization: Bear\x9b1;31mer {credential}",
            f"Auth\x9dwindow-title\x9corization: Basic {credential}",
            f"Authorization:\x9dtitle\x07Digest username={credential}",
            f"Auth\x90private-data\x9corization: Basic {credential}",
            f"Authorization:\x9fprivate-data\x1b\\Bearer {credential}",
        )

        for message in messages:
            sanitized = sanitize_rerank_error(message)
            self.assertFalse(credential in sanitized)
            self.assertEqual(sanitized.count("[REDACTED]"), 1)
            self.assertFalse("]]" in sanitized)

        long_unterminated = "Auth\x9d" + "x" * 100_000
        sanitized = sanitize_rerank_error(long_unterminated, max_chars=80)
        self.assertLessEqual(len(sanitized), 80)

    def test_sanitizer_redacts_schemes_when_ansi_consumes_header_letters(self) -> None:
        credential = "credential-sentinel"
        messages = (
            f"Auth\x9b31orization: Basic {credential}",
            f"Auth\x1b[31orization: Digest username={credential}, realm=private",
            f"\x1bAuthorization: Bearer {credential}",
            f"Authrization: Ba\x00sic {credential}",
            f"uthorization: Dig\x1b[31mest username={credential}",
        )

        for message in messages:
            sanitized = sanitize_rerank_error(message)
            self.assertFalse(credential in sanitized)
            self.assertEqual(sanitized.count("[REDACTED]"), 1)

        multiline = sanitize_rerank_error(
            f"Auth\x9b31orization: Basic {credential}\r\nnext-line: retained"
        )
        self.assertTrue(multiline.startswith("[REDACTED]"))
        self.assertIn("next-line: retained", multiline)

        benign = sanitize_rerank_error(
            "basic diagnostic information retained\ndigest mismatch retained"
        )
        self.assertIn("basic diagnostic information retained", benign)
        self.assertIn("digest mismatch retained", benign)

    def test_unsafe_control_lines_fail_closed_without_consuming_next_line(self) -> None:
        messages = (
            "diagnostic\x1b[31m text\r\nnext-line: retained",
            "diagnostic\x9b31m text\nnext-line: retained",
            "diagnostic\x00 text\rnext-line: retained",
            "Auth\x9b31orization: Basic credential-sentinel\nnext-line: retained",
            "Auth\x1b[31orization: Digest credential-sentinel\nnext-line: retained",
            "\x1bAuthorization: Bearer credential-sentinel\nnext-line: retained",
        )
        for message in messages:
            sanitized = sanitize_rerank_error(message)
            self.assertTrue(sanitized.startswith("[REDACTED]"))
            self.assertIn("next-line: retained", sanitized)
            self.assertFalse("credential-sentinel" in sanitized)

    def test_known_keys_are_replaced_before_input_boundary_processing(self) -> None:
        known_key = "known-boundary-alpha-beta-gamma-delta-omega"
        fragments = (known_key[:12], known_key[-12:])
        for split in range(1, len(known_key)):
            prefix_length = MAX_SANITIZER_INPUT_CHARS - split
            message = "x" * prefix_length + known_key + " trailing"
            sanitized = sanitize_rerank_error(
                message,
                api_key=known_key,
                max_chars=MAX_SANITIZER_INPUT_CHARS + 100,
            )
            self.assertTrue(all(fragment not in sanitized for fragment in fragments))

        with patch.dict(os.environ, {"SILICONFLOW_API_KEY": known_key}):
            message = "x" * (MAX_SANITIZER_INPUT_CHARS - 5) + known_key
            sanitized = sanitize_rerank_error(
                message,
                max_chars=MAX_SANITIZER_INPUT_CHARS + 100,
            )
        self.assertTrue(all(fragment not in sanitized for fragment in fragments))

        shorter_key = "overlap-alpha-beta"
        longer_key = shorter_key + "-gamma-delta-omega"
        with patch.dict(os.environ, {"SILICONFLOW_API_KEY": longer_key}):
            sanitized = sanitize_rerank_error(
                f"provider={longer_key}",
                api_key=shorter_key,
            )
        self.assertFalse("gamma-delta-omega" in sanitized)

        max_guard_key = "k" * MAX_SANITIZER_SECRET_GUARD_CHARS
        boundary_message = (
            "x" * (MAX_SANITIZER_INPUT_CHARS - MAX_SANITIZER_SECRET_GUARD_CHARS // 2)
            + max_guard_key
            + "ignored-tail"
        )
        sanitized = sanitize_rerank_error(
            boundary_message,
            api_key=max_guard_key,
            max_chars=MAX_SANITIZER_INPUT_CHARS + 100,
        )
        self.assertFalse("k" * 32 in sanitized)

        marker_boundary = sanitize_rerank_error(
            "x" * (MAX_SANITIZER_INPUT_CHARS - 1) + max_guard_key,
            api_key=max_guard_key,
            max_chars=MAX_SANITIZER_INPUT_CHARS + 100,
        )
        self.assertTrue(marker_boundary.endswith("[REDACTED]"))

        oversized_key = "z" * (MAX_SANITIZER_SECRET_GUARD_CHARS + 1)
        self.assertEqual(
            sanitize_rerank_error("public diagnostics", api_key=oversized_key),
            "[REDACTED]",
        )
        self.assertLessEqual(
            len(
                sanitize_rerank_error(
                    "public diagnostics",
                    api_key=oversized_key,
                    max_chars=4,
                )
            ),
            4,
        )

    def test_sanitizer_uses_builtin_bounded_slice_for_huge_string_subclasses(self) -> None:
        class HostileString(str):
            def __getitem__(self, _key: object) -> object:
                raise AssertionError("overridden slicing must not run")

            def replace(self, *_args: object, **_kwargs: object) -> str:
                raise AssertionError("overridden replace must not run")

            def __str__(self) -> str:
                raise AssertionError("full conversion must not run")

        message = HostileString("safe-prefix " + "x" * 5_000_000)
        with patch.dict(os.environ, {}, clear=True):
            sanitized = sanitize_rerank_error(message, max_chars=80)

        self.assertLessEqual(len(sanitized), 80)
        self.assertTrue(sanitized.startswith("safe-prefix"))

    def test_oversized_input_with_known_keys_fails_closed_before_replacement(self) -> None:
        configured_key = "configured-key-sentinel"
        environment_key = "environment-key-sentinel"
        message = (
            configured_key
            + "x" * MAX_SANITIZER_INPUT_CHARS
            + configured_key
            + environment_key
        )

        with patch.dict(os.environ, {"SILICONFLOW_API_KEY": environment_key}):
            sanitized = sanitize_rerank_error(message, api_key=configured_key)
            short = sanitize_rerank_error(message, api_key=configured_key, max_chars=4)

        self.assertEqual(sanitized, "[REDACTED]")
        self.assertEqual(short, "[RED")
        self.assertFalse(configured_key in sanitized)
        self.assertFalse(environment_key in sanitized)

        with patch.dict(os.environ, {}, clear=True):
            without_key = sanitize_rerank_error(
                "useful-prefix " + "x" * (MAX_SANITIZER_INPUT_CHARS * 2),
                max_chars=80,
            )
        self.assertTrue(without_key.startswith("useful-prefix"))
        self.assertLessEqual(len(without_key), 80)

    def test_sanitizer_is_idempotent_for_generic_secret_fields(self) -> None:
        credential = "credential-sentinel"
        for key in ("api_key", "token", "access_token"):
            first = sanitize_rerank_error(f"{key}={credential}")
            second = sanitize_rerank_error(first)
            self.assertFalse(credential in first)
            self.assertTrue(first.endswith("=[REDACTED]"))
            self.assertFalse("]]" in first)
            self.assertEqual(first, second)

    def test_normalize_rerank_results_uses_exact_bounded_containers(self) -> None:
        class HostileList(list[dict[str, object]]):
            def __getitem__(self, _index: object) -> object:
                return [{"paragraph_id": str(index)} for index in range(100)]

            def __iter__(self):  # type: ignore[no-untyped-def]
                raise RuntimeError("must not iterate")

        with self.assertRaisesRegex(RuntimeError, "invalid reranker results"):
            normalize_rerank_results(HostileList([{"paragraph_id": "p1"}]), limit=1)
        with self.assertRaisesRegex(RuntimeError, "invalid reranker result row"):
            normalize_rerank_results([{"paragraph_id": "p1"}, object()], limit=2)

        oversized = [{"paragraph_id": str(index)} for index in range(1000)]
        normalized = normalize_rerank_results(oversized, limit=1)

        self.assertEqual(normalized, [{"paragraph_id": "0"}])
        self.assertIsNot(normalized[0], oversized[0])

        class HostileOutcome:
            @property
            def results(self) -> object:
                raise RuntimeError("credential-sentinel")

        with self.assertRaisesRegex(RuntimeError, "invalid reranker results container"):
            normalize_rerank_outcome_results(HostileOutcome(), limit=1)

    def test_snapshot_rerank_outcome_guards_and_sanitizes_every_property(self) -> None:
        credential = "credential-sentinel"

        class CustomOutcome:
            results = [{"paragraph_id": "p1"}]
            model = f"model api_key={credential}" + "m" * 1000
            degraded_feature = f"Authorization: Basic {credential}" + "d" * 1000
            error = f"token={credential}" + "e" * 1000

        snapshot = snapshot_rerank_outcome(CustomOutcome(), limit=1)

        self.assertEqual(type(snapshot).__name__, "RerankOutcome")
        self.assertEqual(snapshot.results, [{"paragraph_id": "p1"}])
        self.assertFalse(credential in snapshot.model)
        self.assertFalse(credential in snapshot.degraded_feature)
        self.assertFalse(credential in snapshot.error)
        self.assertLessEqual(len(snapshot.model), 120)
        self.assertLessEqual(len(snapshot.degraded_feature), 80)
        self.assertLessEqual(len(snapshot.error), 240)

        for field in ("results", "model", "degraded_feature", "error"):
            class RaisingOutcome:
                results = [{"paragraph_id": "p1"}]
                model = "model"
                degraded_feature = ""
                error = ""

            setattr(
                RaisingOutcome,
                field,
                property(lambda _self: (_ for _ in ()).throw(RuntimeError(credential))),
            )
            with self.subTest(field=field):
                with self.assertRaisesRegex(RuntimeError, "^invalid reranker outcome$"):
                    snapshot_rerank_outcome(RaisingOutcome(), limit=1)

    def test_posts_documented_request_and_maps_score_order_without_mutation(self) -> None:
        session = FakeSession(
            {
                "results": [
                    {"index": 1, "relevance_score": 0.91},
                    {"index": 0, "relevance_score": 0.21},
                ]
            }
        )
        backend = SiliconFlowReranker(api_key="secret", session=session, max_retries=1)
        candidates = [
            {"paragraph_id": "p1", "title": " 甲 ", "text": "无关"},
            {"paragraph_id": "p2", "title": "乙", "text": " 桂枝汤主之 "},
        ]
        original = [dict(candidate) for candidate in candidates]

        outcome = backend.rerank("桂枝汤", candidates, limit=2)

        self.assertEqual([row["paragraph_id"] for row in outcome.results], ["p2", "p1"])
        self.assertEqual([row["rerank_score"] for row in outcome.results], [0.91, 0.21])
        self.assertEqual(candidates, original)
        self.assertIsNot(outcome.results[0], candidates[1])
        self.assertEqual(len(session.calls), 1)
        url, headers, payload, timeout = session.calls[0]
        self.assertEqual(url, "https://api.siliconflow.cn/v1/rerank")
        self.assertEqual(
            headers,
            {"Authorization": "Bearer secret", "Content-Type": "application/json"},
        )
        self.assertEqual(
            payload,
            {
                "model": "BAAI/bge-reranker-v2-m3",
                "query": "桂枝汤",
                "documents": ["甲\n无关", "乙\n桂枝汤主之"],
                "return_documents": False,
                "top_n": 2,
            },
        )
        self.assertEqual(timeout, 60)

    def test_unsorted_response_is_ranked_by_score_with_original_index_ties(self) -> None:
        session = FakeSession(
            {
                "results": [
                    {"index": 2, "relevance_score": 0.4},
                    {"index": 1, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.9},
                ]
            }
        )
        backend = SiliconFlowReranker(api_key="secret", session=session, max_retries=1)
        candidates = [
            {"paragraph_id": "p0", "text": "甲"},
            {"paragraph_id": "p1", "text": "乙"},
            {"paragraph_id": "p2", "text": "丙"},
        ]

        outcome = backend.rerank("问题", candidates, limit=3)

        self.assertEqual([row["paragraph_id"] for row in outcome.results], ["p0", "p1", "p2"])
        self.assertEqual([row["rerank_score"] for row in outcome.results], [0.9, 0.9, 0.4])

    def test_blank_documents_are_omitted_and_response_indices_map_to_original_candidates(self) -> None:
        session = FakeSession(
            {
                "results": [
                    {"index": 1, "relevance_score": 0.8},
                    {"index": 0, "relevance_score": 0.2},
                ]
            }
        )
        backend = SiliconFlowReranker(api_key="secret", session=session, max_retries=1)
        candidates = [
            {"paragraph_id": "blank", "title": " ", "text": "\n"},
            {"paragraph_id": "first", "title": "甲", "text": "正文"},
            {"paragraph_id": "second", "text": "第二段"},
        ]

        outcome = backend.rerank("问题", candidates, limit=3)

        self.assertEqual(session.calls[0][2]["documents"], ["甲\n正文", "第二段"])
        self.assertEqual(session.calls[0][2]["top_n"], 2)
        self.assertEqual(outcome.results[0]["paragraph_id"], "second")

    def test_non_strict_network_failure_falls_back_without_sleep_or_secret_leak(self) -> None:
        secret = "top-secret"
        session = FakeSession(error=RuntimeError(f"offline Bearer {secret}"))
        backend = SiliconFlowReranker(
            api_key=secret,
            session=session,
            max_retries=1,
            strict=False,
        )
        candidates = [
            {"paragraph_id": "p1", "text": "甲"},
            {"paragraph_id": "p2", "text": "乙"},
            {"paragraph_id": "p3", "text": "丙"},
        ]

        with patch("nihaisha_kg.rerank.time.sleep") as sleep:
            outcome = backend.rerank("问题", candidates, limit=2)

        self.assertEqual([row["paragraph_id"] for row in outcome.results], ["p1", "p2"])
        self.assertEqual(outcome.degraded_feature, "siliconflow_rerank")
        self.assertIn("offline", outcome.error)
        self.assertNotIn(secret, outcome.error)
        self.assertIsNot(outcome.results[0], candidates[0])
        sleep.assert_not_called()

    def test_strict_failure_traceback_never_contains_raw_provider_credentials(self) -> None:
        api_key = "configured-secret"
        cause = OSError(
            f'provider failed Authorization="Bearer raw-secret" api_key={api_key}'
        )
        backend = SiliconFlowReranker(
            api_key=api_key,
            session=FakeSession(error=cause),
            max_retries=1,
            strict=True,
        )

        with self.assertRaisesRegex(RuntimeError, "SiliconFlow rerank request failed") as raised:
            backend.rerank("问题", [{"text": "甲"}], limit=1)

        formatted = "".join(
            traceback.format_exception(type(raised.exception), raised.exception, raised.exception.__traceback__)
        )
        self.assertIsNone(raised.exception.__cause__)
        self.assertNotIn("raw-secret", formatted)
        self.assertNotIn(api_key, formatted)
        self.assertNotIn("Bearer", formatted)

    def test_malformed_results_are_rejected_as_a_whole_with_deterministic_fallback(self) -> None:
        malformed_payloads = {
            "missing results": {},
            "results not a list": {"results": {}},
            "item not an object": {"results": ["bad"]},
            "boolean index": {"results": [{"index": True, "relevance_score": 0.5}]},
            "out of range": {"results": [{"index": 2, "relevance_score": 0.5}]},
            "duplicate index": {
                "results": [
                    {"index": 0, "relevance_score": 0.8},
                    {"index": 0, "relevance_score": 0.7},
                ]
            },
            "boolean score": {"results": [{"index": 0, "relevance_score": True}]},
            "non-finite score": {"results": [{"index": 0, "relevance_score": math.inf}]},
        }
        candidates = [{"paragraph_id": "p1", "text": "甲"}, {"paragraph_id": "p2", "text": "乙"}]

        for name, payload in malformed_payloads.items():
            with self.subTest(name=name):
                backend = SiliconFlowReranker(
                    api_key="secret",
                    session=FakeSession(payload),
                    max_retries=1,
                )
                outcome = backend.rerank("问题", candidates, limit=2)
                self.assertEqual(
                    [row["paragraph_id"] for row in outcome.results],
                    ["p1", "p2"],
                )
                self.assertEqual(outcome.degraded_feature, "siliconflow_rerank")
                self.assertTrue(outcome.error)

    def test_empty_or_partial_success_response_falls_back_without_retry(self) -> None:
        candidates = [{"paragraph_id": "p1", "text": "甲"}, {"paragraph_id": "p2", "text": "乙"}]
        payloads = (
            {"results": []},
            {"results": [{"index": 0, "relevance_score": 0.8}]},
        )

        for payload in payloads:
            with self.subTest(payload=payload):
                session = FakeSession(payload)
                backend = SiliconFlowReranker(
                    api_key="secret",
                    session=session,
                    max_retries=3,
                )
                with patch("nihaisha_kg.rerank.time.sleep") as sleep:
                    outcome = backend.rerank("问题", candidates, limit=2)
                self.assertEqual([row["paragraph_id"] for row in outcome.results], ["p1", "p2"])
                self.assertEqual(outcome.degraded_feature, "siliconflow_rerank")
                self.assertEqual(len(session.calls), 1)
                sleep.assert_not_called()

    def test_retry_policy_only_retries_transport_429_and_5xx(self) -> None:
        candidates = [{"text": "甲"}]
        cases = (
            ("schema", FakeSession({"results": [{}]}), 1),
            ("http400", FakeSession(error=FakeHttpError(400)), 1),
            ("http429", FakeSession(error=FakeHttpError(429)), 3),
            ("http500", FakeSession(error=FakeHttpError(500)), 3),
            ("builtin timeout", FakeSession(error=TimeoutError("timed out")), 3),
            ("builtin connection", FakeSession(error=ConnectionError("offline")), 3),
            ("requests timeout", FakeSession(error=requests.Timeout("timed out")), 3),
            ("requests connection", FakeSession(error=requests.ConnectionError("offline")), 3),
            ("value error", FakeSession(error=ValueError("programming error")), 1),
            ("type error", FakeSession(error=TypeError("programming error")), 1),
            ("key error", FakeSession(error=KeyError("programming error")), 1),
            ("runtime error", FakeSession(error=RuntimeError("programming error")), 1),
        )

        for name, session, expected_calls in cases:
            with self.subTest(name=name):
                backend = SiliconFlowReranker(
                    api_key="secret",
                    session=session,
                    max_retries=3,
                )
                with patch("nihaisha_kg.rerank.time.sleep") as sleep:
                    outcome = backend.rerank("问题", candidates, limit=1)
                self.assertEqual(len(session.calls), expected_calls)
                self.assertEqual(sleep.call_count, max(0, expected_calls - 1))
                self.assertEqual(outcome.degraded_feature, "siliconflow_rerank")

    def test_empty_candidates_nonpositive_limit_and_all_blank_skip_http(self) -> None:
        session = FakeSession({"results": []})
        backend = SiliconFlowReranker(api_key="secret", session=session, max_retries=1)

        self.assertEqual(backend.rerank("问题", [], limit=2).results, [])
        self.assertEqual(backend.rerank("问题", [{"text": "甲"}], limit=0).results, [])
        self.assertEqual(backend.rerank("问题", [{"title": " ", "text": "\n"}], limit=2).results, [])
        self.assertEqual(session.calls, [])

    def test_request_caps_query_documents_and_document_characters(self) -> None:
        session = FakeSession(
            {
                "results": [
                    {"index": index, "relevance_score": float(MAX_RERANK_DOCUMENTS - index)}
                    for index in range(MAX_RERANK_DOCUMENTS)
                ]
            }
        )
        backend = SiliconFlowReranker(api_key="secret", session=session, max_retries=1)
        candidates = [
            {"paragraph_id": f"p{index}", "title": "标题", "text": "甲" * 5000}
            for index in range(MAX_RERANK_DOCUMENTS + 5)
        ]

        outcome = backend.rerank("问" * 3000, candidates, limit=MAX_RERANK_DOCUMENTS + 5)

        payload = session.calls[0][2]
        self.assertEqual(len(payload["query"]), MAX_RERANK_QUERY_CHARS)
        self.assertEqual(len(payload["documents"]), MAX_RERANK_DOCUMENTS)
        self.assertTrue(
            all(len(document) <= MAX_RERANK_DOCUMENT_CHARS for document in payload["documents"])
        )
        self.assertEqual(payload["top_n"], MAX_RERANK_DOCUMENTS)
        self.assertEqual(len(outcome.results), MAX_RERANK_DOCUMENTS)
        self.assertEqual(outcome.results[-1]["paragraph_id"], f"p{MAX_RERANK_DOCUMENTS - 1}")

    def test_none_title_and_text_are_empty_and_mapping_is_preserved(self) -> None:
        session = FakeSession(
            {
                "results": [
                    {"index": 1, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.8},
                ]
            }
        )
        backend = SiliconFlowReranker(api_key="secret", session=session, max_retries=1)
        candidates = [
            {"paragraph_id": "text", "title": None, "text": "正文"},
            {"paragraph_id": "title", "title": "标题", "text": None},
            {"paragraph_id": "blank", "title": None, "text": None},
        ]

        outcome = backend.rerank("问题", candidates, limit=3)

        self.assertEqual(session.calls[0][2]["documents"], ["正文", "标题"])
        self.assertEqual([row["paragraph_id"] for row in outcome.results], ["title", "text"])

    def test_query_must_be_a_nonempty_string_before_http(self) -> None:
        session = FakeSession({"results": []})
        backend = SiliconFlowReranker(api_key="secret", session=session, max_retries=1)

        for query in ("", "   ", None, 123):
            with self.subTest(query=query):
                with self.assertRaisesRegex(ValueError, "query"):
                    backend.rerank(query, [{"text": "甲"}], limit=1)
        self.assertEqual(session.calls, [])

    def test_model_precedence_is_explicit_then_environment_then_default(self) -> None:
        with patch.dict(os.environ, {"SILICONFLOW_RERANK_MODEL": "env-model"}):
            explicit = SiliconFlowReranker(api_key="secret", model="explicit-model")
            environment = SiliconFlowReranker(api_key="secret")
        with patch.dict(os.environ, {}, clear=True):
            default = SiliconFlowReranker(api_key="secret")

        self.assertEqual(explicit.model, "explicit-model")
        self.assertEqual(environment.model, "env-model")
        self.assertEqual(default.model, "BAAI/bge-reranker-v2-m3")

    def test_missing_key_and_invalid_configuration_fail_before_http(self) -> None:
        session = FakeSession({"results": []})
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "SILICONFLOW_API_KEY"):
                SiliconFlowReranker(session=session)
        for kwargs in ({"timeout": 0}, {"timeout": -1}, {"max_retries": 0}, {"max_retries": -1}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    SiliconFlowReranker(api_key="secret", session=session, **kwargs)
        self.assertEqual(session.calls, [])

    def test_constructor_rejects_invalid_resolved_strings_and_numeric_options(self) -> None:
        invalid_cases = [
            ("whitespace key", {"api_key": " "}, RuntimeError, "SILICONFLOW_API_KEY"),
            ("non-string key", {"api_key": 123}, ValueError, "api_key"),
            ("whitespace model", {"api_key": "key", "model": " "}, ValueError, "model"),
            ("non-string model", {"api_key": "key", "model": 123}, ValueError, "model"),
            ("whitespace url", {"api_key": "key", "base_url": " "}, ValueError, "base_url"),
            ("non-string url", {"api_key": "key", "base_url": 123}, ValueError, "base_url"),
            ("relative url", {"api_key": "key", "base_url": "/v1"}, ValueError, "base_url"),
            ("invalid scheme", {"api_key": "key", "base_url": "ftp://host/v1"}, ValueError, "base_url"),
            ("missing host", {"api_key": "key", "base_url": "https:///v1"}, ValueError, "base_url"),
            ("boolean timeout", {"api_key": "key", "timeout": True}, ValueError, "timeout"),
            ("zero timeout", {"api_key": "key", "timeout": 0}, ValueError, "timeout"),
            ("negative timeout", {"api_key": "key", "timeout": -1}, ValueError, "timeout"),
            ("nan timeout", {"api_key": "key", "timeout": math.nan}, ValueError, "timeout"),
            ("string timeout", {"api_key": "key", "timeout": "60"}, ValueError, "timeout"),
            ("boolean retries", {"api_key": "key", "max_retries": True}, ValueError, "max_retries"),
            ("zero retries", {"api_key": "key", "max_retries": 0}, ValueError, "max_retries"),
            ("negative retries", {"api_key": "key", "max_retries": -1}, ValueError, "max_retries"),
            ("float retries", {"api_key": "key", "max_retries": 1.5}, ValueError, "max_retries"),
        ]

        for name, kwargs, error_type, message in invalid_cases:
            with self.subTest(name=name):
                with self.assertRaisesRegex(error_type, message):
                    SiliconFlowReranker(**kwargs)

    def test_constructor_strips_valid_strings_and_trailing_url_slash(self) -> None:
        backend = SiliconFlowReranker(
            api_key=" key ",
            model=" model ",
            base_url=" https://example.test/v1/ ",
        )

        self.assertEqual(backend.api_key, "key")
        self.assertEqual(backend.model, "model")
        self.assertEqual(backend.base_url, "https://example.test/v1")


if __name__ == "__main__":
    unittest.main()
