from __future__ import annotations

import math
import os
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit


DEFAULT_SILICONFLOW_RERANK_MODEL = "BAAI/bge-reranker-v2-m3"
MAX_RERANK_DOCUMENTS = 100
MAX_RERANK_DOCUMENT_CHARS = 4000
MAX_RERANK_QUERY_CHARS = 2000
PUBLIC_RERANK_MODEL_MAX_CHARS = 120
PUBLIC_RERANK_FEATURE_MAX_CHARS = 80
PUBLIC_RERANK_ERROR_MAX_CHARS = 240
MAX_SANITIZER_INPUT_CHARS = 16_384
MAX_SANITIZER_SECRET_GUARD_CHARS = 512


class _RerankResponseError(ValueError):
    pass


def sanitize_rerank_error(
    error: object,
    *,
    api_key: str | None = None,
    max_chars: int = PUBLIC_RERANK_ERROR_MAX_CHARS,
) -> str:
    if max_chars <= 0:
        return ""
    known_secrets = sorted(
        (
            secret
            for secret in (api_key, os.getenv("SILICONFLOW_API_KEY"))
            if isinstance(secret, str) and secret
        ),
        key=str.__len__,
        reverse=True,
    )
    if any(str.__len__(secret) > MAX_SANITIZER_SECRET_GUARD_CHARS for secret in known_secrets):
        return "[REDACTED]"[:max_chars]
    if isinstance(error, str):
        try:
            raw_length = str.__len__(error)
            if known_secrets and raw_length > MAX_SANITIZER_INPUT_CHARS:
                return "[REDACTED]"[:max_chars]
            raw_message = str.__getitem__(
                error,
                slice(0, MAX_SANITIZER_INPUT_CHARS),
            )
        except Exception:
            raw_message = f"<{type(error).__name__}>"
    else:
        try:
            rendered = str(error)
        except Exception:
            rendered = f"<{type(error).__name__}>"
        if known_secrets and len(rendered) > MAX_SANITIZER_INPUT_CHARS:
            return "[REDACTED]"[:max_chars]
        raw_message = rendered[:MAX_SANITIZER_INPUT_CHARS]
    for secret in known_secrets:
        raw_message = raw_message.replace(secret, "[REDACTED]")
    if len(raw_message) > MAX_SANITIZER_INPUT_CHARS:
        marker = "[REDACTED]"
        marker_start = raw_message.rfind(
            marker,
            max(0, MAX_SANITIZER_INPUT_CHARS - len(marker) + 1),
            min(len(raw_message), MAX_SANITIZER_INPUT_CHARS + len(marker)),
        )
        if marker_start >= 0 and marker_start < MAX_SANITIZER_INPUT_CHARS:
            raw_message = raw_message[:marker_start] + marker
        else:
            raw_message = raw_message[:MAX_SANITIZER_INPUT_CHARS]

    unsafe_control = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
    physical_parts = re.split(r"(\r\n|\r|\n)", raw_message)
    for index in range(0, len(physical_parts), 2):
        if unsafe_control.search(physical_parts[index]):
            physical_parts[index] = "[REDACTED]"
    raw_message = "".join(physical_parts)
    raw_message = re.sub(
        r'''(?ix)
        (?<![A-Za-z0-9_-])
        (?P<prefix>["']?authorization["']?[ \t]*[:=][ \t]*)
        [^\r\n]+
        ''',
        r"\g<prefix>[REDACTED]",
        raw_message,
    )
    message = re.sub(r"[\x00-\x1f\x7f-\x9f]+", " ", raw_message)
    message = re.sub(
        r"(?i)\b(https?://)[^/@\s]+@",
        r"\1[REDACTED]@",
        message,
    )
    message = re.sub(
        r'''(?ix)
        (?<![A-Za-z0-9_-])
        (?P<key_quote>["']?)
        (?P<key>
            api[_-]?key
            | access[_-]?token
            | client[_-]?secret
            | private[_-]?key
            | password
            | passwd
            | token
            | secret
        )
        (?P=key_quote)\s*[:=]\s*
        (?!\[REDACTED\])
        (?:
            "(?:\\.|[^"])*"
            | '(?:\\.|[^'])*'
            | (?:bearer\s+)?[^\s,;}\]]+
        )
        ''',
        r"\g<key>=[REDACTED]",
        message,
    )
    message = re.sub(
        r"(?i)\bbearer\s+(?!\[REDACTED\])[^\s,;}\]]+",
        "Bearer [REDACTED]",
        message,
    )
    message = re.sub(r"\bsk-[A-Za-z0-9_-]{6,}\b", "[REDACTED]", message)
    message = re.sub(
        r"(?i)\b(api[_-]?key|access[_-]?token|token)\s*[:=]\s*(?!\[REDACTED\])[^\s,;}\]]+",
        r"\1=[REDACTED]",
        message,
    )
    message = " ".join(message.split())
    if max_chars <= 0:
        return ""
    if len(message) > max_chars:
        message = message[: max_chars - 1].rstrip() + "…"
    return message


