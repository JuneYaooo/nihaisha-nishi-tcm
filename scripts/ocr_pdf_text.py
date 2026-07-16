#!/usr/bin/env python3
"""Extract resumable page-level OCR text from scanned Chinese PDFs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any


MODEL_CONFIGS = {
    "v5-mobile": {
        "det": "PP-OCRv5_mobile_det",
        "rec": "PP-OCRv5_mobile_rec",
    },
    "v6-tiny": {
        "det": "PP-OCRv6_tiny_det",
        "rec": "PP-OCRv6_tiny_rec",
    },
}

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
MOBILE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
ACCOUNT_RE = re.compile(r"QQ|微信号|私人微信|加我QQ|联系我|发邮件")
PROMOTION_RE = re.compile(r"下载.*资料|关注.*公众|购买正版|推广|加我|联系方式")
RESOURCE_WATERMARK_LINE_RE = re.compile(
    r"更多相关资源|相关资源请访问|hbtmxy|[kK][l1]rs999"
)
LABELED_PHONE_RE = re.compile(r"((?:电话|手机|联系电话)\s*[:：]?\s*)[\d\- ]{7,}")
URL_TOKEN_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
EXCLUDED_PRIVACY_TEXT = (
    "[非正文页已排除] OCR 检测到资料推广或联系方式；"
    "为保护隐私且避免无关内容进入检索，公开证据不保存原文。"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Scanned PDF to OCR")
    parser.add_argument("--doc-id", required=True, help="Stable PDF document ID")
    parser.add_argument("--output", required=True, type=Path, help="Resumable JSONL output")
    parser.add_argument("--model", choices=MODEL_CONFIGS, default="v6-tiny")
    parser.add_argument("--model-root", type=Path, default=Path.home() / ".paddlex/official_models")
    parser.add_argument("--render-scale", type=float, default=1.5)
    parser.add_argument("--det-limit", type=int, default=960)
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument("--end-page", type=int)
    parser.add_argument("--progress-every", type=int, default=10)
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args()


def load_completed_pages(path: Path, doc_id: str) -> set[int]:
    completed: set[int] = set()
    if not path.exists():
        return completed
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("doc_id") != doc_id:
                raise ValueError(f"Unexpected doc_id at {path}:{line_number}")
            completed.add(int(record["page"]))
    return completed


def unwrap_result(result: Any) -> dict[str, Any]:
    data = result.json if hasattr(result, "json") else result
    if callable(data):
        data = data()
    if isinstance(data, dict) and "res" in data:
        data = data["res"]
    if not isinstance(data, dict):
        raise TypeError(f"Unexpected PaddleOCR result: {type(data)!r}")
    return data


def privacy_flags(text: str) -> list[str]:
    flags = []
    for label, pattern in (
        ("email", EMAIL_RE),
        ("url", URL_RE),
        ("mobile", MOBILE_RE),
        ("account_label", ACCOUNT_RE),
        ("promotion", PROMOTION_RE),
    ):
        if pattern.search(text):
            flags.append(label)
    return flags


def clean_ocr_text(text: str) -> str:
    lines = [
        line.rstrip()
        for line in text.splitlines()
        if not RESOURCE_WATERMARK_LINE_RE.search(line)
    ]
    cleaned = "\n".join(lines).strip()
    cleaned = LABELED_PHONE_RE.sub(r"\1[已隐去]", cleaned)
    return URL_TOKEN_RE.sub("[链接已移除]", cleaned)


def should_exclude_for_privacy(flags: list[str]) -> bool:
    flag_set = set(flags)
    has_identifier = bool(flag_set & {"email", "url", "mobile", "account_label"})
    return has_identifier and bool(flag_set & {"account_label", "promotion"})


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> int:
    args = parse_args()
    if args.start_page < 1:
        raise ValueError("--start-page must be at least 1")
    if args.progress_every < 1:
        raise ValueError("--progress-every must be at least 1")

    try:
        import fitz
        import numpy as np
        from paddleocr import PaddleOCR
    except ImportError as exc:
        raise SystemExit(f"Missing OCR dependency: {exc}") from exc

    model = MODEL_CONFIGS[args.model]
    det_dir = args.model_root / model["det"]
    rec_dir = args.model_root / model["rec"]
    for model_dir in (det_dir, rec_dir):
        if not model_dir.exists():
            raise FileNotFoundError(f"OCR model directory not found: {model_dir}")

    completed = set() if args.no_resume else load_completed_pages(args.output, args.doc_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if args.no_resume else "a"

    ocr = PaddleOCR(
        text_detection_model_name=model["det"],
        text_detection_model_dir=str(det_dir),
        text_recognition_model_name=model["rec"],
        text_recognition_model_dir=str(rec_dir),
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        text_det_limit_side_len=args.det_limit,
    )

    pdf = fitz.open(args.input)
    end_page = min(args.end_page or pdf.page_count, pdf.page_count)
    selected_pages = list(range(args.start_page, end_page + 1))
    pending_pages = [page for page in selected_pages if page not in completed]
    started = time.perf_counter()
    processed = 0
    excluded = 0

    print(
        json.dumps(
            {
                "event": "start",
                "doc_id": args.doc_id,
                "model": args.model,
                "physical_pages": pdf.page_count,
                "selected_pages": len(selected_pages),
                "already_completed": len(selected_pages) - len(pending_pages),
                "pending_pages": len(pending_pages),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

    with args.output.open(mode, encoding="utf-8") as output:
        for page_number in pending_pages:
            page_started = time.perf_counter()
            page = pdf[page_number - 1]
            pixmap = page.get_pixmap(
                matrix=fitz.Matrix(args.render_scale, args.render_scale),
                alpha=False,
            )
            image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
                pixmap.height,
                pixmap.width,
                pixmap.n,
            )
            result = list(ocr.predict(image))[0]
            data = unwrap_result(result)
            texts = [str(text).strip() for text in data.get("rec_texts", []) if str(text).strip()]
            scores = [float(score) for score in data.get("rec_scores", [])]
            text = clean_ocr_text("\n".join(texts))
            flags = privacy_flags(text)
            page_kind = "ocr"
            original_hash = None
            if should_exclude_for_privacy(flags):
                original_hash = text_hash(text)
                text = EXCLUDED_PRIVACY_TEXT
                page_kind = "excluded"
                excluded += 1
            elif not text:
                page_kind = "ocr-empty"

            record = {
                "doc_id": args.doc_id,
                "page": page_number,
                "page_kind": page_kind,
                "text": text,
                "line_count": len(texts),
                "mean_confidence": (sum(scores) / len(scores)) if scores else None,
                "min_confidence": min(scores) if scores else None,
                "privacy_flags": flags,
                **({"excluded_text_sha256": original_hash} if original_hash else {}),
                "ocr_model": args.model,
                "render_scale": args.render_scale,
                "seconds": round(time.perf_counter() - page_started, 3),
            }
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
            output.flush()
            processed += 1

            if processed % args.progress_every == 0 or processed == len(pending_pages):
                os.fsync(output.fileno())
                elapsed = time.perf_counter() - started
                print(
                    json.dumps(
                        {
                            "event": "progress",
                            "doc_id": args.doc_id,
                            "page": page_number,
                            "processed": processed,
                            "pending_total": len(pending_pages),
                            "pages_per_minute": round(processed / elapsed * 60, 2),
                            "eta_minutes": round(
                                (len(pending_pages) - processed) / (processed / elapsed) / 60,
                                1,
                            ),
                            "excluded_pages": excluded,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )

    elapsed = time.perf_counter() - started
    print(
        json.dumps(
            {
                "event": "complete",
                "doc_id": args.doc_id,
                "processed": processed,
                "elapsed_minutes": round(elapsed / 60, 2),
                "excluded_pages": excluded,
                "output": str(args.output),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
