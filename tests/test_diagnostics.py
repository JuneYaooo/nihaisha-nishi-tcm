from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from nihaisha_kg import diagnostics
from nihaisha_kg.diagnostics import doctor
from nihaisha_kg.faiss_artifacts import resolve_faiss_artifacts
from nihaisha_kg.pdf_vector import DenseEmbeddingBackend, LocalVectorStore, RetrievalUnit


class ToyDenseBackend(DenseEmbeddingBackend):
    name = "toy_dense"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


class DiagnosticsTests(unittest.TestCase):
    def _create_dense_store(self, base: Path) -> Path:
        db_path = base / "rag.sqlite"
        store = LocalVectorStore(db_path, embedding_backend=ToyDenseBackend())
        store.recreate()
        paragraph = diagnostics_test_paragraph()
        store.insert_paragraphs([paragraph])
        store.insert_units(
            [
                RetrievalUnit(
                    unit_id="u1", paragraph_id=paragraph.paragraph_id, doc_id=paragraph.doc_id,
                    unit_type="sentence", text="桂枝汤", text_for_embedding="桂枝汤",
                    sentence_start=0, sentence_end=0, weight=1.0,
                )
            ]
        )
        store.rebuild_text_index()
        store.rebuild_knowledge_units()
        return db_path

    def test_doctor_reports_dense_database_with_missing_faiss_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "rag.sqlite"
            store = LocalVectorStore(db_path, embedding_backend=ToyDenseBackend())
            store.recreate()
            store.rebuild_text_index()
            store.rebuild_knowledge_units()

            report = doctor(db_path, faiss_loader=lambda: None)

        codes = {item["code"] for item in report["diagnoses"]}
        self.assertEqual(report["status"], "error")
        self.assertIn("faiss_files_missing", codes)

    def test_doctor_does_not_require_faiss_for_sparse_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "rag.sqlite"
            store = LocalVectorStore(db_path)
            store.recreate()
            store.rebuild_text_index()
            store.rebuild_knowledge_units()

            report = doctor(db_path, faiss_loader=lambda: None)

        codes = {item["code"] for item in report["diagnoses"]}
        self.assertEqual(report["status"], "ok")
        self.assertNotIn("faiss_files_missing", codes)
        self.assertNotIn("faiss_module_missing", codes)

    def test_doctor_rejects_missing_empty_and_unknown_vector_kind(self) -> None:
        for vector_kind in (None, "", "bogus"):
            with self.subTest(vector_kind=vector_kind), tempfile.TemporaryDirectory() as tmpdir:
                db_path = Path(tmpdir) / "rag.sqlite"
                store = LocalVectorStore(db_path)
                store.recreate()
                store.rebuild_text_index()
                store.rebuild_knowledge_units()
                with closing(sqlite3.connect(db_path)) as conn:
                    if vector_kind is None:
                        conn.execute("DELETE FROM meta WHERE key = 'vector_kind'")
                    else:
                        conn.execute(
                            "UPDATE meta SET value = ? WHERE key = 'vector_kind'",
                            (vector_kind,),
                        )
                    conn.commit()

                report = doctor(db_path, faiss_loader=lambda: None)

            codes = {item["code"] for item in report["diagnoses"]}
            self.assertNotEqual(report["status"], "ok")
            self.assertIn("vector_metadata_invalid", codes)

    def test_doctor_rejects_missing_embedding_and_nonpositive_vector_dimension(self) -> None:
        for sql in (
            "DELETE FROM meta WHERE key = 'embedding'",
            "UPDATE meta SET value = '0' WHERE key = 'vector_dim'",
        ):
            with self.subTest(sql=sql), tempfile.TemporaryDirectory() as tmpdir:
                db_path = Path(tmpdir) / "rag.sqlite"
                store = LocalVectorStore(db_path)
                store.recreate()
                store.rebuild_text_index()
                store.rebuild_knowledge_units()
                with closing(sqlite3.connect(db_path)) as conn:
                    conn.execute(sql)
                    conn.commit()

                report = doctor(db_path, faiss_loader=lambda: None)

            codes = {item["code"] for item in report["diagnoses"]}
            self.assertNotEqual(report["status"], "ok")
            self.assertIn("vector_metadata_invalid", codes)

    def test_doctor_handles_missing_invalid_and_incomplete_databases(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            cases = [base / "missing.sqlite", base / "invalid.sqlite", base / "empty.sqlite"]
            cases[1].write_text("not sqlite", encoding="utf-8")
            sqlite3.connect(cases[2]).close()

            reports = [doctor(path, faiss_loader=lambda: None) for path in cases]

        self.assertTrue(all(report["status"] == "error" for report in reports))
        self.assertTrue(all(report["diagnoses"] for report in reports))

    def test_doctor_handles_missing_meta_and_malformed_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            db_path = base / "rag.sqlite"
            with closing(sqlite3.connect(db_path)) as conn:
                conn.executescript(
                    """
                    CREATE TABLE paragraphs (paragraph_id TEXT);
                    CREATE TABLE retrieval_units (unit_id TEXT);
                    CREATE TABLE paragraphs_fts (paragraph_id TEXT);
                    CREATE TABLE knowledge_units (knowledge_unit_id TEXT);
                    """
                )
            (base / "vectors.faiss").write_bytes(b"index")
            (base / "vector_ids.jsonl").write_text('{"unit_id": "u1"}\nnot-json\n', encoding="utf-8")

            report = doctor(db_path, faiss_loader=lambda: object())

        codes = {item["code"] for item in report["diagnoses"]}
        self.assertIn("meta_missing", codes)
        self.assertIn("faiss_mapping_invalid", codes)

    def test_doctor_reports_mapping_count_and_index_count_mismatch(self) -> None:
        class Index:
            ntotal = 1
            d = 2

        class FakeFaiss:
            def read_index(self, path: str) -> Index:
                return Index()

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            db_path = base / "rag.sqlite"
            store = LocalVectorStore(db_path, embedding_backend=ToyDenseBackend())
            store.recreate()
            store.rebuild_text_index()
            store.rebuild_knowledge_units()
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    """INSERT INTO retrieval_units
                    (unit_id, paragraph_id, doc_id, unit_type, text, sentence_start,
                     sentence_end, weight, vector_blob)
                    VALUES ('u1', 'p1', 'd', 'sentence', 'a', 0, 0, 1, X'00000000')"""
                )
            (base / "vectors.faiss").write_bytes(b"index")
            (base / "vector_ids.jsonl").write_text(
                "\n".join(json.dumps({"unit_id": value}) for value in ("u1", "u2")) + "\n",
                encoding="utf-8",
            )

            report = doctor(db_path, faiss_loader=lambda: FakeFaiss())

        codes = {item["code"] for item in report["diagnoses"]}
        self.assertIn("faiss_mapping_count_mismatch", codes)
        self.assertIn("faiss_index_count_mismatch", codes)

    def test_doctor_streams_deeply_nested_json_as_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            db_path = self._create_dense_store(base)
            (base / "vectors.faiss").write_bytes(b"index")
            (base / "vector_ids.jsonl").write_text("[" * 10_000 + "0" + "]" * 10_000 + "\n")

            report = doctor(db_path, faiss_loader=lambda: None)

        codes = {item["code"] for item in report["diagnoses"]}
        self.assertIn("faiss_mapping_invalid", codes)

    def test_doctor_rejects_oversized_mapping_line_and_file(self) -> None:
        for limit_name in ("MAX_MAPPING_LINE_BYTES", "MAX_MAPPING_FILE_BYTES"):
            with self.subTest(limit_name=limit_name), tempfile.TemporaryDirectory() as tmpdir:
                base = Path(tmpdir)
                db_path = self._create_dense_store(base)
                (base / "vectors.faiss").write_bytes(b"index")
                (base / "vector_ids.jsonl").write_bytes(b"x" * 128)
                with patch.object(diagnostics, limit_name, 64):
                    report = doctor(db_path, faiss_loader=lambda: None)

            codes = {item["code"] for item in report["diagnoses"]}
            self.assertIn("faiss_mapping_limits_exceeded", codes)

    def test_doctor_honors_relative_custom_faiss_paths(self) -> None:
        class Index:
            ntotal = 1
            d = 2

        class FakeFaiss:
            def read_index(self, path: str) -> Index:
                return Index()

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            db_path = self._create_dense_store(base)
            custom = base / "custom"
            custom.mkdir()
            (custom / "index.faiss").write_bytes(b"index")
            (custom / "ids.jsonl").write_text('{"unit_id": "u1"}\n', encoding="utf-8")
            with closing(sqlite3.connect(db_path)) as conn:
                conn.executemany(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                    (("faiss_index", "custom/index.faiss"), ("faiss_ids", "custom/ids.jsonl")),
                )
                conn.commit()

            report = doctor(db_path, faiss_loader=lambda: FakeFaiss())

        self.assertEqual(report["status"], "ok")

    def test_artifact_resolution_never_probes_cwd_relative_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            db_path = base / "store" / "rag.sqlite"
            relative_index = Path("legacy/custom.faiss")
            relative_ids = Path("legacy/custom.jsonl")

            with patch.object(
                Path,
                "exists",
                autospec=True,
                side_effect=lambda path: path in {relative_index, relative_ids},
            ) as exists:
                artifacts = resolve_faiss_artifacts(
                    db_path,
                    str(relative_index),
                    str(relative_ids),
                )

        self.assertEqual(artifacts.index, db_path.parent / relative_index)
        self.assertEqual(artifacts.ids, db_path.parent / relative_ids)
        self.assertTrue(all(call.args[0].is_absolute() for call in exists.call_args_list))

    def test_doctor_prefers_sibling_artifacts_without_cwd_dependency(self) -> None:
        class Index:
            ntotal = 1
            d = 2

        class FakeFaiss:
            def read_index(self, path: str) -> Index:
                return Index()

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            store_dir = base / "data" / "store"
            store_dir.mkdir(parents=True)
            db_path = self._create_dense_store(store_dir)
            (store_dir / "vectors.faiss").write_bytes(b"index")
            (store_dir / "vector_ids.jsonl").write_text('{"unit_id": "u1"}\n', encoding="utf-8")
            with closing(sqlite3.connect(db_path)) as conn:
                conn.executemany(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                    (
                        ("faiss_index", "data/store/vectors.faiss"),
                        ("faiss_ids", "data/store/vector_ids.jsonl"),
                    ),
                )
                conn.commit()

            report = doctor(db_path.resolve(), faiss_loader=lambda: FakeFaiss())

        self.assertEqual(report["status"], "ok")

    def test_doctor_selects_only_recognized_metadata_through_read_only_connection(self) -> None:
        original_connect = sqlite3.connect
        statements: list[str] = []
        connect_calls: list[tuple[object, dict[str, object]]] = []

        class TrackingConnection(sqlite3.Connection):
            def execute(self, sql: str, parameters: object = (), /) -> sqlite3.Cursor:
                statements.append(sql)
                return super().execute(sql, parameters)

        def tracking_connect(database: object, **kwargs: object) -> sqlite3.Connection:
            connect_calls.append((database, dict(kwargs)))
            kwargs.setdefault("factory", TrackingConnection)
            return original_connect(database, **kwargs)

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "rag.sqlite"
            store = LocalVectorStore(db_path)
            store.recreate()
            store.rebuild_text_index()
            store.rebuild_knowledge_units()
            with patch.object(diagnostics.sqlite3, "connect", side_effect=tracking_connect):
                report = doctor(db_path, faiss_loader=lambda: None)

        meta_statements = [sql for sql in statements if "FROM meta" in sql]
        self.assertEqual(report["status"], "ok")
        self.assertTrue(meta_statements)
        self.assertTrue(all("WHERE" in sql.upper() for sql in meta_statements))
        self.assertIn("mode=ro", str(connect_calls[0][0]))
        self.assertTrue(connect_calls[0][1].get("uri"))

    def test_doctor_ignores_unrelated_huge_metadata_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "rag.sqlite"
            store = LocalVectorStore(db_path)
            store.recreate()
            store.rebuild_text_index()
            store.rebuild_knowledge_units()
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute("INSERT INTO meta(key, value) VALUES ('unrelated', zeroblob(5000000))")
                conn.commit()

            report = doctor(db_path, faiss_loader=lambda: None)

        self.assertEqual(report["status"], "ok")

    def test_doctor_rejects_huge_or_nontext_recognized_metadata(self) -> None:
        for sql in (
            "UPDATE meta SET value = zeroblob(1000000) WHERE key = 'embedding'",
            "UPDATE meta SET value = X'00' WHERE key = 'vector_kind'",
        ):
            with self.subTest(sql=sql), tempfile.TemporaryDirectory() as tmpdir:
                db_path = Path(tmpdir) / "rag.sqlite"
                store = LocalVectorStore(db_path)
                store.recreate()
                store.rebuild_text_index()
                store.rebuild_knowledge_units()
                with closing(sqlite3.connect(db_path)) as conn:
                    conn.execute(sql)
                    conn.commit()

                report = doctor(db_path, faiss_loader=lambda: None)

            codes = {item["code"] for item in report["diagnoses"]}
            self.assertIn("meta_invalid", codes)

    def test_doctor_rejects_duplicate_recognized_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "rag.sqlite"
            store = LocalVectorStore(db_path)
            store.recreate()
            store.rebuild_text_index()
            store.rebuild_knowledge_units()
            with closing(sqlite3.connect(db_path)) as conn:
                conn.executescript(
                    """
                    ALTER TABLE meta RENAME TO old_meta;
                    CREATE TABLE meta(key TEXT, value TEXT);
                    INSERT INTO meta SELECT key, value FROM old_meta;
                    INSERT INTO meta(key, value) VALUES ('vector_kind', 'sparse');
                    DROP TABLE old_meta;
                    """
                )

            report = doctor(db_path, faiss_loader=lambda: None)

        codes = {item["code"] for item in report["diagnoses"]}
        self.assertIn("meta_invalid", codes)

    def test_doctor_accepts_uppercase_meta_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "rag.sqlite"
            store = LocalVectorStore(db_path)
            store.recreate()
            store.rebuild_text_index()
            store.rebuild_knowledge_units()
            with closing(sqlite3.connect(db_path)) as conn:
                conn.executescript(
                    """
                    ALTER TABLE meta RENAME TO old_meta;
                    CREATE TABLE META(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    INSERT INTO META SELECT key, value FROM old_meta;
                    DROP TABLE old_meta;
                    """
                )

            report = doctor(db_path, faiss_loader=lambda: None)

        self.assertEqual(report["status"], "ok")

    def test_doctor_rejects_meta_views_case_insensitively(self) -> None:
        for view_name in ("meta", "META"):
            with self.subTest(view_name=view_name), tempfile.TemporaryDirectory() as tmpdir:
                db_path = Path(tmpdir) / "rag.sqlite"
                store = LocalVectorStore(db_path)
                store.recreate()
                store.rebuild_text_index()
                store.rebuild_knowledge_units()
                with closing(sqlite3.connect(db_path)) as conn:
                    conn.executescript(
                        f"""
                        ALTER TABLE meta RENAME TO backing_meta;
                        CREATE VIEW {view_name} AS SELECT key, value FROM backing_meta;
                        """
                    )

                report = doctor(db_path, faiss_loader=lambda: None)

            codes = {item["code"] for item in report["diagnoses"]}
            self.assertEqual(report["status"], "error")
            self.assertIn("meta_invalid", codes)

    def test_doctor_accepts_uppercase_required_table_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "rag.sqlite"
            with closing(sqlite3.connect(db_path)) as conn:
                conn.executescript(
                    """
                    CREATE TABLE PARAGRAPHS(paragraph_id TEXT);
                    CREATE TABLE RETRIEVAL_UNITS(unit_id TEXT);
                    CREATE TABLE PARAGRAPHS_FTS(paragraph_id TEXT);
                    CREATE TABLE KNOWLEDGE_UNITS(knowledge_unit_id TEXT);
                    CREATE TABLE META(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    INSERT INTO META VALUES ('vector_kind', 'sparse');
                    INSERT INTO META VALUES ('embedding', 'sparse_hash');
                    INSERT INTO META VALUES ('vector_dim', '2048');
                    """
                )

            report = doctor(db_path, faiss_loader=lambda: None)

        self.assertEqual(report["status"], "ok")

    def test_doctor_rejects_required_name_views_and_reports_only_non_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "rag.sqlite"
            with closing(sqlite3.connect(db_path)) as conn:
                conn.executescript(
                    """
                    CREATE TABLE PARAGRAPHS(paragraph_id TEXT);
                    CREATE VIEW RETRIEVAL_UNITS AS SELECT paragraph_id AS unit_id FROM PARAGRAPHS;
                    CREATE VIRTUAL TABLE PARAGRAPHS_FTS USING fts5(paragraph_id);
                    CREATE VIEW KNOWLEDGE_UNITS AS
                        SELECT paragraph_id AS knowledge_unit_id FROM PARAGRAPHS;
                    CREATE TABLE META(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    INSERT INTO META VALUES ('vector_kind', 'sparse');
                    INSERT INTO META VALUES ('embedding', 'sparse_hash');
                    INSERT INTO META VALUES ('vector_dim', '2048');
                    """
                )

            report = doctor(db_path, faiss_loader=lambda: None)

        diagnoses = {item["code"]: item for item in report["diagnoses"]}
        self.assertEqual(report["status"], "error")
        self.assertEqual(
            diagnoses["schema_missing_tables"]["details"]["tables"],
            ["retrieval_units", "knowledge_units"],
        )

    def test_doctor_reports_faiss_dimension_mismatch(self) -> None:
        class Index:
            ntotal = 1
            d = 3

        class FakeFaiss:
            def read_index(self, path: str) -> Index:
                return Index()

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            db_path = self._create_dense_store(base)
            (base / "vectors.faiss").write_bytes(b"index")
            (base / "vector_ids.jsonl").write_text('{"unit_id": "u1"}\n', encoding="utf-8")
            report = doctor(db_path, faiss_loader=lambda: FakeFaiss())

        codes = {item["code"] for item in report["diagnoses"]}
        self.assertIn("faiss_index_dimension_mismatch", codes)

    def test_doctor_rejects_nonintegral_faiss_counts(self) -> None:
        for ntotal in (True, "1", 1.5, -1):
            with self.subTest(ntotal=ntotal), tempfile.TemporaryDirectory() as tmpdir:
                class Index:
                    d = 2

                index = Index()
                index.ntotal = ntotal

                class FakeFaiss:
                    def read_index(self, path: str) -> Index:
                        return index

                base = Path(tmpdir)
                db_path = self._create_dense_store(base)
                (base / "vectors.faiss").write_bytes(b"index")
                (base / "vector_ids.jsonl").write_text('{"unit_id": "u1"}\n', encoding="utf-8")
                report = doctor(db_path, faiss_loader=lambda: FakeFaiss())

            codes = {item["code"] for item in report["diagnoses"]}
            self.assertIn("faiss_index_invalid", codes)


def diagnostics_test_paragraph():
    from nihaisha_kg.pdf_vector import ParsedParagraph

    return ParsedParagraph(
        paragraph_id="p1", doc_id="doc", source_path="/tmp/doc.pdf", title="test",
        page_start=1, page_end=1, text="桂枝汤主之。",
    )


if __name__ == "__main__":
    unittest.main()
