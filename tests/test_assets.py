from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from nihaisha_kg.assets import AssetSpec, asset_url, download_asset, file_sha256


class FakeResponse:
    def __init__(
        self,
        body: bytes,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.body = body
        self.status_code = status_code
        self.headers = headers or {}
        self.closed = False

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size: int):
        for start in range(0, len(self.body), chunk_size):
            yield self.body[start : start + chunk_size]

    def close(self) -> None:
        self.closed = True


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return self.responses.pop(0)


def spec_for(filename: str, content: bytes) -> AssetSpec:
    import hashlib

    return AssetSpec(filename, len(content), hashlib.sha256(content).hexdigest())


class AssetDownloadTests(unittest.TestCase):
    def test_asset_url_pins_public_dataset_revision(self) -> None:
        url = asset_url("JuneYao/nihaisha-rag-assets", "production-2026-07-15", "rag.sqlite")

        self.assertEqual(
            url,
            "https://huggingface.co/datasets/JuneYao/nihaisha-rag-assets/resolve/"
            "production-2026-07-15/rag.sqlite",
        )

    def test_existing_verified_asset_skips_network(self) -> None:
        content = b"already present"
        spec = spec_for("asset.bin", content)
        session = FakeSession([])
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / spec.filename
            target.write_bytes(content)

            result = download_asset(spec, Path(tmpdir), session=session)

        self.assertEqual(result["status"], "verified")
        self.assertEqual(session.calls, [])

    def test_download_verifies_and_atomically_publishes_asset(self) -> None:
        content = b"complete asset"
        spec = spec_for("asset.bin", content)
        session = FakeSession([FakeResponse(content)])
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)

            result = download_asset(
                spec,
                out_dir,
                session=session,
                progress_stream=io.StringIO(),
            )

            self.assertEqual((out_dir / spec.filename).read_bytes(), content)
            self.assertFalse((out_dir / f"{spec.filename}.part").exists())
            self.assertEqual(file_sha256(out_dir / spec.filename), spec.sha256)
        self.assertEqual(result["status"], "downloaded")

    def test_download_resumes_partial_file_with_range_request(self) -> None:
        content = b"resume this download"
        prefix = content[:7]
        spec = spec_for("asset.bin", content)
        response = FakeResponse(
            content[len(prefix) :],
            status_code=206,
            headers={"Content-Range": f"bytes {len(prefix)}-{len(content) - 1}/{len(content)}"},
        )
        session = FakeSession([response])
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            (out_dir / f"{spec.filename}.part").write_bytes(prefix)

            download_asset(
                spec,
                out_dir,
                session=session,
                progress_stream=io.StringIO(),
            )

            self.assertEqual((out_dir / spec.filename).read_bytes(), content)
        self.assertEqual(session.calls[0]["headers"], {"Range": f"bytes={len(prefix)}-"})

    def test_server_ignoring_range_restarts_partial_file(self) -> None:
        content = b"server returned the full object"
        spec = spec_for("asset.bin", content)
        session = FakeSession([FakeResponse(content, status_code=200)])
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            (out_dir / f"{spec.filename}.part").write_bytes(b"stale")

            download_asset(
                spec,
                out_dir,
                session=session,
                progress_stream=io.StringIO(),
            )

            self.assertEqual((out_dir / spec.filename).read_bytes(), content)

    def test_checksum_failure_removes_invalid_partial(self) -> None:
        expected = b"expected"
        spec = spec_for("asset.bin", expected)
        session = FakeSession([FakeResponse(b"corrupt!")])
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)

            with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                download_asset(
                    spec,
                    out_dir,
                    session=session,
                    progress_stream=io.StringIO(),
                )

            self.assertFalse((out_dir / f"{spec.filename}.part").exists())
            self.assertFalse((out_dir / spec.filename).exists())


if __name__ == "__main__":
    unittest.main()
