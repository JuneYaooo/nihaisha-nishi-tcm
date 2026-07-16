from __future__ import annotations

import io
import json
import math
import os
import sqlite3
import tempfile
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, redirect_stdout
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

from nihaisha_kg import pdf_vector
from nihaisha_kg import cli as rag_cli
from nihaisha_kg.rerank import MAX_SANITIZER_INPUT_CHARS, RerankOutcome
from nihaisha_kg.pdf_vector import (
    DenseEmbeddingBackend,
    LocalBgeM3EmbeddingBackend,
    LocalVectorStore,
    ParsedParagraph,
    RetrievalUnit,
    SiliconFlowEmbeddingBackend,
    answer_pdf_rag,
    augment_pdf_vector_store_questions,
    build_differentiation_flow,
    build_query_plan,
    answer_anchor_terms,
    extract_formula_terms,
    explicit_query_formula_terms,
    extract_knowledge_units_from_paragraph,
    filter_results_for_intent,
    known_formula_terms_in_evidence,
    synthesize_pdf_rag_answer,
    knowledge_search_terms,
    text_search_terms,
    write_build_traces,
    build_retrieval_units,
    build_faiss_vector_index,
    create_embedding_backend,
    create_embedding_backend_for_db,
    generate_paragraph_questions,
    pack_dense_vector,
    pack_sparse_vector,
    parse_unit_types,
    fuse_query_rewrites,
    run_query_plan_search,
    select_diverse_results,
    split_sentences,
    sparse_dot,
    unpack_dense_vector,
    unpack_sparse_vector,
    load_faiss_bundle,
    read_faiss_unit_ids,
)


def synthetic_private_values() -> dict[str, str]:
    marker = uuid.uuid4().hex
    account = f"account-{marker}"
    directory = f"segment-{marker}"
    credential = f"value-{marker}"
    return {
        "marker": marker,
        "account": account,
        "directory": directory,
        "credential": credential,
        "posix_root": f"/mnt/{account}/{directory}",
        "windows_root": rf"Z:\{account}\{directory}",
        "drive_relative_root": rf"Z:{account}\{directory}",
        "uri_authority": f"{account}:{credential}@example.test:8443",
    }


class FakeFaissIndex:
    def __init__(self, dims: int) -> None:
        self.dims = dims
        self.vectors: list[list[float]] = []

    def add(self, vectors: object) -> None:
        if hasattr(vectors, "tolist"):
            rows = vectors.tolist()
        else:
            rows = vectors
        self.vectors.extend([[float(value) for value in row] for row in rows])

    @property
    def ntotal(self) -> int:
        return len(self.vectors)

    @property
    def d(self) -> int:
        return self.dims

    def search(self, queries: object, top_k: int) -> tuple[list[list[float]], list[list[int]]]:
        if hasattr(queries, "tolist"):
            query = queries.tolist()[0]
        else:
            query = queries[0]
        scored = []
        for index, vector in enumerate(self.vectors):
            score = sum(float(a) * float(b) for a, b in zip(query, vector))
            scored.append((score, index))
        scored.sort(key=lambda item: item[0], reverse=True)
        scored = scored[:top_k]
        return [[score for score, _ in scored]], [[index for _, index in scored]]


class FakeFaiss:
    def __init__(self) -> None:
        self.indexes: dict[str, FakeFaissIndex] = {}
        self.read_count = 0

    def IndexFlatIP(self, dims: int) -> FakeFaissIndex:
        return FakeFaissIndex(dims)

    def write_index(self, index: FakeFaissIndex, path: str) -> None:
        self.indexes[path] = index
        Path(path).write_text("fake-faiss-index", encoding="utf-8")

    def read_index(self, path: str) -> FakeFaissIndex:
        self.read_count += 1
        return self.indexes[path]


