#!/usr/bin/env python3
"""Search complete page-level PDF evidence cards."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


SAFETY_NOTICE = (
    "安全提示：以下仅为PDF证据定位。涉及剂量、煎服、针灸、放血、外敷、"
    "急症或毒烈药内容时，不得作为个人医疗建议或自行操作依据。"
)
HIGH_RISK_RE = re.compile(
    r"剂量|煎|服|内服|外敷|处方|抓药|下针|针刺|刺破|放血|火罐|艾灸|灸|"
    r"附子|乌头|细辛|硫磺|巴豆|甘遂|大戟|芫花|水蛭|虻虫|朱砂|雄黄|铅丹|砒|"
    r"癌|肿瘤|急救|中毒|毒蛇|破伤风"
)
FOLDED_NOTICE = (
    "[高风险内容已折叠：原摘录涉及可执行医疗、方药、针灸或急重症细节；"
    "默认只用于定位证据，不展开为操作说明。]"
)


def iter_cards(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def card_text(card: dict) -> str:
    """Read the complete page text while remaining compatible with legacy cards."""
    return card.get("text", card.get("excerpt", ""))


def load_module_indexes(path: Path, module: str | None) -> list[dict]:
    if path.is_file():
        return [json.loads(path.read_text(encoding="utf-8"))]
    if not path.exists():
        return []
    if module:
        module_path = path / f"{module}.json"
        return [json.loads(module_path.read_text(encoding="utf-8"))] if module_path.exists() else []
    indexes = []
    for item in sorted(path.glob("*.json")):
        if item.name != "index.json":
            indexes.append(json.loads(item.read_text(encoding="utf-8")))
    return indexes


def load_term_hits(path: Path, terms: list[str], module: str | None) -> dict[str, list[dict]]:
    hits = {term: [] for term in terms}
    for index in load_module_indexes(path, module):
        for term in terms:
            hits[term].extend(index.get(term, {}).get("citations", []))
    return hits


def safe_excerpt(text: str, show_excerpt: bool) -> str:
    if show_excerpt or not HIGH_RISK_RE.search(text):
        return text
    return FOLDED_NOTICE


def main() -> int:
    parser = argparse.ArgumentParser(description="Search references/pdf-evidence/evidence-cards.jsonl")
    parser.add_argument("terms", nargs="+", help="Chinese terms to search, e.g. 大青龙汤 荥穴")
    parser.add_argument("--evidence-dir", default="references/pdf-evidence", help="PDF evidence directory")
    parser.add_argument("--limit", type=int, default=10, help="Maximum rows to print; use 0 for all matches")
    parser.add_argument("--module", help="Optional module index, e.g. shanghan, bencao, acupuncture")
    parser.add_argument(
        "--show-excerpt",
        "--show-full-page",
        dest="show_full_page",
        action="store_true",
        help="Print the complete stored page text for manual scholarly verification.",
    )
    args = parser.parse_args()

    evidence_dir = Path(args.evidence_dir)
    cards_path = evidence_dir / "evidence-cards.jsonl"
    term_index_path = evidence_dir / "term-index"
    terms = [term.strip() for term in args.terms if term.strip()]
    term_hits = load_term_hits(term_index_path, terms, args.module)
    print(SAFETY_NOTICE)

    shown = 0
    for card in iter_cards(cards_path):
        if args.module and card.get("module") != args.module:
            continue
        full_page_text = card_text(card)
        haystack = "\n".join(
            [
                card.get("source_name", ""),
                full_page_text,
                " ".join(card.get("terms", [])),
            ]
        )
        if all(term in haystack for term in terms):
            print(f"{card['citation']} {card['source_name']} {card['locator']}")
            snippets = []
            for term in terms:
                for hit in term_hits.get(term, []):
                    if hit.get("card_id") == card.get("card_id") and hit.get("snippet"):
                        snippets.append(safe_excerpt(hit["snippet"], args.show_full_page))
                        break
            if args.show_full_page:
                result_text = safe_excerpt(full_page_text, True)
            elif snippets:
                result_text = " / ".join(snippets)
            else:
                result_text = safe_excerpt(full_page_text, False)
            print(result_text)
            print()
            shown += 1
            if args.limit > 0 and shown >= args.limit:
                break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
