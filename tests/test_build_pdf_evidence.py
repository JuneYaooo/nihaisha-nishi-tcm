import json
from pathlib import Path

from scripts.build_pdf_evidence import clean_page_text, redact_ocr_privacy
from scripts.ocr_pdf_text import clean_ocr_text
from scripts.search_pdf_evidence import (
    FOLDED_NOTICE,
    find_matches,
    is_supplement,
    limit_matches,
    safe_excerpt,
    should_show_supplements,
)


def test_cjk_spacing_normalization_is_opt_in() -> None:
    raw = "针 灸 大 成\nA B\n第 3 页\n足\n三\n里"

    assert clean_page_text(raw) == raw
    assert clean_page_text(raw, normalize_cjk_spacing=True) == "针灸大成\nA B\n第 3 页足三里"


def test_traditional_actionable_terms_are_folded() -> None:
    assert safe_excerpt("原文含四逆湯與處方細節", show_excerpt=False) == FOLDED_NOTICE
    assert safe_excerpt("原文含四逆湯與處方細節", show_excerpt=True) != FOLDED_NOTICE


def test_recommended_books_have_an_explicit_supplement_role() -> None:
    assert is_supplement({"source_role": "ni-recommended-supplement"})
    assert not is_supplement({})


def test_resource_watermark_lines_are_removed_from_ocr_text() -> None:
    text = "正文\n更多相关资源请访问 https://example.invalid 制作\n续文"

    assert clean_ocr_text(text) == "正文\n续文"
    assert clean_page_text(text) == "正文\n续文"


def test_labeled_phone_is_redacted_only_in_ocr_text() -> None:
    text = "出版社电话：64065413 邮码：100027"

    assert clean_ocr_text(text) == "出版社电话：[已隐去]邮码：100027"
    assert redact_ocr_privacy(text) == "出版社电话：[已隐去]邮码：100027"


def test_ocr_url_is_removed() -> None:
    text = "正文 http://example.invalid/path 续文"

    assert clean_ocr_text(text) == "正文 [链接已移除] 续文"
    assert redact_ocr_privacy(text) == "正文 [链接已移除] 续文"


def test_supplement_second_pass_requires_primary_match_by_default() -> None:
    assert should_show_supplements(
        primary_matches=2,
        supplement_matches=3,
        force_include=False,
        primary_only=False,
    )
    assert not should_show_supplements(
        primary_matches=0,
        supplement_matches=3,
        force_include=False,
        primary_only=False,
    )
    assert should_show_supplements(
        primary_matches=0,
        supplement_matches=3,
        force_include=True,
        primary_only=False,
    )


def test_recommended_doc_has_stable_section_citations() -> None:
    path = Path("references/text-evidence/evidence-cards.jsonl")
    cards = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    assert len(cards) == 183
    assert cards[0]["citation"] == "text-evidence:77af3a7c9960#s001"
    assert cards[-1]["citation"] == "text-evidence:77af3a7c9960#s183"
    assert [card["clause_number"] for card in cards[1:]] == list(range(1, 183))
    assert all(card["source_role"] == "ni-recommended-supplement" for card in cards)


def test_text_evidence_participates_in_forced_supplement_search() -> None:
    primary, supplements = find_matches(
        [Path("references/text-evidence/evidence-cards.jsonl")],
        ["太陽病提綱"],
        module="shanghan",
        doc_id="77af3a7c9960",
    )

    assert primary == []
    assert [card["citation"] for card in supplements] == [
        "text-evidence:77af3a7c9960#s002"
    ]

    _, title_matches = find_matches(
        [Path("references/text-evidence/evidence-cards.jsonl")],
        ["大塚敬节伤寒论解说"],
        doc_id="77af3a7c9960",
    )
    assert len(title_matches) == 183


def test_supplement_limit_surfaces_distinct_sources_first() -> None:
    cards = [
        {"card_id": "a-1", "doc_id": "a"},
        {"card_id": "a-2", "doc_id": "a"},
        {"card_id": "b-1", "doc_id": "b"},
    ]

    assert [card["card_id"] for card in limit_matches(cards, 2, diversify_sources=True)] == [
        "a-1",
        "b-1",
    ]
