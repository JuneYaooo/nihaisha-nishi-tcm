from scripts.build_pdf_evidence import clean_page_text
from scripts.search_pdf_evidence import FOLDED_NOTICE, is_supplement, safe_excerpt


def test_cjk_spacing_normalization_is_opt_in() -> None:
    raw = "针 灸 大 成\nA B\n第 3 页"

    assert clean_page_text(raw) == raw
    assert clean_page_text(raw, normalize_cjk_spacing=True) == "针灸大成\nA B\n第 3 页"


def test_traditional_actionable_terms_are_folded() -> None:
    assert safe_excerpt("原文含四逆湯與處方細節", show_excerpt=False) == FOLDED_NOTICE
    assert safe_excerpt("原文含四逆湯與處方細節", show_excerpt=True) != FOLDED_NOTICE


def test_recommended_books_have_an_explicit_supplement_role() -> None:
    assert is_supplement({"source_role": "ni-recommended-supplement"})
    assert not is_supplement({})
