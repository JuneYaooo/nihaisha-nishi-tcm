#!/usr/bin/env python3
"""Search complete PDF pages and supplemental text-evidence sections."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import unicodedata


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
SUPPLEMENT_LABELS = {
    SUPPLEMENT_ROLE: SUPPLEMENT_LABEL,
    "practitioner-recommended-safety-reference": (
        "针灸安全外部参考（叶昭呈医师推荐；刘德毅医师提供；非倪师本人资料）"
    ),
    "user-provided-translation-aid": "中文翻译辅助（非原始论文，须回核日文原文）",
}
AUTO_SUPPLEMENT_NOTICE = "二次检索：课程主资料已命中，以下自动补充独立标注的外部参考资料。"
SAFETY_REFERENCE_ROLE = "practitioner-recommended-safety-reference"
SAFETY_QUERY_RE = re.compile(
    r"进针|针刺|刺针|刺鍼|刺入|深度|危险|危険|气胸|胸膜|肺俞|肺腧|肺兪|"
    r"哑门|肩井|膏肓|风府|风池|睛明|胸背|颈项|眼眶"
)

SEARCH_CHAR_NORMALIZATION = str.maketrans(
    {
        "兪": "俞",
        "腧": "俞",
        "鍼": "针",
        "針": "针",
        "険": "险",
        "風": "风",
        "門": "门",
        "體": "体",
        "頸": "颈",
        "髙": "高",
    }
)


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


def normalize_search_text(text: str) -> str:
    """Normalize common Japanese/traditional acupoint variants for exact local search."""
    normalized = unicodedata.normalize("NFKC", text).translate(SEARCH_CHAR_NORMALIZATION)
    return (
        normalized.replace("刺针", "针刺")
        .replace("晴明", "睛明")
        .replace("欠盆", "缺盆")
        .replace("淵液", "渊腋")
    )


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
    return card.get("source_role") in SUPPLEMENT_LABELS


def supplement_label(card: dict) -> str:
    return SUPPLEMENT_LABELS.get(card.get("source_role"), "外部补充资料")


def is_safety_depth_query(terms: list[str]) -> bool:
    return bool(SAFETY_QUERY_RE.search(normalize_search_text(" ".join(terms))))


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
    primary_scored: list[tuple[int, int, dict]] = []
    supplement_scored: list[tuple[int, int, dict]] = []
    order = 0
    normalized_terms = [normalize_search_text(term) for term in terms]
    for cards_path in card_paths:
        for card in iter_cards(cards_path):
            if module and card.get("module") != module:
                continue
            if doc_id and card.get("doc_id") != doc_id:
                continue
            full_text = card_text(card)
            content_haystack = normalize_search_text(
                "\n".join(
                    [
                        card.get("locator", ""),
                        full_text,
                        " ".join(card.get("terms", [])),
                    ]
                )
            )
            metadata_haystack = normalize_search_text(
                "\n".join(
                    [
                        card.get("source_name", ""),
                        card.get("bibliographic_title", ""),
                        card.get("archive_name", ""),
                        " ".join(card.get("aliases", [])),
                    ]
                )
            )
            haystack = content_haystack + "\n" + metadata_haystack
            if all(term in haystack for term in normalized_terms):
                content_hits = sum(term in content_haystack for term in normalized_terms)
                all_terms_in_content = content_hits == len(normalized_terms)
                score = (1000 if all_terms_in_content else 0) + content_hits
                target = supplement_scored if is_supplement(card) else primary_scored
                target.append((score, order, card))
                order += 1

    def ranked(items: list[tuple[int, int, dict]]) -> list[dict]:
        ordered = sorted(items, key=lambda item: (-item[0], item[1]))
        return [card for score, position, card in ordered]

    return ranked(primary_scored), ranked(supplement_scored)


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
            print(f"来源层级：{supplement_label(card)}")
        if card.get("recommended_by"):
            print(f"推荐者：{card['recommended_by']}")
        if card.get("provided_by"):
            print(f"资料提供：{card['provided_by']}")
        if card.get("translation_caveat"):
            print(f"翻译边界：{card['translation_caveat']}")
        print()

    for card in limit_matches(primary_matches, args.limit):
        print_card(card)

    safety_query = is_safety_depth_query(terms)
    safety_matches = [
        card for card in supplement_matches if card.get("source_role") == SAFETY_REFERENCE_ROLE
    ]
    ni_recommended_matches = [
        card for card in supplement_matches if card.get("source_role") == SUPPLEMENT_ROLE
    ]
    if args.doc_id:
        visible_supplements = supplement_matches
    elif safety_query:
        # Put the original safety paper ahead of general recommended books. The derivative
        # translation aid remains directly searchable by its doc_id but cannot displace original data.
        visible_supplements = safety_matches + ni_recommended_matches
    else:
        # Practitioner safety references should not leak into unrelated broad acupuncture searches.
        visible_supplements = ni_recommended_matches

    show_supplements = should_show_supplements(
        primary_matches=len(primary_matches),
        supplement_matches=len(visible_supplements),
        force_include=args.include_supplements,
        primary_only=args.primary_only,
    )
    if not args.primary_only and safety_query and safety_matches:
        show_supplements = True
    if show_supplements:
        if not args.include_supplements and primary_matches:
            print(AUTO_SUPPLEMENT_NOTICE)
        for card in limit_matches(
            visible_supplements,
            args.limit,
            diversify_sources=not safety_matches,
        ):
            print_card(card)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
