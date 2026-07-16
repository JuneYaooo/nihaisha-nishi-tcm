from scripts.build_pdf_evidence import clean_page_text, redact_ocr_privacy
from scripts.ocr_pdf_text import clean_ocr_text
from scripts.search_pdf_evidence import (
    FOLDED_NOTICE,
    is_supplement,
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