def safe_rerank_metadata_value(value: object, *, max_chars: int) -> str:
    if value is None or max_chars <= 0:
        return ""
    if not isinstance(value, str):
        marker = f"<{type(value).__name__}>"
        return marker[:max_chars]
    return sanitize_rerank_error(value, max_chars=max_chars)


def normalize_rerank_results(results: object, *, limit: int) -> list[dict[str, object]]:
    """Copy a bounded reranker result list without invoking overridable container methods."""
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise ValueError("reranker result limit must be a nonnegative integer")
    if type(results) is not list:
        raise RuntimeError("invalid reranker results container")
    source_length = list.__len__(results)
    normalized: list[dict[str, object]] = []
    for index in range(min(source_length, limit, MAX_RERANK_DOCUMENTS)):
        row = list.__getitem__(results, index)
        if type(row) is not dict:
            raise RuntimeError("invalid reranker result row")
        normalized.append(dict.copy(row))
    return normalized


def normalize_rerank_outcome_results(
    outcome: object,
    *,
    limit: int,
) -> list[dict[str, object]]:
    try:
        results = object.__getattribute__(outcome, "results")
    except Exception:
        raise RuntimeError("invalid reranker results container") from None
    return normalize_rerank_results(results, limit=limit)


@dataclass(frozen=True)
class RerankOutcome:
    results: list[dict[str, object]]
    model: str
    degraded_feature: str = ""
    error: str = ""


def snapshot_rerank_outcome(outcome: object, *, limit: int) -> RerankOutcome:
    try:
        results = object.__getattribute__(outcome, "results")
        model = object.__getattribute__(outcome, "model")
        degraded_feature = object.__getattribute__(outcome, "degraded_feature")
        error = object.__getattribute__(outcome, "error")
        safe_model = safe_rerank_metadata_value(
            model,
            max_chars=PUBLIC_RERANK_MODEL_MAX_CHARS,
        )
        safe_degraded_feature = safe_rerank_metadata_value(
            degraded_feature,
            max_chars=PUBLIC_RERANK_FEATURE_MAX_CHARS,
        )
        safe_error = safe_rerank_metadata_value(
            error,
            max_chars=PUBLIC_RERANK_ERROR_MAX_CHARS,
        )
    except Exception:
        raise RuntimeError("invalid reranker outcome") from None
    return RerankOutcome(
        results=normalize_rerank_results(results, limit=limit),
        model=safe_model,
        degraded_feature=safe_degraded_feature,
        error=safe_error,
    )


