from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
import time
from pathlib import Path

from .assets import DEFAULT_ASSET_DIR, download_assets
from .diagnostics import doctor as run_doctor
from .evaluation import evaluate_database, load_eval_cases
from .normalization import normalize_query_text
from .pdf_vector import (
    LocalVectorStore,
    answer_pdf_rag,
    augment_pdf_vector_store_questions,
    build_faiss_vector_index,
    build_pdf_vector_store,
    create_embedding_backend_for_db,
    load_faiss_module,
    logical_retrieval_channel,
    siliconflow_api_key_available,
)
from .rerank import (
    PUBLIC_RERANK_FEATURE_MAX_CHARS,
    PUBLIC_RERANK_MODEL_MAX_CHARS,
    SiliconFlowReranker,
    safe_rerank_metadata_value,
    sanitize_rerank_error,
    snapshot_rerank_outcome,
)


DEFAULT_DB = Path("data/pdf_rag_bge_m3/rag.sqlite")
DEFAULT_EVAL_CASES = Path("evals/golden_v1.jsonl")
TRACE_CHANNELS = frozenset({"vector", "text", "knowledge", "graph"})
TRACE_MAX_IDS = 50
MAX_PUBLIC_LIMIT = 100


def _trace_text(value: object, max_chars: int = 500) -> str:
    return sanitize_rerank_error(value, max_chars=max_chars)


def _dict_get(mapping: dict[str, object], key: str, default: object = None) -> object:
    try:
        return dict.get(mapping, key, default)
    except Exception:
        return default


def _json_fallback(value: object) -> str:
    return f"<{type(value).__name__}>"[:80]


