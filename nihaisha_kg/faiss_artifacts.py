from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


MAX_MAPPING_FILE_BYTES = 64 * 1024 * 1024
MAX_MAPPING_LINE_BYTES = 1024 * 1024
MAX_MAPPING_RECORDS = 500_000


@dataclass(frozen=True)
class FaissArtifactPaths:
    index: Path
    ids: Path


def _resolve_artifact(
    db_path: Path,
    configured: str | None,
    default_name: str,
) -> Path:
    sibling = db_path.parent / default_name
    if not configured:
        return sibling
    candidate = Path(configured)
    if candidate.is_absolute():
        return candidate
    db_relative = db_path.parent / candidate
    if db_relative.exists():
        return db_relative
    if sibling.exists():
        return sibling
    return db_relative


def resolve_faiss_artifacts(
    db_path: Path,
    configured_index: str | None = None,
    configured_ids: str | None = None,
) -> FaissArtifactPaths:
    db_path = Path(db_path)
    return FaissArtifactPaths(
        index=_resolve_artifact(db_path, configured_index, "vectors.faiss"),
        ids=_resolve_artifact(db_path, configured_ids, "vector_ids.jsonl"),
    )