class PdfVectorTests(unittest.TestCase):
    def setUp(self) -> None:
        pdf_vector.clear_faiss_caches()

    def test_public_source_path_removes_absolute_posix_and_windows_roots(self) -> None:
        private = synthetic_private_values()
        self.assertEqual(
            pdf_vector.public_source_path(f"{private['posix_root']}/伤寒论.pdf"),
            "pdfs/伤寒论.pdf",
        )
        self.assertEqual(
            pdf_vector.public_source_path(rf"{private['windows_root']}\金匮.pdf"),
            "pdfs/金匮.pdf",
        )
        self.assertEqual(
            pdf_vector.public_source_path(rf"{private['drive_relative_root']}\温病.pdf"),
            "pdfs/温病.pdf",
        )
        self.assertEqual(
            pdf_vector.public_source_path(
                f"file:Z:/{private['account']}/{private['directory']}/本草.pdf"
            ),
            "pdfs/本草.pdf",
        )
        self.assertEqual(
            pdf_vector.public_source_path("course/pdfs/针灸.pdf"),
            "course/pdfs/针灸.pdf",
        )
        self.assertEqual(
            pdf_vector.public_source_path(r"course\\pdfs\\针灸.pdf"),
            "course/pdfs/针灸.pdf",
        )

    def test_public_source_path_discards_uri_secrets_and_sanitizes_basename(self) -> None:
        private = synthetic_private_values()
        sentinel = private["credential"]
        authority = private["uri_authority"]
        directory = private["directory"]
        cases = {
            f"https://{authority}": "pdfs/source.pdf",
            f"https://{authority}/{directory}/伤寒论.pdf?sig={sentinel}#{sentinel}":
                "pdfs/伤寒论.pdf",
            f"s3://bucket-{private['marker']}/{directory}/金匮.pdf?token={sentinel}": "pdfs/金匮.pdf",
            f"file://{private['posix_root']}/针灸.pdf": "pdfs/针灸.pdf",
            f"file:Z:/{private['account']}/{directory}/本草.pdf": "pdfs/本草.pdf",
            "https://example.test/course/%E9%BB%84%E5%B8%9D%E5%86%85%E7%BB%8F.pdf":
                "pdfs/黄帝内经.pdf",
            "https://example.test/course/%2E%2E%2Fodd%5Cname.pdf": "pdfs/name.pdf",
            "https://example.test/course/%252E%252E%252Fdouble.pdf": "pdfs/double.pdf",
            "https://example.test/course/%00%1Fcontrol.pdf": "pdfs/control.pdf",
            f"https://example.test/course/?signed={sentinel}#{sentinel}": "pdfs/source.pdf",
        }

        for source, expected in cases.items():
            with self.subTest(source=source):
                public = pdf_vector.public_source_path(source)
                self.assertEqual(public, expected)
                self.assertNotIn(sentinel, public)
                self.assertNotRegex(public, r"[?#\x00-\x1f\x7f]")

    def test_public_source_path_rejects_encoded_unsafe_relative_components(self) -> None:
        private = synthetic_private_values()
        filename = f"source-{private['marker']}.pdf"
        unsafe = (
            f"safe/%2e%2e/{filename}",
            f"safe/%2Fetc/{filename}",
            f"safe/%5Cserver/{filename}",
            f"safe/%00hidden/{filename}",
            f"safe/%3Ftoken/{filename}",
            f"safe/%252e%252e/{filename}",
            f"safe/%252Fetc/{filename}",
            f"safe/%2500hidden/{filename}",
            f"%5A%3A/{private['account']}/{filename}",
            f"%66%69%6c%65%3A/{private['account']}/{filename}",
            f"%255A%253A/{private['account']}/{filename}",
        )
        for source in unsafe:
            with self.subTest(source=source):
                self.assertEqual(pdf_vector.public_source_path(source), f"pdfs/{filename}")

        self.assertEqual(
            pdf_vector.public_source_path(
                "%E8%AF%BE%E7%A8%8B/pdfs/%E9%92%88%E7%81%B8.pdf"
            ),
            "课程/pdfs/针灸.pdf",
        )

    def test_public_source_path_decodes_whole_path_before_selecting_basename(self) -> None:
        private = synthetic_private_values()
        sentinel = private["credential"]
        filename = f"source-{private['marker']}.pdf"
        posix = f"{private['posix_root']}/{filename}"
        windows = rf"{private['windows_root']}\{filename}"
        encoded_uri = quote(
            f"https://{private['uri_authority']}/{posix.lstrip('/')}"
            f"?signature={sentinel}#{sentinel}",
            safe="",
        )
        encoded_uri_path = quote(quote(posix, safe=""), safe="")
        cases = (
            quote(posix, safe=""),
            quote(quote(posix, safe=""), safe=""),
            quote(windows, safe=""),
            quote(quote(windows, safe=""), safe=""),
            encoded_uri,
            f"https://example.test/{encoded_uri_path}?signature={sentinel}#{sentinel}",
        )
        for source in cases:
            with self.subTest(source=source):
                public = pdf_vector.public_source_path(source)
                self.assertEqual(public, f"pdfs/{filename}")
                for private_fragment in (
                    private["account"], private["directory"], sentinel
                ):
                    self.assertNotIn(private_fragment, public)

        excessive = posix
        for _ in range(10):
            excessive = quote(excessive, safe="")
        self.assertEqual(pdf_vector.public_source_path(excessive), "pdfs/source.pdf")
        self.assertEqual(
            pdf_vector.public_source_path(
                f"/mnt/{private['account']}/" + "x" * 9000 + f"/{filename}"
            ),
            "pdfs/source.pdf",
        )

    def test_public_search_modes_and_answer_hide_absolute_source_roots(self) -> None:
        private = synthetic_private_values()
        sentinel = private["credential"]
        encoded_private_path = quote(
            quote(f"{private['posix_root']}/伤寒论.pdf", safe=""),
            safe="",
        )
        private_source = (
            f"https://{private['uri_authority']}/{encoded_private_path}"
            f"?signature={sentinel}#{sentinel}"
        )
        paragraph = ParsedParagraph(
            paragraph_id="p-public",
            doc_id="doc",
            source_path=private_source,
            title="伤寒论 p42",
            page_start=42,
            page_end=42,
            text="桂枝汤用于太阳中风，有汗恶风。",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "rag.sqlite"
            store = LocalVectorStore(db_path)
            store.recreate()
            store.insert_paragraphs([paragraph])
            store.insert_units(build_retrieval_units([paragraph]))
            store.rebuild_text_index()
            store.rebuild_knowledge_units()

            mode_results = {
                mode: store.search("桂枝汤 太阳中风", mode=mode, limit=3)
                for mode in ("vector", "text", "knowledge")
            }
            answer = answer_pdf_rag(
                "桂枝汤的出处在哪本书哪一页？",
                db_path=db_path,
                mode="text",
                limit=3,
                reranker="none",
            )

        for results in mode_results.values():
            self.assertTrue(results)
            self.assertTrue(all(row["source_path"] == "pdfs/伤寒论.pdf" for row in results))
        serialized = json.dumps(answer, ensure_ascii=False)
        self.assertNotIn(sentinel, serialized)
        self.assertNotIn(private["account"], serialized)
        self.assertNotIn(private["directory"], serialized)
        self.assertTrue(all(row["source_path"] == "pdfs/伤寒论.pdf" for row in answer["results"]))
        self.assertTrue(
            all(citation["source_path"] == "pdfs/伤寒论.pdf" for citation in answer["citations"])
        )
        self.assertTrue(all(citation["label"] == "伤寒论.pdf p42" for citation in answer["citations"]))

    def _assert_unhealthy_faiss_mapping_reaches_dense_guard(
        self,
        mapped_unit_ids: list[str],
    ) -> None:
        paragraph = ParsedParagraph(
            paragraph_id="p-a", doc_id="doc", source_path="/tmp/doc.pdf", title="test",
            page_start=1, page_end=1, text="桂枝汤主之。",
        )

        class ToyDenseBackend(DenseEmbeddingBackend):
            name = "toy_dense"

            def embed_texts(self, texts: list[str]) -> list[list[float]]:
                return [[1.0, 0.0] for _ in texts]

        units = [
            RetrievalUnit(
                unit_id=f"u-{index}", paragraph_id="p-a", doc_id="doc",
                unit_type="sentence", text=f"unit {index}", text_for_embedding=f"unit {index}",
                sentence_start=index, sentence_end=index, weight=1.0,
            )
            for index in range(3)
        ]
        fake_faiss = FakeFaiss()
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            db_path = base / "rag.sqlite"
            index_path = base / "vectors.faiss"
            ids_path = base / "vector_ids.jsonl"
            store = LocalVectorStore(
                db_path, embedding_backend=ToyDenseBackend(), brute_force_limit=2,
            )
            store.recreate()
            store.insert_paragraphs([paragraph])
            store.insert_units(units)
            index_path.write_text("index", encoding="utf-8")
            ids_path.write_text(
                "\n".join(json.dumps({"unit_id": unit_id}) for unit_id in mapped_unit_ids) + "\n",
                encoding="utf-8",
            )
            index = FakeFaissIndex(2)
            index.add([[1.0, 0.0] for _ in mapped_unit_ids])
            fake_faiss.indexes[str(index_path)] = index

            with self.assertRaisesRegex(RuntimeError, "FAISS.*nihaisha-rag doctor"):
                store.search_vector("桂枝汤", faiss_module=fake_faiss)

    def test_dense_search_rejects_faiss_mapping_count_mismatch(self) -> None:
        self._assert_unhealthy_faiss_mapping_reaches_dense_guard(["u-0"])

    def test_dense_search_rejects_duplicate_faiss_mapping_ids(self) -> None:
        self._assert_unhealthy_faiss_mapping_reaches_dense_guard(["u-0", "u-0", "u-2"])

    def test_runtime_search_honors_db_relative_custom_faiss_paths(self) -> None:
        paragraph = ParsedParagraph(
            paragraph_id="p-a", doc_id="doc", source_path="/tmp/doc.pdf", title="test",
            page_start=1, page_end=1, text="桂枝汤主之。",
        )

        class ToyDenseBackend(DenseEmbeddingBackend):
            name = "toy_dense"

            def embed_texts(self, texts: list[str]) -> list[list[float]]:
                return [[1.0, 0.0] for _ in texts]

        unit = RetrievalUnit(
            unit_id="u-1", paragraph_id="p-a", doc_id="doc", unit_type="sentence",
            text="桂枝汤", text_for_embedding="桂枝汤", sentence_start=0, sentence_end=0,
            weight=1.0,
        )
        fake_faiss = FakeFaiss()
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            custom = base / "custom"
            custom.mkdir()
            index_path = custom / "index.faiss"
            ids_path = custom / "ids.jsonl"
            store = LocalVectorStore(
                base / "rag.sqlite",
                embedding_backend=ToyDenseBackend(),
                brute_force_limit=0,
            )
            store.recreate()
            store.insert_paragraphs([paragraph])
            store.insert_units([unit])
            with store.connect() as conn:
                conn.executemany(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                    (("faiss_index", "custom/index.faiss"), ("faiss_ids", "custom/ids.jsonl")),
                )
            index_path.write_text("index", encoding="utf-8")
            ids_path.write_text('{"unit_id": "u-1"}\n', encoding="utf-8")
            index = FakeFaissIndex(2)
            index.add([[1.0, 0.0]])
            fake_faiss.indexes[str(index_path)] = index

            results = store.search_vector("桂枝汤", faiss_module=fake_faiss)

        self.assertEqual(results[0]["retrieval_sources"], ["faiss"])

    def test_vector_search_uses_bounded_metadata_reader(self) -> None:
        paragraph = ParsedParagraph(
            paragraph_id="p-a", doc_id="doc", source_path="/tmp/doc.pdf", title="test",
            page_start=1, page_end=1, text="桂枝汤主之。",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(Path(tmpdir) / "rag.sqlite")
            store.recreate()
            store.insert_paragraphs([paragraph])
            store.insert_units(build_retrieval_units([paragraph], window_size=2, overlap=1))
            with store.connect() as conn:
                conn.execute("INSERT INTO meta(key, value) VALUES ('unrelated', zeroblob(5000000))")

            with patch.object(store, "read_meta", side_effect=AssertionError("full metadata read")):
                results = store.search_vector("桂枝汤")

        self.assertEqual(results[0]["paragraph_id"], "p-a")

    def test_vector_search_rejects_hostile_recognized_metadata_with_bounded_message(self) -> None:
        class ToyDenseBackend(DenseEmbeddingBackend):
            name = "toy_dense"

            def embed_texts(self, texts: list[str]) -> list[list[float]]:
                return [[1.0, 0.0] for _ in texts]

        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(
                Path(tmpdir) / "rag.sqlite",
                embedding_backend=ToyDenseBackend(),
            )
            store.recreate()
            with store.connect() as conn:
                conn.execute("UPDATE meta SET value = zeroblob(10000) WHERE key = 'vector_kind'")

            with self.assertRaises(RuntimeError) as raised:
                store.search_vector("桂枝汤")

        self.assertIn("metadata", str(raised.exception).lower())
        self.assertLess(len(str(raised.exception)), 200)

    def test_vector_search_rejects_invalid_utf8_metadata_without_leaking_decoder_error(self) -> None:
        class ToyDenseBackend(DenseEmbeddingBackend):
            name = "toy_dense"

            def embed_texts(self, texts: list[str]) -> list[list[float]]:
                return [[1.0, 0.0] for _ in texts]

        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(
                Path(tmpdir) / "rag.sqlite",
                embedding_backend=ToyDenseBackend(),
            )
            store.recreate()
            with store.connect() as conn:
                conn.execute(
                    "UPDATE meta SET value = CAST(X'80' AS TEXT) WHERE key = 'vector_kind'"
                )

            with self.assertRaises(RuntimeError) as raised:
                store.search_vector("桂枝汤")

        message = str(raised.exception)
        self.assertEqual(message, "database metadata is invalid")
        self.assertNotIn("decode", message.lower())

    def test_bounded_metadata_reader_rejects_malformed_meta_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(Path(tmpdir) / "rag.sqlite")
            store.recreate()
            with store.connect() as conn:
                conn.executescript("DROP TABLE meta; CREATE TABLE meta(unexpected TEXT);")

            with self.assertRaisesRegex(RuntimeError, "^database metadata is invalid$"):
                store.read_meta_keys(("vector_kind",))

    def test_bounded_metadata_reader_allows_absent_meta_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(Path(tmpdir) / "rag.sqlite")
            store.recreate()
            with store.connect() as conn:
                conn.execute("DROP TABLE meta")

            metadata = store.read_meta_keys(("vector_kind",))

        self.assertEqual(metadata, {})

    def test_bounded_metadata_reader_rejects_meta_view(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(Path(tmpdir) / "rag.sqlite")
            store.recreate()
            with store.connect() as conn:
                conn.executescript(
                    "DROP TABLE meta; CREATE VIEW meta AS SELECT 'vector_kind' AS key, 'sparse' AS value;"
                )

            with self.assertRaisesRegex(RuntimeError, "^database metadata is invalid$"):
                store.read_meta_keys(("vector_kind",))

    def test_uppercase_meta_table_preserves_vector_kind_mismatch_guard(self) -> None:
        paragraph = ParsedParagraph(
            paragraph_id="p-a", doc_id="doc", source_path="/tmp/doc.pdf", title="test",
            page_start=1, page_end=1, text="桂枝汤主之。",
        )

        class ToyDenseBackend(DenseEmbeddingBackend):
            name = "toy_dense"

            def embed_texts(self, texts: list[str]) -> list[list[float]]:
                return [[1.0, 0.0] for _ in texts]

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "rag.sqlite"
            store = LocalVectorStore(db_path)
            store.recreate()
            store.insert_paragraphs([paragraph])
            store.insert_units(build_retrieval_units([paragraph], window_size=2, overlap=1))
            with store.connect() as conn:
                conn.executescript(
                    """
                    ALTER TABLE meta RENAME TO old_meta;
                    CREATE TABLE META(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    INSERT INTO META SELECT key, value FROM old_meta;
                    DROP TABLE old_meta;
                    """
                )

            mismatched = LocalVectorStore(db_path, embedding_backend=ToyDenseBackend())
            with self.assertRaisesRegex(RuntimeError, "vector_kind mismatch"):
                mismatched.search_vector("桂枝汤")

    def test_bounded_metadata_reader_rejects_uppercase_meta_view(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(Path(tmpdir) / "rag.sqlite")
            store.recreate()
            with store.connect() as conn:
                conn.executescript(
                    """
                    ALTER TABLE meta RENAME TO backing_meta;
                    CREATE VIEW META AS SELECT key, value FROM backing_meta;
                    """
                )

            with self.assertRaisesRegex(RuntimeError, "^database metadata is invalid$"):
                store.read_meta_keys(("vector_kind",))

    def test_runtime_mapping_loader_streams_without_path_read_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ids_path = Path(tmpdir) / "ids.jsonl"
            ids_path.write_text('{"unit_id": "u-1"}\n', encoding="utf-8")
            with patch.object(Path, "read_text", side_effect=AssertionError("whole-file read")):
                unit_ids = read_faiss_unit_ids(ids_path)

        self.assertEqual(unit_ids, ["u-1"])

    def test_runtime_mapping_loader_rejects_oversized_line_and_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            long_line = base / "long.jsonl"
            long_line.write_bytes(b"x" * (1024 * 1024 + 1))
            with self.assertRaisesRegex(ValueError, "safety limit"):
                read_faiss_unit_ids(long_line)

            huge_file = base / "huge.jsonl"
            with huge_file.open("wb") as output:
                output.seek(64 * 1024 * 1024)
                output.write(b"x")
            with self.assertRaisesRegex(ValueError, "safety limit"):
                read_faiss_unit_ids(huge_file)

    def test_runtime_mapping_loader_sanitizes_deep_json_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ids_path = Path(tmpdir) / "ids.jsonl"
            ids_path.write_text("[" * 10_000 + "0" + "]" * 10_000 + "\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "invalid FAISS ID mapping"):
                read_faiss_unit_ids(ids_path)

    def test_faiss_cache_clear_helper_is_available(self) -> None:
        self.assertTrue(callable(pdf_vector.clear_faiss_caches))

    def test_vector_store_rebuilds_guide_nodes_from_original_evidence(self) -> None:
        paragraph = ParsedParagraph(
            paragraph_id="p-guide",
            doc_id="doc",
            source_path="/tmp/伤寒.pdf",
            title="伤寒 p169",
            page_start=169,
            page_end=169,
            text="黄芩加半夏生姜汤，治下利，是热利，但是腹痛同时有恶心。",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(Path(tmpdir) / "rag.sqlite")
            store.recreate()
            store.insert_paragraphs([paragraph])
            store.rebuild_knowledge_units()

            rebuilt = store.rebuild_guide_nodes()
            results = store.search_guide_nodes("下利 恶心 黄芩加半夏生姜汤", limit=3)

        self.assertGreaterEqual(rebuilt["guide_nodes"], 1)
        self.assertEqual(results[0]["label"], "黄芩加半夏生姜汤")
        self.assertEqual(results[0]["node_type"], "formula")
        self.assertEqual(results[0]["badge"], "方证")
        self.assertEqual(results[0]["paragraph_id"], "p-guide")
        self.assertEqual(results[0]["source_path"], "pdfs/伤寒.pdf")
        self.assertEqual(results[0]["page_start"], 169)
        self.assertIn("腹痛", results[0]["content"])
        self.assertIn("热利", results[0]["evidence_quote"])

    def test_rebuild_guide_nodes_skips_table_of_contents_formula_noise(self) -> None:
        toc = ParsedParagraph(
            paragraph_id="p-toc",
            doc_id="doc",
            source_path="/tmp/伤寒.pdf",
            title="伤寒 p8",
            page_start=8,
            page_end=8,
            text="黄芩加半夏生姜汤方................................................81105小柴胡汤方................................................812",
        )
        body = ParsedParagraph(
            paragraph_id="p-body",
            doc_id="doc",
            source_path="/tmp/伤寒.pdf",
            title="伤寒 p168",
            page_start=168,
            page_end=168,
            text="若呕者，黄芩加半夏生姜汤主之。",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(Path(tmpdir) / "rag.sqlite")
            store.recreate()
            store.insert_paragraphs([toc, body])
            store.rebuild_knowledge_units()
            store.rebuild_guide_nodes()

            results = store.search_guide_nodes("黄芩加半夏生姜汤", limit=5)

        self.assertTrue(results)
        self.assertTrue(all(result["paragraph_id"] != "p-toc" for result in results))
        self.assertEqual(results[0]["paragraph_id"], "p-body")

    def test_rebuild_guide_nodes_skips_repeated_ocr_boilerplate_formula_noise(self) -> None:
        noisy = ParsedParagraph(
            paragraph_id="p-noisy",
            doc_id="doc",
            source_path="/tmp/金匮.pdf",
            title="金匮 p345",
            page_start=345,
            page_end=345,
            text=(
                "倪海厦注倪海厦注倪海厦注倪海厦注《金匮金匮金匮金匮》"
                "勤求古訓勤求古訓勤求古訓勤求古訓博采眾方博采眾方"
                "博采眾方博采眾方小桂枝小桂枝小桂枝小桂枝·"
                "群龙无首群龙无首群龙无首群龙无首10.10.100.10.100.10.100.10.10"
                "校排校排校排校排干呕而利者干呕而利者干呕而利者干呕而利者，"
                "黄芩加半夏生姜汤主之黄芩加半夏生姜汤主之黄芩加半夏生姜汤主之。"
            ),
        )
        body = ParsedParagraph(
            paragraph_id="p-body",
            doc_id="doc",
            source_path="/tmp/伤寒.pdf",
            title="伤寒 p168",
            page_start=168,
            page_end=168,
            text="若呕者，黄芩加半夏生姜汤主之。",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(Path(tmpdir) / "rag.sqlite")
            store.recreate()
            store.insert_paragraphs([noisy, body])
            store.rebuild_knowledge_units()
            store.rebuild_guide_nodes()

            results = store.search_guide_nodes("下利 恶心 黄芩加半夏生姜汤", limit=5)

        self.assertTrue(results)
        self.assertTrue(all(result["paragraph_id"] != "p-noisy" for result in results))
        self.assertEqual(results[0]["paragraph_id"], "p-body")

    def test_differentiation_flow_collapses_duplicate_formula_labels(self) -> None:
        flow = build_differentiation_flow(
            "下利 恶心 黄芩加半夏生姜汤",
            [
                {"badge": "方证", "label": "黄芩加半夏生姜汤", "path": "伤寒 p168 > 方证 > 黄芩加半夏生姜汤"},
                {"badge": "方证", "label": "黄芩加半夏生姜汤", "path": "伤寒 p169 > 方证 > 黄芩加半夏生姜汤"},
                {"badge": "方证", "label": "小半夏汤", "path": "金匮 p232 > 方证 > 小半夏汤"},
            ],
        )

        self.assertEqual(flow["text_steps"].count("方证：黄芩加半夏生姜汤"), 1)
        self.assertEqual(flow["text_steps"].count("方证：小半夏汤"), 1)

    def test_rebuild_guide_nodes_cleans_social_header_from_guide_excerpt(self) -> None:
        paragraph = ParsedParagraph(
            paragraph_id="p-header",
            doc_id="doc",
            source_path="/tmp/金匮.pdf",
            title="金匮 p232",
            page_start=232,
            page_end=232,
            text="微信公众号：岐黄圣贤智慧、岐黄传承道法自然220下利，黄芩加半夏生姜汤。",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(Path(tmpdir) / "rag.sqlite")
            store.recreate()
            store.insert_paragraphs([paragraph])
            store.rebuild_knowledge_units()
            store.rebuild_guide_nodes()

            results = store.search_guide_nodes("下利 黄芩加半夏生姜汤", limit=3)

        self.assertTrue(results)
        self.assertIn("下利", results[0]["evidence_quote"])
        self.assertNotIn("微信公众号", results[0]["evidence_quote"])
        self.assertNotIn("岐黄传承", results[0]["evidence_quote"])
        self.assertFalse(str(results[0]["content"]).startswith("220"))

    def test_search_guide_nodes_prioritizes_distinct_labels(self) -> None:
        paragraphs = [
            ParsedParagraph(
                paragraph_id="p-a",
                doc_id="doc",
                source_path="/tmp/伤寒.pdf",
                title="伤寒 p168",
                page_start=168,
                page_end=168,
                text="若呕者，黄芩加半夏生姜汤主之。",
            ),
            ParsedParagraph(
                paragraph_id="p-b",
                doc_id="doc",
                source_path="/tmp/伤寒.pdf",
                title="伤寒 p169",
                page_start=169,
                page_end=169,
                text="黄芩加半夏生姜汤，治下利，是热利，同时有恶心。",
            ),
            ParsedParagraph(
                paragraph_id="p-c",
                doc_id="doc",
                source_path="/tmp/金匮.pdf",
                title="金匮 p232",
                page_start=232,
                page_end=232,
                text="小半夏汤，治呕吐，胃中水饮。",
            ),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(Path(tmpdir) / "rag.sqlite")
            store.recreate()
            store.insert_paragraphs(paragraphs)
            store.rebuild_knowledge_units()
            store.rebuild_guide_nodes()

            results = store.search_guide_nodes("下利 恶心 黄芩加半夏生姜汤 小半夏汤", limit=3)

        labels = [str(result["label"]) for result in results]
        self.assertIn("黄芩加半夏生姜汤", labels)
        self.assertIn("小半夏汤", labels)
        self.assertEqual(len(labels), len(set(labels)))

    def test_cli_answer_rejects_llm_composer_options(self) -> None:
        stderr = io.StringIO()
        with redirect_stdout(io.StringIO()), patch("sys.stderr", stderr):
            with self.assertRaises(SystemExit) as raised:
                rag_cli.main(["answer", "一钱是多少克？", "--composer", "llm"])

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("unrecognized arguments: --composer llm", stderr.getvalue())

    def test_cli_build_dispatches_to_full_build_function(self) -> None:
        calls: dict[str, object] = {}

        def fake_build_pdf_vector_store(**kwargs: object) -> dict[str, object]:
            calls.update(kwargs)
            return {"paragraphs": 2, "retrieval_units": 3}

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            stdout = io.StringIO()
            with patch("nihaisha_kg.cli.build_pdf_vector_store", side_effect=fake_build_pdf_vector_store, create=True):
                with redirect_stdout(stdout):
                    exit_code = rag_cli.main(
                        [
                            "build",
                            "--pdf-dir",
                            str(base / "pdfs"),
                            "--out",
                            str(base / "store"),
                            "--embedding",
                            "sparse",
                            "--window-size",
                            "4",
                            "--overlap",
                            "1",
                            "--trace-dir",
                            str(base / "trace"),
                            "--source-catalog",
                            str(base / "catalog.json"),
                            "--portable-source-paths",
                        ]
                    )

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls["pdf_dir"], base / "pdfs")
        self.assertEqual(calls["out_dir"], base / "store")
        self.assertEqual(calls["embedding"], "sparse")
        self.assertEqual(calls["window_size"], 4)
        self.assertEqual(calls["overlap"], 1)
        self.assertEqual(calls["trace_dir"], base / "trace")
        self.assertEqual(calls["source_catalog_path"], base / "catalog.json")
        self.assertTrue(calls["portable_source_paths"])
        self.assertIn('"paragraphs": 2', stdout.getvalue())

    def test_source_catalog_validates_excluded_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            catalog = Path(tmpdir) / "catalog.json"
            catalog.write_text(
                json.dumps(
                    {
                        "documents": [
                            {
                                "ingest_filename": "四圣心源.pdf",
                                "source_layer": "reference_secondary",
                                "exclude_pages": [1, 21],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            loaded = pdf_vector.load_build_source_catalog(catalog)

        self.assertEqual(loaded[pdf_vector.source_catalog_key("四圣心源.pdf")]["exclude_pages"], [1, 21])

    def test_build_manifest_preserves_reference_link_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            pdf_dir = base / "pdfs"
            out_dir = base / "store"
            pdf_dir.mkdir()
            pdf_path = pdf_dir / "关联书.pdf"
            pdf_path.write_bytes(b"placeholder")
            catalog = base / "catalog.json"
            catalog.write_text(
                json.dumps(
                    {
                        "course_evidence": [
                            {
                                "evidence_id": "course-p10",
                                "logical_source_path": "pdfs/课程.pdf",
                                "page": 10,
                                "evidence_quote": "课程明确提到《关联书》。",
                            }
                        ],
                        "documents": [
                            {
                                "ingest_filename": "关联书.pdf",
                                "source_layer": "reference_secondary",
                                "relation_type": "course_cited_reference",
                                "authorship": "external_non_nihaisha",
                                "edition_verification": "unverified",
                                "relation_evidence_ids": ["course-p10"],
                                "quality_flags": ["needs_identity_review"],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            paragraph = ParsedParagraph(
                "p-ref",
                "d-ref",
                "pdfs/关联书.pdf",
                "关联书 p1",
                1,
                1,
                "这是用于构建测试的关联资料原文段落。",
            )

            with patch("nihaisha_kg.pdf_vector.extract_pdf_paragraphs", return_value=[paragraph]):
                pdf_vector.build_pdf_vector_store(
                    pdf_dir,
                    out_dir,
                    embedding="sparse",
                    source_catalog_path=catalog,
                    portable_source_paths=True,
                )

            manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(manifest["reference_link_evidence"][0]["evidence_id"], "course-p10")
        self.assertEqual(manifest["reference_link_evidence"][0]["logical_source_path"], "pdfs/课程.pdf")
        document = manifest["documents"][0]
        self.assertEqual(document["source_path"], "pdfs/关联书.pdf")
        self.assertEqual(document["relation_evidence_ids"], ["course-p10"])
        self.assertEqual(document["quality_flags"], ["needs_identity_review"])

    def test_public_search_excludes_secondary_references_unless_explicit(self) -> None:
        paragraphs = [
            ParsedParagraph("p-course", "d-course", "pdfs/课程.pdf", "课程", 1, 1, "桂枝汤课程原文。"),
            ParsedParagraph("p-ref", "d-ref", "pdfs/参考书.pdf", "参考", 2, 2, "桂枝汤参考资料。"),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(Path(tmpdir) / "rag.sqlite")
            store.recreate()
            store.insert_paragraphs(paragraphs)
            store.rebuild_text_index()
            with store.connect() as conn:
                conn.executescript(
                    """
                    CREATE TABLE documents (
                      document_id TEXT PRIMARY KEY,
                      source_layer TEXT NOT NULL
                    );
                    CREATE TABLE evidence_records (
                      evidence_id TEXT PRIMARY KEY,
                      document_id TEXT NOT NULL,
                      paragraph_id TEXT NOT NULL UNIQUE
                    );
                    """
                )
                conn.executemany(
                    "INSERT INTO documents VALUES (?, ?)",
                    [("course", "course_primary"), ("reference", "reference_secondary")],
                )
                conn.executemany(
                    "INSERT INTO evidence_records VALUES (?, ?, ?)",
                    [("e1", "course", "p-course"), ("e2", "reference", "p-ref")],
                )

            primary = store.search("桂枝汤", mode="text", limit=5)
            with_references = store.search(
                "桂枝汤",
                mode="text",
                limit=5,
                include_reference_secondary=True,
            )

        self.assertEqual([row["paragraph_id"] for row in primary], ["p-course"])
        self.assertEqual(
            {row["paragraph_id"] for row in with_references},
            {"p-course", "p-ref"},
        )
        reference = next(row for row in with_references if row["paragraph_id"] == "p-ref")
        citation = pdf_vector.build_citations([reference])[0]
        self.assertEqual(citation["source_layer"], "reference_secondary")
        self.assertIn("非倪海厦著作", citation["label"])

    def test_linked_reference_materials_require_visible_primary_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            db_path = base / "rag.sqlite"
            documents = [
                {
                    "source_path": f"pdfs/{name}.pdf",
                    "source_layer": "reference_secondary",
                    "relation_type": "recommended_title_match_unverified_edition",
                    "authorship": "external_non_nihaisha",
                    "edition_verification": edition,
                    "relation_evidence_ids": ["nh-course-booklist-p276"],
                    "quality_flags": flags,
                }
                for name, edition, flags in (
                    ("02.大塚敬節傷寒論解說", "unverified", ["only_9_pages"]),
                    ("世补斋医书全集-陆懋修", "unverified", []),
                    ("徐灵胎医书全集", "unverified", []),
                    ("石室秘录", "unverified", []),
                    (
                        "黄帝外经",
                        "authenticity_disputed_and_edition_unverified",
                        ["course_authenticity_claim_must_not_be_presented_as_objective_fact"],
                    ),
                )
            ]
            documents.append(
                {
                    "source_path": "pdfs/四圣心源.pdf",
                    "source_layer": "reference_secondary",
                    "relation_type": "user_supplied_related",
                    "edition_verification": "unverified",
                    "relation_evidence_ids": [],
                }
            )
            (base / "manifest.json").write_text(
                json.dumps(
                    {
                        "reference_link_evidence": [
                            {
                                "evidence_id": "nh-course-booklist-p276",
                                "logical_source_path": "pdfs/人纪04伤寒视频同步文稿 2024新版.pdf",
                                "page": 276,
                                "evidence_quote": "我这里开八本书给诸位。",
                            }
                        ],
                        "documents": documents,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            citation = {
                "index": 1,
                "label": "人纪04伤寒视频同步文稿 2024新版.pdf p276",
                "source_path": "pdfs/人纪04伤寒视频同步文稿 2024新版.pdf",
                "source_layer": "course_primary",
                "page_start": 276,
                "page_end": 276,
                "evidence_quote": "我这里开八本书给诸位。",
            }

            linked = pdf_vector.linked_reference_materials(db_path, [citation])
            wrong_page = pdf_vector.linked_reference_materials(
                db_path,
                [{**citation, "page_start": 275, "page_end": 275}],
            )
            secondary = pdf_vector.linked_reference_materials(
                db_path,
                [{**citation, "source_layer": "reference_secondary"}],
            )
            derived = pdf_vector.linked_reference_materials(
                db_path,
                [{**citation, "source_layer": "derived"}],
            )

        self.assertEqual(len(linked), 5)
        self.assertEqual(linked[0]["source_path"], "pdfs/02.大塚敬節傷寒論解說.pdf")
        self.assertEqual(linked[0]["trigger"]["citation_index"], 1)
        self.assertNotIn("四圣心源", {item["title"] for item in linked})
        disputed = next(item for item in linked if item["title"] == "黄帝外经")
        self.assertEqual(disputed["edition_label"], "真伪存在争议，具体版本未核实")
        self.assertEqual(wrong_page, [])
        self.assertEqual(secondary, [])
        self.assertEqual(derived, [])

    def test_linked_reference_materials_fail_closed_for_invalid_or_oversized_manifest(self) -> None:
        citation = {
            "source_path": "pdfs/课程.pdf",
            "source_layer": "course_primary",
            "page_start": 1,
            "page_end": 1,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            db_path = base / "rag.sqlite"
            manifest = base / "manifest.json"
            for content in ("not-json", "[]", json.dumps({"documents": [{}]})):
                with self.subTest(content=content[:20]):
                    manifest.write_text(content, encoding="utf-8")
                    self.assertEqual(
                        pdf_vector.linked_reference_materials(db_path, [citation]),
                        [],
                    )
            manifest.write_bytes(b"x" * (pdf_vector.MAX_RUNTIME_MANIFEST_BYTES + 1))
            self.assertEqual(pdf_vector.linked_reference_materials(db_path, [citation]), [])

    def test_answer_pdf_rag_exposes_previous_current_next_evidence_context(self) -> None:
        paragraphs = [
            ParsedParagraph(
                "p-prev", "doc", "pdfs/课程.pdf", "课程 p1", 1, 1,
                "上一段用于说明章节背景。",
            ),
            ParsedParagraph(
                "p-current", "doc", "pdfs/课程.pdf", "课程 p2", 2, 2,
                "木香饼以生地和木香作饼，热熨贴之，用于课程原文出处测试。",
            ),
            ParsedParagraph(
                "p-next", "doc", "pdfs/课程.pdf", "课程 p3", 3, 3,
                "下一段继续讲解相关课程内容。",
            ),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "rag.sqlite"
            store = LocalVectorStore(db_path)
            store.recreate()
            store.insert_paragraphs(paragraphs)
            with store.connect() as conn:
                conn.executescript(
                    """
                    CREATE TABLE documents (
                      document_id TEXT PRIMARY KEY,
                      canonical_title TEXT NOT NULL,
                      source_layer TEXT NOT NULL,
                      logical_source_path TEXT NOT NULL
                    );
                    CREATE TABLE evidence_records (
                      evidence_id TEXT PRIMARY KEY,
                      document_id TEXT NOT NULL,
                      paragraph_id TEXT NOT NULL UNIQUE,
                      locator TEXT NOT NULL,
                      original_text TEXT NOT NULL,
                      previous_evidence_id TEXT,
                      next_evidence_id TEXT
                    );
                    """
                )
                conn.execute(
                    "INSERT INTO documents VALUES (?, ?, ?, ?)",
                    ("doc", "课程", "course_primary", "pdfs/课程.pdf"),
                )
                conn.executemany(
                    "INSERT INTO evidence_records VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [
                        ("ev-prev", "doc", "p-prev", "p1", paragraphs[0].text, None, "ev-current"),
                        ("ev-current", "doc", "p-current", "p2", paragraphs[1].text, "ev-prev", "ev-next"),
                        ("ev-next", "doc", "p-next", "p3", paragraphs[2].text, "ev-current", None),
                    ],
                )

            answer = answer_pdf_rag(
                "木香饼热熨法来自哪一本书哪一段？",
                db_path,
                mode="text",
                limit=2,
                reranker="none",
            )

        citation = answer["citations"][0]
        self.assertEqual(citation["evidence_id"], "ev-current")
        self.assertEqual(citation["previous_evidence_id"], "ev-prev")
        self.assertEqual(citation["next_evidence_id"], "ev-next")
        self.assertEqual(citation["context_navigation"]["previous"]["label"], "课程.pdf p1")
        self.assertEqual(citation["context_navigation"]["current"]["paragraph_id"], "p-current")
        self.assertEqual(citation["context_navigation"]["next"]["label"], "课程.pdf p3")
        self.assertIn("上一段用于说明章节背景", citation["context_navigation"]["previous"]["paragraph_text"])
        self.assertTrue(answer["answer_sections"]["has_context_navigation"])
        self.assertIn("详细依据", answer["answer"])

    def test_cli_answer_prints_linked_reference_cards_separately(self) -> None:
        payload = {
            "answer": "主结论只来自课程原文。[1]",
            "citations": [
                {
                    "index": 1,
                    "label": "课程.pdf p10",
                    "evidence_quote": "课程提到关联书。",
                    "evidence_id": "ev-10",
                    "paragraph_id": "p-10",
                    "context_navigation": {
                        "previous": {"label": "课程.pdf p9", "evidence_id": "ev-9"},
                        "current": {"label": "课程.pdf p10", "evidence_id": "ev-10"},
                        "next": {"label": "课程.pdf p11", "evidence_id": "ev-11"},
                    },
                    "retrieval_provenance": {"channels": ["text", "vector"]},
                }
            ],
            "linked_reference_materials": [
                {
                    "title": "关联书",
                    "relation_label": "课程引用资料",
                    "edition_label": "版本未核实",
                    "trigger": {"citation_label": "课程.pdf p10"},
                }
            ],
            "related_knowledge_units": [],
        }
        stdout = io.StringIO()
        with patch("nihaisha_kg.cli.answer_pdf_rag", return_value=payload), redirect_stdout(stdout):
            status = rag_cli.main(["answer", "课程提到了什么书？", "--mode", "text"])

        output = stdout.getvalue()
        self.assertEqual(status, 0)
        self.assertIn("课程提到的关联资料（非倪海厦著作）", output)
        self.assertIn("关联类型：课程引用资料", output)
        self.assertIn("版本状态：版本未核实", output)
        self.assertIn("课程依据：课程.pdf p10", output)
        self.assertIn("索引：evidence_id=ev-10；paragraph_id=p-10", output)
        self.assertIn("上文：课程.pdf p9 (ev-9)", output)
        self.assertIn("下文：课程.pdf p11 (ev-11)", output)
        self.assertIn("检索路径：text, vector", output)

    def test_cli_rebuild_guide_nodes_dispatches_to_store(self) -> None:
        class FakeStore:
            def __init__(self, db_path: Path) -> None:
                self.db_path = db_path

            def rebuild_guide_nodes(self) -> dict[str, object]:
                return {"db_path": str(self.db_path), "guide_nodes": 2}

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            stdout = io.StringIO()
            with patch("nihaisha_kg.cli.LocalVectorStore", FakeStore):
                with redirect_stdout(stdout):
                    exit_code = rag_cli.main(
                        [
                            "rebuild-guide-nodes",
                            "--db",
                            str(base / "rag.sqlite"),
                        ]
                    )

        self.assertEqual(exit_code, 0)
        self.assertIn('"guide_nodes": 2', stdout.getvalue())

    def test_cli_augment_questions_dispatches_to_existing_function(self) -> None:
        calls: dict[str, object] = {}

        def fake_augment_pdf_vector_store_questions(db_path: Path, **kwargs: object) -> dict[str, object]:
            calls["db_path"] = db_path
            calls.update(kwargs)
            return {"question_units": 5}

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "rag.sqlite"
            stdout = io.StringIO()
            with patch(
                "nihaisha_kg.cli.augment_pdf_vector_store_questions",
                side_effect=fake_augment_pdf_vector_store_questions,
                create=True,
            ):
                with redirect_stdout(stdout):
                    exit_code = rag_cli.main(["augment-questions", "--db", str(db_path)])

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls["db_path"], db_path)
        self.assertIn('"question_units": 5', stdout.getvalue())

    def test_cli_rebuild_indexes_dispatch_to_store_methods(self) -> None:
        calls: list[tuple[str, Path | None]] = []

        class FakeStore:
            def __init__(self, db_path: Path) -> None:
                self.db_path = db_path

            def rebuild_text_index(self) -> dict[str, object]:
                calls.append(("text", self.db_path))
                return {"text_index_rows": 7}

            def rebuild_knowledge_units(self, trace_dir: Path | None = None) -> dict[str, object]:
                calls.append(("knowledge", trace_dir))
                return {"knowledge_units": 9}

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            db_path = base / "rag.sqlite"
            trace_dir = base / "trace"
            stdout = io.StringIO()
            with patch("nihaisha_kg.cli.LocalVectorStore", FakeStore):
                with redirect_stdout(stdout):
                    text_exit = rag_cli.main(["rebuild-text-index", "--db", str(db_path)])
                    knowledge_exit = rag_cli.main(
                        [
                            "rebuild-knowledge-units",
                            "--db",
                            str(db_path),
                            "--trace-dir",
                            str(trace_dir),
                        ]
                    )

        self.assertEqual(text_exit, 0)
        self.assertEqual(knowledge_exit, 0)
        self.assertEqual(calls, [("text", db_path), ("knowledge", trace_dir)])
        output = stdout.getvalue()
        self.assertIn('"text_index_rows": 7', output)
        self.assertIn('"knowledge_units": 9', output)

    def test_cli_doctor_injects_faiss_loader_and_maps_report_status(self) -> None:
        loader = object()
        calls: list[tuple[Path, object]] = []

        def fake_doctor(db_path: Path, faiss_loader: object) -> dict[str, object]:
            calls.append((db_path, faiss_loader))
            statuses = ["ok", "error", "warning"]
            return {"status": statuses[len(calls) - 1], "checks": []}

        stdout = io.StringIO()
        with (
            patch("nihaisha_kg.cli.run_doctor", side_effect=fake_doctor),
            patch("nihaisha_kg.cli.load_faiss_module", loader),
            redirect_stdout(stdout),
        ):
            ok_status = rag_cli.main(["doctor", "--db", "/tmp/ok.sqlite"])
            error_status = rag_cli.main(["doctor", "--db", "/tmp/bad.sqlite"])
            warning_status = rag_cli.main(["doctor", "--db", "/tmp/warn.sqlite"])

        self.assertEqual((ok_status, error_status, warning_status), (0, 1, 1))
        self.assertEqual(calls[0], (Path("/tmp/ok.sqlite"), loader))
        self.assertIn('"status": "ok"', stdout.getvalue())

    def test_cli_evaluate_text_avoids_embedding_backend_and_prints_aggregate(self) -> None:
        case = object()
        store_instances: list[tuple[Path, dict[str, object]]] = []

        class FakeStore:
            def __init__(self, db_path: Path, **kwargs: object) -> None:
                store_instances.append((db_path, kwargs))

        payload = {"cases": 1, "aggregate": {"hit_at_1": 1.0}, "results": []}
        stdout = io.StringIO()
        with (
            patch("nihaisha_kg.cli.load_eval_cases", return_value=[case]) as load_cases,
            patch("nihaisha_kg.cli.LocalVectorStore", FakeStore),
            patch("nihaisha_kg.cli.evaluate_database", return_value=payload) as evaluate,
            patch("nihaisha_kg.cli.create_embedding_backend_for_db") as backend,
            redirect_stdout(stdout),
        ):
            status = rag_cli.main(
                ["evaluate", "--db", "/tmp/rag.sqlite", "--cases", "/tmp/cases.jsonl", "--mode", "text"]
            )

        self.assertEqual(status, 0)
        backend.assert_not_called()
        load_cases.assert_called_once_with(Path("/tmp/cases.jsonl"))
        self.assertEqual(store_instances, [(Path("/tmp/rag.sqlite"), {})])
        evaluate.assert_called_once_with(unittest.mock.ANY, [case], mode="text", limit=10)
        self.assertIn('"hit_at_1": 1.0', stdout.getvalue())

    def test_cli_invalid_limits_fail_before_dispatch_dependencies(self) -> None:
        commands = [
            ["search", "q", "--mode", "text", "--limit", "0"],
            ["search", "q", "--mode", "text", "--limit", "-2", "--reranker", "auto"],
            ["evaluate", "--mode", "hybrid", "--limit", "0"],
            ["answer", "q", "--mode", "text", "--limit", "0"],
            ["search", "q", "--mode", "text", "--limit", "101"],
            ["evaluate", "--mode", "text", "--limit", str(10**50)],
            ["answer", "q", "--mode", "text", "--limit", "101"],
        ]
        for command in commands:
            with self.subTest(command=command):
                stderr = io.StringIO()
                with (
                    patch("nihaisha_kg.cli.load_eval_cases") as load_cases,
                    patch("nihaisha_kg.cli.LocalVectorStore") as store,
                    patch("nihaisha_kg.cli.create_embedding_backend_for_db") as backend,
                    patch("nihaisha_kg.cli.siliconflow_api_key_available") as key_check,
                    patch("nihaisha_kg.cli.answer_pdf_rag") as answer,
                    patch("sys.stderr", stderr),
                ):
                    status = rag_cli.main(command)
                self.assertEqual(status, 1)
                self.assertIn("limit must be a positive integer", stderr.getvalue())
                load_cases.assert_not_called()
                store.assert_not_called()
                backend.assert_not_called()
                key_check.assert_not_called()
                answer.assert_not_called()

        for invalid in (True, 0, -1, 1.5, "2"):
            with self.subTest(helper_value=invalid):
                with self.assertRaises((TypeError, ValueError)):
                    rag_cli._positive_limit(invalid)  # type: ignore[arg-type]
        self.assertEqual(rag_cli._positive_limit(100), 100)

    def test_answer_limit_is_bounded_before_store_or_backend_creation(self) -> None:
        with (
            patch("nihaisha_kg.pdf_vector.LocalVectorStore") as store,
            patch("nihaisha_kg.pdf_vector.create_embedding_backend_for_db") as backend,
        ):
            with self.assertRaisesRegex(ValueError, "at most 100"):
                answer_pdf_rag("query", Path("unused.sqlite"), limit=101)
        store.assert_not_called()
        backend.assert_not_called()

    def test_vector_store_rejects_oversized_search_work_before_embedding_or_faiss(self) -> None:
        class CountingBackend(DenseEmbeddingBackend):
            name = "counting"

            def __init__(self) -> None:
                self.calls = 0

            def embed_texts(self, texts: list[str]) -> list[list[float]]:
                self.calls += 1
                return [[1.0, 0.0] for _ in texts]

        backend = CountingBackend()
        store = LocalVectorStore(Path("unused.sqlite"), embedding_backend=backend)
        for call in (
            lambda: store.search("q", limit=401),
            lambda: store.search_vector("q", unit_limit=401),
            lambda: store.search_text("q", candidate_limit=401),
            lambda: store.search_knowledge_units("q", candidate_limit=401),
            lambda: store.search_guide_nodes("q", limit=101),
        ):
            with self.subTest(call=call):
                with self.assertRaisesRegex(ValueError, "at most (?:100|400)"):
                    call()
        self.assertEqual(backend.calls, 0)

    def test_cli_search_retrieves_and_reranks_once_then_limits_output(self) -> None:
        candidates = [
            {"paragraph_id": f"p{index}", "text": f"text {index}", "score": 1.0}
            for index in range(15)
        ]
        search_calls: list[tuple[str, int, str]] = []
        rerank_calls: list[tuple[str, list[dict[str, object]], int]] = []

        class FakeStore:
            def __init__(self, *_args: object, **_kwargs: object) -> None:
                pass

            def search(self, query: str, limit: int, mode: str) -> list[dict[str, object]]:
                search_calls.append((query, limit, mode))
                return candidates

        class FakeReranker:
            def __init__(self, model: str | None = None) -> None:
                self.model = model

            def rerank(self, query: str, rows: list[dict[str, object]], limit: int) -> RerankOutcome:
                rerank_calls.append((query, rows, limit))
                return RerankOutcome(results=list(reversed(rows))[:limit], model=self.model or "default")

        stdout = io.StringIO()
        with (
            patch("nihaisha_kg.cli.LocalVectorStore", FakeStore),
            patch("nihaisha_kg.cli.SiliconFlowReranker", FakeReranker),
            redirect_stdout(stdout),
        ):
            status = rag_cli.main(
                ["search", "needle", "--mode", "text", "--limit", "3", "--reranker", "siliconflow", "--rerank-model", "chosen", "--json"]
            )

        output = json.loads(stdout.getvalue())
        self.assertEqual(status, 0)
        self.assertEqual(search_calls, [("needle", 12, "text")])
        self.assertEqual(len(rerank_calls), 1)
        self.assertIs(rerank_calls[0][1], candidates)
        self.assertEqual(rerank_calls[0][2], 3)
        self.assertEqual(len(output), 3)

    def test_cli_search_auto_without_key_and_none_do_not_rerank(self) -> None:
        class FakeStore:
            def __init__(self, *_args: object, **_kwargs: object) -> None:
                pass

            def search(self, _query: str, limit: int, mode: str) -> list[dict[str, object]]:
                if mode != "text":
                    raise AssertionError(mode)
                return [{"paragraph_id": str(index), "text": "x", "score": 1.0} for index in range(limit)]

        with (
            patch("nihaisha_kg.cli.LocalVectorStore", FakeStore),
            patch("nihaisha_kg.cli.siliconflow_api_key_available", return_value=False),
            patch("nihaisha_kg.cli.SiliconFlowReranker") as reranker,
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(rag_cli.main(["search", "q", "--mode", "text", "--reranker", "auto", "--json"]), 0)
            self.assertEqual(rag_cli.main(["search", "q", "--mode", "text", "--reranker", "none", "--json"]), 0)
        reranker.assert_not_called()

    def test_cli_search_explicit_reranker_configuration_failure_is_safe(self) -> None:
        secret = "configured-secret-value"

        class FakeStore:
            def __init__(self, *_args: object, **_kwargs: object) -> None:
                pass

            def search(self, *_args: object, **_kwargs: object) -> list[dict[str, object]]:
                return [{"paragraph_id": "p1", "text": "evidence"}]

        stderr = io.StringIO()
        with (
            patch("nihaisha_kg.cli.LocalVectorStore", FakeStore),
            patch(
                "nihaisha_kg.cli.SiliconFlowReranker",
                side_effect=RuntimeError(f"api_key={secret} is unavailable"),
            ),
            patch("sys.stderr", stderr),
        ):
            status = rag_cli.main(
                ["search", "q", "--mode", "text", "--reranker", "siliconflow", "--json"]
            )

        self.assertEqual(status, 1)
        self.assertIn("search failed", stderr.getvalue())
        self.assertNotIn(secret, stderr.getvalue())

    def test_cli_search_normalizes_untrusted_reranker_results(self) -> None:
        candidates = [{"paragraph_id": "candidate", "text": "evidence", "score": 1.0}]

        class FakeStore:
            def __init__(self, *_args: object, **_kwargs: object) -> None:
                pass

            def search(self, *_args: object, **_kwargs: object) -> list[dict[str, object]]:
                return candidates

        class FakeReranker:
            outcome: object

            def __init__(self, *_args: object, **_kwargs: object) -> None:
                pass

            def rerank(self, *_args: object, **_kwargs: object) -> object:
                return self.outcome

        oversized = type(
            "Outcome",
            (),
            {
                "results": [{"paragraph_id": str(index), "text": "evidence"} for index in range(1000)],
                "model": "model",
                "degraded_feature": "",
                "error": "",
            },
        )()
        FakeReranker.outcome = oversized
        stdout = io.StringIO()
        with (
            patch("nihaisha_kg.cli.LocalVectorStore", FakeStore),
            patch("nihaisha_kg.cli.SiliconFlowReranker", FakeReranker),
            redirect_stdout(stdout),
        ):
            status = rag_cli.main(
                ["search", "q", "--mode", "text", "--reranker", "siliconflow", "--limit", "1", "--json"]
            )
        self.assertEqual(status, 0)
        self.assertEqual(len(json.loads(stdout.getvalue())), 1)

        class HostileList(list[dict[str, object]]):
            def __getitem__(self, _index: object) -> object:
                return [{"paragraph_id": str(index)} for index in range(100)]

        FakeReranker.outcome = type(
            "Outcome",
            (),
            {
                "results": HostileList(candidates),
                "model": "model",
                "degraded_feature": "",
                "error": "",
            },
        )()
        stderr = io.StringIO()
        with (
            patch("nihaisha_kg.cli.LocalVectorStore", FakeStore),
            patch("nihaisha_kg.cli.SiliconFlowReranker", FakeReranker),
            patch("sys.stderr", stderr),
        ):
            status = rag_cli.main(
                ["search", "q", "--mode", "text", "--reranker", "siliconflow", "--limit", "1", "--json"]
            )
        self.assertEqual(status, 1)
        self.assertIn("invalid reranker results", stderr.getvalue())

        FakeReranker.outcome = type(
            "Outcome",
            (),
            {"results": [object()], "model": "model", "degraded_feature": "", "error": ""},
        )()
        with (
            patch("nihaisha_kg.cli.LocalVectorStore", FakeStore),
            patch("nihaisha_kg.cli.SiliconFlowReranker", FakeReranker),
            patch("sys.stderr", io.StringIO()),
        ):
            self.assertEqual(
                rag_cli.main(
                    ["search", "q", "--mode", "text", "--reranker", "siliconflow", "--limit", "1", "--json"]
                ),
                1,
            )

        class RaisingMetadataOutcome:
            results = [{"paragraph_id": "p1", "text": "evidence"}]
            degraded_feature = ""
            error = ""

            @property
            def model(self) -> object:
                raise RuntimeError("credential-sentinel")

        FakeReranker.outcome = RaisingMetadataOutcome()
        stderr = io.StringIO()
        with (
            patch("nihaisha_kg.cli.LocalVectorStore", FakeStore),
            patch("nihaisha_kg.cli.SiliconFlowReranker", FakeReranker),
            patch("sys.stderr", stderr),
        ):
            status = rag_cli.main(
                [
                    "search", "q", "--mode", "text", "--reranker", "siliconflow",
                    "--limit", "1", "--json", "--trace",
                ]
            )
        self.assertEqual(status, 1)
        self.assertIn("invalid reranker outcome", stderr.getvalue())
        self.assertFalse("credential-sentinel" in stderr.getvalue())

    def test_cli_search_trace_is_allowlisted_bounded_and_reflects_selected_rows(self) -> None:
        secret = "sk-hostile-secret-123456789"
        hostile = {
            "paragraph_id": "p1",
            "text": secret,
            "score": 1.0,
            "retrieval_sources": ["text", f"api_key={secret}", {"bad": secret}],
            "channel_ranks": {"text": 2, "vector": 3, f"token={secret}": secret},
            "provider": {"authorization": secret},
        }

        class FakeStore:
            def __init__(self, *_args: object, **_kwargs: object) -> None:
                pass

            def search(self, *_args: object, **_kwargs: object) -> list[dict[str, object]]:
                return [hostile]

        stdout = io.StringIO()
        with patch("nihaisha_kg.cli.LocalVectorStore", FakeStore), redirect_stdout(stdout):
            status = rag_cli.main(
                [
                    "search",
                    f"query Auth\x1b[31orization: Digest username={secret}",
                    "--mode",
                    "text",
                    "--reranker",
                    "none",
                    "--json",
                    "--trace",
                ]
            )

        payload = json.loads(stdout.getvalue())
        serialized_trace = json.dumps(payload["trace"], ensure_ascii=False)
        self.assertEqual(status, 0)
        self.assertEqual(payload["trace"]["selected_paragraph_ids"], ["p1"])
        self.assertEqual(payload["trace"]["retrieval_channels"], ["text", "vector"])
        self.assertEqual(payload["trace"]["channel_ranks"], [{"paragraph_id": "p1", "text": 2, "vector": 3}])
        self.assertNotIn(secret, serialized_trace)
        self.assertNotIn("provider", serialized_trace)

    def test_cli_plain_search_trace_flag_does_not_append_trace_output(self) -> None:
        result = {
            "paragraph_id": "p1",
            "score": 1.0,
            "retrieval_sources": ["text"],
            "source_path": "/tmp/doc.pdf",
            "page_start": 1,
            "text": "evidence",
        }

        class FakeStore:
            def __init__(self, *_args: object, **_kwargs: object) -> None:
                pass

            def search(self, *_args: object, **_kwargs: object) -> list[dict[str, object]]:
                return [result]

        outputs: list[str] = []
        clock = unittest.mock.Mock(side_effect=AssertionError("clock must not run"))
        with (
            patch("nihaisha_kg.cli.LocalVectorStore", FakeStore),
            patch("nihaisha_kg.cli.time.perf_counter", clock),
        ):
            for extra in ([], ["--trace"]):
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    status = rag_cli.main(
                        ["search", "query", "--mode", "text", "--reranker", "none", *extra]
                    )
                self.assertEqual(status, 0)
                outputs.append(stdout.getvalue())

        self.assertEqual(outputs[0], outputs[1])
        self.assertNotIn("normalized_query", outputs[1])
        clock.assert_not_called()

    def test_search_trace_tolerates_hostile_mapping_subclasses(self) -> None:
        secret = "sk-hostile-container-123456"

        class HostileDict(dict[str, object]):
            def get(self, *_args: object, **_kwargs: object) -> object:
                raise RuntimeError(secret)

            def __iter__(self):  # type: ignore[no-untyped-def]
                raise KeyError(secret)

            def values(self):  # type: ignore[no-untyped-def]
                raise RecursionError(secret)

        row = HostileDict(
            paragraph_id="p1",
            retrieval_sources=["text"],
            channel_ranks=HostileDict(text=1),
        )

        trace = rag_cli._search_trace(
            "query",
            [row],
            reranker_model="none",
            latency_ms=float("inf"),
        )
        answer_plan_trace = pdf_vector._trace_query_plan(
            ["query"],
            [
                HostileDict(
                    paragraph_id="p1",
                    retrieval_sources=["text"],
                    channel_ranks=HostileDict(text=1),
                    rewrite_observations=[HostileDict(rewrite_index=1, rank=1)],
                )
            ],
        )

        serialized = json.dumps(trace, ensure_ascii=False, allow_nan=False)
        self.assertEqual(trace["selected_paragraph_ids"], ["p1"])
        self.assertEqual(trace["channel_ranks"], [{"paragraph_id": "p1", "text": 1}])
        self.assertNotIn(secret, serialized)
        self.assertEqual(trace["latency_ms"], {"search": 0.0})
        self.assertEqual(answer_plan_trace[0]["observations"][0]["paragraph_id"], "p1")
        self.assertNotIn(secret, json.dumps(answer_plan_trace, ensure_ascii=False))

    def test_cli_answer_forwards_reranker_model_and_trace_once(self) -> None:
        calls: list[dict[str, object]] = []

        def fake_answer(query: str, **kwargs: object) -> dict[str, object]:
            calls.append({"query": query, **kwargs})
            return {"answer": "ok", "citations": []}

        with patch("nihaisha_kg.cli.answer_pdf_rag", side_effect=fake_answer), redirect_stdout(io.StringIO()):
            status = rag_cli.main(
                ["answer", "question", "--mode", "text", "--reranker", "siliconflow", "--rerank-model", "chosen", "--trace", "--json"]
            )

        self.assertEqual(status, 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["reranker"], "siliconflow")
        self.assertEqual(calls[0]["rerank_model"], "chosen")
        self.assertIs(calls[0]["trace_enabled"], True)

    def test_cli_answer_reports_expected_failure_without_secret_or_traceback(self) -> None:
        secret = "answer-secret-value"
        stderr = io.StringIO()
        with (
            patch(
                "nihaisha_kg.cli.answer_pdf_rag",
                side_effect=RuntimeError(f"Auth\x9b31orization=Basic {secret}"),
            ),
            patch("sys.stderr", stderr),
        ):
            status = rag_cli.main(["answer", "question", "--mode", "text", "--json"])

        self.assertEqual(status, 1)
        self.assertIn("answer failed", stderr.getvalue())
        self.assertNotIn(secret, stderr.getvalue())

    def test_cli_error_and_trace_fail_closed_for_oversized_known_key_input(self) -> None:
        known_key = "configured-key-sentinel"
        oversized = known_key + "x" * MAX_SANITIZER_INPUT_CHARS + known_key
        stderr = io.StringIO()
        with (
            patch.dict(os.environ, {"SILICONFLOW_API_KEY": known_key}),
            patch("nihaisha_kg.cli.answer_pdf_rag", side_effect=RuntimeError(oversized)),
            patch("sys.stderr", stderr),
        ):
            status = rag_cli.main(["answer", "question", "--mode", "text", "--json"])

        self.assertEqual(status, 1)
        self.assertIn("[REDACTED]", stderr.getvalue())
        self.assertFalse(known_key in stderr.getvalue())

        class FakeStore:
            def __init__(self, *_args: object, **_kwargs: object) -> None:
                pass

            def search(self, *_args: object, **_kwargs: object) -> list[dict[str, object]]:
                return [{"paragraph_id": "p1", "text": "evidence", "score": 1.0}]

        stdout = io.StringIO()
        with (
            patch.dict(os.environ, {"SILICONFLOW_API_KEY": known_key}),
            patch("nihaisha_kg.cli.LocalVectorStore", FakeStore),
            redirect_stdout(stdout),
        ):
            status = rag_cli.main(
                [
                    "search", oversized, "--mode", "text", "--reranker", "none",
                    "--json", "--trace",
                ]
            )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(status, 0)
        self.assertEqual(payload["trace"]["normalized_query"], "[REDACTED]")
        self.assertFalse(known_key in json.dumps(payload["trace"], ensure_ascii=False))

    def test_split_sentences_keeps_chinese_clause_punctuation(self) -> None:
        text = "太阳中风，阳浮而阴弱。桂枝汤主之！若无汗，不可误作同证？"

        self.assertEqual(
            split_sentences(text),
            ["太阳中风，阳浮而阴弱。", "桂枝汤主之！", "若无汗，不可误作同证？"],
        )

    def test_build_retrieval_units_links_sentence_windows_to_paragraph(self) -> None:
        paragraph = ParsedParagraph(
            paragraph_id="p1",
            doc_id="doc",
            source_path="/tmp/doc.pdf",
            title="太阳病篇",
            page_start=3,
            page_end=3,
            text="太阳中风，阳浮而阴弱。桂枝汤主之。若无汗，不可误作同证。还须看恶风。",
        )

        units = build_retrieval_units([paragraph], window_size=2, overlap=1)
        unit_types = {unit.unit_type for unit in units}

        self.assertIn("sentence", unit_types)
        self.assertIn("window", unit_types)
        self.assertIn("paragraph", unit_types)
        self.assertTrue(all(unit.paragraph_id == "p1" for unit in units))
        self.assertTrue(any("太阳病篇" in unit.text_for_embedding for unit in units))

    def test_paragraph_generates_multiple_question_units_mapped_to_source(self) -> None:
        paragraph = ParsedParagraph(
            paragraph_id="p1",
            doc_id="doc",
            source_path="/tmp/doc.pdf",
            title="方证比较",
            page_start=9,
            page_end=9,
            text="太阳中风，汗出恶风，桂枝汤主之。太阳伤寒，无汗而喘，麻黄汤主之。少阴咽痛，可以讨论猪肤汤和桔梗汤。",
        )

        questions = generate_paragraph_questions(paragraph)
        units = build_retrieval_units([paragraph], window_size=2, overlap=1)
        question_units = [unit for unit in units if unit.unit_type == "question"]

        self.assertGreaterEqual(len(questions), 4)
        self.assertGreaterEqual(len(question_units), 4)
        self.assertTrue(all(unit.paragraph_id == "p1" for unit in question_units))
        self.assertTrue(all(unit.text.endswith("？") for unit in question_units))
        self.assertTrue(any("桂枝汤" in unit.text for unit in question_units))
        self.assertTrue(any("麻黄汤" in unit.text for unit in question_units))
        self.assertTrue(any("问题：" in unit.text_for_embedding for unit in question_units))

    def test_extract_knowledge_units_detects_grounded_dosage_method_and_formula(self) -> None:
        paragraph = ParsedParagraph(
            paragraph_id="p1",
            doc_id="doc",
            source_path="/tmp/doc.pdf",
            title="神农本草经 木香",
            page_start=33,
            page_end=33,
            text=(
                "一钱有人说是3.75克，也有人说4克，还有说5克，重点是黄金比例。"
                "木香饼（生地木香作饼），热熨贴之，治结肿成核，消乳中结核酸痛。"
                "太阳中风，汗出恶风，桂枝汤主之。若无汗，不可误作同证。"
            ),
        )

        units = extract_knowledge_units_from_paragraph(paragraph)
        by_type = {unit.unit_type: unit for unit in units}

        self.assertIn("dosage", by_type)
        self.assertEqual(by_type["dosage"].subject, "一钱")
        self.assertIn("3.75克", by_type["dosage"].object)
        self.assertIn("4克", by_type["dosage"].object)
        self.assertIn("5克", by_type["dosage"].object)
        self.assertIn("method", by_type)
        self.assertEqual(by_type["method"].subject, "木香饼热熨法")
        self.assertIn("结肿成核", by_type["method"].evidence_quote)
        self.assertIn("formula_pattern", by_type)
        self.assertEqual(by_type["formula_pattern"].subject, "桂枝汤")
        self.assertIn("caution", by_type)
        self.assertTrue(all(unit.paragraph_id == "p1" for unit in units))
        self.assertTrue(all(unit.source_path == "/tmp/doc.pdf" for unit in units))

    def test_rebuild_knowledge_units_is_idempotent_and_writes_trace(self) -> None:
        paragraph = ParsedParagraph(
            paragraph_id="p-a",
            doc_id="doc",
            source_path="/tmp/doc.pdf",
            title="神农本草经 木香",
            page_start=33,
            page_end=33,
            text="木香饼（生地木香作饼），热熨贴之，治结肿成核，消乳中结核酸痛。",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            manifest_path = base / "manifest.json"
            manifest_path.write_text(json.dumps({"paragraphs": 1}), encoding="utf-8")
            store = LocalVectorStore(base / "rag.sqlite")
            store.recreate()
            store.insert_paragraphs([paragraph])

            first = store.rebuild_knowledge_units(trace_dir=base / "traces")
            second = store.rebuild_knowledge_units(trace_dir=base / "traces")
            results = store.search_knowledge_units("木香饼热熨法 出处", limit=3)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            trace_exists = (base / "traces" / "knowledge_units.jsonl").exists()

        self.assertEqual(first["knowledge_units"], 1)
        self.assertEqual(second["knowledge_units"], 1)
        self.assertEqual(results[0]["paragraph_id"], "p-a")
        self.assertEqual(results[0]["unit_type"], "method")
        self.assertEqual(manifest["knowledge_units"], 1)
        self.assertEqual(manifest["knowledge_unit_types"]["method"], 1)
        self.assertEqual(manifest["knowledge_trace"], str(base / "traces" / "knowledge_units.jsonl"))
        self.assertTrue(trace_exists)

    def test_hybrid_search_includes_grounded_knowledge_units(self) -> None:
        paragraph = ParsedParagraph(
            paragraph_id="p-a",
            doc_id="doc",
            source_path="/tmp/doc.pdf",
            title="剂量说明",
            page_start=7,
            page_end=7,
            text="一钱有人说是3.75克，也有人说4克，还有说5克，重点是黄金比例。",
        )

        class ToyDenseBackend(DenseEmbeddingBackend):
            name = "toy_dense"

            def embed_texts(self, texts: list[str]) -> list[list[float]]:
                return [[1.0, 0.0] for _ in texts]

        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(Path(tmpdir) / "rag.sqlite", embedding_backend=ToyDenseBackend())
            store.recreate()
            store.insert_paragraphs([paragraph])
            store.insert_units(build_retrieval_units([paragraph], window_size=2, overlap=1))
            store.rebuild_knowledge_units()

            results = store.search_hybrid("古时候一钱是多少克", limit=3)

        self.assertEqual(results[0]["paragraph_id"], "p-a")
        self.assertIn("knowledge", results[0]["retrieval_sources"])
        self.assertEqual(results[0]["matched_knowledge_units"][0]["unit_type"], "dosage")
        self.assertIn("3.75克", results[0]["matched_knowledge_units"][0]["object"])

    def test_hybrid_search_fuses_channel_ranks_instead_of_adding_raw_scores(self) -> None:
        def result(paragraph_id: str, score: float, source: str) -> dict[str, object]:
            return {
                "paragraph_id": paragraph_id,
                "score": score,
                "vector_score": score if source == "vector" else 0.0,
                "text_score": score if source == "text" else 0.0,
                "knowledge_score": score if source == "knowledge" else 0.0,
                "retrieval_sources": [source],
                "matched_units": [],
                "matched_knowledge_units": [],
                "matched_text_terms": [],
                "unit_types": [],
            }

        store = LocalVectorStore(Path("unused.sqlite"))
        vector_results = [result("shared", 0.2, "vector"), result("vector-only", 99.0, "vector")]
        text_results = [result("shared", 0.1, "text"), result("text-only", 500.0, "text")]
        knowledge_results: list[dict[str, object]] = []
        original_vector = json.loads(json.dumps(vector_results))
        original_text = json.loads(json.dumps(text_results))

        with (
            patch.object(store, "search_vector", return_value=vector_results),
            patch.object(store, "search_text", return_value=text_results),
            patch.object(store, "search_knowledge_units", return_value=knowledge_results),
        ):
            results = store.search_hybrid("query", limit=3)

        self.assertEqual(results[0]["paragraph_id"], "shared")
        self.assertEqual(results[0]["channel_ranks"], {"text": 1, "vector": 1})
        self.assertEqual(results[0]["score"], results[0]["fusion_score"])
        self.assertEqual(vector_results, original_vector)
        self.assertEqual(text_results, original_text)

    def test_synthesize_answer_aggregates_dosage_evidence_with_citations(self) -> None:
        private = synthetic_private_values()
        private_source = rf"{private['windows_root']}\仲景心法.pdf"
        results = [
            {
                "paragraph_id": "p-a",
                "source_path": private_source,
                "title": "仲景心法 p20",
                "page_start": 20,
                "page_end": 20,
                "text": "倪师在南宁讲一钱等于3.75克，人纪教程是一钱约等于5克。",
                "matched_knowledge_units": [
                    {
                        "unit_type": "dosage",
                        "subject": "一钱",
                        "predicate": "换算与剂量原则",
                        "object": "3.75克；5克",
                        "evidence_quote": "倪师在南宁讲一钱等于3.75克，人纪教程是一钱约等于5克。",
                        "source_path": private_source,
                    }
                ],
            },
            {
                "paragraph_id": "p-b",
                "source_path": "/tmp/伤寒视频.pdf",
                "title": "伤寒视频 p25",
                "page_start": 25,
                "page_end": 25,
                "text": "中国人跟我讲，我们是一钱是5克。有的人跟我说一钱是3.6克。",
                "matched_knowledge_units": [
                    {
                        "unit_type": "dosage",
                        "subject": "一钱",
                        "predicate": "换算与剂量原则",
                        "object": "5克",
                        "evidence_quote": "中国人跟我讲，我们是一钱是5克。",
                    }
                ],
            },
        ]

        answer = synthesize_pdf_rag_answer("古时候一钱是多少克？", results)

        self.assertEqual(answer["intent"], "dosage")
        self.assertIn("3.75克", answer["answer"])
        self.assertIn("5克", answer["answer"])
        self.assertIn("3.6克", answer["answer"])
        self.assertIn("[1]", answer["answer"])
        self.assertEqual(len(answer["citations"]), 2)
        self.assertEqual(answer["citations"][0]["label"], "仲景心法.pdf p20")
        self.assertIn("3.6克", answer["citations"][1]["evidence_quote"])
        self.assertIn("不是个人用药剂量建议", answer["safety_notice"])
        self.assertIn("不同人的体质不同", answer["safety_notice"])
        self.assertIn("不要私自购药", answer["safety_notice"])
        self.assertIn("线下正规中医", answer["safety_notice"])
        self.assertEqual(len(answer["related_knowledge_units"]), 2)
        self.assertEqual(answer["related_knowledge_units"][0]["subject"], "一钱")
        self.assertIn("3.75克", answer["related_knowledge_units"][0]["object"])
        self.assertEqual(answer["related_knowledge_units"][0]["source_path"], "pdfs/仲景心法.pdf")
        self.assertEqual(answer["related_knowledge_units"][0]["page_start"], 20)
        self.assertEqual(answer["related_knowledge_units"][0]["label"], "仲景心法.pdf p20")

    def test_source_query_plan_and_anchors_use_named_topic_without_fixed_method_terms(self) -> None:
        plan = build_query_plan("桂枝汤的出处在哪本书哪一页？", intent="source_lookup")
        anchors = answer_anchor_terms("桂枝汤的出处在哪本书哪一页？")

        self.assertIn("桂枝汤", anchors)
        self.assertTrue(any("出处" in query and "原文" in query for query in plan))
        self.assertNotIn("木香饼", "\n".join(plan))
        self.assertNotIn("热熨", "\n".join(plan))

    def test_reference_book_query_rewrites_to_course_booklist_and_filters_noise(self) -> None:
        query = "倪海厦推荐过哪些伤寒参考书？"
        plan = build_query_plan(query)
        booklist = {
            "paragraph_id": "p-booklist",
            "source_path": "pdfs/人纪04伤寒视频同步文稿 2024新版.pdf",
            "source_layer": "course_primary",
            "title": "人纪04伤寒视频同步文稿 2024新版 p276",
            "page_start": 276,
            "page_end": 276,
            "text": (
                "我这里开八本书给诸位，书单诸位看完以后尽量赶快去找。"
                "《伤寒论辑义》《世补斋医书全集》《徐灵胎医书全集》"
                "《伤寒杂病论》《石室秘录》《黄帝外经》《伤寒论解说》这都可以拿来参考。"
            ),
        }
        noise = {
            "paragraph_id": "p-noise",
            "source_path": "pdfs/伤寒论.pdf",
            "source_layer": "course_primary",
            "title": "伤寒论 p4",
            "page_start": 4,
            "page_end": 4,
            "text": "这是伤寒论电子书说明和目录。",
        }

        filtered = filter_results_for_intent(query, "source_lookup", [noise, booklist])
        answer = synthesize_pdf_rag_answer(query, [noise, booklist])

        self.assertEqual(pdf_vector.detect_answer_intent(query), "source_lookup")
        self.assertIn("书单 开八本书 参考 看伤寒", plan)
        self.assertNotIn("出处 原文 治法 材料 方法 来源", plan)
        self.assertEqual([row["paragraph_id"] for row in filtered], ["p-booklist"])
        self.assertIn("《伤寒论辑义》", answer["answer"])
        self.assertIn("《伤寒论解说》", answer["answer"])
        self.assertIn("详细依据", answer["answer"])
        self.assertEqual(len(answer["answer_sections"]["key_points"]), 2)
        self.assertEqual(answer["answer_sections"]["citation_count"], 1)
        self.assertEqual(answer["citations"][0]["label"], "人纪04伤寒视频同步文稿 2024新版.pdf p276")
        self.assertIn("开八本书", answer["citations"][0]["evidence_quote"])
        self.assertIn("世补斋医书全集", answer["citations"][0]["evidence_quote"])

    def test_build_query_plan_creates_multiple_generic_retrieval_queries(self) -> None:
        plan = build_query_plan("古时候的一钱，是现代的多少克？", intent="dosage")

        self.assertGreaterEqual(len(plan), 3)
        self.assertNotEqual(plan[0], "古时候的一钱，是现代的多少克？")
        self.assertTrue(any("剂量" in query and "换算" in query for query in plan))
        self.assertTrue(any("古时候" not in query and "一钱" in query for query in plan[1:]))
        self.assertEqual(plan[-1], "古时候的一钱，是现代的多少克？")
        joined_plan = "\n".join(plan)
        self.assertNotIn("3.75克", joined_plan)
        self.assertNotIn("3.6克", joined_plan)
        self.assertNotIn("5克", joined_plan)

    def test_clinical_query_plan_rewrites_long_case_before_raw_fallback(self) -> None:
        query = (
            "病人，男，25岁，亚裔。三天前开始感觉疲劳，肩颈酸痛，怕冷。"
            "之后开始头痛，发烧39摄氏度，咳嗽，咽喉疼痛，有白痰。"
            "昨天上午退烧了，但下午开始拉肚子，排泄物黄臭，恶心，食欲很差。"
            "建议开什么中药方？"
        )

        plan = build_query_plan(query, intent="clinical")
        primary_queries = plan[:-1]
        joined_primary = "\n".join(primary_queries)

        self.assertEqual(plan[-1], query)
        self.assertNotIn("男", joined_primary)
        self.assertNotIn("25岁", joined_primary)
        self.assertNotIn("亚裔", joined_primary)
        self.assertTrue(any("下利" in item or "拉肚子" in item for item in primary_queries))
        self.assertIn("黄臭", joined_primary)
        self.assertIn("恶心", joined_primary)
        self.assertIn("热利", joined_primary)
        self.assertTrue(any("黄芩加半夏生姜汤" in item for item in primary_queries))
        self.assertTrue(any("葛根黄芩黄连汤" in item for item in primary_queries))

    def test_query_plan_can_add_evidence_derived_followup_queries(self) -> None:
        seed_results = [
            {
                "paragraph_id": "p-a",
                "title": "剂量 p1",
                "source_path": "/tmp/a.pdf",
                "page_start": 1,
                "page_end": 1,
                "text": "一钱是5克，也有人说一钱是3.6克，古今度量衡不同，还要看比例。",
                "matched_knowledge_units": [
                    {
                        "unit_type": "dosage",
                        "subject": "一钱",
                        "predicate": "换算与剂量原则",
                        "object": "5克",
                        "evidence_quote": "一钱是5克，也有人说一钱是3.6克。",
                    }
                ],
            }
        ]

        plan = build_query_plan("古时候的一钱，是现代的多少克？", intent="dosage", seed_results=seed_results)

        self.assertGreaterEqual(len(plan), 5)
        self.assertTrue(any("5克" in query or "3.6克" in query for query in plan))
        self.assertTrue(any("度量衡" in query and "比例" in query for query in plan))

    def test_query_plan_handles_seed_results_when_raw_query_is_already_primary(self) -> None:
        query = "下利 恶心 黄芩加半夏生姜汤"
        seed_results = [
            {
                "paragraph_id": "p-a",
                "text": "下利，恶心，黄芩加半夏生姜汤。",
                "matched_knowledge_units": [
                    {
                        "unit_type": "formula_pattern",
                        "subject": "黄芩加半夏生姜汤",
                        "predicate": "方证线索",
                        "object": "下利、恶心",
                        "evidence_quote": "下利，恶心，黄芩加半夏生姜汤。",
                    }
                ],
            }
        ]

        plan = build_query_plan(query, intent="clinical", seed_results=seed_results, max_queries=2)

        self.assertLessEqual(len(plan), 2)
        self.assertIn(query, plan)

    def test_fuse_query_rewrites_selects_one_atomic_representative_observation(self) -> None:
        result_a = {
            "paragraph_id": "p-a",
            "score": 10.0,
            "fusion_score": 0.03,
            "channel_ranks": {"text": 1},
            "raw_channel_scores": {"text": 10.0},
            "vector_score": 0.0,
            "text_score": 10.0,
            "knowledge_score": 0.0,
            "retrieval_sources": ["text"],
            "matched_knowledge_units": [],
            "matched_units": [],
        }
        result_b_low_first = {
            "paragraph_id": "p-b",
            "score": 1.0,
            "fusion_score": 0.02,
            "channel_ranks": {"text": 2, "vector": 3},
            "raw_channel_scores": {"text": 1.0, "vector": 0.5},
            "vector_score": 0.0,
            "text_score": 1.0,
            "knowledge_score": 0.0,
            "retrieval_sources": ["text"],
            "matched_knowledge_units": [],
            "matched_units": [],
        }
        result_b_high_second = {
            **result_b_low_first,
            "score": 8.0,
            "fusion_score": 0.04,
            "channel_ranks": {"knowledge": 1, "vector": 2},
            "raw_channel_scores": {"knowledge": 800.0, "vector": 0.8},
            "vector_score": 0.8,
            "text_score": 0.0,
            "knowledge_score": 800.0,
            "retrieval_sources": ["knowledge", "vector"],
            "matched_knowledge_units": [{"id": "ku-1"}],
            "matched_units": [{"id": "unit-1"}],
        }

        fused = fuse_query_rewrites(
            [
                [result_a, result_b_low_first],
                [result_b_high_second],
            ],
            limit=2,
            rank_constant=10,
        )

        self.assertEqual(fused[0]["paragraph_id"], "p-b")
        self.assertEqual(fused[0]["score"], fused[0]["query_fusion_score"])
        self.assertAlmostEqual(fused[0]["query_fusion_score"], 1 / 12 + 1 / 11)
        self.assertEqual(fused[0]["fusion_score"], 0.04)
        self.assertEqual(fused[0]["channel_ranks"], {"knowledge": 1, "vector": 2})
        self.assertEqual(fused[0]["raw_channel_scores"], {"knowledge": 800.0, "vector": 0.8})
        self.assertEqual(fused[0]["vector_score"], 0.8)
        self.assertEqual(fused[0]["text_score"], 0.0)
        self.assertEqual(fused[0]["knowledge_score"], 800.0)
        self.assertEqual(fused[0]["raw_score"], 8.0)
        self.assertEqual(
            fused[0]["rewrite_observations"],
            [
                {
                    "rewrite_index": 1,
                    "rank": 2,
                    "raw_score": 1.0,
                    "fusion_score": 0.02,
                    "channel_ranks": {"text": 2, "vector": 3},
                },
                {
                    "rewrite_index": 2,
                    "rank": 1,
                    "raw_score": 8.0,
                    "fusion_score": 0.04,
                    "channel_ranks": {"knowledge": 1, "vector": 2},
                },
            ],
        )

    def test_fuse_query_rewrites_counts_duplicate_once_but_inspects_it_for_representative(self) -> None:
        first = {
            "paragraph_id": "p-a",
            "score": 2.0,
            "fusion_score": 0.02,
            "channel_ranks": {"text": 1},
            "matched_units": [{"id": "first"}],
        }
        duplicate = {
            "paragraph_id": "p-a",
            "score": 999.0,
            "fusion_score": 0.99,
            "channel_ranks": {"knowledge": 1},
            "matched_units": [{"id": "duplicate"}],
        }

        fused = fuse_query_rewrites([[first, duplicate]], limit=1, rank_constant=10)

        self.assertAlmostEqual(fused[0]["query_fusion_score"], 1 / 11)
        self.assertEqual(fused[0]["raw_score"], 999.0)
        self.assertEqual(fused[0]["fusion_score"], 0.99)
        self.assertEqual(fused[0]["channel_ranks"], {"knowledge": 1})
        self.assertEqual(fused[0]["matched_units"], [{"id": "first"}, {"id": "duplicate"}])
        self.assertEqual(len(fused[0]["rewrite_observations"]), 2)

    def test_fuse_query_rewrites_deduplicates_merged_list_diagnostics(self) -> None:
        shared_unit = {"id": "unit-1", "payload": ["桂枝", {"x": 1}]}
        first = {
            "paragraph_id": "p-a",
            "score": 2.0,
            "retrieval_sources": ["text"],
            "matched_units": [shared_unit],
            "matched_knowledge_units": [{"id": "ku-1"}],
            "matched_text_terms": ["桂枝"],
            "unit_types": ["formula"],
        }
        second = {
            **first,
            "score": 1.0,
            "retrieval_sources": ["knowledge", "text"],
            "matched_units": [dict(shared_unit), {"id": "unit-2"}],
            "matched_knowledge_units": [{"id": "ku-1"}, {"id": "ku-2"}],
            "matched_text_terms": ["桂枝", "麻黄"],
            "unit_types": ["formula", "clinical"],
        }

        fused = fuse_query_rewrites([[first], [second]], limit=1)

        self.assertEqual(fused[0]["retrieval_sources"], ["knowledge", "text"])
        self.assertEqual(fused[0]["matched_units"], [shared_unit, {"id": "unit-2"}])
        self.assertEqual(fused[0]["matched_knowledge_units"], [{"id": "ku-1"}, {"id": "ku-2"}])
        self.assertEqual(fused[0]["matched_text_terms"], ["桂枝", "麻黄"])
        self.assertEqual(fused[0]["unit_types"], ["formula", "clinical"])

    def test_fuse_query_rewrites_has_stable_ties_and_nonpositive_limits(self) -> None:
        p_a = {"paragraph_id": "p-a", "score": 1.0}
        p_b = {"paragraph_id": "p-b", "score": 1.0}

        first_order = fuse_query_rewrites([[p_b], [p_a]], limit=2)
        second_order = fuse_query_rewrites([[p_a], [p_b]], limit=2)

        self.assertEqual([item["paragraph_id"] for item in first_order], ["p-a", "p-b"])
        self.assertEqual([item["paragraph_id"] for item in second_order], ["p-a", "p-b"])
        self.assertEqual(fuse_query_rewrites([[p_a]], limit=0), [])
        self.assertEqual(fuse_query_rewrites([[p_a]], limit=-1), [])

    def test_fuse_query_rewrites_bounds_observation_trace(self) -> None:
        result_sets = [[{"paragraph_id": "p-a", "score": float(index)}] for index in range(20)]

        fused = fuse_query_rewrites(result_sets, limit=1)

        self.assertEqual(fused[0]["rewrite_observation_count"], 20)
        self.assertLessEqual(len(fused[0]["rewrite_observations"]), 16)

    def test_run_query_plan_search_executes_distinct_queries_and_fuses_results(self) -> None:
        class FakeStore:
            def __init__(self) -> None:
                self.calls: list[tuple[str, str, int]] = []

            def search(self, query: str, limit: int, mode: str) -> list[dict[str, object]]:
                self.calls.append((mode, query, limit))
                paragraph_id = "p-shared" if "度量衡" in query or "一钱" in query else "p-other"
                return [
                    {
                        "paragraph_id": paragraph_id,
                        "score": 1.0,
                        "vector_score": 0.0,
                        "text_score": 1.0,
                        "knowledge_score": 0.0,
                        "retrieval_sources": ["text"],
                        "matched_knowledge_units": [],
                        "matched_units": [],
                    }
                ]

            def search_knowledge_units(self, query: str, limit: int) -> list[dict[str, object]]:
                self.calls.append(("knowledge", query, limit))
                return []

        store = FakeStore()
        plan = ["原始问题", "一钱 剂量", "度量衡 比例"]

        results = run_query_plan_search(store, plan, limit=3, mode="hybrid", intent="dosage")

        searched_queries = [call[1] for call in store.calls if call[0] == "hybrid"]
        self.assertEqual(searched_queries, plan)
        self.assertFalse(any(call[0] == "knowledge" for call in store.calls))
        self.assertEqual(results[0]["paragraph_id"], "p-shared")

    def test_clinical_query_plan_filters_single_term_noise_before_fusion(self) -> None:
        class FakeStore:
            def search(self, query: str, limit: int, mode: str) -> list[dict[str, object]]:
                if "黄芩加半夏生姜汤" in query:
                    return [
                        {
                            "paragraph_id": "p-good",
                            "score": 1.0,
                            "text": "下利，恶心，黄芩加半夏生姜汤。",
                            "title": "伤寒 p169",
                            "source_path": "/tmp/good.pdf",
                            "page_start": 169,
                            "page_end": 169,
                            "vector_score": 0.0,
                            "text_score": 1.0,
                            "knowledge_score": 0.0,
                            "retrieval_sources": ["text"],
                            "matched_knowledge_units": [],
                            "matched_units": [],
                        }
                    ]
                return [
                    {
                        "paragraph_id": "p-noise",
                        "score": 10.0,
                        "text": "某段只提到下利一次。",
                        "title": "噪声 p1",
                        "source_path": "/tmp/noise.pdf",
                        "page_start": 1,
                        "page_end": 1,
                        "vector_score": 0.0,
                        "text_score": 10.0,
                        "knowledge_score": 0.0,
                        "retrieval_sources": ["text"],
                        "matched_knowledge_units": [],
                        "matched_units": [],
                    }
                ]

            def search_knowledge_units(self, query: str, limit: int) -> list[dict[str, object]]:
                return []

        results = run_query_plan_search(
            FakeStore(),
            ["下利 黄臭 热利 方证 鉴别", "下利 恶心 黄芩加半夏生姜汤 黄芩汤"],
            limit=4,
            mode="hybrid",
            intent="clinical",
        )

        self.assertEqual(results[0]["paragraph_id"], "p-good")
        self.assertNotIn("p-noise", {str(result["paragraph_id"]) for result in results})

    def test_clinical_intent_filter_requires_formula_or_multiple_core_clues(self) -> None:
        noisy = {
            "paragraph_id": "p-noise",
            "title": "针灸 p79",
            "text": "任何胃病、胸口闷痛、气喘咳嗽，通通可以治。",
            "matched_knowledge_units": [],
        }
        useful = {
            "paragraph_id": "p-useful",
            "title": "伤寒 p169",
            "text": "病人下利、黄臭、恶心，要看热利与寒利。",
            "matched_knowledge_units": [],
        }

        filtered = filter_results_for_intent("病人下利黄臭恶心", "clinical", [noisy, useful])

        self.assertEqual([item["paragraph_id"] for item in filtered], ["p-useful"])

    def test_clinical_intent_filter_does_not_keep_formula_name_without_clues(self) -> None:
        formula_only = {
            "paragraph_id": "p-formula-only",
            "title": "方剂提及 p1",
            "text": "老师这里提到葛根黄芩黄连汤这个方。",
            "matched_knowledge_units": [],
        }
        formula_with_clue = {
            "paragraph_id": "p-formula-clue",
            "title": "伤寒 p168",
            "text": "葛根黄芩黄连汤，治下利，属于热利。",
            "matched_knowledge_units": [],
        }
        clue_cluster = {
            "paragraph_id": "p-clue-cluster",
            "title": "伤寒 p169",
            "text": "病人下利、黄臭、恶心，要看热利与寒利。",
            "matched_knowledge_units": [],
        }

        filtered = filter_results_for_intent(
            "病人下利黄臭恶心",
            "clinical",
            [formula_only, formula_with_clue, clue_cluster],
        )

        self.assertEqual(
            [item["paragraph_id"] for item in filtered],
            ["p-formula-clue"],
        )

    def test_formula_extraction_rejects_common_non_formula_san_words(self) -> None:
        text = "病势越来越扩散，来急去散，提到睾丸；这里才是真正的葛根黄芩黄连汤和四逆散。"

        formulas = extract_formula_terms(text)

        self.assertIn("葛根黄芩黄连汤", formulas)
        self.assertIn("四逆散", formulas)
        self.assertNotIn("越来越扩散", formulas)
        self.assertNotIn("来急去散", formulas)
        self.assertFalse(any("睾丸" in formula for formula in formulas))

    def test_formula_extraction_strips_common_instructional_prefixes(self) -> None:
        text = "所以桂枝人参汤和葛根黄芩黄连汤互为鉴别；有表证时解表用桂枝汤；这就是甘草泻心汤。"

        formulas = extract_formula_terms(text)

        self.assertIn("桂枝人参汤", formulas)
        self.assertIn("葛根黄芩黄连汤", formulas)
        self.assertIn("桂枝汤", formulas)
        self.assertIn("甘草泻心汤", formulas)
        self.assertFalse(any(formula.startswith(("所以", "解表用", "就是")) for formula in formulas))

    def test_known_formula_evidence_uses_longest_valid_occurrence(self) -> None:
        text = "乌头桂枝汤用于寒疝；太阳中风，桂枝汤主之；另有桂枝汤锅产品。"

        formulas = known_formula_terms_in_evidence(text)

        self.assertEqual(formulas, ["乌头桂枝汤", "桂枝汤"])

    def test_known_formula_evidence_suppresses_short_anchor_inside_unknown_compound(self) -> None:
        self.assertEqual(known_formula_terms_in_evidence("通脉四逆汤主之。"), ["通脉四逆汤"])
        self.assertEqual(known_formula_terms_in_evidence("太阳中风桂枝汤。"), [])
        self.assertEqual(known_formula_terms_in_evidence("桂枝汤主之。"), ["桂枝汤"])
        self.assertEqual(known_formula_terms_in_evidence("用桂枝汤。"), ["桂枝汤"])

    def test_explicit_query_formula_terms_are_product_safe_and_bounded(self) -> None:
        confirmed = ("白虎加人参汤", "通脉四逆汤", "大陷胸汤", "小半夏汤")
        rejected = ("喝人参鸡汤", "人参鸡汤", "排骨汤", "酸辣汤", "因为桂枝汤")
        for formula in confirmed:
            with self.subTest(confirmed=formula):
                self.assertEqual(pdf_vector.reliable_formula_anchors(f"{formula}出处"), [formula])
                self.assertEqual(explicit_query_formula_terms(f"{formula}出处"), [])
        for phrase in rejected:
            with self.subTest(rejected=phrase):
                self.assertEqual(explicit_query_formula_terms(f"{phrase}出处"), [])
        self.assertEqual(explicit_query_formula_terms("桂枝汤圆出处"), [])
        many = "、".join(f"测试{index}桂枝汤" for index in range(20)) + "出处"
        self.assertLessEqual(len(explicit_query_formula_terms(many)), 8)

    def test_clinical_formula_output_allows_only_matching_request_scoped_compound(self) -> None:
        result = {
            "paragraph_id": "p-explicit",
            "source_path": "/tmp/课程.pdf",
            "title": "课程 p1",
            "page_start": 1,
            "page_end": 1,
            "text": "患者发热口渴，白虎加人参汤见于本段。白虎汤主之。",
            "matched_knowledge_units": [
                {"unit_type": "clinical_pattern", "evidence_quote": "患者发热口渴"}
            ],
        }
        explicit = synthesize_pdf_rag_answer("患者发热口渴，白虎加人参汤如何理解？", [result])
        explicit_compound = synthesize_pdf_rag_answer(
            "患者下利恶心，通脉四逆汤如何理解？",
            [{**result, "text": "患者下利恶心，通脉四逆汤见于本段。"}],
        )
        generic = synthesize_pdf_rag_answer(
            "患者咳嗽怕冷，开什么方？",
            [{**result, "text": "患者咳嗽怕冷，通脉四逆汤见于旁文。"}],
        )

        self.assertIn("方名包括：白虎加人参汤。", explicit["answer"])
        self.assertIn("白虎加人参汤", explicit["citations"][0]["evidence_quote"])
        self.assertIn("方名包括：通脉四逆汤。", explicit_compound["answer"])
        self.assertIn("方名包括：通脉四逆汤。", generic["answer"])
        self.assertNotIn("方名包括：四逆汤。", generic["answer"])

    def test_clinical_requested_compound_focuses_results_over_shorter_curated_formula(self) -> None:
        compound = {
            "paragraph_id": "p-compound",
            "source_path": "/tmp/课程.pdf",
            "title": "课程 p1",
            "page_start": 1,
            "page_end": 1,
            "text": "患者发热口渴，白虎加人参汤见于本段。",
            "matched_knowledge_units": [
                {"unit_type": "clinical_pattern", "evidence_quote": "患者发热口渴"}
            ],
        }
        shorter = {
            **compound,
            "paragraph_id": "p-shorter",
            "page_start": 2,
            "page_end": 2,
            "text": "患者发热口渴，白虎汤主之。",
        }

        for suffix in ("开什么方", "是什么方", "怎么理解", "如何理解"):
            with self.subTest(suffix=suffix):
                query = f"患者发热口渴，白虎加人参汤{suffix}？"
                self.assertEqual(pdf_vector.reliable_formula_anchors(query), ["白虎加人参汤"])

                answer = synthesize_pdf_rag_answer(query, [shorter, compound])

                self.assertIn("方名包括：白虎加人参汤。", answer["answer"])
                self.assertNotIn("方名包括：白虎汤", answer["answer"])
                self.assertEqual(
                    [item["paragraph_id"] for item in answer["citations"]], ["p-compound"]
                )
                self.assertIn("白虎加人参汤", answer["citations"][0]["evidence_quote"])

    def test_clinical_direct_curated_formula_still_works_without_explicit_unknown(self) -> None:
        result = {
            "paragraph_id": "p-direct-known",
            "source_path": "/tmp/课程.pdf",
            "title": "课程 p3",
            "page_start": 3,
            "page_end": 3,
            "text": "患者恶寒无汗而喘，麻黄汤主之。",
            "matched_knowledge_units": [],
        }

        answer = synthesize_pdf_rag_answer("患者恶寒无汗而喘，开什么方？", [result])

        self.assertIn("麻黄汤", answer["answer"])
        self.assertEqual(answer["citations"][0]["paragraph_id"], "p-direct-known")

    def test_invented_literal_herb_soups_never_become_clinical_formula_authority(self) -> None:
        invented = ("桂枝热汤", "生姜热汤", "麻黄热汤", "甘草红枣汤")
        for formula in invented:
            with self.subTest(formula=formula):
                result = {
                    "paragraph_id": f"p-{formula}",
                    "source_path": "/tmp/课程.pdf",
                    "title": "课程 p5",
                    "page_start": 5,
                    "page_end": 5,
                    "text": f"患者下利恶心，饮食段落提到{formula}。",
                    "matched_knowledge_units": [],
                }
                answer = synthesize_pdf_rag_answer(
                    f"患者下利恶心，{formula}如何理解？", [result]
                )
                self.assertNotIn(f"方名包括：{formula}", answer["answer"])

    def test_no_result_formula_like_source_queries_keep_medical_safety_without_assertion(self) -> None:
        for query in ("大陷胸汤出处", "白虎加人参汤出处", "桂枝热汤出处"):
            with self.subTest(query=query):
                answer = synthesize_pdf_rag_answer(query, [])
                self.assertIn(pdf_vector.FORMULA_DOSAGE_SAFETY_NOTICE, answer["safety_notice"])
                self.assertIn("没有检索到足够可靠的原文证据", answer["answer"])

    def test_source_lookup_does_not_treat_embedded_short_formula_as_direct_evidence(self) -> None:
        longer = {
            "paragraph_id": "p-longer",
            "source_path": "/tmp/金匮.pdf",
            "title": "金匮 p1",
            "page_start": 1,
            "page_end": 1,
            "text": "寒疝腹中痛，乌头桂枝汤主之。桂枝汤要另外煮过，再加入乌头蜜。",
            "matched_knowledge_units": [],
        }
        direct = {
            "paragraph_id": "p-direct",
            "source_path": "/tmp/伤寒.pdf",
            "title": "伤寒 p2",
            "page_start": 2,
            "page_end": 2,
            "text": "太阳中风，桂枝汤主之。",
            "matched_knowledge_units": [],
        }

        answer = synthesize_pdf_rag_answer("桂枝汤出处", [longer, direct])

        self.assertEqual([item["paragraph_id"] for item in answer["citations"]], ["p-direct"])
        self.assertNotIn("乌头桂枝汤", answer["answer"])

    def test_text_store_source_lookup_retains_only_direct_formula_evidence(self) -> None:
        paragraphs = [
            ParsedParagraph(
                paragraph_id="p-longer", doc_id="doc", source_path="/tmp/金匮.pdf",
                title="金匮 p1", page_start=1, page_end=1,
                text="寒疝腹中痛，乌头桂枝汤主之。",
            ),
            ParsedParagraph(
                paragraph_id="p-direct", doc_id="doc", source_path="/tmp/伤寒.pdf",
                title="伤寒 p2", page_start=2, page_end=2,
                text="太阳中风，桂枝汤主之。",
            ),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(Path(tmpdir) / "rag.sqlite")
            store.recreate()
            store.insert_paragraphs(paragraphs)
            store.rebuild_text_index()
            candidates = store.search("桂枝汤 出处", limit=8, mode="text")

        answer = synthesize_pdf_rag_answer("桂枝汤出处", candidates)

        self.assertEqual([item["paragraph_id"] for item in answer["citations"]], ["p-direct"])
        self.assertNotIn("乌头桂枝汤", answer["answer"])

    def test_clinical_answer_asserts_only_curated_formulas_from_primary_evidence(self) -> None:
        result = {
            "paragraph_id": "p-clinical",
            "source_path": "/tmp/伤寒.pdf",
            "title": "伤寒 p3",
            "page_start": 3,
            "page_end": 3,
            "text": (
                "有四逆很多汤，也可能出现麻黄汤，因为桂枝汤；夏汤只是残片。"
                "病人恶寒咳嗽。太阳中风，桂枝汤主之。太阳伤寒，无汗而喘，麻黄汤主之。"
            ),
            "matched_knowledge_units": [
                {
                    "unit_type": "formula_pattern",
                    "subject": "有四逆很多汤",
                    "predicate": "主治",
                    "object": "夏汤和伪造汤",
                    "evidence_quote": "图谱错误字段，不是原文。",
                }
            ],
        }

        answer = synthesize_pdf_rag_answer("病人怕冷咳嗽，开什么方？", [result])

        self.assertIn("桂枝汤", answer["answer"])
        self.assertIn("麻黄汤", answer["answer"])
        self.assertNotIn("有四逆很多汤", answer["answer"])
        self.assertNotIn("夏汤", answer["answer"])
        self.assertNotIn("伪造汤", answer["answer"])

    def test_general_answer_uses_primary_paragraph_not_hostile_derived_unit(self) -> None:
        result = {
            "paragraph_id": "p-general",
            "source_path": "/tmp/课程.pdf",
            "title": "课程 p4",
            "page_start": 4,
            "page_end": 4,
            "text": "课程原文说明太阳病可见恶寒，并提醒应结合原段落上下文理解。",
            "matched_knowledge_units": [
                {
                    "unit_type": "clinical_pattern",
                    "subject": "错误结论",
                    "predicate": "等于",
                    "object": "太阳病必然不恶寒",
                    "evidence_quote": "派生导航字段可能有误",
                }
            ],
        }

        answer = synthesize_pdf_rag_answer("太阳病怎么理解", [result])

        self.assertIn("太阳病可见恶寒", answer["answer"])
        self.assertNotIn("错误结论", answer["answer"])
        self.assertNotIn("必然不恶寒", answer["answer"])
        self.assertEqual(answer["related_knowledge_units"][0]["subject"], "错误结论")

    def test_clinical_intent_filter_prefers_formula_evidence_over_symptom_only(self) -> None:
        symptom_only = {
            "paragraph_id": "p-symptom-only",
            "title": "针灸 p131",
            "text": "有的时候很麻烦要上吐下利，按着内关想好恶心，全部吐掉。",
            "matched_knowledge_units": [],
        }
        formula_evidence = {
            "paragraph_id": "p-formula",
            "title": "伤寒 p169",
            "text": "黄芩加半夏生姜汤，治下利，是热利，同时有恶心。",
            "matched_knowledge_units": [
                {"unit_type": "formula_pattern", "subject": "黄芩加半夏生姜汤", "object": "下利恶心"}
            ],
        }

        filtered = filter_results_for_intent(
            "病人下利恶心",
            "clinical",
            [symptom_only, formula_evidence],
        )

        self.assertEqual([item["paragraph_id"] for item in filtered], ["p-formula"])

    def test_clinical_diversity_selection_prioritizes_richer_formula_pattern_evidence(self) -> None:
        thin_formula = {
            "paragraph_id": "p-thin",
            "score": 10.0,
            "title": "金匮 p59",
            "source_path": "/tmp/a.pdf",
            "page_start": 59,
            "page_end": 59,
            "text": "下利，恶心，甘草泻心汤证。",
            "matched_knowledge_units": [],
        }
        rich_formula = {
            "paragraph_id": "p-rich",
            "score": 6.0,
            "title": "伤寒 p169",
            "source_path": "/tmp/b.pdf",
            "page_start": 169,
            "page_end": 169,
            "text": "黄芩加半夏生姜汤，治下利，是热利，腹痛，同时有恶心。",
            "matched_knowledge_units": [
                {"unit_type": "formula_pattern", "subject": "黄芩加半夏生姜汤", "object": "热利下利恶心腹痛"}
            ],
        }

        selected = select_diverse_results([thin_formula, rich_formula], limit=2, intent="clinical")

        self.assertEqual(selected[0]["paragraph_id"], "p-rich")

    def test_clinical_diversity_selection_accepts_empty_filtered_results(self) -> None:
        self.assertEqual(select_diverse_results([], limit=8, intent="clinical"), [])

    def test_answer_pdf_rag_runs_followup_search_for_diverse_dosage_evidence(self) -> None:
        seed = ParsedParagraph(
            paragraph_id="p-seed",
            doc_id="doc",
            source_path="/tmp/伤寒.pdf",
            title="伤寒 p25",
            page_start=25,
            page_end=25,
            text="一钱是5克，也有人说一钱是3.6克，古今度量衡不同，不要斤斤计较，还要看比例。",
        )
        conversion = ParsedParagraph(
            paragraph_id="p-conversion",
            doc_id="doc",
            source_path="/tmp/本草.pdf",
            title="本草 p20",
            page_start=20,
            page_end=20,
            text="中国用克，几克几克，看不懂，大概1钱3.3克，有尾数的3.3克，差个1克2克，误解成4克5克，这一点点倒无所谓，1克的剂量差不了多少。",
        )
        ratio = ParsedParagraph(
            paragraph_id="p-ratio",
            doc_id="doc",
            source_path="/tmp/伤寒.pdf",
            title="伤寒 p49",
            page_start=49,
            page_end=49,
            text="所以黄金比例，就是4：3：2：2，黄金比例很重要。葛根汤重用葛根，再来重用麻黄。",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "rag.sqlite"
            store = LocalVectorStore(db_path)
            store.recreate()
            store.insert_paragraphs([seed, conversion, ratio])
            store.rebuild_text_index()
            store.rebuild_knowledge_units()

            answer = answer_pdf_rag(
                "古时候的一钱，是现代的多少克？",
                db_path=db_path,
                mode="text",
                limit=3,
                reranker="none",
            )

        citation_text = "\n".join(str(citation["evidence_quote"]) for citation in answer["citations"])
        self.assertIn("3.3克", answer["answer"])
        self.assertIn("3.6克", answer["answer"])
        self.assertIn("5克", answer["answer"])
        self.assertNotIn("1克", answer["answer"])
        self.assertNotIn("2克", answer["answer"])
        self.assertIn("3.3克", citation_text)
        self.assertIn("黄金比例", citation_text)
        self.assertEqual(
            {"p-seed", "p-conversion", "p-ratio"},
            {str(citation["paragraph_id"]) for citation in answer["citations"]},
        )

    def test_answer_pdf_rag_attaches_links_from_final_visible_citations(self) -> None:
        candidate = {"paragraph_id": "p-course", "text": "课程提到关联书。"}
        citations = [
            {
                "index": 1,
                "source_path": "pdfs/课程.pdf",
                "source_layer": "course_primary",
                "page_start": 10,
                "page_end": 10,
                "label": "课程.pdf p10",
                "evidence_quote": "课程提到关联书。",
            }
        ]
        synthesized = {
            "query": "问题",
            "intent": "general",
            "answer": "课程结论。[1]",
            "citations": citations,
            "related_knowledge_units": [],
            "safety_notice": "",
            "results": [candidate],
        }
        linked = [{"title": "关联书", "source_layer": "reference_secondary"}]

        class FakeStore:
            def __init__(self, *_args: object, **_kwargs: object) -> None:
                pass

            def search_guide_nodes(self, _query: str, limit: int = 8) -> list[dict[str, object]]:
                return []

        db_path = Path("/unused/rag.sqlite")
        with (
            patch("nihaisha_kg.pdf_vector.LocalVectorStore", FakeStore),
            patch("nihaisha_kg.pdf_vector.build_query_plan", return_value=["问题"]),
            patch("nihaisha_kg.pdf_vector.run_query_plan_search", return_value=[candidate]),
            patch("nihaisha_kg.pdf_vector.filter_results_for_intent", return_value=[candidate]),
            patch("nihaisha_kg.pdf_vector.select_diverse_results", return_value=[candidate]),
            patch("nihaisha_kg.pdf_vector.synthesize_pdf_rag_answer", return_value=synthesized),
            patch("nihaisha_kg.pdf_vector.linked_reference_materials", return_value=linked) as resolver,
        ):
            answer = answer_pdf_rag("问题", db_path, mode="text", reranker="none")

        resolver.assert_called_once_with(db_path, citations)
        self.assertEqual(answer["linked_reference_materials"], linked)
        self.assertFalse(answer["reference_secondary_included"])
        self.assertEqual(answer["related_guide_nodes"], [])
        self.assertEqual(answer["differentiation_flow"]["mermaid"], "")

    def test_answer_pdf_rag_reranks_once_after_rewrite_fusion_and_intent_filtering(self) -> None:
        initial = [{"paragraph_id": "initial", "title": "初检", "text": "初检证据"}]
        followup = [{"paragraph_id": "followup", "title": "追检", "text": "追检证据"}]
        filtered = [
            {"paragraph_id": "initial", "title": "初检", "text": "初检证据"},
            {"paragraph_id": "followup", "title": "追检", "text": "追检证据"},
        ]
        reranked = [dict(filtered[1], rerank_score=0.9), dict(filtered[0], rerank_score=0.4)]
        events: list[str] = []

        class FakeStore:
            def __init__(self, *_args: object, **_kwargs: object) -> None:
                pass

            def search_guide_nodes(self, _query: str, limit: int = 8) -> list[dict[str, object]]:
                return []

        class FakeReranker:
            calls: list[tuple[str, list[dict[str, object]], int]] = []

            def rerank(
                self,
                query: str,
                candidates: list[dict[str, object]],
                limit: int,
            ) -> RerankOutcome:
                events.append("rerank")
                self.calls.append((query, candidates, limit))
                return RerankOutcome(results=reranked, model="fake-reranker")

        backend = FakeReranker()

        def fake_filter(
            _query: str,
            _intent: str,
            candidates: list[dict[str, object]],
        ) -> list[dict[str, object]]:
            events.append("filter")
            self.assertEqual(
                {row["paragraph_id"] for row in candidates},
                {"initial", "followup"},
            )
            return filtered

        def fake_select(
            candidates: list[dict[str, object]],
            limit: int,
            intent: str,
        ) -> list[dict[str, object]]:
            events.append("select")
            self.assertEqual(candidates, reranked)
            self.assertIsNot(candidates, reranked)
            self.assertTrue(
                all(candidate is not original for candidate, original in zip(candidates, reranked))
            )
            self.assertEqual(limit, 2)
            return candidates[:limit]

        with (
            patch("nihaisha_kg.pdf_vector.LocalVectorStore", FakeStore),
            patch(
                "nihaisha_kg.pdf_vector.build_query_plan",
                side_effect=[["original"], ["original", "followup"]],
            ),
            patch(
                "nihaisha_kg.pdf_vector.run_query_plan_search",
                side_effect=[initial, followup],
            ),
            patch(
                "nihaisha_kg.pdf_vector.fuse_query_rewrites",
                return_value=filtered,
            ) as fuse,
            patch("nihaisha_kg.pdf_vector.filter_results_for_intent", side_effect=fake_filter),
            patch("nihaisha_kg.pdf_vector.select_diverse_results", side_effect=fake_select),
            patch(
                "nihaisha_kg.pdf_vector.synthesize_pdf_rag_answer",
                return_value={
                    "query": "问题",
                    "intent": "general",
                    "answer": "已生成",
                    "citations": [],
                    "related_knowledge_units": [],
                    "safety_notice": "",
                    "results": reranked,
                },
            ),
        ):
            answer = answer_pdf_rag(
                "原始问题",
                Path("/unused/rag.sqlite"),
                mode="text",
                limit=2,
                reranker_backend=backend,
            )

        fuse.assert_called_once_with([initial, followup], limit=32)
        self.assertEqual(events, ["filter", "rerank", "select"])
        self.assertEqual(len(backend.calls), 1)
        self.assertEqual(backend.calls[0], ("原始问题", filtered, 2))
        self.assertEqual(
            answer["rerank"],
            {"model": "fake-reranker", "degraded_feature": "", "error": ""},
        )

    def test_answer_pdf_rag_synthesizes_after_rerank_degradation(self) -> None:
        candidates = [{"paragraph_id": "p1", "text": "甲"}, {"paragraph_id": "p2", "text": "乙"}]
        configured_key = "configured-secret"
        injected_secret = "supersecret"
        sk_secret = "sk-abcdefghijklmnopqrstuvwxyz012345"
        unsafe_error = (
            f"Authorization: Bearer {injected_secret}\x00 api_key={configured_key} "
            f"token={sk_secret} " + "details " * 200
        )

        class FakeStore:
            def __init__(self, *_args: object, **_kwargs: object) -> None:
                pass

            def search_guide_nodes(self, _query: str, limit: int = 8) -> list[dict[str, object]]:
                return []

        class DegradedReranker:
            def rerank(
                self,
                _query: str,
                incoming: list[dict[str, object]],
                limit: int,
            ) -> RerankOutcome:
                return RerankOutcome(
                    results=[dict(row) for row in incoming[:limit]],
                    model="fake-reranker",
                    degraded_feature="siliconflow_rerank",
                    error=unsafe_error,
                )

        def fake_synthesize(_query: str, results: list[dict[str, object]]) -> dict[str, object]:
            self.assertEqual([row["paragraph_id"] for row in results], ["p1", "p2"])
            return {
                "query": "问题",
                "intent": "general",
                "answer": "fallback evidence synthesized",
                "citations": [],
                "related_knowledge_units": [],
                "safety_notice": "",
                "results": results,
            }

        with patch.dict(os.environ, {"SILICONFLOW_API_KEY": configured_key}):
            with (
                patch("nihaisha_kg.pdf_vector.LocalVectorStore", FakeStore),
                patch("nihaisha_kg.pdf_vector.build_query_plan", return_value=["问题"]),
                patch("nihaisha_kg.pdf_vector.run_query_plan_search", return_value=candidates),
                patch("nihaisha_kg.pdf_vector.filter_results_for_intent", return_value=candidates),
                patch("nihaisha_kg.pdf_vector.select_diverse_results", side_effect=lambda rows, **_: rows),
                patch("nihaisha_kg.pdf_vector.synthesize_pdf_rag_answer", side_effect=fake_synthesize),
            ):
                answer = answer_pdf_rag(
                    "问题",
                    Path("/unused/rag.sqlite"),
                    mode="text",
                    limit=2,
                    reranker_backend=DegradedReranker(),
                )

        self.assertEqual(answer["answer"], "fallback evidence synthesized")
        metadata = answer["rerank"]
        self.assertEqual(set(metadata), {"model", "degraded_feature", "error"})
        self.assertEqual(metadata["model"], "fake-reranker")
        self.assertEqual(metadata["degraded_feature"], "siliconflow_rerank")
        self.assertLessEqual(len(metadata["error"]), 240)
        self.assertNotIn(injected_secret, metadata["error"])
        self.assertNotIn(configured_key, metadata["error"])
        self.assertNotIn(sk_secret, metadata["error"])
        self.assertNotIn("\x00", metadata["error"])
        self.assertNotIn("Bearer supersecret", metadata["error"])

    def test_answer_pdf_rag_normalizes_hostile_injected_rerank_metadata(self) -> None:
        candidate = {"paragraph_id": "p1", "text": "证据"}
        secret = "metadata-secret"

        class RaisingDict(dict[str, object]):
            def __str__(self) -> str:
                raise RuntimeError("must not stringify")

        class FakeStore:
            def __init__(self, *_args: object, **_kwargs: object) -> None:
                pass

            def search_guide_nodes(self, _query: str, limit: int = 8) -> list[dict[str, object]]:
                return []

        class HostileOutcome:
            results = [candidate]
            model = f'{{"api_key": "{secret}"}}' + "m" * 10_000
            degraded_feature = "token='feature-secret' " + "d" * 10_000
            error = RaisingDict(
                {"authorization": "Bearer object-secret", "candidate": candidate}
            )

        class HostileReranker:
            def rerank(self, *_args: object, **_kwargs: object) -> HostileOutcome:
                return HostileOutcome()

        synthesized = {
            "query": "问题",
            "intent": "general",
            "answer": "已生成",
            "citations": [],
            "related_knowledge_units": [],
            "safety_notice": "",
            "results": [candidate],
        }
        with (
            patch("nihaisha_kg.pdf_vector.LocalVectorStore", FakeStore),
            patch("nihaisha_kg.pdf_vector.build_query_plan", return_value=["问题"]),
            patch("nihaisha_kg.pdf_vector.run_query_plan_search", return_value=[candidate]),
            patch("nihaisha_kg.pdf_vector.filter_results_for_intent", return_value=[candidate]),
            patch("nihaisha_kg.pdf_vector.select_diverse_results", side_effect=lambda rows, **_: rows),
            patch("nihaisha_kg.pdf_vector.synthesize_pdf_rag_answer", return_value=synthesized),
        ):
            answer = answer_pdf_rag(
                "问题",
                Path("/unused/rag.sqlite"),
                mode="text",
                reranker_backend=HostileReranker(),
            )

        metadata = answer["rerank"]
        self.assertEqual(set(metadata), {"model", "degraded_feature", "error"})
        self.assertTrue(all(isinstance(value, str) for value in metadata.values()))
        self.assertLessEqual(len(metadata["model"]), 120)
        self.assertLessEqual(len(metadata["degraded_feature"]), 80)
        self.assertLessEqual(len(metadata["error"]), 240)
        self.assertNotIn(secret, json.dumps(metadata))
        self.assertNotIn("feature-secret", json.dumps(metadata))
        self.assertNotIn("object-secret", json.dumps(metadata))
        self.assertNotIn("paragraph_id", json.dumps(metadata))
        json.dumps(answer)

    def test_answer_pdf_rag_validates_reranker_before_opening_store(self) -> None:
        with patch("nihaisha_kg.pdf_vector.LocalVectorStore") as store:
            with self.assertRaisesRegex(ValueError, "unsupported reranker"):
                answer_pdf_rag("问题", Path("/unused/rag.sqlite"), mode="text", reranker="bad")
        store.assert_not_called()

    def test_answer_pdf_rag_trace_is_opt_in_grouped_bounded_and_json_safe(self) -> None:
        secret = "sk-trace-secret-123456789"
        initial = [
            {
                "paragraph_id": "p-initial",
                "text": secret,
                "retrieval_sources": ["text", f"token={secret}"],
                "channel_ranks": {"text": 1, f"api_key={secret}": secret},
                "rewrite_observations": [{"rewrite_index": 1, "rank": 1}],
            }
        ]
        followup = [
            {
                "paragraph_id": "p-followup",
                "text": "evidence",
                "retrieval_sources": ["knowledge"],
                "channel_ranks": {"knowledge": 2},
                "rewrite_observations": [{"rewrite_index": 1, "rank": 1}],
            }
        ]

        class FakeStore:
            def __init__(self, *_args: object, **_kwargs: object) -> None:
                pass

            def search_guide_nodes(self, *_args: object, **_kwargs: object) -> list[dict[str, object]]:
                return []

        synthesized = {
            "answer": "answer",
            "citations": [],
            "related_knowledge_units": [],
            "results": [initial[0], followup[0]],
        }
        patches = (
            patch("nihaisha_kg.pdf_vector.LocalVectorStore", FakeStore),
            patch("nihaisha_kg.pdf_vector.detect_answer_intent", return_value="general"),
            patch("nihaisha_kg.pdf_vector.build_query_plan", side_effect=[["initial query"], ["initial query", "followup query"]]),
            patch("nihaisha_kg.pdf_vector.run_query_plan_search", side_effect=[initial, followup]),
            patch("nihaisha_kg.pdf_vector.fuse_query_rewrites", return_value=[initial[0], followup[0]]),
            patch("nihaisha_kg.pdf_vector.filter_results_for_intent", side_effect=lambda _q, _i, rows: rows),
            patch("nihaisha_kg.pdf_vector.select_diverse_results", side_effect=lambda rows, **_: rows),
            patch("nihaisha_kg.pdf_vector.synthesize_pdf_rag_answer", return_value=synthesized),
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
            without_trace = answer_pdf_rag("question", Path("/unused.sqlite"), mode="text")

        self.assertNotIn("trace", without_trace)

        with (
            patch("nihaisha_kg.pdf_vector.LocalVectorStore", FakeStore),
            patch("nihaisha_kg.pdf_vector.detect_answer_intent", return_value="general"),
            patch("nihaisha_kg.pdf_vector.build_query_plan", side_effect=[["initial query"], ["initial query", "followup query"]]),
            patch("nihaisha_kg.pdf_vector.run_query_plan_search", side_effect=[initial, followup]),
            patch("nihaisha_kg.pdf_vector.fuse_query_rewrites", return_value=[initial[0], followup[0]]),
            patch("nihaisha_kg.pdf_vector.filter_results_for_intent", side_effect=lambda _q, _i, rows: rows),
            patch("nihaisha_kg.pdf_vector.select_diverse_results", side_effect=lambda rows, **_: rows),
            patch("nihaisha_kg.pdf_vector.synthesize_pdf_rag_answer", return_value=synthesized),
        ):
            traced = answer_pdf_rag(
                f"question \x1bAuthorization: Bearer {secret}",
                Path("/unused.sqlite"),
                mode="text",
                trace_enabled=True,
            )

        trace = traced["trace"]
        self.assertEqual(trace["query_plan"][0]["query"], "initial query")
        self.assertEqual(trace["query_plan"][0]["observations"][0]["paragraph_id"], "p-initial")
        self.assertEqual(trace["followup_plan"][0]["query"], "followup query")
        self.assertEqual(trace["followup_plan"][0]["observations"][0]["paragraph_id"], "p-followup")
        self.assertEqual(trace["retrieval_channels"], ["knowledge", "text"])
        self.assertEqual(trace["selected_paragraph_ids"], ["p-initial", "p-followup"])
        self.assertTrue(all(value >= 0 for value in trace["latency_ms"].values()))
        serialized = json.dumps(trace, ensure_ascii=False)
        self.assertNotIn(secret, serialized)
        self.assertNotIn("evidence", serialized)

    def test_answer_pdf_rag_trace_rejects_non_boolean_flag(self) -> None:
        with patch("nihaisha_kg.pdf_vector.LocalVectorStore") as store:
            with self.assertRaisesRegex(TypeError, "trace_enabled"):
                answer_pdf_rag("question", Path("/unused.sqlite"), mode="text", trace_enabled=1)  # type: ignore[arg-type]
        store.assert_not_called()

    def test_answer_trace_latency_has_required_phases_and_covers_all_work(self) -> None:
        initial = [{"paragraph_id": "p1", "rewrite_observations": []}]
        followup = [{"paragraph_id": "p2", "rewrite_observations": []}]

        class FakeStore:
            def __init__(self, *_args: object, **_kwargs: object) -> None:
                pass

            def search_guide_nodes(self, *_args: object, **_kwargs: object) -> list[dict[str, object]]:
                return []

        synthesized = {
            "answer": "answer",
            "citations": [],
            "related_knowledge_units": [],
            "results": initial + followup,
        }
        with (
            patch("nihaisha_kg.pdf_vector.LocalVectorStore", FakeStore),
            patch("nihaisha_kg.pdf_vector.detect_answer_intent", return_value="general"),
            patch("nihaisha_kg.pdf_vector.build_query_plan", side_effect=[["initial"], ["initial", "followup"]]),
            patch("nihaisha_kg.pdf_vector.run_query_plan_search", side_effect=[initial, followup]),
            patch("nihaisha_kg.pdf_vector.fuse_query_rewrites", return_value=initial + followup),
            patch("nihaisha_kg.pdf_vector.filter_results_for_intent", side_effect=lambda _q, _i, rows: rows),
            patch("nihaisha_kg.pdf_vector.select_diverse_results", side_effect=lambda rows, **_: rows),
            patch("nihaisha_kg.pdf_vector.synthesize_pdf_rag_answer", return_value=synthesized),
        ):
            answer = answer_pdf_rag(
                "query",
                Path("/unused.sqlite"),
                mode="text",
                reranker="none",
                trace_enabled=True,
            )

        latency = answer["trace"]["latency_ms"]
        self.assertEqual(set(latency), {"planning", "retrieval", "rerank", "guide", "synthesis"})
        self.assertTrue(all(0.0 <= value <= 3_600_000.0 for value in latency.values()))
        self.assertEqual(pdf_vector._bounded_latency_ms(float("inf")), 0.0)
        self.assertEqual(pdf_vector._bounded_latency_ms(10_000_000.0), 3_600_000.0)

    def test_answer_timing_is_trace_only_and_resilient_to_bad_clocks(self) -> None:
        candidate = {"paragraph_id": "p1", "text": "evidence"}

        class FakeStore:
            def __init__(self, *_args: object, **_kwargs: object) -> None:
                pass

            def search_guide_nodes(self, *_args: object, **_kwargs: object) -> list[dict[str, object]]:
                return []

        synthesized = {
            "answer": "answer",
            "citations": [],
            "related_knowledge_units": [],
            "results": [candidate],
        }

        def run(trace_enabled: bool, clock: object) -> dict[str, object]:
            with (
                patch("nihaisha_kg.pdf_vector.LocalVectorStore", FakeStore),
                patch("nihaisha_kg.pdf_vector.time.perf_counter", clock),
                patch("nihaisha_kg.pdf_vector.build_query_plan", return_value=["query"]),
                patch("nihaisha_kg.pdf_vector.run_query_plan_search", return_value=[candidate]),
                patch("nihaisha_kg.pdf_vector.filter_results_for_intent", return_value=[candidate]),
                patch("nihaisha_kg.pdf_vector.select_diverse_results", return_value=[candidate]),
                patch("nihaisha_kg.pdf_vector.synthesize_pdf_rag_answer", return_value=synthesized),
            ):
                return answer_pdf_rag(
                    "query",
                    Path("/unused.sqlite"),
                    mode="text",
                    reranker="none",
                    trace_enabled=trace_enabled,
                )

        disabled_clock = unittest.mock.Mock(side_effect=AssertionError("clock must not run"))
        without_trace = run(False, disabled_clock)
        disabled_clock.assert_not_called()
        self.assertNotIn("trace", without_trace)

        bad_values = iter([float("nan"), float("inf"), 5.0, 4.0] * 20)
        with_trace = run(True, unittest.mock.Mock(side_effect=lambda: next(bad_values)))
        latency = with_trace["trace"]["latency_ms"]
        self.assertEqual(set(latency), {"planning", "retrieval", "rerank", "guide", "synthesis"})
        self.assertTrue(all(0.0 <= value <= 3_600_000.0 for value in latency.values()))

    def test_answer_normalizes_untrusted_reranker_results(self) -> None:
        candidate = {"paragraph_id": "p1", "text": "evidence"}

        class FakeStore:
            def __init__(self, *_args: object, **_kwargs: object) -> None:
                pass

            def search_guide_nodes(self, *_args: object, **_kwargs: object) -> list[dict[str, object]]:
                return []

        class Backend:
            results: object

            def rerank(self, *_args: object, **_kwargs: object) -> object:
                return type(
                    "Outcome",
                    (),
                    {"results": self.results, "model": "model", "degraded_feature": "", "error": ""},
                )()

        selected_rows: list[list[dict[str, object]]] = []

        def synthesize(_query: str, rows: list[dict[str, object]]) -> dict[str, object]:
            selected_rows.append(rows)
            return {
                "answer": "answer",
                "citations": [],
                "related_knowledge_units": [],
                "results": rows,
            }
        backend = Backend()
        backend.results = [{"paragraph_id": str(index), "text": "evidence"} for index in range(1000)]
        with (
            patch("nihaisha_kg.pdf_vector.LocalVectorStore", FakeStore),
            patch("nihaisha_kg.pdf_vector.build_query_plan", return_value=["query"]),
            patch("nihaisha_kg.pdf_vector.run_query_plan_search", return_value=[candidate]),
            patch("nihaisha_kg.pdf_vector.filter_results_for_intent", return_value=[candidate]),
            patch("nihaisha_kg.pdf_vector.select_diverse_results", side_effect=lambda rows, **_: rows),
            patch("nihaisha_kg.pdf_vector.synthesize_pdf_rag_answer", side_effect=synthesize),
        ):
            answer = answer_pdf_rag(
                "query", Path("/unused.sqlite"), mode="text", limit=1, reranker_backend=backend
            )
        self.assertEqual(len(answer["results"]), 1)
        self.assertEqual(len(selected_rows[0]), 1)
        self.assertIsNot(selected_rows[0][0], backend.results[0])

        class HostileList(list[dict[str, object]]):
            def __getitem__(self, _index: object) -> object:
                return [{"paragraph_id": "bypass"}] * 100

        backend.results = HostileList([candidate])
        with (
            patch("nihaisha_kg.pdf_vector.LocalVectorStore", FakeStore),
            patch("nihaisha_kg.pdf_vector.build_query_plan", return_value=["query"]),
            patch("nihaisha_kg.pdf_vector.run_query_plan_search", return_value=[candidate]),
            patch("nihaisha_kg.pdf_vector.filter_results_for_intent", return_value=[candidate]),
        ):
            with self.assertRaisesRegex(RuntimeError, "invalid reranker results"):
                answer_pdf_rag(
                    "query", Path("/unused.sqlite"), mode="text", limit=1, reranker_backend=backend
                )

        class RaisingMetadataOutcome:
            results = [candidate]
            degraded_feature = ""
            error = ""

            @property
            def model(self) -> object:
                raise RuntimeError("credential-sentinel")

        class RaisingBackend:
            def rerank(self, *_args: object, **_kwargs: object) -> object:
                return RaisingMetadataOutcome()

        with (
            patch("nihaisha_kg.pdf_vector.LocalVectorStore", FakeStore),
            patch("nihaisha_kg.pdf_vector.build_query_plan", return_value=["query"]),
            patch("nihaisha_kg.pdf_vector.run_query_plan_search", return_value=[candidate]),
            patch("nihaisha_kg.pdf_vector.filter_results_for_intent", return_value=[candidate]),
        ):
            with self.assertRaisesRegex(RuntimeError, "^invalid reranker outcome$"):
                answer_pdf_rag(
                    "query",
                    Path("/unused.sqlite"),
                    mode="text",
                    limit=1,
                    reranker_backend=RaisingBackend(),
                )

        backend.results = [object()]
        with (
            patch("nihaisha_kg.pdf_vector.LocalVectorStore", FakeStore),
            patch("nihaisha_kg.pdf_vector.build_query_plan", return_value=["query"]),
            patch("nihaisha_kg.pdf_vector.run_query_plan_search", return_value=[candidate]),
            patch("nihaisha_kg.pdf_vector.filter_results_for_intent", return_value=[candidate]),
        ):
            with self.assertRaisesRegex(RuntimeError, "invalid reranker result row"):
                answer_pdf_rag(
                    "query", Path("/unused.sqlite"), mode="text", limit=1, reranker_backend=backend
                )

    def test_answer_pdf_rag_explicit_siliconflow_uses_model_and_auto_without_key_skips(self) -> None:
        candidate = {"paragraph_id": "p1", "text": "证据"}

        class FakeStore:
            def __init__(self, *_args: object, **_kwargs: object) -> None:
                pass

            def search_guide_nodes(self, _query: str, limit: int = 8) -> list[dict[str, object]]:
                return []

        class FakeReranker:
            calls: list[tuple[str, list[dict[str, object]], int]] = []

            def rerank(
                self,
                query: str,
                candidates: list[dict[str, object]],
                limit: int,
            ) -> RerankOutcome:
                self.calls.append((query, candidates, limit))
                return RerankOutcome(results=[dict(candidate)], model="selected-model")

        backend = FakeReranker()
        synthesize_result = {
            "query": "问题",
            "intent": "general",
            "answer": "已生成",
            "citations": [],
            "related_knowledge_units": [],
            "safety_notice": "",
            "results": [candidate],
        }
        with (
            patch("nihaisha_kg.pdf_vector.LocalVectorStore", FakeStore),
            patch("nihaisha_kg.pdf_vector.build_query_plan", return_value=["问题"]),
            patch("nihaisha_kg.pdf_vector.run_query_plan_search", return_value=[candidate]),
            patch("nihaisha_kg.pdf_vector.filter_results_for_intent", return_value=[candidate]),
            patch("nihaisha_kg.pdf_vector.select_diverse_results", side_effect=lambda rows, **_: rows),
            patch("nihaisha_kg.pdf_vector.synthesize_pdf_rag_answer", return_value=synthesize_result),
            patch("nihaisha_kg.rerank.SiliconFlowReranker", return_value=backend) as factory,
        ):
            explicit = answer_pdf_rag(
                "问题",
                Path("/unused/rag.sqlite"),
                mode="text",
                reranker="siliconflow",
                rerank_model="selected-model",
            )

        factory.assert_called_once_with(model="selected-model")
        self.assertEqual(backend.calls, [("问题", [candidate], 1)])
        self.assertEqual(explicit["rerank"]["model"], "selected-model")

        with (
            patch("nihaisha_kg.pdf_vector.LocalVectorStore", FakeStore),
            patch("nihaisha_kg.pdf_vector.build_query_plan", return_value=["问题"]),
            patch("nihaisha_kg.pdf_vector.run_query_plan_search", return_value=[candidate]),
            patch("nihaisha_kg.pdf_vector.filter_results_for_intent", return_value=[candidate]),
            patch("nihaisha_kg.pdf_vector.select_diverse_results", side_effect=lambda rows, **_: rows),
            patch("nihaisha_kg.pdf_vector.synthesize_pdf_rag_answer", return_value=synthesize_result),
            patch("nihaisha_kg.pdf_vector.siliconflow_api_key_available", return_value=False),
            patch("nihaisha_kg.rerank.SiliconFlowReranker") as skipped_factory,
        ):
            automatic = answer_pdf_rag(
                "问题",
                Path("/unused/rag.sqlite"),
                mode="text",
                reranker="auto",
            )

        skipped_factory.assert_not_called()
        self.assertEqual(
            automatic["rerank"],
            {"model": "none", "degraded_feature": "", "error": ""},
        )

    def test_answer_pdf_rag_returns_clinical_safety_boundary(self) -> None:
        paragraph = ParsedParagraph(
            paragraph_id="p-a",
            doc_id="doc",
            source_path="/tmp/金匮.pdf",
            title="金匮 p232",
            page_start=232,
            page_end=232,
            text="干呕就是恶心。下利，黄芩加半夏生姜汤。腹痛的时候一律加白芍。",
        )

        class ToyDenseBackend(DenseEmbeddingBackend):
            name = "toy_dense"

            def embed_texts(self, texts: list[str]) -> list[list[float]]:
                return [[1.0, 0.0] for _ in texts]

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "rag.sqlite"
            store = LocalVectorStore(db_path, embedding_backend=ToyDenseBackend())
            store.recreate()
            store.insert_paragraphs([paragraph])
            store.insert_units(build_retrieval_units([paragraph], window_size=2, overlap=1))
            store.rebuild_knowledge_units()
            store.rebuild_guide_nodes()

            answer = answer_pdf_rag(
                "病人发烧后下利黄臭恶心，建议开什么方？",
                db_path=db_path,
                embedding_backend=ToyDenseBackend(),
                limit=3,
                reranker="none",
            )

        self.assertEqual(answer["intent"], "clinical")
        self.assertIn("不能替代诊断", answer["safety_notice"])
        self.assertIn("不同人的体质不同", answer["safety_notice"])
        self.assertIn("药效也和以前差很多", answer["safety_notice"])
        self.assertIn("不要私自购药", answer["safety_notice"])
        self.assertIn("不直接给个人处方", answer["answer"])
        self.assertIn("黄芩加半夏生姜汤", answer["answer"])
        self.assertGreaterEqual(len(answer["citations"]), 1)
        self.assertEqual(answer["related_guide_nodes"][0]["label"], "黄芩加半夏生姜汤")
        self.assertEqual(answer["related_guide_nodes"][0]["paragraph_id"], "p-a")
        self.assertIn("黄芩加半夏生姜汤", answer["differentiation_flow"]["mermaid"])
        self.assertIn("腹痛", "\n".join(answer["followup_questions"]))
        self.assertIn("恶心", "\n".join(answer["followup_questions"]))

    def test_local_bge_m3_backend_uses_injected_flagembedding_model(self) -> None:
        class FakeBgeM3Model:
            def __init__(self) -> None:
                self.calls = []

            def encode(
                self,
                texts: list[str],
                batch_size: int,
                max_length: int,
                return_dense: bool,
                return_sparse: bool,
                return_colbert_vecs: bool,
            ) -> dict[str, list[list[float]]]:
                self.calls.append(
                    {
                        "texts": texts,
                        "batch_size": batch_size,
                        "max_length": max_length,
                        "return_dense": return_dense,
                        "return_sparse": return_sparse,
                        "return_colbert_vecs": return_colbert_vecs,
                    }
                )
                return {"dense_vecs": [[3.0, 4.0]]}

        model = FakeBgeM3Model()
        backend = LocalBgeM3EmbeddingBackend(model_instance=model, batch_size=7, max_length=4096)

        vectors = backend.embed_texts(["桂枝汤"])

        self.assertEqual(backend.name, "local-bge-m3:BAAI/bge-m3")
        self.assertEqual(backend.vector_kind, "dense")
        self.assertAlmostEqual(vectors[0][0], 0.6)
        self.assertAlmostEqual(vectors[0][1], 0.8)
        self.assertEqual(model.calls[0]["texts"], ["桂枝汤"])
        self.assertEqual(model.calls[0]["batch_size"], 7)
        self.assertEqual(model.calls[0]["max_length"], 4096)
        self.assertTrue(model.calls[0]["return_dense"])
        self.assertFalse(model.calls[0]["return_sparse"])
        self.assertFalse(model.calls[0]["return_colbert_vecs"])

    def test_create_embedding_backend_supports_local_bge_m3(self) -> None:
        backend = create_embedding_backend("local-bge-m3")

        self.assertIsInstance(backend, LocalBgeM3EmbeddingBackend)
        self.assertEqual(backend.name, "local-bge-m3:BAAI/bge-m3")

    def test_auto_embedding_uses_siliconflow_when_key_exists_and_local_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "rag.sqlite"
            store = LocalVectorStore(db_path)
            store.recreate()
            with store.connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                    ("embedding", "siliconflow:BAAI/bge-m3"),
                )

            with patch.dict(os.environ, {"SILICONFLOW_API_KEY": "secret"}, clear=False):
                api_backend = create_embedding_backend_for_db(db_path)
            with patch.dict(os.environ, {"SILICONFLOW_API_KEY": ""}, clear=False):
                local_backend = create_embedding_backend_for_db(db_path)

        self.assertIsInstance(api_backend, SiliconFlowEmbeddingBackend)
        self.assertIsInstance(local_backend, LocalBgeM3EmbeddingBackend)

    def test_parse_unit_types_accepts_question_units(self) -> None:
        self.assertEqual(
            parse_unit_types("sentence,question,paragraph"),
            {"sentence", "question", "paragraph"},
        )

    def test_vector_store_search_returns_paragraphs_deduplicated_by_score(self) -> None:
        paragraph_a = ParsedParagraph(
            paragraph_id="p-a",
            doc_id="doc",
            source_path="/tmp/doc.pdf",
            title="桂枝汤证",
            page_start=1,
            page_end=1,
            text="太阳中风，汗出恶风，桂枝汤主之。",
        )
        paragraph_b = ParsedParagraph(
            paragraph_id="p-b",
            doc_id="doc",
            source_path="/tmp/doc.pdf",
            title="麻黄汤证",
            page_start=2,
            page_end=2,
            text="太阳伤寒，无汗而喘，麻黄汤主之。",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(Path(tmpdir) / "rag.sqlite")
            store.recreate()
            store.insert_paragraphs([paragraph_a, paragraph_b])
            store.insert_units(build_retrieval_units([paragraph_a, paragraph_b], window_size=2, overlap=1))

            results = store.search("桂枝汤 汗出 恶风", limit=4)

        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0]["paragraph_id"], "p-a")
        self.assertIn("桂枝汤", results[0]["text"])
        self.assertEqual(len({item["paragraph_id"] for item in results}), len(results))

    def test_text_search_returns_exact_original_paragraph_without_embedding(self) -> None:
        paragraph_a = ParsedParagraph(
            paragraph_id="p-a",
            doc_id="doc",
            source_path="/tmp/doc.pdf",
            title="桂枝汤证",
            page_start=1,
            page_end=1,
            text="太阳中风，汗出恶风，桂枝汤主之。",
        )
        paragraph_b = ParsedParagraph(
            paragraph_id="p-b",
            doc_id="doc",
            source_path="/tmp/doc.pdf",
            title="少阴咽痛",
            page_start=2,
            page_end=2,
            text="少阴咽痛，可以讨论猪肤汤和桔梗汤。",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(Path(tmpdir) / "rag.sqlite")
            store.recreate()
            store.insert_paragraphs([paragraph_a, paragraph_b])

            results = store.search_text("猪肤汤", limit=2)

        self.assertEqual(results[0]["paragraph_id"], "p-b")
        self.assertIn("text", results[0]["retrieval_sources"])
        self.assertIn("猪肤汤", results[0]["matched_text_terms"])

    def test_search_term_apis_delegate_to_boundary_preserving_normalization(self) -> None:
        text_terms = text_search_terms("太阳病欲解时从什么时候到什么时候？")
        knowledge_terms = knowledge_search_terms("比较与区别")

        self.assertEqual(text_terms, ["太阳病", "欲解", "太陽病"])
        self.assertNotIn("太阳", text_terms)
        self.assertEqual(
            knowledge_terms,
            ["比较与区别", "比較與區別", "比较", "区别"],
        )

    def test_text_search_retrieves_across_traditional_and_simplified_scripts(self) -> None:
        traditional_paragraph = ParsedParagraph(
            paragraph_id="p-traditional",
            doc_id="doc",
            source_path="/tmp/traditional.pdf",
            title="太陽病脈證",
            page_start=1,
            page_end=1,
            text="太陽病的脈證可見發熱惡風。",
        )
        simplified_paragraph = ParsedParagraph(
            paragraph_id="p-simplified",
            doc_id="doc",
            source_path="/tmp/simplified.pdf",
            title="少阴病脉证",
            page_start=2,
            page_end=2,
            text="少阴病的脉证可见咽痛。",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(Path(tmpdir) / "rag.sqlite")
            store.recreate()
            store.insert_paragraphs([traditional_paragraph, simplified_paragraph])

            cases = (
                ("太阳病的脉证有哪些？", "p-traditional", "太陽病"),
                ("少陰病的脈證有哪些？", "p-simplified", "少阴"),
            )
            for query, expected_id, expected_anchor in cases:
                with self.subTest(query=query):
                    results = store.search_text(query, limit=2)

                    self.assertTrue(results)
                    self.assertEqual(results[0]["paragraph_id"], expected_id)
                    self.assertIn(expected_anchor, results[0]["matched_text_terms"])

    def test_text_search_bounds_large_ascii_query_without_sqlite_error(self) -> None:
        paragraph = ParsedParagraph(
            paragraph_id="p-bounded-query",
            doc_id="doc",
            source_path="/tmp/bounded.pdf",
            title="手足厥冷",
            page_start=1,
            page_end=1,
            text="手足厥冷时可辨证选方。needleanchor",
        )
        oversized_query = "needleanchor " + " ".join(
            f"token{index:04d}" for index in range(1001)
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(Path(tmpdir) / "rag.sqlite")
            store.recreate()
            store.insert_paragraphs([paragraph])

            results = store.search_text(oversized_query, limit=2)

        self.assertTrue(results)
        self.assertEqual(results[0]["paragraph_id"], "p-bounded-query")

    def test_traditional_question_scaffold_retrieves_simplified_paragraph(self) -> None:
        paragraph = ParsedParagraph(
            paragraph_id="p-simplified-cold-limbs",
            doc_id="doc",
            source_path="/tmp/simplified-cold-limbs.pdf",
            title="手足厥冷",
            page_start=1,
            page_end=1,
            text="手足厥冷时应辨证选方。",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(Path(tmpdir) / "rag.sqlite")
            store.recreate()
            store.insert_paragraphs([paragraph])

            results = store.search_text("手足厥冷應該用什麼方？", limit=2)

        self.assertTrue(results)
        self.assertEqual(results[0]["paragraph_id"], "p-simplified-cold-limbs")

    def test_simplified_query_retrieves_each_traditional_li_form(self) -> None:
        cases = (
            ("裡", "p-traditional-inner"),
            ("裏", "p-traditional-alternate"),
        )

        for traditional_li, paragraph_id in cases:
            with self.subTest(traditional_li=traditional_li), tempfile.TemporaryDirectory() as tmpdir:
                paragraph = ParsedParagraph(
                    paragraph_id=paragraph_id,
                    doc_id="doc",
                    source_path=f"/tmp/{paragraph_id}.pdf",
                    title=f"經方{traditional_li}面辨證",
                    page_start=1,
                    page_end=1,
                    text=f"經方{traditional_li}面辨證須依原文。",
                )
                store = LocalVectorStore(Path(tmpdir) / "rag.sqlite")
                store.recreate()
                store.insert_paragraphs([paragraph])

                results = store.search_text("经方里面辨证", limit=2)

                self.assertTrue(results)
                self.assertEqual(results[0]["paragraph_id"], paragraph_id)

    def test_hybrid_search_combines_vector_and_text_sources(self) -> None:
        paragraph_a = ParsedParagraph(
            paragraph_id="p-a",
            doc_id="doc",
            source_path="/tmp/doc.pdf",
            title="桂枝汤证",
            page_start=1,
            page_end=1,
            text="太阳中风，汗出恶风，桂枝汤主之。",
        )
        paragraph_b = ParsedParagraph(
            paragraph_id="p-b",
            doc_id="doc",
            source_path="/tmp/doc.pdf",
            title="少阴咽痛",
            page_start=2,
            page_end=2,
            text="少阴咽痛，可以讨论猪肤汤和桔梗汤。",
        )

        class ToyDenseBackend(DenseEmbeddingBackend):
            name = "toy_dense"

            def embed_texts(self, texts: list[str]) -> list[list[float]]:
                vectors = []
                for text in texts:
                    if "桂枝" in text or "汗出" in text or "恶风" in text:
                        vectors.append([1.0, 0.0])
                    else:
                        vectors.append([0.0, 1.0])
                return vectors

        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(Path(tmpdir) / "rag.sqlite", embedding_backend=ToyDenseBackend())
            store.recreate()
            store.insert_paragraphs([paragraph_a, paragraph_b])
            store.insert_units(build_retrieval_units([paragraph_a, paragraph_b], window_size=2, overlap=1))

            results = store.search_hybrid("猪肤汤", limit=4)

        by_id = {item["paragraph_id"]: item for item in results}
        self.assertIn("p-b", by_id)
        self.assertIn("text", by_id["p-b"]["retrieval_sources"])
        self.assertIn("猪肤汤", by_id["p-b"]["matched_text_terms"])

    def test_build_faiss_vector_index_writes_index_and_unit_mapping(self) -> None:
        paragraph_a = ParsedParagraph(
            paragraph_id="p-a",
            doc_id="doc",
            source_path="/tmp/doc.pdf",
            title="桂枝汤证",
            page_start=1,
            page_end=1,
            text="太阳中风，汗出恶风，桂枝汤主之。",
        )
        paragraph_b = ParsedParagraph(
            paragraph_id="p-b",
            doc_id="doc",
            source_path="/tmp/doc.pdf",
            title="麻黄汤证",
            page_start=2,
            page_end=2,
            text="太阳伤寒，无汗而喘，麻黄汤主之。",
        )

        class ToyDenseBackend(DenseEmbeddingBackend):
            name = "toy_dense"

            def embed_texts(self, texts: list[str]) -> list[list[float]]:
                vectors = []
                for text in texts:
                    if "桂枝" in text or "汗出" in text or "恶风" in text:
                        vectors.append([1.0, 0.0])
                    else:
                        vectors.append([0.0, 1.0])
                return vectors

        fake_faiss = FakeFaiss()
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            db_path = base / "rag.sqlite"
            store = LocalVectorStore(db_path, embedding_backend=ToyDenseBackend())
            store.recreate()
            store.insert_paragraphs([paragraph_a, paragraph_b])
            store.insert_units(build_retrieval_units([paragraph_a, paragraph_b], window_size=2, overlap=1))

            stats = build_faiss_vector_index(
                db_path,
                index_path=base / "vectors.faiss",
                ids_path=base / "vector_ids.jsonl",
                faiss_module=fake_faiss,
            )
            unit_count = store.stats()["retrieval_units"]
            mapping_lines = (base / "vector_ids.jsonl").read_text(encoding="utf-8").splitlines()
            index_exists = (base / "vectors.faiss").exists()

        self.assertEqual(stats["faiss_vectors"], unit_count)
        self.assertEqual(stats["faiss_dim"], 2)
        self.assertEqual(len(mapping_lines), unit_count)
        self.assertIn("unit_id", json.loads(mapping_lines[0]))
        self.assertTrue(index_exists)

    def test_build_faiss_vector_index_keeps_vectors_unweighted(self) -> None:
        paragraph = ParsedParagraph(
            paragraph_id="p-a",
            doc_id="doc",
            source_path="/tmp/doc.pdf",
            title="桂枝汤证",
            page_start=1,
            page_end=1,
            text="太阳中风，汗出恶风，桂枝汤主之。",
        )
        unit = RetrievalUnit(
            unit_id="u-a",
            paragraph_id="p-a",
            doc_id="doc",
            unit_type="sentence",
            text="桂枝汤",
            text_for_embedding="桂枝汤",
            sentence_start=0,
            sentence_end=0,
            weight=3.0,
        )

        class ToyDenseBackend(DenseEmbeddingBackend):
            name = "toy_dense"

            def embed_texts(self, texts: list[str]) -> list[list[float]]:
                return [[1.0, 0.0] for _ in texts]

        fake_faiss = FakeFaiss()
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            db_path = base / "rag.sqlite"
            index_path = base / "vectors.faiss"
            store = LocalVectorStore(db_path, embedding_backend=ToyDenseBackend())
            store.recreate()
            store.insert_paragraphs([paragraph])
            store.insert_units([unit])
            build_faiss_vector_index(
                db_path,
                index_path=index_path,
                ids_path=base / "vector_ids.jsonl",
                faiss_module=fake_faiss,
            )
            indexed_vector = fake_faiss.indexes[str(index_path.resolve())].vectors[0]

        self.assertEqual(indexed_vector, [1.0, 0.0])

    def test_build_faiss_vector_index_writes_absolute_artifact_metadata(self) -> None:
        paragraph = ParsedParagraph(
            paragraph_id="p-a", doc_id="doc", source_path="/tmp/doc.pdf", title="test",
            page_start=1, page_end=1, text="桂枝汤主之。",
        )

        class ToyDenseBackend(DenseEmbeddingBackend):
            name = "toy_dense"

            def embed_texts(self, texts: list[str]) -> list[list[float]]:
                return [[1.0, 0.0] for _ in texts]

        with tempfile.TemporaryDirectory(dir=".") as tmpdir:
            base = Path(os.path.relpath(tmpdir))
            db_path = base / "rag.sqlite"
            store = LocalVectorStore(db_path, embedding_backend=ToyDenseBackend())
            store.recreate()
            store.insert_paragraphs([paragraph])
            store.insert_units(build_retrieval_units([paragraph], window_size=2, overlap=1))
            (base / "manifest.json").write_text("{}", encoding="utf-8")
            stats = build_faiss_vector_index(db_path, faiss_module=FakeFaiss())
            meta = store.read_meta()
            manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))

        self.assertTrue(Path(str(stats["faiss_index"])).is_absolute())
        self.assertTrue(Path(str(stats["faiss_ids"])).is_absolute())
        self.assertTrue(Path(meta["faiss_index"]).is_absolute())
        self.assertTrue(Path(meta["faiss_ids"]).is_absolute())
        self.assertTrue(Path(manifest["faiss_index"]).is_absolute())
        self.assertTrue(Path(manifest["faiss_ids"]).is_absolute())

    def test_vector_search_uses_faiss_index_when_available(self) -> None:
        paragraph_a = ParsedParagraph(
            paragraph_id="p-a",
            doc_id="doc",
            source_path="/tmp/doc.pdf",
            title="桂枝汤证",
            page_start=1,
            page_end=1,
            text="太阳中风，汗出恶风，桂枝汤主之。",
        )
        paragraph_b = ParsedParagraph(
            paragraph_id="p-b",
            doc_id="doc",
            source_path="/tmp/doc.pdf",
            title="麻黄汤证",
            page_start=2,
            page_end=2,
            text="太阳伤寒，无汗而喘，麻黄汤主之。",
        )

        class ToyDenseBackend(DenseEmbeddingBackend):
            name = "toy_dense"

            def embed_texts(self, texts: list[str]) -> list[list[float]]:
                vectors = []
                for text in texts:
                    if "桂枝" in text or "汗出" in text or "恶风" in text:
                        vectors.append([1.0, 0.0])
                    else:
                        vectors.append([0.0, 1.0])
                return vectors

        fake_faiss = FakeFaiss()
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            db_path = base / "rag.sqlite"
            store = LocalVectorStore(db_path, embedding_backend=ToyDenseBackend())
            store.recreate()
            store.insert_paragraphs([paragraph_a, paragraph_b])
            store.insert_units(build_retrieval_units([paragraph_a, paragraph_b], window_size=2, overlap=1))
            build_faiss_vector_index(
                db_path,
                index_path=base / "vectors.faiss",
                ids_path=base / "vector_ids.jsonl",
                faiss_module=fake_faiss,
            )

            search_store = LocalVectorStore(db_path, embedding_backend=ToyDenseBackend())
            results = search_store.search_vector("桂枝汤 汗出", limit=2, faiss_module=fake_faiss)

        self.assertEqual(results[0]["paragraph_id"], "p-a")
        self.assertIn("faiss", results[0]["retrieval_sources"])
        self.assertGreater(results[0]["vector_score"], 0)

    def test_faiss_bundle_is_cached_until_either_file_changes(self) -> None:
        fake_faiss = FakeFaiss()
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            index_path = base / "vectors.faiss"
            ids_path = base / "vector_ids.jsonl"
            index_path.write_text("index", encoding="utf-8")
            ids_path.write_text('{"unit_id": "u1"}\n', encoding="utf-8")
            fake_faiss.indexes[str(index_path)] = FakeFaissIndex(2)

            first = load_faiss_bundle(index_path, ids_path, fake_faiss)
            second = load_faiss_bundle(index_path, ids_path, fake_faiss)
            old_mtime = ids_path.stat().st_mtime_ns
            ids_path.write_text('{"unit_id": "u1"}\n\n', encoding="utf-8")
            os.utime(ids_path, ns=(old_mtime + 1_000_000, old_mtime + 1_000_000))
            third = load_faiss_bundle(index_path, ids_path, fake_faiss)

        self.assertIs(first, second)
        self.assertIsNot(second, third)
        self.assertEqual(fake_faiss.read_count, 2)

    def test_faiss_bundle_cache_separates_loader_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            index_path = base / "vectors.faiss"
            ids_path = base / "vector_ids.jsonl"
            index_path.write_text("index", encoding="utf-8")
            ids_path.write_text('{"unit_id": "u1"}\n', encoding="utf-8")
            loader_a = FakeFaiss()
            loader_b = FakeFaiss()
            loader_a.indexes[str(index_path)] = FakeFaissIndex(2)
            loader_b.indexes[str(index_path)] = FakeFaissIndex(3)

            bundle_a = load_faiss_bundle(index_path, ids_path, loader_a)
            bundle_b = load_faiss_bundle(index_path, ids_path, loader_b)

        self.assertIs(bundle_a[0], loader_a.indexes[str(index_path)])
        self.assertIs(bundle_b[0], loader_b.indexes[str(index_path)])
        self.assertEqual(loader_a.read_count, 1)
        self.assertEqual(loader_b.read_count, 1)

    def test_faiss_bundle_cache_detects_same_size_replacement_with_restored_mtime(self) -> None:
        fake_faiss = FakeFaiss()
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            index_path = base / "vectors.faiss"
            ids_path = base / "vector_ids.jsonl"
            index_path.write_text("index", encoding="utf-8")
            ids_path.write_text('{"unit_id": "u1"}\n', encoding="utf-8")
            fake_faiss.indexes[str(index_path)] = FakeFaissIndex(2)
            first = load_faiss_bundle(index_path, ids_path, fake_faiss)
            original = ids_path.stat()
            original_fingerprint = pdf_vector._file_fingerprint(ids_path)
            replacement = base / "replacement.jsonl"
            replacement.write_text('{"unit_id": "u2"}\n', encoding="utf-8")
            os.utime(replacement, ns=(original.st_atime_ns, original.st_mtime_ns))
            os.replace(replacement, ids_path)
            self.assertEqual(ids_path.stat().st_size, original.st_size)
            self.assertEqual(ids_path.stat().st_mtime_ns, original.st_mtime_ns)
            self.assertNotEqual(pdf_vector._file_fingerprint(ids_path), original_fingerprint)

            second = load_faiss_bundle(index_path, ids_path, fake_faiss)

        self.assertIsNot(first, second)
        self.assertEqual(second[1], ["u2"])
        self.assertEqual(fake_faiss.read_count, 2)

    def test_faiss_bundle_cache_serializes_concurrent_loads(self) -> None:
        class SlowFakeFaiss(FakeFaiss):
            def read_index(self, path: str) -> FakeFaissIndex:
                time.sleep(0.02)
                return super().read_index(path)

        fake_faiss = SlowFakeFaiss()
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            index_path = base / "vectors.faiss"
            ids_path = base / "vector_ids.jsonl"
            index_path.write_text("index", encoding="utf-8")
            ids_path.write_text('{"unit_id": "u1"}\n', encoding="utf-8")
            expected = FakeFaissIndex(2)
            fake_faiss.indexes[str(index_path)] = expected
            with ThreadPoolExecutor(max_workers=8) as executor:
                bundles = list(
                    executor.map(
                        lambda _: load_faiss_bundle(index_path, ids_path, fake_faiss),
                        range(16),
                    )
                )

        self.assertTrue(all(bundle[0] is expected for bundle in bundles))
        self.assertEqual(fake_faiss.read_count, 1)

    def test_faiss_bundle_cache_retains_only_one_large_index(self) -> None:
        fake_faiss = FakeFaiss()
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            for name in ("one", "two"):
                directory = base / name
                directory.mkdir()
                index_path = directory / "vectors.faiss"
                ids_path = directory / "vector_ids.jsonl"
                index_path.write_text("index", encoding="utf-8")
                ids_path.write_text('{"unit_id": "u1"}\n', encoding="utf-8")
                fake_faiss.indexes[str(index_path)] = FakeFaissIndex(2)
                load_faiss_bundle(index_path, ids_path, fake_faiss)

        self.assertEqual(len(pdf_vector._FAISS_BUNDLE_CACHE), 1)

    def test_faiss_exact_id_audit_is_cached_until_artifact_or_database_changes(self) -> None:
        paragraph = ParsedParagraph(
            paragraph_id="p-a", doc_id="doc", source_path="/tmp/doc.pdf", title="test",
            page_start=1, page_end=1, text="桂枝汤主之。",
        )

        class ToyDenseBackend(DenseEmbeddingBackend):
            name = "toy_dense"

            def embed_texts(self, texts: list[str]) -> list[list[float]]:
                return [[1.0, 0.0] for _ in texts]

        unit = RetrievalUnit(
            unit_id="u-1", paragraph_id="p-a", doc_id="doc", unit_type="sentence",
            text="桂枝汤", text_for_embedding="桂枝汤", sentence_start=0, sentence_end=0,
            weight=1.0,
        )
        fake_faiss = FakeFaiss()
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            store = LocalVectorStore(base / "rag.sqlite", embedding_backend=ToyDenseBackend())
            store.recreate()
            with store.connect() as conn:
                conn.execute("PRAGMA journal_mode=WAL")
            store.insert_paragraphs([paragraph])
            store.insert_units([unit])
            build_faiss_vector_index(store.db_path, faiss_module=fake_faiss)
            with patch.object(
                pdf_vector,
                "_audit_faiss_bundle_ids",
                wraps=pdf_vector._audit_faiss_bundle_ids,
            ) as audit:
                store.search_vector("桂枝汤", faiss_module=fake_faiss)
                store.search_vector("桂枝汤", faiss_module=fake_faiss)
                self.assertEqual(audit.call_count, 1)

                ids_path = base / "vector_ids.jsonl"
                old_mtime = ids_path.stat().st_mtime_ns
                ids_path.write_text('{"unit_id": "u-1"}\n\n', encoding="utf-8")
                os.utime(ids_path, ns=(old_mtime + 1_000_000, old_mtime + 1_000_000))
                store.search_vector("桂枝汤", faiss_module=fake_faiss)
                self.assertEqual(audit.call_count, 2)

                database_fingerprint = pdf_vector._database_revision_fingerprint(store.db_path)
                with closing(sqlite3.connect(store.db_path)) as writer:
                    writer.execute("UPDATE retrieval_units SET text = text || ' changed'")
                    writer.commit()
                    self.assertNotEqual(
                        pdf_vector._database_revision_fingerprint(store.db_path),
                        database_fingerprint,
                    )
                    store.search_vector("桂枝汤", faiss_module=fake_faiss)
                self.assertEqual(audit.call_count, 3)

    def test_faiss_search_rejects_nonfinite_scores(self) -> None:
        class NonfiniteIndex(FakeFaissIndex):
            def search(self, queries: object, top_k: int) -> tuple[list[list[float]], list[list[int]]]:
                return [[math.nan, math.inf]], [[0, 1]]

        results = self._search_with_custom_faiss_index(NonfiniteIndex(2), ["u-0", "u-1"])
        self.assertEqual(results, [])

    def test_faiss_search_deduplicates_returned_row_indices(self) -> None:
        class DuplicateIndex(FakeFaissIndex):
            def search(self, queries: object, top_k: int) -> tuple[list[list[float]], list[list[int]]]:
                return [[0.9, 0.8]], [[0, 0]]

        results = self._search_with_custom_faiss_index(DuplicateIndex(2), ["u-0", "u-1"])
        self.assertEqual(results[0]["hit_count"], 1)
        self.assertEqual(len(results[0]["matched_units"]), 1)

    def test_faiss_search_hostile_iterator_falls_back_safely(self) -> None:
        class HostileRows:
            def __getitem__(self, key: int) -> object:
                class HostileIterator:
                    def __iter__(self) -> object:
                        return self

                    def __next__(self) -> object:
                        raise RuntimeError("hostile iterator secret")

                return HostileIterator()

        class HostileIndex(FakeFaissIndex):
            def search(self, queries: object, top_k: int) -> tuple[object, object]:
                return HostileRows(), HostileRows()

        results = self._search_with_custom_faiss_index(HostileIndex(2), ["u-0", "u-1"])
        self.assertEqual(results[0]["retrieval_sources"], ["vector"])

    def _search_with_custom_faiss_index(
        self,
        index: FakeFaissIndex,
        unit_ids: list[str],
    ) -> list[dict[str, object]]:
        paragraph = ParsedParagraph(
            paragraph_id="p-a", doc_id="doc", source_path="/tmp/doc.pdf", title="test",
            page_start=1, page_end=1, text="桂枝汤主之。",
        )

        class ToyDenseBackend(DenseEmbeddingBackend):
            name = "toy_dense"

            def embed_texts(self, texts: list[str]) -> list[list[float]]:
                return [[1.0, 0.0] for _ in texts]

        units = [
            RetrievalUnit(
                unit_id=unit_id, paragraph_id="p-a", doc_id="doc", unit_type="sentence",
                text=unit_id, text_for_embedding=unit_id, sentence_start=offset,
                sentence_end=offset, weight=1.0,
            )
            for offset, unit_id in enumerate(unit_ids)
        ]
        index.add([[1.0, 0.0] for _ in unit_ids])
        fake_faiss = FakeFaiss()
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            index_path = base / "vectors.faiss"
            ids_path = base / "vector_ids.jsonl"
            store = LocalVectorStore(base / "rag.sqlite", embedding_backend=ToyDenseBackend())
            store.recreate()
            store.insert_paragraphs([paragraph])
            store.insert_units(units)
            index_path.write_text("index", encoding="utf-8")
            ids_path.write_text(
                "\n".join(json.dumps({"unit_id": unit_id}) for unit_id in unit_ids) + "\n",
                encoding="utf-8",
            )
            fake_faiss.indexes[str(index_path)] = index
            return store.search_vector("桂枝汤", faiss_module=fake_faiss)

    def test_dense_search_refuses_large_brute_force_scan_without_faiss(self) -> None:
        paragraph = ParsedParagraph(
            paragraph_id="p-a",
            doc_id="doc",
            source_path="/tmp/doc.pdf",
            title="test",
            page_start=1,
            page_end=1,
            text="桂枝汤。麻黄汤。葛根汤。",
        )

        class ToyDenseBackend(DenseEmbeddingBackend):
            name = "toy_dense"

            def embed_texts(self, texts: list[str]) -> list[list[float]]:
                return [[1.0, 0.0] for _ in texts]

        units = [
            RetrievalUnit(
                unit_id=f"u-{index}", paragraph_id="p-a", doc_id="doc",
                unit_type="sentence", text=f"unit {index}", text_for_embedding=f"unit {index}",
                sentence_start=index, sentence_end=index, weight=1.0,
            )
            for index in range(3)
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(
                Path(tmpdir) / "rag.sqlite",
                embedding_backend=ToyDenseBackend(),
                brute_force_limit=2,
            )
            store.recreate()
            store.insert_paragraphs([paragraph])
            store.insert_units(units)

            with self.assertRaisesRegex(RuntimeError, "FAISS.*nihaisha-rag doctor"):
                store.search_vector("桂枝汤", faiss_module=False)

    def test_small_dense_search_can_brute_force_without_faiss(self) -> None:
        paragraph = ParsedParagraph(
            paragraph_id="p-a", doc_id="doc", source_path="/tmp/doc.pdf", title="test",
            page_start=1, page_end=1, text="桂枝汤主之。",
        )

        class ToyDenseBackend(DenseEmbeddingBackend):
            name = "toy_dense"

            def embed_texts(self, texts: list[str]) -> list[list[float]]:
                return [[1.0, 0.0] for _ in texts]

        unit = RetrievalUnit(
            unit_id="u-1", paragraph_id="p-a", doc_id="doc", unit_type="sentence",
            text="桂枝汤主之", text_for_embedding="桂枝汤主之", sentence_start=0,
            sentence_end=0, weight=1.0,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(
                Path(tmpdir) / "rag.sqlite",
                embedding_backend=ToyDenseBackend(),
                brute_force_limit=1,
            )
            store.recreate()
            store.insert_paragraphs([paragraph])
            store.insert_units([unit])

            results = store.search_vector("桂枝汤", faiss_module=False)

        self.assertEqual(results[0]["paragraph_id"], "p-a")

    def test_brute_force_limit_rejects_bool_and_negative_values(self) -> None:
        with self.assertRaises(ValueError):
            LocalVectorStore(Path("x.sqlite"), brute_force_limit=-1)
        with self.assertRaises(TypeError):
            LocalVectorStore(Path("x.sqlite"), brute_force_limit=True)

    def test_vector_search_rejects_embedding_kind_mismatch(self) -> None:
        paragraph = ParsedParagraph(
            paragraph_id="p-a",
            doc_id="doc",
            source_path="/tmp/doc.pdf",
            title="桂枝汤证",
            page_start=1,
            page_end=1,
            text="太阳中风，汗出恶风，桂枝汤主之。",
        )

        class ToyDenseBackend(DenseEmbeddingBackend):
            name = "toy_dense"

            def embed_texts(self, texts: list[str]) -> list[list[float]]:
                return [[1.0, 0.0] for _ in texts]

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "rag.sqlite"
            store = LocalVectorStore(db_path, embedding_backend=ToyDenseBackend())
            store.recreate()
            store.insert_paragraphs([paragraph])
            store.insert_units(build_retrieval_units([paragraph], window_size=2, overlap=1))

            mismatched_store = LocalVectorStore(db_path, embedding_backend=create_embedding_backend("sparse"))
            with self.assertRaisesRegex(RuntimeError, "vector_kind mismatch"):
                mismatched_store.search_vector("桂枝汤", limit=1)

    def test_rebuild_text_index_is_idempotent(self) -> None:
        paragraph = ParsedParagraph(
            paragraph_id="p-a",
            doc_id="doc",
            source_path="/tmp/doc.pdf",
            title="桂枝汤证",
            page_start=1,
            page_end=1,
            text="太阳中风，汗出恶风，桂枝汤主之。",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(Path(tmpdir) / "rag.sqlite")
            store.recreate()
            store.insert_paragraphs([paragraph])
            first = store.rebuild_text_index()
            second = store.rebuild_text_index()
            meta = store.read_meta()

        self.assertEqual(first["text_index_rows"], 1)
        self.assertEqual(second["text_index_rows"], 1)
        self.assertTrue(meta["text_index"].startswith("fts5_"))

    def test_rebuild_text_index_updates_manifest_when_present(self) -> None:
        paragraph = ParsedParagraph(
            paragraph_id="p-a",
            doc_id="doc",
            source_path="/tmp/doc.pdf",
            title="桂枝汤证",
            page_start=1,
            page_end=1,
            text="太阳中风，汗出恶风，桂枝汤主之。",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            manifest_path = base / "manifest.json"
            manifest_path.write_text(json.dumps({"paragraphs": 0}), encoding="utf-8")
            store = LocalVectorStore(base / "rag.sqlite")
            store.recreate()
            store.insert_paragraphs([paragraph])
            store.rebuild_text_index()

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(manifest["text_index"], "fts5_trigram")
        self.assertEqual(manifest["text_index_rows"], 1)

    def test_write_build_traces_records_intermediate_artifacts_without_secrets(self) -> None:
        paragraph = ParsedParagraph(
            paragraph_id="p-a",
            doc_id="doc",
            source_path="/tmp/doc.pdf",
            title="桂枝汤证",
            page_start=1,
            page_end=1,
            text="太阳中风，汗出恶风，桂枝汤主之。",
        )
        units = build_retrieval_units([paragraph], window_size=2, overlap=1)

        with tempfile.TemporaryDirectory() as tmpdir:
            trace_dir = Path(tmpdir) / "traces"
            write_build_traces(
                trace_dir=trace_dir,
                pdf_dir=Path("/tmp/pdfs"),
                out_dir=Path(tmpdir),
                embedding_name="siliconflow:BAAI/bge-m3",
                vector_kind="dense",
                window_size=2,
                overlap=1,
                unit_types={"sentence", "window", "paragraph", "question"},
                paragraphs=[paragraph],
                units=units,
                document_events=[
                    {
                        "source_path": "/tmp/doc.pdf",
                        "paragraphs": 1,
                        "retrieval_units": len(units),
                    }
                ],
            )

            paragraphs_path = trace_dir / "paragraphs.jsonl"
            units_path = trace_dir / "retrieval_units.jsonl"
            events_path = trace_dir / "build_events.jsonl"
            config_path = trace_dir / "build_config.json"
            trace_text = "\n".join(
                path.read_text(encoding="utf-8")
                for path in [paragraphs_path, units_path, events_path, config_path]
            )
            files_exist = all(
                path.exists()
                for path in [paragraphs_path, units_path, events_path, config_path]
            )

        self.assertTrue(files_exist)
        self.assertIn('"paragraph_id": "p-a"', trace_text)
        self.assertIn('"unit_type": "question"', trace_text)
        self.assertNotIn("SILICONFLOW_API_KEY", trace_text)
        self.assertNotIn("sk-", trace_text)

    def test_sparse_vector_blob_round_trips_with_cosine_score(self) -> None:
        vector = {1: 0.5, 42: 0.25, 2047: 0.75}

        restored = unpack_sparse_vector(pack_sparse_vector(vector))

        self.assertEqual(set(restored), set(vector))
        self.assertAlmostEqual(sparse_dot(vector, restored), sparse_dot(vector, vector), places=5)

    def test_dense_vector_blob_round_trips_normalized_vector(self) -> None:
        vector = [3.0, 4.0, 0.0]

        restored = unpack_dense_vector(pack_dense_vector(vector))

        self.assertAlmostEqual(restored[0], 0.6, places=5)
        self.assertAlmostEqual(restored[1], 0.8, places=5)
        self.assertAlmostEqual(sum(value * value for value in restored), 1.0, places=5)

    def test_siliconflow_backend_posts_bge_m3_batches(self) -> None:
        class FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {
                    "data": [
                        {"index": 0, "embedding": [1.0, 0.0]},
                        {"index": 1, "embedding": [0.0, 2.0]},
                    ]
                }

        class FakeSession:
            def __init__(self) -> None:
                self.calls = []

            def post(self, url: str, headers: dict, json: dict, timeout: int) -> FakeResponse:
                self.calls.append((url, headers, json, timeout))
                return FakeResponse()

        session = FakeSession()
        backend = SiliconFlowEmbeddingBackend(api_key="secret", session=session, batch_size=2)

        vectors = backend.embed_texts(["桂枝汤", "麻黄汤"])

        self.assertEqual(vectors, [[1.0, 0.0], [0.0, 2.0]])
        self.assertEqual(session.calls[0][0], "https://api.siliconflow.cn/v1/embeddings")
        self.assertEqual(session.calls[0][2]["model"], "BAAI/bge-m3")
        self.assertEqual(session.calls[0][2]["input"], ["桂枝汤", "麻黄汤"])
        self.assertEqual(session.calls[0][2]["encoding_format"], "float")

    def test_vector_store_can_use_dense_embedding_backend(self) -> None:
        paragraph_a = ParsedParagraph(
            paragraph_id="p-a",
            doc_id="doc",
            source_path="/tmp/doc.pdf",
            title="桂枝汤证",
            page_start=1,
            page_end=1,
            text="太阳中风，汗出恶风，桂枝汤主之。",
        )
        paragraph_b = ParsedParagraph(
            paragraph_id="p-b",
            doc_id="doc",
            source_path="/tmp/doc.pdf",
            title="麻黄汤证",
            page_start=2,
            page_end=2,
            text="太阳伤寒，无汗而喘，麻黄汤主之。",
        )

        class ToyDenseBackend(DenseEmbeddingBackend):
            name = "toy_dense"

            def embed_texts(self, texts: list[str]) -> list[list[float]]:
                vectors = []
                for text in texts:
                    if "桂枝" in text or "汗出" in text or "恶风" in text:
                        vectors.append([1.0, 0.0])
                    else:
                        vectors.append([0.0, 1.0])
                return vectors

        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(Path(tmpdir) / "rag.sqlite", embedding_backend=ToyDenseBackend())
            store.recreate()
            store.insert_paragraphs([paragraph_a, paragraph_b])
            store.insert_units(build_retrieval_units([paragraph_a, paragraph_b], window_size=2, overlap=1))

            results = store.search("桂枝汤 汗出 恶风", limit=2)

        self.assertEqual(results[0]["paragraph_id"], "p-a")

    def test_dense_vector_store_records_actual_vector_dimension(self) -> None:
        paragraph = ParsedParagraph(
            paragraph_id="p-a",
            doc_id="doc",
            source_path="/tmp/doc.pdf",
            title="桂枝汤证",
            page_start=1,
            page_end=1,
            text="太阳中风，汗出恶风，桂枝汤主之。",
        )

        class ToyDenseBackend(DenseEmbeddingBackend):
            name = "toy_dense"

            def embed_texts(self, texts: list[str]) -> list[list[float]]:
                return [[1.0, 0.0] for _ in texts]

        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalVectorStore(
                Path(tmpdir) / "rag.sqlite",
                dims=2048,
                embedding_backend=ToyDenseBackend(),
            )
            store.recreate()
            store.insert_paragraphs([paragraph])
            store.insert_units(build_retrieval_units([paragraph], window_size=2, overlap=1))

            meta = store.read_meta()

        self.assertEqual(meta["dims"], "2")
        self.assertEqual(meta["vector_dim"], "2")

    def test_augment_pdf_vector_store_questions_is_idempotent(self) -> None:
        paragraph = ParsedParagraph(
            paragraph_id="p-a",
            doc_id="doc",
            source_path="/tmp/doc.pdf",
            title="方证比较",
            page_start=1,
            page_end=1,
            text="太阳中风，汗出恶风，桂枝汤主之。太阳伤寒，无汗而喘，麻黄汤主之。",
        )

        class ToyDenseBackend(DenseEmbeddingBackend):
            name = "toy_dense"

            def embed_texts(self, texts: list[str]) -> list[list[float]]:
                return [[1.0, 0.0] for _ in texts]

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "rag.sqlite"
            store = LocalVectorStore(db_path, embedding_backend=ToyDenseBackend())
            store.recreate()
            store.insert_paragraphs([paragraph])
            base_units = [
                unit
                for unit in build_retrieval_units([paragraph], window_size=2, overlap=1)
                if unit.unit_type != "question"
            ]
            store.insert_units(base_units)

            first = augment_pdf_vector_store_questions(db_path, embedding_backend=ToyDenseBackend())
            second = augment_pdf_vector_store_questions(db_path, embedding_backend=ToyDenseBackend())

            with store.connect() as conn:
                question_count = conn.execute(
                    "SELECT COUNT(*) FROM retrieval_units WHERE unit_type = 'question'"
                ).fetchone()[0]

        self.assertGreaterEqual(first["question_units"], 4)
        self.assertEqual(second["question_units"], first["question_units"])
        self.assertEqual(question_count, first["question_units"])


if __name__ == "__main__":
    unittest.main()