def _bounded_latency_ms(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        parsed = float(value)
    except (OverflowError, TypeError, ValueError):
        return 0.0
    if not math.isfinite(parsed):
        return 0.0
    return round(max(0.0, min(parsed, 3_600_000.0)), 3)


def _search_trace(
    query: str,
    results: list[dict[str, object]],
    *,
    reranker_model: object,
    degraded_feature: object = "",
    latency_ms: float = 0.0,
) -> dict[str, object]:
    selected_ids: list[str] = []
    channels: set[str] = set()
    channel_ranks: list[dict[str, object]] = []
    for selected_rank, row in enumerate(results[:TRACE_MAX_IDS], start=1):
        paragraph_id = _trace_text(_dict_get(row, "paragraph_id", ""), max_chars=120)
        if paragraph_id:
            selected_ids.append(paragraph_id)
        entry: dict[str, object] = {"paragraph_id": paragraph_id}
        raw_ranks = _dict_get(row, "channel_ranks")
        if isinstance(raw_ranks, dict):
            normalized_ranks = {
                logical_retrieval_channel(channel): rank
                for channel, rank in raw_ranks.items()
                if logical_retrieval_channel(channel) in TRACE_CHANNELS
            }
            for channel in sorted(TRACE_CHANNELS):
                rank = normalized_ranks.get(channel)
                if isinstance(rank, int) and not isinstance(rank, bool) and 0 < rank <= 1_000_000:
                    entry[channel] = rank
                    channels.add(channel)
        raw_sources = _dict_get(row, "retrieval_sources")
        if type(raw_sources) in {list, tuple}:
            for source in raw_sources[:12]:
                channel = logical_retrieval_channel(source)
                if channel in TRACE_CHANNELS:
                    channels.add(channel)
                    entry.setdefault(channel, selected_rank)
        channel_ranks.append(entry)
    degraded = safe_rerank_metadata_value(
        degraded_feature,
        max_chars=PUBLIC_RERANK_FEATURE_MAX_CHARS,
    )
    return {
        "normalized_query": _trace_text(normalize_query_text(query), max_chars=500),
        "retrieval_channels": sorted(channels),
        "channel_ranks": channel_ranks,
        "selected_paragraph_ids": selected_ids,
        "reranker": safe_rerank_metadata_value(
            reranker_model,
            max_chars=PUBLIC_RERANK_MODEL_MAX_CHARS,
        ) or "none",
        "degraded_features": [degraded] if degraded else [],
        "latency_ms": {"search": _bounded_latency_ms(latency_ms)},
    }


def _print_cli_error(command: str, error: BaseException) -> int:
    message = sanitize_rerank_error(error, max_chars=240)
    print(f"{command} failed: {message or type(error).__name__}", file=sys.stderr)
    return 1


def _positive_limit(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("limit must be a positive integer")
    if value <= 0:
        raise ValueError("limit must be a positive integer")
    if value > MAX_PUBLIC_LIMIT:
        raise ValueError(f"limit must be a positive integer at most {MAX_PUBLIC_LIMIT}")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nihaisha-rag",
        description="Search and answer from the local Nihaisha PDF RAG database.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    stats = sub.add_parser("stats", help="show database counts")
    stats.add_argument("--db", type=Path, default=DEFAULT_DB)

    doctor = sub.add_parser("doctor", help="diagnose database and FAISS artifacts")
    doctor.add_argument("--db", type=Path, default=DEFAULT_DB)

    download = sub.add_parser(
        "download-assets",
        help="download and verify the public production RAG assets",
    )
    download.add_argument("--out", type=Path, default=DEFAULT_ASSET_DIR)
    download.add_argument(
        "--force",
        action="store_true",
        help="redownload assets even when an existing file passes verification",
    )

    evaluate = sub.add_parser("evaluate", help="evaluate retrieval against JSONL cases")
    evaluate.add_argument("--db", type=Path, default=DEFAULT_DB)
    evaluate.add_argument("--cases", type=Path, default=DEFAULT_EVAL_CASES)
    evaluate.add_argument(
        "--mode",
        choices=["hybrid", "vector", "text", "knowledge", "graph"],
        default="hybrid",
    )
    evaluate.add_argument("--limit", type=int, default=10)

    build = sub.add_parser("build", help="build a complete local PDF RAG database")
    build.add_argument("--pdf-dir", type=Path, required=True)
    build.add_argument("--out", type=Path, required=True)
    build.add_argument("--window-size", type=int, default=6)
    build.add_argument("--overlap", type=int, default=2)
    build.add_argument("--dims", type=int, default=2048)
    build.add_argument(
        "--embedding",
        choices=["sparse", "siliconflow", "local-bge-m3"],
        default="siliconflow",
    )
    build.add_argument("--model", default="BAAI/bge-m3")
    build.add_argument("--batch-size", type=int, default=32)
    build.add_argument("--trace-dir", type=Path, default=None)
    build.add_argument("--source-catalog", type=Path, default=None)
    build.add_argument(
        "--portable-source-paths",
        action="store_true",
        help="store logical pdfs/<basename> paths and generation-relative manifest paths",
    )

    augment_questions = sub.add_parser(
        "augment-questions",
        help="add paragraph question retrieval units to an existing database",
    )
    augment_questions.add_argument("--db", type=Path, default=DEFAULT_DB)
    augment_questions.add_argument(
        "--embedding",
        choices=["auto", "sparse", "siliconflow", "local-bge-m3"],
        default="auto",
    )
    augment_questions.add_argument("--model", default="BAAI/bge-m3")
    augment_questions.add_argument("--batch-size", type=int, default=32)

    text_index = sub.add_parser("rebuild-text-index", help="rebuild paragraph FTS index")
    text_index.add_argument("--db", type=Path, default=DEFAULT_DB)

    knowledge = sub.add_parser("rebuild-knowledge-units", help="rebuild grounded knowledge units")
    knowledge.add_argument("--db", type=Path, default=DEFAULT_DB)
    knowledge.add_argument("--trace-dir", type=Path, default=None)

    build_faiss = sub.add_parser("build-faiss", help="build FAISS index from stored dense vectors")
    build_faiss.add_argument("--db", type=Path, default=DEFAULT_DB)
    build_faiss.add_argument("--index", type=Path, default=None)
    build_faiss.add_argument("--ids", type=Path, default=None)
    build_faiss.add_argument("--batch-size", type=int, default=4096)

    guide_nodes = sub.add_parser(
        "rebuild-guide-nodes",
        help="rebuild source-grounded clinical guide nodes from original evidence",
    )
    guide_nodes.add_argument("--db", type=Path, default=DEFAULT_DB)

    search = sub.add_parser("search", help="search the local PDF RAG database")
    search.add_argument("query")
    search.add_argument("--db", type=Path, default=DEFAULT_DB)
    search.add_argument("--limit", type=int, default=5)
    search.add_argument(
        "--mode",
        choices=["hybrid", "vector", "text", "knowledge", "graph"],
        default="hybrid",
    )
    search.add_argument(
        "--embedding",
        choices=["auto", "sparse", "siliconflow", "local-bge-m3"],
        default="auto",
    )
    search.add_argument("--model", default="BAAI/bge-m3")
    search.add_argument("--batch-size", type=int, default=32)
    search.add_argument("--json", action="store_true")
    search.add_argument(
        "--reranker",
        choices=["auto", "none", "siliconflow"],
        default="auto",
    )
    search.add_argument("--rerank-model", default=None)
    search.add_argument("--trace", action="store_true")
    search.add_argument(
        "--include-references",
        action="store_true",
        help="include reference_secondary material and label it as external reference evidence",
    )

    answer = sub.add_parser("answer", help="answer with grounded citations")
    answer.add_argument("query")
    answer.add_argument("--db", type=Path, default=DEFAULT_DB)
    answer.add_argument("--limit", type=int, default=8)
    answer.add_argument(
        "--mode",
        choices=["hybrid", "vector", "text", "knowledge", "graph"],
        default="hybrid",
    )
    answer.add_argument(
        "--embedding",
        choices=["auto", "sparse", "siliconflow", "local-bge-m3"],
        default="auto",
    )
    answer.add_argument("--model", default="BAAI/bge-m3")
    answer.add_argument("--batch-size", type=int, default=32)
    answer.add_argument("--json", action="store_true")
    answer.add_argument(
        "--reranker",
        choices=["auto", "none", "siliconflow"],
        default="auto",
    )
    answer.add_argument("--rerank-model", default=None)
    answer.add_argument("--trace", action="store_true")
    answer.add_argument(
        "--include-references",
        action="store_true",
        help="include reference_secondary material and label it as external reference evidence",
    )

    args = parser.parse_args(argv)

    if args.command in {"search", "evaluate", "answer"}:
        try:
            args.limit = _positive_limit(args.limit)
        except (TypeError, ValueError) as exc:
            return _print_cli_error(args.command, exc)

    if args.command == "stats":
        store = LocalVectorStore(args.db)
        payload = store.stats()
        payload.update(store.read_meta())
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "doctor":
        try:
            report = run_doctor(args.db, faiss_loader=load_faiss_module)
        except (OSError, RuntimeError, ValueError, sqlite3.DatabaseError) as exc:
            return _print_cli_error("doctor", exc)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report.get("status") == "ok" else 1

    if args.command == "download-assets":
        try:
            payload = download_assets(args.out, force=args.force)
        except (OSError, RuntimeError, ValueError) as exc:
            return _print_cli_error("download-assets", exc)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "evaluate":
        try:
            cases = load_eval_cases(args.cases)
            if args.mode in {"text", "knowledge", "graph"}:
                store = LocalVectorStore(args.db)
            else:
                backend = create_embedding_backend_for_db(args.db)
                store = LocalVectorStore(args.db, embedding_backend=backend)
            payload = evaluate_database(store, cases, mode=args.mode, limit=args.limit)
        except (OSError, RuntimeError, TypeError, ValueError, sqlite3.DatabaseError) as exc:
            return _print_cli_error("evaluate", exc)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "build":
        payload = build_pdf_vector_store(
            pdf_dir=args.pdf_dir,
            out_dir=args.out,
            window_size=args.window_size,
            overlap=args.overlap,
            dims=args.dims,
            embedding=args.embedding,
            model=args.model,
            batch_size=args.batch_size,
            trace_dir=args.trace_dir,
            source_catalog_path=args.source_catalog,
            portable_source_paths=args.portable_source_paths,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "augment-questions":
        backend = create_embedding_backend_for_db(
            args.db,
            embedding=args.embedding,
            model=args.model,
            batch_size=args.batch_size,
        )
        payload = augment_pdf_vector_store_questions(args.db, embedding_backend=backend)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "rebuild-text-index":
        store = LocalVectorStore(args.db)
        print(json.dumps(store.rebuild_text_index(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "rebuild-knowledge-units":
        store = LocalVectorStore(args.db)
        trace_dir = args.trace_dir or (args.db.parent / "traces")
        print(json.dumps(store.rebuild_knowledge_units(trace_dir=trace_dir), ensure_ascii=False, indent=2))
        return 0

    if args.command == "build-faiss":
        payload = build_faiss_vector_index(
            args.db,
            index_path=args.index,
            ids_path=args.ids,
            batch_size=args.batch_size,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "rebuild-guide-nodes":
        store = LocalVectorStore(args.db)
        print(json.dumps(store.rebuild_guide_nodes(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "search":
        try:
            if args.mode in {"text", "knowledge", "graph"}:
                store = LocalVectorStore(args.db)
            else:
                backend = create_embedding_backend_for_db(
                    args.db,
                    embedding=args.embedding,
                    model=args.model,
                    batch_size=args.batch_size,
                )
                store = LocalVectorStore(args.db, embedding_backend=backend)
            started: float | None = None
            if args.json and args.trace:
                try:
                    clock_value = float(time.perf_counter())
                    if math.isfinite(clock_value):
                        started = clock_value
                except Exception:
                    started = None
            candidate_limit = max(args.limit * 3, 12) if args.reranker != "none" else args.limit
            if args.include_references:
                candidates = store.search(
                    args.query,
                    limit=candidate_limit,
                    mode=args.mode,
                    include_reference_secondary=True,
                )
            else:
                candidates = store.search(args.query, limit=candidate_limit, mode=args.mode)
            rerank_outcome = None
            if args.reranker == "siliconflow" or (
                args.reranker == "auto" and siliconflow_api_key_available()
            ):
                raw_rerank_outcome = SiliconFlowReranker(model=args.rerank_model).rerank(
                    args.query,
                    candidates,
                    limit=args.limit,
                )
                rerank_outcome = snapshot_rerank_outcome(
                    raw_rerank_outcome,
                    limit=args.limit,
                )
                results = rerank_outcome.results
            else:
                results = list(candidates[: args.limit])
        except (OSError, RuntimeError, TypeError, ValueError, sqlite3.DatabaseError) as exc:
            return _print_cli_error("search", exc)
        elapsed_ms = 0.0
        if started is not None:
            try:
                elapsed_ms = _bounded_latency_ms(
                    (float(time.perf_counter()) - started) * 1000.0
                )
            except Exception:
                elapsed_ms = 0.0
        if args.json:
            payload: object = results
            if args.trace:
                payload = {
                    "results": results,
                    "trace": _search_trace(
                        args.query,
                        results,
                        reranker_model=(rerank_outcome.model if rerank_outcome else "none"),
                        degraded_feature=(
                            rerank_outcome.degraded_feature if rerank_outcome else ""
                        ),
                        latency_ms=elapsed_ms,
                    ),
                }
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_fallback))
            return 0
        for index, item in enumerate(results, start=1):
            print(
                f"[{index}] score={item['score']} "
                f"sources={','.join(item.get('retrieval_sources', []))} "
                f"{Path(str(item['source_path'])).name} p{item['page_start']}"
            )
            for unit in item.get("matched_knowledge_units", [])[:3]:
                print(
                    "knowledge: "
                    f"{unit['unit_type']} | {unit['subject']} | {unit['predicate']} | {unit['object']}"
                )
            print(str(item["text"])[:500])
            print()
        return 0

    if args.command == "answer":
        try:
            answer_options = (
                {"include_reference_secondary": True} if args.include_references else {}
            )
            payload = answer_pdf_rag(
                args.query,
                db_path=args.db,
                limit=args.limit,
                mode=args.mode,
                embedding=args.embedding,
                model=args.model,
                batch_size=args.batch_size,
                reranker=args.reranker,
                rerank_model=args.rerank_model,
                trace_enabled=args.trace,
                **answer_options,
            )
        except (OSError, RuntimeError, TypeError, ValueError, sqlite3.DatabaseError) as exc:
            return _print_cli_error("answer", exc)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        answer_text = str(payload["answer"])
        print(answer_text)
        if payload.get("safety_notice"):
            print()
            print(f"安全边界：{payload['safety_notice']}")
        flow = payload.get("differentiation_flow") or {}
        if flow.get("mermaid"):
            print()
            print("辨证流程图：")
            print(str(flow["mermaid"]))
        if payload.get("followup_questions"):
            print()
            print("关键追问：")
            for question in payload.get("followup_questions", []):
                print(f"- {question}")
        print()
        print("引用：")
        for citation in payload.get("citations", []):
            print(f"[{citation['index']}] {citation['label']}")
            print(str(citation["evidence_quote"])[:260])
            evidence_id = str(citation.get("evidence_id", "")).strip()
            paragraph_id = str(citation.get("paragraph_id", "")).strip()
            index_parts = [
                part
                for part in (
                    f"evidence_id={evidence_id}" if evidence_id else "",
                    f"paragraph_id={paragraph_id}" if paragraph_id else "",
                )
                if part
            ]
            if index_parts:
                print(f"索引：{'；'.join(index_parts)}")
            context = citation.get("context_navigation") or {}
            if isinstance(context, dict):
                previous = context.get("previous")
                following = context.get("next")
                if isinstance(previous, dict) and previous.get("label"):
                    print(
                        f"上文：{previous['label']} "
                        f"({previous.get('evidence_id', '')})"
                    )
                if isinstance(following, dict) and following.get("label"):
                    print(
                        f"下文：{following['label']} "
                        f"({following.get('evidence_id', '')})"
                    )
            provenance = citation.get("retrieval_provenance") or {}
            if isinstance(provenance, dict):
                channels = provenance.get("channels") or []
                if isinstance(channels, list) and channels:
                    print(f"检索路径：{', '.join(str(channel) for channel in channels)}")
        linked_references = payload.get("linked_reference_materials", []) or []
        if linked_references:
            print()
            print("课程提到的关联资料（非倪海厦著作）：")
            for material in linked_references[:12]:
                print(f"- {material.get('title') or Path(str(material.get('source_path', ''))).stem}")
                relation_label = str(material.get("relation_label", "")).strip()
                edition_label = str(material.get("edition_label", "")).strip()
                if relation_label:
                    print(f"  关联类型：{relation_label}")
                if edition_label:
                    print(f"  版本状态：{edition_label}")
                trigger = material.get("trigger") or {}
                trigger_label = str(trigger.get("citation_label", "")).strip()
                if trigger_label:
                    print(f"  课程依据：{trigger_label}")
        related_units = payload.get("related_knowledge_units", []) or []
        if related_units:
            print()
            print("关联知识点：")
            for unit in related_units[:8]:
                label = str(unit.get("label", "")).strip()
                if label:
                    print(f"- 来源：{label}")
                print(
                    f"  {unit.get('unit_type')} | {unit.get('subject')} | "
                    f"{unit.get('predicate')} | {unit.get('object')}"
                )
                quote = str(unit.get("evidence_quote", "")).strip()
                if quote:
                    print(f"  原文线索：{quote[:180]}")
        guide_nodes = payload.get("related_guide_nodes", []) or []
        if guide_nodes:
            print()
            print("关联导图节点：")
            for node in guide_nodes[:6]:
                print(f"- {node.get('badge') or node.get('node_type')} | {node.get('path')}")
                content = str(node.get("content", "")).strip()
                if content:
                    print(f"  导图摘要：{content[:180]}")
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2
