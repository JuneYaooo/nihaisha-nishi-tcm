from __future__ import annotations

import io
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from nihaisha_kg import pdf_vector
from nihaisha_kg import cli as rag_cli


class RuntimeKnowledgeStructureTests(unittest.TestCase):
    def test_graph_search_uses_only_accepted_grounded_relations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "rag.sqlite"
            with sqlite3.connect(store_path) as conn:
                conn.executescript(
                    """
                    CREATE TABLE paragraphs (
                      paragraph_id TEXT PRIMARY KEY, doc_id TEXT, source_path TEXT,
                      title TEXT, page_start INTEGER, page_end INTEGER, text TEXT
                    );
                    CREATE TABLE documents (
                      document_id TEXT PRIMARY KEY, canonical_title TEXT,
                      source_layer TEXT, logical_source_path TEXT
                    );
                    CREATE TABLE evidence_records (
                      evidence_id TEXT PRIMARY KEY, document_id TEXT,
                      paragraph_id TEXT, locator TEXT, original_text TEXT,
                      previous_evidence_id TEXT, next_evidence_id TEXT
                    );
                    CREATE TABLE entities (
                      entity_id TEXT PRIMARY KEY, entity_type TEXT,
                      canonical_name TEXT, normalized_key TEXT
                    );
                    CREATE TABLE relations (
                      relation_id TEXT PRIMARY KEY, subject_entity_id TEXT,
                      predicate TEXT, object_entity_id TEXT, literal_value TEXT,
                      evidence_id TEXT, evidence_quote TEXT, source_layer TEXT, confidence REAL,
                      extraction_method TEXT, extractor_version TEXT,
                      review_status TEXT
                    );
                    """
                )
                conn.execute(
                    "INSERT INTO paragraphs VALUES ('p1','d1','pdfs/课程讲义.pdf','课程讲义',12,12,'太阳中风，桂枝汤主之。')"
                )
                conn.execute(
                    "INSERT INTO documents VALUES ('d1','课程讲义','course_primary','pdfs/课程讲义.pdf')"
                )
                conn.execute(
                    "INSERT INTO evidence_records VALUES ('ev1','d1','p1','p12','太阳中风，桂枝汤主之。',NULL,NULL)"
                )
                conn.executemany(
                    "INSERT INTO entities VALUES (?, 'formula', ?, ?)",
                    [("e1", "桂枝汤", "桂枝汤"), ("e2", "渴欲饮", "渴欲饮")],
                )
                conn.executemany(
                    "INSERT INTO relations VALUES (?, ?, 'indicates_pattern', NULL, ?, 'ev1', '太阳中风，桂枝汤主之。', 'course_primary', 0.8, 'legacy', 'v1', ?)",
                    [
                        ("r1", "e1", "太阳中风", "auto_accepted"),
                        ("r2", "e1", "不应返回", "rejected"),
                        ("r3", "e2", "候选噪声", "needs_review"),
                    ],
                )

            store = pdf_vector.LocalVectorStore(store_path)
            accepted = store.search_graph_relations("桂枝汤怎么理解", limit=5)
            ambiguous = store.search_graph_relations("渴欲饮", limit=5)

        self.assertEqual([row["paragraph_id"] for row in accepted], ["p1"])
        self.assertEqual(accepted[0]["retrieval_sources"], ["graph"])
        self.assertEqual(accepted[0]["matched_graph_relations"][0]["relation_id"], "r1")
        self.assertEqual(accepted[0]["text"], "太阳中风，桂枝汤主之。")
        self.assertEqual(ambiguous, [])

    def test_hybrid_fusion_includes_low_weight_graph_channel(self) -> None:
        store = pdf_vector.LocalVectorStore(Path("unused.sqlite"))
        graph_result = {
            "paragraph_id": "graph-p",
            "score": 0.8,
            "retrieval_sources": ["graph"],
            "matched_graph_relations": [{"relation_id": "r1"}],
        }
        with (
            patch.object(store, "search_vector", return_value=[]),
            patch.object(store, "search_text", return_value=[]),
            patch.object(store, "search_knowledge_units", return_value=[]),
            patch.object(store, "search_graph_relations", return_value=[graph_result]),
        ):
            results = store.search_hybrid("桂枝汤", limit=3)

        self.assertEqual(results[0]["paragraph_id"], "graph-p")
        self.assertEqual(results[0]["channel_ranks"], {"graph": 1})
        self.assertEqual(results[0]["matched_graph_relations"], [{"relation_id": "r1"}])

    def test_graph_is_a_public_search_mode_without_embedding(self) -> None:
        class FakeStore:
            def __init__(self, *_args: object, **_kwargs: object) -> None:
                pass

            def search(self, query: str, limit: int, mode: str) -> list[dict[str, object]]:
                self.call = (query, limit, mode)
                return []

        stdout = io.StringIO()
        with (
            patch("nihaisha_kg.cli.LocalVectorStore", FakeStore),
            patch("nihaisha_kg.cli.create_embedding_backend_for_db") as backend,
            redirect_stdout(stdout),
        ):
            status = rag_cli.main(
                ["search", "桂枝汤", "--mode", "graph", "--json", "--reranker", "none"]
            )

        self.assertEqual(status, 0)
        self.assertEqual(stdout.getvalue().strip(), "[]")
        backend.assert_not_called()

    def test_graph_answer_stays_on_original_entity_without_followup_expansion(self) -> None:
        graph_quote = "太阳病，头痛发热，无汗而喘者，麻黄汤主之。"
        result = {
            "paragraph_id": "p-mahuang",
            "doc_id": "d1",
            "source_path": "pdfs/课程讲义.pdf",
            "title": "课程讲义",
            "page_start": 53,
            "page_end": 53,
            "text": "前文讲解。" * 80 + graph_quote,
            "score": 0.82,
            "retrieval_sources": ["graph"],
            "matched_graph_relations": [
                {
                    "entity_name": "麻黄汤",
                    "predicate": "indicates_pattern",
                    "literal_value": "太阳中风方证",
                    "evidence_quote": graph_quote,
                    "review_status": "auto_accepted",
                }
            ],
            "matched_knowledge_units": [],
            "matched_units": [],
            "matched_text_terms": [],
            "unit_types": [],
        }

        class FakeStore:
            def __init__(self, *_args: object, **_kwargs: object) -> None:
                self.queries: list[str] = []

            def search(self, query: str, limit: int, mode: str) -> list[dict[str, object]]:
                self.queries.append(query)
                return [result]

            def search_guide_nodes(self, *_args: object, **_kwargs: object) -> list[dict[str, object]]:
                return []

        with (
            patch("nihaisha_kg.pdf_vector.LocalVectorStore", FakeStore),
            patch("nihaisha_kg.pdf_vector.build_query_plan", side_effect=AssertionError("no graph expansion")),
        ):
            answer = pdf_vector.answer_pdf_rag(
                "麻黄汤对应什么方证？",
                Path("unused.sqlite"),
                mode="graph",
                limit=3,
                reranker="none",
            )

        self.assertEqual([item["paragraph_id"] for item in answer["citations"]], ["p-mahuang"])
        self.assertEqual(answer["citations"][0]["evidence_quote"], graph_quote)
        self.assertIn("麻黄汤主之", answer["citations"][0]["paragraph_text"])

    def test_knowledge_relations_returns_grounded_non_rejected_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Path(tmpdir) / "rag.sqlite"
            with sqlite3.connect(store) as conn:
                conn.executescript(
                    """
                    CREATE TABLE documents (
                      document_id TEXT PRIMARY KEY, canonical_title TEXT,
                      source_layer TEXT, logical_source_path TEXT
                    );
                    CREATE TABLE evidence_records (
                      evidence_id TEXT PRIMARY KEY, document_id TEXT,
                      paragraph_id TEXT, locator TEXT, original_text TEXT,
                      previous_evidence_id TEXT, next_evidence_id TEXT
                    );
                    CREATE TABLE entities (
                      entity_id TEXT PRIMARY KEY, entity_type TEXT,
                      canonical_name TEXT, normalized_key TEXT
                    );
                    CREATE TABLE relations (
                      relation_id TEXT PRIMARY KEY, subject_entity_id TEXT,
                      predicate TEXT, object_entity_id TEXT, literal_value TEXT,
                      evidence_id TEXT, source_layer TEXT, confidence REAL,
                      extraction_method TEXT, extractor_version TEXT,
                      review_status TEXT
                    );
                    """
                )
                conn.execute(
                    "INSERT INTO documents VALUES ('d1','课程讲义','course_primary','pdfs/课程讲义.pdf')"
                )
                conn.execute(
                    "INSERT INTO evidence_records VALUES ('ev1','d1','p1','p12','太阳中风，桂枝汤主之。',NULL,NULL)"
                )
                conn.execute(
                    "INSERT INTO entities VALUES ('e1','formula','桂枝汤','桂枝汤')"
                )
                conn.executemany(
                    "INSERT INTO relations VALUES (?, 'e1', ?, NULL, ?, 'ev1', 'course_primary', 0.8, 'legacy', 'v1', ?)",
                    [
                        ("r1", "indicates_pattern", "太阳中风", "needs_review"),
                        ("r2", "supported_by", "不应返回", "rejected"),
                    ],
                )

            relations = pdf_vector.knowledge_relations(store, "桂枝汤")

        self.assertEqual(len(relations), 1)
        self.assertEqual(relations[0]["predicate"], "indicates_pattern")
        self.assertEqual(relations[0]["paragraph_text"], "太阳中风，桂枝汤主之。")
        self.assertEqual(relations[0]["source_layer"], "course_primary")
        self.assertEqual(relations[0]["source_path"], "pdfs/课程讲义.pdf")
        self.assertEqual(relations[0]["review_status"], "needs_review")

    def test_knowledge_relations_is_compatible_with_legacy_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Path(tmpdir) / "rag.sqlite"
            with sqlite3.connect(store) as conn:
                conn.execute("CREATE TABLE paragraphs (paragraph_id TEXT)")
            self.assertEqual(pdf_vector.knowledge_relations(store, "桂枝汤"), [])

    def test_citations_include_complete_paragraph_and_context_ids(self) -> None:
        paragraph = "太阳中风，桂枝汤主之。其原始段落可完整展开。"
        citations = pdf_vector.build_citations(
            [
                {
                    "paragraph_id": "p1",
                    "source_path": "pdfs/课程讲义.pdf",
                    "title": "课程讲义",
                    "page_start": 12,
                    "page_end": 12,
                    "text": paragraph,
                    "previous_evidence_id": "ev0",
                    "next_evidence_id": "ev2",
                }
            ]
        )

        self.assertEqual(citations[0]["paragraph_text"], paragraph)
        self.assertEqual(citations[0]["previous_evidence_id"], "ev0")
        self.assertEqual(citations[0]["next_evidence_id"], "ev2")
        self.assertLessEqual(len(str(citations[0]["evidence_quote"])), 220)


if __name__ == "__main__":
    unittest.main()
