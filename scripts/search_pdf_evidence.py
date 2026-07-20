#!/usr/bin/env python3
"""Search complete PDF pages and supplemental text-evidence sections."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


SAFETY_NOTICE = (
    "安全提示：以下仅为文献证据定位。涉及剂量、煎服、针灸、放血、外敷、"
    "急症或毒烈药内容时，不得作为个人医疗建议或自行操作依据。"
)
ACTIONABLE_RISK_RE = re.compile(
    r"剂量|劑量|煎服|煎煮|内服|內服|外敷|处方|處方|抓药|抓藥|"
    r"下针|下針|针刺|針刺|刺破|放血|火罐|艾灸|灸法|"
    r"用法用量|每日\s*\d|一日\s*\d|\d+(?:\.\d+)?\s*(?:克|钱|錢|两|兩|毫升|ml)"
)
SENTENCE_RE = re.compile(r"[^\n。！？!?；;]+(?:[。！？!?；;]|$)")
FOLDED_NOTICE = (
    "[高风险内容已折叠：原摘录涉及可执行医疗、方药、针灸或急重症细节；"
    "默认只用于定位证据，不展开为操作说明。]"
)
SUPPLEMENT_ROLE = "ni-recommended-supplement"
SUPPLEMENT_LABEL = "倪师推荐补充资料（非倪师本人资料）"
AUTO_SUPPLEMENT_NOTICE = "二次检索：课程主资料已命中，以下自动补充倪师推荐资料。"


def iter_cards(path: Path):
    if not path.exists():
        return
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
    """Keep safe source sentences visible and fold only actionable instructions."""
    if show_excerpt or not ACTIONABLE_RISK_RE.search(text):
        return text
    visible: list[str] = []
    folded = False
    for match in SENTENCE_RE.finditer(text):
        sentence = match.group(0).strip()
        if not sentence:
            continue
        if ACTIONABLE_RISK_RE.search(sentence):
            if not folded:
                visible.append(FOLDED_NOTICE)
                folded = True
            continue
        visible.append(sentence)
    return " ".join(visible) if visible else FOLDED_NOTICE


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


def find_matches(
    card_paths: list[Path],
    terms: list[str],
    *,
    module: str | None = None,
    doc_id: str | None = None,
) -> tuple[list[dict], list[dict]]:
    """Return primary and recommended-supplement hits across evidence formats."""
    primary_matches = []
    supplement_matches = []
    for cards_path in card_paths:
        for card in iter_cards(cards_path):
            if module and card.get("module") != module:
                continue
            if doc_id and card.get("doc_id") != doc_id:
                continue
            full_text = card_text(card)
            haystack = "\n".join(
                [
                    card.get("source_name", ""),
                    card.get("archive_name", ""),
                    " ".join(card.get("aliases", [])),
                    card.get("locator", ""),
                    full_text,
                    " ".join(card.get("terms", [])),
                ]
            )
            if all(term in haystack for term in terms):
                (supplement_matches if is_supplement(card) else primary_matches).append(card)
    return primary_matches, supplement_matches


def limit_matches(cards: list[dict], limit: int, *, diversify_sources: bool = False) -> list[dict]:
    """Apply a row limit, optionally surfacing one hit per source before repeats."""
    if limit == 0 or len(cards) <= limit:
        return cards
    if not diversify_sources:
        return cards[:limit]
    selected = []
    selected_ids = set()
    seen_docs = set()
    for card in cards:
        doc_id = card.get("doc_id")
        if doc_id in seen_docs:
            continue
        selected.append(card)
        selected_ids.add(card.get("card_id", card.get("citation")))
        seen_docs.add(doc_id)
        if len(selected) == limit:
            return selected
    for card in cards:
        card_id = card.get("card_id", card.get("citation"))
        if card_id in selected_ids:
            continue
        selected.append(card)
        if len(selected) == limit:
            break
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("terms", nargs="+", help="Chinese terms to search, e.g. 大青龙汤 荥穴")
    parser.add_argument(
        "--evidence-dir", default="references/pdf-evidence", help="PDF evidence directory"
    )
    parser.add_argument(
        "--text-evidence-dir",
        default="references/text-evidence",
        help="Supplemental section-level text evidence directory",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum rows per evidence layer; use 0 for all matches",
    )
    parser.add_argument(
        "--module", help="Optional module index, e.g. shanghan, bencao, acupuncture"
    )
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
        help="Print the complete stored page or section text for scholarly verification.",
    )
    args = parser.parse_args()

    evidence_dir = Path(args.evidence_dir)
    cards_path = evidence_dir / "evidence-cards.jsonl"
    text_cards_path = Path(args.text_evidence_dir) / "evidence-cards.jsonl"
    term_index_path = evidence_dir / "term-index"
    terms = [term.strip() for term in args.terms if term.strip()]
    term_hits = load_term_hits(term_index_path, terms, args.module)
    print(SAFETY_NOTICE)

    primary_matches, supplement_matches = find_matches(
        [cards_path, text_cards_path],
        terms,
        module=args.module,
        doc_id=args.doc_id,
    )

    def print_card(card: dict) -> None:
        full_page_text = card_text(card)
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
        print(f"原文摘录：{result_text}")
        print(f"来源：{card['citation']} {card['source_name']} {card['locator']}")
        if is_supplement(card):
            print(f"来源层级：{SUPPLEMENT_LABEL}")
        print()

    for card in limit_matches(primary_matches, args.limit):
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
        for card in limit_matches(supplement_matches, args.limit, diversify_sources=True):
            print_card(card)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
