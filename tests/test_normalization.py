from __future__ import annotations

import unittest

from nihaisha_kg import normalization as query_normalization
from nihaisha_kg.normalization import lexical_query_terms, normalize_query_text


class NormalizationTests(unittest.TestCase):
    def test_lexical_query_terms_extracts_recognized_domain_terms(self) -> None:
        terms = lexical_query_terms(
            "桂枝湯和麻黃湯的方證如何鑒別？",
            domain_terms=("桂枝汤", "麻黄汤", "方证", "鉴别"),
        )

        self.assertTrue({"桂枝汤", "麻黄汤", "方证", "鉴别"}.issubset(terms))
        self.assertNotIn("桂枝汤和麻黄汤的方证如何鉴别", terms)

    def test_lexical_query_terms_prioritizes_domain_terms_and_drops_scaffolding(self) -> None:
        terms = lexical_query_terms(
            "太阳病欲解时从什么时候到什么时候？",
            domain_terms=("太阳病", "欲解"),
        )

        self.assertEqual(terms[:2], ["太阳病", "欲解"])
        self.assertNotIn("什么时候", terms)

    def test_normalize_query_text_translates_traditional_query_characters(self) -> None:
        self.assertEqual(
            normalize_query_text("一錢、方證、發熱"),
            "一钱、方证、发热",
        )

    def test_lexical_terms_preserve_phrase_boundaries_and_remove_generic_glue(self) -> None:
        cases = (
            (
                "调和营卫的方证有哪些？",
                ("方证",),
                ["方证", "方證", "调和营卫", "調和營衛"],
            ),
            (
                "和解少阳如何理解？",
                (),
                ["和解少阳", "和解少陽", "理解"],
            ),
            (
                "从容脉是什么脉象？",
                (),
                ["从容脉", "從容脈", "脉象", "脈象"],
            ),
            (
                "手足厥冷应该用什么方？",
                (),
                ["手足厥冷"],
            ),
        )

        for query, domain_terms, expected in cases:
            with self.subTest(query=query):
                terms = lexical_query_terms(query, domain_terms=domain_terms)

                self.assertEqual(terms, expected)
                self.assertFalse(
                    any(
                        glue in term
                        for term in terms
                        for glue in (
                            "什么",
                            "哪些",
                            "这个",
                            "那个",
                            "问题",
                            "资料",
                            "内容",
                            "时候",
                        )
                    )
                )

    def test_lexical_terms_emit_normalized_and_traditional_domain_anchors(self) -> None:
        terms = lexical_query_terms(
            "太陽病的脈證有哪些？",
            domain_terms=("太阳病", "脉证", "太阳"),
        )

        self.assertEqual(terms, ["太阳病", "脉证", "太陽病", "脈證"])

    def test_overlapping_domain_term_requires_an_independent_occurrence(self) -> None:
        nested_only = lexical_query_terms("太阳病", domain_terms=("太阳病", "太阳"))
        independently_present = lexical_query_terms(
            "太阳病属于太阳证",
            domain_terms=("太阳病", "太阳"),
        )

        self.assertNotIn("太阳", nested_only)
        self.assertEqual(independently_present[:2], ["太阳病", "太阳"])

    def test_normalize_query_text_maps_reviewer_confirmed_traditional_characters(self) -> None:
        self.assertEqual(
            normalize_query_text(
                "脈隨兩陽陰時從麼書頁經衛營氣虛實風濕為歸屬開關體"
            ),
            "脉随两阳阴时从么书页经卫营气虚实风湿为归属开关体",
        )

    def test_zero_fallback_budget_preserves_only_unbounded_domain_variants(self) -> None:
        terms = lexical_query_terms(
            "方證和调和营卫",
            domain_terms=("方证",),
            max_fallback_terms=0,
        )

        self.assertEqual(terms, ["方证", "方證"])

    def test_traditional_scaffold_and_generic_vocabulary_normalizes_completely(self) -> None:
        cases = (
            ("請問", "请问"),
            ("告訴我", "告诉我"),
            ("對應", "对应"),
            ("應該用", "应该用"),
            ("課程裡", "课程里"),
            ("課程裏", "课程里"),
            ("這個", "这个"),
            ("問題", "问题"),
            ("資料", "资料"),
            ("內容", "内容"),
            ("什麼嗎", "什么吗"),
        )
        traditional_characters = set("請問訴對應該課這個題資內嗎裏裡")

        for traditional, simplified in cases:
            with self.subTest(traditional=traditional):
                normalized = normalize_query_text(traditional)

                self.assertEqual(normalized, simplified)
                self.assertTrue(traditional_characters.isdisjoint(normalized))

    def test_paired_script_questions_remove_equivalent_scaffold(self) -> None:
        cases = (
            (
                "手足厥冷应该用什么方？",
                "手足厥冷應該用什麼方？",
                (),
                ["手足厥冷"],
            ),
            (
                "这个问题的内容是什么吗？",
                "這個問題的內容是什麼嗎？",
                (),
                [],
            ),
            (
                "课程里太阳病的原文？",
                "課程裡太陽病的原文？",
                ("太阳病", "太阳"),
                ["太阳病", "太陽病"],
            ),
        )

        for simplified, traditional, domain_terms, expected in cases:
            with self.subTest(query=simplified):
                self.assertEqual(
                    lexical_query_terms(simplified, domain_terms=domain_terms),
                    expected,
                )
                self.assertEqual(
                    lexical_query_terms(traditional, domain_terms=domain_terms),
                    expected,
                )

    def test_complete_term_list_is_bounded_after_priority_ordering(self) -> None:
        query = "太阳病 " + " ".join(f"token{index:04d}" for index in range(1001))

        first = lexical_query_terms(
            query,
            domain_terms=("太阳病", "太阳"),
            max_terms=8,
        )
        second = lexical_query_terms(
            query,
            domain_terms=("太阳病", "太阳"),
            max_terms=8,
        )

        self.assertEqual(len(first), 8)
        self.assertEqual(first, second)
        self.assertEqual(first[:4], ["太阳病", "太陽病", "token0000", "token0001"])

    def test_reverse_equivalence_retains_all_traditional_forms_for_li(self) -> None:
        self.assertEqual(
            query_normalization._SIMPLIFIED_TO_TRADITIONAL_EQUIVALENTS["里"],
            ("裡", "裏"),
        )

    def test_term_variants_include_both_traditional_li_forms(self) -> None:
        terms = lexical_query_terms("经方里面辨证")

        self.assertEqual(
            terms,
            ["经方里面辨证", "經方裡面辨證", "經方裏面辨證"],
        )

    def test_term_variant_expansion_is_deterministic_and_bounded(self) -> None:
        first = lexical_query_terms("里里里里", domain_terms=("里里里里",))
        second = lexical_query_terms("里里里里", domain_terms=("里里里里",))

        self.assertEqual(first, second)
        self.assertEqual(len(first), query_normalization.MAX_TERM_VARIANTS)
        self.assertEqual(first[0], "里里里里")


if __name__ == "__main__":
    unittest.main()