class SiliconFlowReranker:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str = "https://api.siliconflow.cn/v1",
        timeout: float = 60,
        max_retries: int = 2,
        strict: bool = False,
        session: object | None = None,
    ) -> None:
        resolved_key = api_key if api_key is not None else os.getenv("SILICONFLOW_API_KEY", "")
        if not isinstance(resolved_key, str):
            raise ValueError("api_key must be a string")
        normalized_key = resolved_key.strip()
        if not normalized_key:
            raise RuntimeError("SILICONFLOW_API_KEY is required for SiliconFlow reranking")

        if model is not None:
            resolved_model = model
        else:
            environment_model = os.getenv("SILICONFLOW_RERANK_MODEL")
            resolved_model = (
                DEFAULT_SILICONFLOW_RERANK_MODEL
                if environment_model is None
                else environment_model
            )
        if not isinstance(resolved_model, str):
            raise ValueError("model must be a string")
        normalized_model = resolved_model.strip()
        if not normalized_model:
            raise ValueError("model must be a nonempty string")

        if not isinstance(base_url, str):
            raise ValueError("base_url must be a string")
        normalized_base_url = base_url.strip().rstrip("/")
        try:
            parsed_base_url = urlsplit(normalized_base_url)
        except ValueError as exc:
            raise ValueError("base_url must be an absolute http/https URL") from exc
        if parsed_base_url.scheme not in {"http", "https"} or not parsed_base_url.netloc:
            raise ValueError("base_url must be an absolute http/https URL")

        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("timeout must be a positive finite number")
        if isinstance(max_retries, bool) or not isinstance(max_retries, int) or max_retries <= 0:
            raise ValueError("max_retries must be a positive integer")

        self.api_key = normalized_key
        self.model = normalized_model
        self.base_url = normalized_base_url
        self.timeout = timeout
        self.max_retries = max_retries
        self.strict = strict
        self.session = session

    def rerank(
        self,
        query: str,
        candidates: Sequence[dict[str, object]],
        limit: int,
    ) -> RerankOutcome:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a nonempty string")
        if not candidates or limit <= 0:
            return RerankOutcome(results=[], model=self.model)

        bounded_query = query.strip()[:MAX_RERANK_QUERY_CHARS]
        documents: list[str] = []
        original_indices: list[int] = []
        for original_index, candidate in enumerate(candidates):
            if len(documents) >= MAX_RERANK_DOCUMENTS:
                break
            raw_title = candidate.get("title", "")
            raw_text = candidate.get("text", "")
            title = "" if raw_title is None else str(raw_title).strip()
            text = "" if raw_text is None else str(raw_text).strip()
            document = "\n".join(part for part in (title, text) if part)[:MAX_RERANK_DOCUMENT_CHARS]
            if not document:
                continue
            documents.append(document)
            original_indices.append(original_index)
        if not documents:
            return RerankOutcome(results=[], model=self.model)

        top_n = min(limit, len(documents))
        payload: dict[str, object] = {
            "model": self.model,
            "query": bounded_query,
            "documents": documents,
            "return_documents": False,
            "top_n": top_n,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        session = self.session
        if session is None:
            import requests

            session = requests.Session()

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = session.post(
                    f"{self.base_url}/rerank",
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                try:
                    response_payload = response.json()
                except Exception:
                    raise _RerankResponseError("rerank response body must be valid JSON") from None
                ranked = self._validated_results(
                    response_payload,
                    candidates=candidates,
                    original_indices=original_indices,
                    limit=top_n,
                )
                return RerankOutcome(results=ranked, model=self.model)
            except Exception as exc:
                last_error = exc
                if attempt + 1 < self.max_retries and self._is_retryable_error(exc):
                    time.sleep(1.5 * (attempt + 1))
                    continue
                break

        assert last_error is not None
        if self.strict:
            raise RuntimeError(
                f"SiliconFlow rerank request failed: {self._safe_error(last_error)}"
            ) from None
        return RerankOutcome(
            results=[dict(candidate) for candidate in candidates[:limit]],
            model=self.model,
            degraded_feature="siliconflow_rerank",
            error=self._safe_error(last_error),
        )

    @staticmethod
    def _validated_results(
        payload: object,
        *,
        candidates: Sequence[dict[str, object]],
        original_indices: Sequence[int],
        limit: int,
    ) -> list[dict[str, object]]:
        if not isinstance(payload, Mapping):
            raise _RerankResponseError("rerank response must be an object")
        raw_results = payload.get("results")
        if not isinstance(raw_results, list):
            raise _RerankResponseError("rerank response results must be a list")

        validated: list[tuple[int, float]] = []
        seen_indices: set[int] = set()
        for item in raw_results:
            if not isinstance(item, Mapping):
                raise _RerankResponseError("rerank result must be an object")
            index = item.get("index")
            if isinstance(index, bool) or not isinstance(index, int):
                raise _RerankResponseError("rerank result index must be an integer")
            if index < 0 or index >= len(original_indices):
                raise _RerankResponseError("rerank result index is out of range")
            if index in seen_indices:
                raise _RerankResponseError("rerank result indices must be unique")
            seen_indices.add(index)

            score = item.get("relevance_score")
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                raise _RerankResponseError("rerank relevance_score must be numeric")
            score_value = float(score)
            if not math.isfinite(score_value):
                raise _RerankResponseError("rerank relevance_score must be finite")
            validated.append((index, score_value))

        if len(validated) != limit:
            raise _RerankResponseError(
                f"rerank response returned {len(validated)} results; expected {limit}"
            )
        validated.sort(key=lambda pair: (-pair[1], original_indices[pair[0]]))
        ranked: list[dict[str, object]] = []
        for document_index, score in validated[:limit]:
            candidate = dict(candidates[original_indices[document_index]])
            candidate["rerank_score"] = score
            ranked.append(candidate)
        return ranked

    def _safe_error(self, error: Exception) -> str:
        return sanitize_rerank_error(error, api_key=self.api_key)

    @staticmethod
    def _is_retryable_error(error: Exception) -> bool:
        if isinstance(error, _RerankResponseError):
            return False
        response = getattr(error, "response", None)
        status_code = getattr(response, "status_code", None)
        if status_code is None:
            status_code = getattr(error, "status_code", None)
        if isinstance(status_code, int) and not isinstance(status_code, bool):
            return status_code == 429 or status_code >= 500
        if isinstance(error, (TimeoutError, ConnectionError)):
            return True
        try:
            import requests
        except ImportError:
            return False
        return isinstance(error, (requests.Timeout, requests.ConnectionError))
