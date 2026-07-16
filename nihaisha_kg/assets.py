from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterable
from urllib.parse import quote

import requests


DEFAULT_ASSET_REPO = "JuneYao/nihaisha-rag-assets"
DEFAULT_ASSET_REVISION = "production-2026-07-15"
DEFAULT_ASSET_DIR = Path("data/pdf_rag_bge_m3")
DOWNLOAD_CHUNK_BYTES = 8 * 1024 * 1024
PROGRESS_INTERVAL_BYTES = 256 * 1024 * 1024


@dataclass(frozen=True)
class AssetSpec:
    filename: str
    size: int
    sha256: str


PRODUCTION_ASSETS = (
    AssetSpec(
        "rag.sqlite",
        2_195_161_088,
        "286b2389ed3096f6e378c1f869aecb00445d5335a98720679c647bfd3ca22997",
    ),
    AssetSpec(
        "vectors.faiss",
        1_472_745_517,
        "ec5c576af53c56c6a22871ed0ebf8d3346435c200c54be6711a866fcb0a52cba",
    ),
    AssetSpec(
        "vector_ids.jsonl",
        11_505_824,
        "dc90ebf490393e87ef998918242e4e8a41423507d260fa8f5afa6c6bc54ebf6f",
    ),
    AssetSpec(
        "manifest.json",
        11_175,
        "fadfccd700e86c9522181f495ece1a5deab6dc838dac935273d709635e3597f3",
    ),
    AssetSpec(
        "knowledge_structure_report.json",
        637,
        "b442c5053b81ab4bd48f85cb48f2ceec3d584c47993bbe8e04ac578d5917da9b",
    ),
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(DOWNLOAD_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def asset_url(repo_id: str, revision: str, filename: str) -> str:
    quoted_repo = quote(repo_id, safe="/")
    quoted_revision = quote(revision, safe="")
    quoted_filename = quote(filename, safe="/")
    return (
        f"https://huggingface.co/datasets/{quoted_repo}/resolve/"
        f"{quoted_revision}/{quoted_filename}"
    )


def _verified(path: Path, spec: AssetSpec) -> bool:
    return path.is_file() and path.stat().st_size == spec.size and file_sha256(path) == spec.sha256


def _print_progress(
    filename: str,
    downloaded: int,
    total: int,
    *,
    stream: BinaryIO | object,
) -> None:
    percent = min(100.0, downloaded * 100.0 / total) if total else 100.0
    print(
        f"{filename}: {downloaded}/{total} bytes ({percent:.1f}%)",
        file=stream,
        flush=True,
    )


def _download_response(
    *,
    session: requests.Session,
    url: str,
    offset: int,
) -> requests.Response:
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    response = session.get(url, headers=headers, stream=True, timeout=(15, 180))
    if response.status_code == 416:
        return response
    response.raise_for_status()
    return response


def download_asset(
    spec: AssetSpec,
    out_dir: Path,
    *,
    repo_id: str = DEFAULT_ASSET_REPO,
    revision: str = DEFAULT_ASSET_REVISION,
    force: bool = False,
    session: requests.Session | None = None,
    progress_stream: object = sys.stderr,
) -> dict[str, object]:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / spec.filename
    partial = out_dir / f"{spec.filename}.part"

    if not force and _verified(target, spec):
        return {"filename": spec.filename, "status": "verified", "bytes": spec.size}

    if force and partial.exists():
        partial.unlink()
    if partial.exists() and partial.stat().st_size > spec.size:
        partial.unlink()

    client = session or requests.Session()
    owns_session = session is None
    url = asset_url(repo_id, revision, spec.filename)
    offset = partial.stat().st_size if partial.exists() else 0
    response: requests.Response | None = None
    try:
        response = _download_response(session=client, url=url, offset=offset)
        if response.status_code == 416:
            response.close()
            response = None
            if offset == spec.size and _verified(partial, spec):
                partial.replace(target)
                return {"filename": spec.filename, "status": "downloaded", "bytes": spec.size}
            partial.unlink(missing_ok=True)
            offset = 0
            response = _download_response(session=client, url=url, offset=0)

        resumed = offset > 0 and response.status_code == 206
        if resumed:
            content_range = response.headers.get("Content-Range", "")
            if not content_range.startswith(f"bytes {offset}-"):
                response.close()
                response = _download_response(session=client, url=url, offset=0)
                resumed = False

        mode = "ab" if resumed else "wb"
        downloaded = offset if resumed else 0
        next_progress = downloaded + PROGRESS_INTERVAL_BYTES
        with partial.open(mode) as handle:
            for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_BYTES):
                if not chunk:
                    continue
                handle.write(chunk)
                downloaded += len(chunk)
                if downloaded >= next_progress:
                    _print_progress(
                        spec.filename,
                        downloaded,
                        spec.size,
                        stream=progress_stream,
                    )
                    next_progress = downloaded + PROGRESS_INTERVAL_BYTES
        _print_progress(spec.filename, downloaded, spec.size, stream=progress_stream)
    finally:
        if response is not None:
            response.close()
        if owns_session:
            client.close()

    actual_size = partial.stat().st_size if partial.exists() else 0
    if actual_size != spec.size:
        raise RuntimeError(
            f"incomplete asset {spec.filename}: expected {spec.size} bytes, got {actual_size}"
        )
    actual_sha = file_sha256(partial)
    if actual_sha != spec.sha256:
        partial.unlink(missing_ok=True)
        raise RuntimeError(
            f"checksum mismatch for {spec.filename}: expected {spec.sha256}, got {actual_sha}"
        )
    partial.replace(target)
    return {"filename": spec.filename, "status": "downloaded", "bytes": spec.size}


def download_assets(
    out_dir: Path = DEFAULT_ASSET_DIR,
    *,
    repo_id: str = DEFAULT_ASSET_REPO,
    revision: str = DEFAULT_ASSET_REVISION,
    force: bool = False,
    assets: Iterable[AssetSpec] = PRODUCTION_ASSETS,
    progress_stream: object = sys.stderr,
) -> dict[str, object]:
    results: list[dict[str, object]] = []
    with requests.Session() as session:
        for spec in assets:
            results.append(
                download_asset(
                    spec,
                    out_dir,
                    repo_id=repo_id,
                    revision=revision,
                    force=force,
                    session=session,
                    progress_stream=progress_stream,
                )
            )
    return {
        "repo_id": repo_id,
        "revision": revision,
        "out_dir": str(out_dir),
        "total_bytes": sum(int(item["bytes"]) for item in results),
        "assets": results,
    }
