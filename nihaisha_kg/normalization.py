from __future__ import annotations

import re
from collections.abc import Iterable


_TRADITIONAL_TO_SIMPLIFIED = {
    "錢": "钱",
    "證": "证",
    "發": "发",
    "燒": "烧",
    "噁": "恶",
    "瀉": "泻",
    "黃": "黄",
    "餅": "饼",
    "熱": "热",
    "藥": "药",
    "處": "处",
    "裡": "里",
    "來": "来",
    "頭": "头",
    "頸": "颈",
    "痠": "酸",
    "湯": "汤",
    "鑒": "鉴",
    "別": "别",
    "與": "与",
    "脈": "脉",
    "隨": "随",
    "兩": "两",
    "陽": "阳",
    "陰": "阴",
    "時": "时",
    "從": "从",
    "麼": "么",
    "書": "书",
    "頁": "页",
    "經": "经",
    "衛": "卫",
    "營": "营",
    "氣": "气",
    "虛": "虚",
    "實": "实",
    "風": "风",
    "濕": "湿",
    "為": "为",
    "歸": "归",
    "屬": "属",
    "開": "开",
    "關": "关",
    "體": "体",
    "現": "现",
    "歲": "岁",
    "調": "调",
    "較": "较",
    "區": "区",
    "於": "于",
    "應": "应",
    "請": "请",
    "問": "问",
    "訴": "诉",
    "對": "对",
    "該": "该",
    "課": "课",
    "這": "这",
    "個": "个",
    "題": "题",
    "資": "资",
    "內": "内",
    "嗎": "吗",
    "裏": "里",
}

TRADITIONAL_QUERY_TRANSLATION = str.maketrans(_TRADITIONAL_TO_SIMPLIFIED)


def _build_simplified_to_traditional_equivalents() -> dict[str, tuple[str, ...]]:
    equivalents: dict[str, list[str]] = {}
    for traditional, simplified in _TRADITIONAL_TO_SIMPLIFIED.items():
        equivalents.setdefault(simplified, []).append(traditional)
    return {simplified: tuple(values) for simplified, values in equivalents.items()}


_SIMPLIFIED_TO_TRADITIONAL_EQUIVALENTS = _build_simplified_to_traditional_equivalents()
MAX_TERM_VARIANTS = 8

CHINESE_RUN_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
ASCII_TERM_RE = re.compile(r"[A-Za-z0-9_+.-]{2,}")
MEASURE_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:克|钱|两|分|升|斗|斤|铢)")

QUESTION_SCAFFOLD = (
    "从什么时候到什么时候",
    "哪一本书",
    "什么时候",
    "告诉我",
    "是什么",
    "有哪些",
    "哪本书",
    "哪一页",
    "哪一段",
    "课程里",
    "课程中",
    "应该用",
    "能不能",
    "可以",
    "请问",
    "如何",
    "怎么",
    "对应",
    "相关",
    "原文",
    "出处",
)

GENERIC_FRAGMENTS = {
    "这个",
    "那个",
    "问题",
    "资料",
    "内容",
    "时候",
    "什么",
    "哪些",
}

_TRAILING_PARTICLES = "的了呢吗"


def normalize_query_text(query: str) -> str:
    return query.translate(TRADITIONAL_QUERY_TRANSLATION)


def _traditional_query_variants(query: str) -> list[str]:
    variants = [""]
    for character in query:
        equivalents = _SIMPLIFIED_TO_TRADITIONAL_EQUIVALENTS.get(character, (character,))
        expanded: list[str] = []
        for prefix in variants:
            for equivalent in equivalents:
                expanded.append(prefix + equivalent)
                if len(expanded) >= MAX_TERM_VARIANTS:
                    break
            if len(expanded) >= MAX_TERM_VARIANTS:
                break
        variants = expanded
    return variants


def _dedupe_keep_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        term = value.strip()
        if not term or term in seen:
            continue
        seen.add(term)
        unique.append(term)
    return unique


