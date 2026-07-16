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
    r"剂量|劑量|煎|服|内服|內服|外敷|处方|處方|抓药|抓藥|汤|湯|"
    r"下针|下針|针刺|針刺|刺破|放血|火罐|艾灸|灸|"
    r"附子|乌头|烏頭|细辛|細辛|硫磺|巴豆|甘遂|大戟|芫花|水蛭|虻虫|虻蟲|"
    r"朱砂|雄黄|雄黃|铅丹|鉛丹|砒|癌|肿瘤|腫瘤|急救|中毒|毒蛇|破伤风|破傷風"
)
FOLDED_NOTICE = (
    "[高风险内容已折叠：原摘录涉及可执行医疗、方药、针灸或急重症细节；"
    "默认只用于定位证据，不展开为操作说明。]"
)
SUPPLEMENT_ROLE = "ni-recommended-supplement"
SUPPLEMENT_LABEL = "倪师推荐补充资料（非倪师本人资料）"
AUTO_SUPPLEMENT_NOTICE = "二次检索：课程主资料已命中，以下自动补充倪师推荐资料。"


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


def is_supplement(card: dict) -> bool:
    return card.get("source_role") == SUPPLEMENT_ROLE


def should_show_supplements(
    *,
    primary_matches: int,
    supplement_matches: int,
    force_include: bool,
    primary_only: bool,
) -> bool:
    if primary_only or supplement_matches == 0:
        return False
    return force_include or primary_matches > 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Search references/pdf-evidence/evidence-cards.jsonl")
    parser.add_argument("terms", nargs="+", help="Chinese terms to search, e.g. 大青龙汤 荥穴")
    parser.add_argument("--evidence-dir", default="references/pdf-evidence", help="PDF evidence directory")
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum rows per evidence layer; use 0 for all matches",
    )
    parser.add_argument("--module", help="Optional module index, e.g. shanghan, bencao, acupuncture")
    parser.add_argument("--doc-id", help="Optional stable document ID from source-manifest.json")
    layer_group = parser.add_mutually_exclusive_group()
    layer_group.add_argument(
        "--include-supplements",
        action="store_true",
        help="Force supplemental-book results even when no primary course evidence matches.",
    )
    layer_group.add_argument(
        "--primary-only",
        action="store_true",
        help="Disable the default supplemental second-pass search.",
    )
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

    primary_matches = []
    supplement_matches = []
    for card in iter_cards(cards_path):
        if args.module and card.get("module") != args.module:
            continue
        if args.doc_id and card.get("doc_id") != args.doc_id:
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
            (supplement_matches if is_supplement(card) else primary_matches).append(card)

    def limited(cards: list[dict]) -> list[dict]:
        return cards if args.limit == 0 else cards[: args.limit]

    def print_card(card: dict) -> None:
        full_page_text = card_text(card)
        if is_supplement(card):
            print(f"来源层级：{SUPPLEMENT_LABEL}")
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

    for card in limited(primary_matches):
        print_card(card)

    show_supplements = should_show_supplements(
        primary_matches=len(primary_matches),
        supplement_matches=len(supplement_matches),
        force_include=args.include_supplements,
        primary_only=args.primary_only,
    )
    if show_supplements:
        if not args.include_supplements:
            print(AUTO_SUPPLEMENT_NOTICE)
        for card in limited(supplement_matches):
            print_card(card)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