def _find_spans(text: str, phrase: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    offset = text.find(phrase)
    while offset >= 0:
        spans.append((offset, offset + len(phrase)))
        offset = text.find(phrase, offset + 1)
    return spans


def _select_recognized_terms(
    normalized: str,
    domain_terms: Iterable[str],
) -> tuple[list[str], dict[str, list[tuple[int, int]]], list[tuple[int, int]]]:
    candidates = sorted(
        _dedupe_keep_order(normalize_query_text(term) for term in domain_terms),
        key=lambda term: (-len(term), term),
    )
    recognized: list[str] = []
    term_spans: dict[str, list[tuple[int, int]]] = {}
    covered_spans: list[tuple[int, int]] = []
    for term in candidates:
        independent_spans = [
            span
            for span in _find_spans(normalized, term)
            if not any(
                span[0] >= covered[0] and span[1] <= covered[1]
                for covered in covered_spans
            )
        ]
        if not independent_spans:
            continue
        recognized.append(term)
        term_spans[term] = independent_spans
        covered_spans.extend(independent_spans)
    return recognized, term_spans, covered_spans


def _replace_spans_with_boundaries(text: str, spans: Iterable[tuple[int, int]]) -> str:
    characters = list(text)
    for start, end in spans:
        characters[start:end] = [" "] * (end - start)
    return re.sub(r"\s+", " ", "".join(characters)).strip()


def _term_variants(normalized_term: str, *surface_terms: str) -> list[str]:
    variants = _dedupe_keep_order(
        [normalized_term, *surface_terms, *_traditional_query_variants(normalized_term)]
    )
    return variants[:MAX_TERM_VARIANTS]


def _contains_generic_fragment(term: str) -> bool:
    normalized = normalize_query_text(term)
    return any(fragment in normalized for fragment in GENERIC_FRAGMENTS)


def lexical_query_terms(
    query: str,
    domain_terms: Iterable[str] = (),
    max_fallback_terms: int = 12,
    max_terms: int = 64,
) -> list[str]:
    normalized = normalize_query_text(query)
    recognized, recognized_spans, removal_spans = _select_recognized_terms(
        normalized,
        domain_terms,
    )

    recognized_variants: list[str] = []
    for term in recognized:
        surfaces = [query[start:end] for start, end in recognized_spans[term]]
        recognized_variants.extend(_term_variants(term, *surfaces)[1:])

    measure_matches = list(MEASURE_RE.finditer(normalized))
    measure_terms = [re.sub(r"\s+", "", match.group(0)) for match in measure_matches]
    measure_variants: list[str] = []
    for normalized_term, match in zip(measure_terms, measure_matches):
        surface = re.sub(r"\s+", "", query[match.start() : match.end()])
        measure_variants.extend(_term_variants(normalized_term, surface)[1:])

    ascii_matches = list(ASCII_TERM_RE.finditer(normalized))
    ascii_terms = [match.group(0) for match in ascii_matches]
    removal_spans.extend((match.start(), match.end()) for match in measure_matches)
    removal_spans.extend((match.start(), match.end()) for match in ascii_matches)
    for phrase in (*QUESTION_SCAFFOLD, *GENERIC_FRAGMENTS):
        removal_spans.extend(_find_spans(normalized, phrase))

    normalized_remainder = _replace_spans_with_boundaries(normalized, removal_spans)
    surface_remainder = _replace_spans_with_boundaries(query, removal_spans)
    fallback_terms: list[str] = []
    fallback_limit = max(0, max_fallback_terms)
    for match in CHINESE_RUN_RE.finditer(normalized_remainder):
        if not fallback_limit:
            break
        chunk = match.group(0).rstrip(_TRAILING_PARTICLES)
        if len(chunk) < 2:
            continue
        chunk_start = match.start()
        spans = (
            [(chunk_start, chunk_start + len(chunk))]
            if len(chunk) <= 8
            else [
                (chunk_start + index, chunk_start + index + 3)
                for index in range(len(chunk) - 2)
            ]
        )
        for start, end in spans:
            normalized_term = normalized_remainder[start:end]
            surface_term = surface_remainder[start:end]
            for variant in _term_variants(normalized_term, surface_term):
                if _contains_generic_fragment(variant) or variant in fallback_terms:
                    continue
                fallback_terms.append(variant)
                if len(fallback_terms) >= fallback_limit:
                    break
            if len(fallback_terms) >= fallback_limit:
                break
        if len(fallback_terms) >= fallback_limit:
            break

    terms = _dedupe_keep_order(
        [
            *recognized,
            *recognized_variants,
            *measure_terms,
            *measure_variants,
            *ascii_terms,
            *fallback_terms,
        ]
    )
    return terms[: max(0, max_terms)]
