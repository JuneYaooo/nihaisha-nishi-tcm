from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from nihaisha_kg import pdf_vector


def result(
    text: str,
    *,
    source_path: str = "/tmp/伤寒论.pdf",
    page: int = 68,
    paragraph_id: str = "p-1",
) -> dict[str, object]:
    return {
        "paragraph_id": paragraph_id,
        "source_path": source_path,
        "title": f"{source_path.rsplit('/', 1)[-1]} p{page}",
        "page_start": page,
        "page_end": page,
        "text": text,
        "matched_knowledge_units": [],
    }


class AnswerQualityTests(unittest.TestCase):
    def test_reliable_formula_anchors_use_exact_curated_lexicon(self) -> None:
        known = (
            "桂枝汤",
            "麻黄汤",
            "四逆汤",
            "真武汤",
            "葛根汤",
            "小柴胡汤",
            "理中汤",
            "黄芩加半夏生姜汤",
            "黄芩汤",
            "半夏泻心汤",
            "生姜泻心汤",
            "甘草泻心汤",
            "葛根黄芩黄连汤",
            "白虎汤",
            "大承气汤",
            "小承气汤",
            "调胃承气汤",
            "小建中汤",
            "十枣汤",
            "大柴胡汤",
            "小青龙汤",
            "大青龙汤",
            "吴茱萸汤",
            "当归四逆汤",
            "苓桂术甘汤",
            "茵陈蒿汤",
            "越婢汤",
            "旋覆代赭汤",
            "麦门冬汤",
            "木防己汤",
            "百合知母汤",
            "五苓散",
            "肾气丸",
            "麻子仁丸",
        )
        for formula in known:
            with self.subTest(formula=formula):
                self.assertEqual(pdf_vector.reliable_source_anchors(f"{formula}出处"), [formula])

        generic = (
            "红枣汤",
            "白米汤",
            "人参鸡汤",
            "排骨汤",
            "每天喝白米汤",
            "小药丸",
            "护手膏",
            "喝汤",
            "鸡汤",
            "热汤",
            "一碗汤",
            "米汤",
            "煎汤",
            "喝热汤",
            "一碗热汤",
        )
        for phrase in generic:
            with self.subTest(phrase=phrase):
                self.assertEqual(pdf_vector.reliable_source_anchors(f"{phrase}出处"), [])

    def test_reliable_formula_anchors_require_query_boundaries(self) -> None:
        for query in ("桂枝汤圆出处", "大承气汤锅出处", "五苓散装产品出处", "肾气丸子出处"):
            with self.subTest(query=query):
                self.assertEqual(pdf_vector.reliable_formula_anchors(query), [])
                self.assertEqual(
                    pdf_vector.synthesize_pdf_rag_answer(query, [])["safety_notice"], ""
                )

        positives = {
            "桂枝汤出处": ["桂枝汤"],
            "请问桂枝汤的出处": ["桂枝汤"],
            "关于大承气汤原文": ["大承气汤"],
            "桂枝汤和麻黄汤如何鉴别": ["桂枝汤", "麻黄汤"],
        }
        for query, expected in positives.items():
            with self.subTest(query=query):
                self.assertEqual(pdf_vector.reliable_formula_anchors(query), expected)

    def test_embedded_product_formula_phrase_does_not_hard_filter(self) -> None:
        candidate = result("课程资料提到日常产品名称。")

        filtered = pdf_vector.filter_results_for_intent(
            "桂枝汤圆出处", "source_lookup", [candidate]
        )

        self.assertEqual(filtered, [candidate])

    def test_food_source_query_does_not_receive_formula_safety_warning(self) -> None:
        answer = pdf_vector.synthesize_pdf_rag_answer("白米汤出处", [])

        self.assertEqual(answer["safety_notice"], "")

    def test_reliable_formula_anchors_reject_natural_language_tang_phrases(self) -> None:
        generic = (
            "这个汤",
            "如何熬汤",
            "有哪些相关汤方",
            "喝汤",
            "鸡汤",
            "热汤",
            "一碗汤",
            "米汤",
            "煎汤",
            "喝热汤",
            "一碗热汤",
        )
        for phrase in generic:
            query = f"{phrase}的出处"
            with self.subTest(query=query):
                self.assertEqual(pdf_vector.reliable_source_anchors(query), [])
        for formula in ("桂枝汤", "麻黄汤", "四逆汤", "真武汤", "葛根汤", "小柴胡汤", "理中汤"):
            with self.subTest(formula=formula):
                self.assertEqual(pdf_vector.reliable_source_anchors(f"{formula}出处"), [formula])

    def test_generic_soup_source_query_does_not_hard_filter_candidates(self) -> None:
        candidate = result("课程中讨论饮食与汤液的日常语境。")

        filtered = pdf_vector.filter_results_for_intent("喝汤出处", "source_lookup", [candidate])

        self.assertEqual(filtered, [candidate])

    def test_source_lookup_answer_uses_retrieved_formula_and_location_only(self) -> None:
        answer = pdf_vector.synthesize_pdf_rag_answer(
            "桂枝汤的出处在哪本书哪一页？",
            [result("太阳中风，汗出恶风，桂枝汤主之。")],
        )

        self.assertEqual(answer["intent"], "source_lookup")
        self.assertIn("桂枝汤", answer["answer"])
        self.assertIn("伤寒论.pdf p68", answer["answer"])
        self.assertNotIn("木香饼", answer["answer"])
        self.assertNotIn("热熨", answer["answer"])

    def test_clinical_answer_uses_query_focus_without_fixed_diarrhea_checklist(self) -> None:
        answer = pdf_vector.synthesize_pdf_rag_answer(
            "患者咳嗽、怕冷、无汗，课程有哪些相关线索？",
            [result("恶寒无汗而喘，麻黄汤主之。", page=35)],
        )

        self.assertEqual(answer["intent"], "clinical")
        self.assertTrue(any(clue in answer["answer"] for clue in ("咳嗽", "怕冷", "无汗")))
        self.assertIn("麻黄汤", answer["answer"])
        self.assertNotIn("下利性质", answer["answer"])
        self.assertNotIn("心下痞满", answer["answer"])

    def test_clinical_synthesis_rejects_evidence_without_query_clue_overlap(self) -> None:
        answer = pdf_vector.synthesize_pdf_rag_answer(
            "患者咳嗽、怕冷、无汗，课程有哪些相关线索？",
            [result("下利恶心，黄芩加半夏生姜汤主之。", page=169)],
        )

        self.assertEqual(answer["citations"], [])
        self.assertIn("没有检索到足够可靠", answer["answer"])
        self.assertNotIn("黄芩加半夏生姜汤", answer["answer"])
        self.assertIn(pdf_vector.FORMULA_DOSAGE_SAFETY_NOTICE, answer["safety_notice"])

    def test_clinical_synthesis_keeps_canonical_clue_match(self) -> None:
        answer = pdf_vector.synthesize_pdf_rag_answer(
            "患者咳嗽、怕冷、无汗，课程有哪些相关线索？",
            [result("恶寒无汗而喘，麻黄汤主之。", page=35)],
        )

        self.assertIn("麻黄汤", answer["answer"])
        self.assertTrue(answer["citations"])

    def test_clinical_synonym_groups_match_bidirectionally(self) -> None:
        pairs = (
            ("发烧", "发热"),
            ("发热", "发烧"),
            ("發燒", "发热"),
            ("咽喉疼痛", "咽痛"),
            ("咽痛", "咽喉疼痛"),
            ("胃口差", "食欲差"),
            ("食欲差", "胃口差"),
            ("胃口不好", "食欲差"),
            ("食欲差", "胃口不好"),
            ("食欲不振", "食欲差"),
            ("食欲差", "食欲不振"),
        )
        for query_clue, evidence_clue in pairs:
            with self.subTest(query=query_clue, evidence=evidence_clue):
                answer = pdf_vector.synthesize_pdf_rag_answer(
                    f"患者{query_clue}，课程有哪些线索？",
                    [result(f"{evidence_clue}，麻黄汤主之。", page=35)],
                )
                self.assertIn("麻黄汤", answer["answer"])
                self.assertTrue(answer["citations"])

    def test_source_citation_prefers_anchor_bearing_paragraph_over_unrelated_unit_quote(
        self,
    ) -> None:
        evidence = result("太阳中风，桂枝汤主之。")
        evidence["matched_knowledge_units"] = [
            {"unit_type": "clinical_pattern", "evidence_quote": "头痛者另论"}
        ]

        answer = pdf_vector.synthesize_pdf_rag_answer("桂枝汤出处", [evidence])

        self.assertIn("桂枝汤主之", answer["citations"][0]["evidence_quote"])
        self.assertNotIn("头痛者另论", answer["citations"][0]["evidence_quote"])

    def test_citation_falls_back_to_paragraph_when_unit_quote_is_blank(self) -> None:
        evidence = result("太阳中风，桂枝汤主之。")
        evidence["matched_knowledge_units"] = [
            {"unit_type": "formula_pattern", "subject": "桂枝汤", "evidence_quote": "   "}
        ]

        answer = pdf_vector.synthesize_pdf_rag_answer("桂枝汤原文", [evidence])

        self.assertTrue(answer["citations"][0]["evidence_quote"].strip())
        self.assertIn("桂枝汤主之", answer["citations"][0]["evidence_quote"])
        self.assertNotIn("原文摘录：[1] ；", answer["answer"])

    def test_formula_source_no_results_preserves_formula_safety(self) -> None:
        answer = pdf_vector.synthesize_pdf_rag_answer("桂枝汤出处", [])

        self.assertIn(pdf_vector.FORMULA_DOSAGE_SAFETY_NOTICE, answer["safety_notice"])

    def test_nonclinical_gender_words_do_not_trigger_clinical_intent(self) -> None:
        self.assertEqual(pdf_vector.detect_answer_intent("男女有别"), "general")
        self.assertEqual(pdf_vector.detect_answer_intent("女生课程"), "general")
        self.assertEqual(pdf_vector.detect_answer_intent("60岁男"), "clinical")

    def test_answer_pdf_rag_source_lookup_uses_real_text_store(self) -> None:
        paragraph = pdf_vector.ParsedParagraph(
            paragraph_id="p-gz",
            doc_id="doc",
            source_path="/tmp/伤寒论.pdf",
            title="伤寒论 p68",
            page_start=68,
            page_end=68,
            text="太阳中风，汗出恶风，桂枝汤主之。",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "rag.sqlite"
            store = pdf_vector.LocalVectorStore(db_path)
            store.recreate()
            store.insert_paragraphs([paragraph])
            store.rebuild_text_index()
            answer = pdf_vector.answer_pdf_rag(
                "桂枝汤出处在哪一页？",
                db_path,
                mode="text",
                reranker="none",
            )

        self.assertEqual(answer["intent"], "source_lookup")
        self.assertIn("伤寒论.pdf p68", answer["answer"])
        self.assertIn("桂枝汤主之", answer["citations"][0]["evidence_quote"])

    def test_no_results_never_emit_empty_citation_marker(self) -> None:
        answer = pdf_vector.synthesize_pdf_rag_answer("桂枝汤的出处在哪本书？", [])

        self.assertNotIn("证据见 。", answer["answer"])
        self.assertNotIn("证据见。", answer["answer"])
        self.assertEqual(answer["citations"], [])

    def test_detect_answer_intent_orders_specific_intents(self) -> None:
        for query in ("桂枝汤出处", "桂枝汤在哪本书", "桂枝汤哪一页", "桂枝汤原文"):
            with self.subTest(query=query):
                self.assertEqual(pdf_vector.detect_answer_intent(query), "source_lookup")
        for query in ("桂枝汤和麻黄汤的鉴别", "桂枝汤与麻黄汤比较", "二者有什么区别"):
            with self.subTest(query=query):
                self.assertEqual(pdf_vector.detect_answer_intent(query), "comparison")
        self.assertEqual(pdf_vector.detect_answer_intent("患者咳嗽、怕冷、无汗"), "clinical")
        self.assertEqual(pdf_vector.detect_answer_intent("古时候一钱是多少克？"), "dosage")

    def test_answer_anchor_terms_prefers_named_formula_and_excludes_task_words(self) -> None:
        anchors = pdf_vector.answer_anchor_terms("桂枝汤的出处在哪本书哪一页？")

        self.assertIn("桂枝汤", anchors)
        self.assertNotIn("出处", anchors)
        self.assertNotIn("哪本书", anchors)

    def test_reliable_source_anchors_exclude_generic_reference_phrases(self) -> None:
        query = "这种治法的原文在哪一段？"
        evidence = result("老师说明此法用于课程示例。")

        self.assertEqual(pdf_vector.reliable_source_anchors(query), [])
        self.assertEqual(
            pdf_vector.filter_results_for_intent(query, "source_lookup", [evidence]),
            [evidence],
        )

    def test_source_anchors_do_not_create_cross_boundary_symptom_terms(self) -> None:
        query = "咳嗽怕冷无汗出处"

        self.assertNotIn("汗出", pdf_vector.answer_anchor_terms(query))
        self.assertEqual(pdf_vector.reliable_source_anchors(query), [])

    def test_reliable_source_anchors_keep_explicit_named_entities(self) -> None:
        cases = {
            "桂枝汤出处": ["桂枝汤"],
            "木香饼热熨法原文": ["木香饼"],
            "一钱的原文": ["一钱"],
            "太阳病原文": ["太阳病"],
        }
        for query, expected in cases.items():
            with self.subTest(query=query):
                self.assertEqual(pdf_vector.reliable_source_anchors(query), expected)

    def test_named_source_anchors_require_query_boundaries(self) -> None:
        for query in ("木香饼干出处", "太阳病人原文", "一钱包原文"):
            with self.subTest(query=query):
                self.assertEqual(pdf_vector.reliable_source_anchors(query), [])
        positives = {
            "木香饼出处": ["木香饼"],
            "太阳病原文": ["太阳病"],
            "一钱是多少克": ["一钱"],
            "一钱原文": ["一钱"],
        }
        for query, expected in positives.items():
            with self.subTest(query=query):
                self.assertEqual(pdf_vector.reliable_source_anchors(query), expected)

    def test_source_citation_keeps_anchor_after_long_paragraph_prefix(self) -> None:
        paragraph = "背景说明" * 65 + "。太阳中风，桂枝汤主之。"

        answer = pdf_vector.synthesize_pdf_rag_answer("桂枝汤出处", [result(paragraph)])
        excerpt = answer["citations"][0]["evidence_quote"]

        self.assertIn("桂枝汤", excerpt)
        self.assertLessEqual(len(excerpt), 220)

    def test_source_citation_budget_retains_all_distant_query_anchors(self) -> None:
        formulas = ("桂枝汤", "麻黄汤", "四逆汤", "真武汤", "葛根汤", "小柴胡汤")
        paragraph = ("。" + "背景说明" * 40 + "。").join(formulas)
        query = "、".join(formulas) + "出处"

        answer = pdf_vector.synthesize_pdf_rag_answer(query, [result(paragraph)])
        excerpt = answer["citations"][0]["evidence_quote"]

        self.assertLessEqual(len(excerpt), 220)
        for formula in formulas:
            self.assertIn(formula, excerpt)

    def test_generic_source_query_uses_formula_safety_from_evidence_prose(self) -> None:
        answer = pdf_vector.synthesize_pdf_rag_answer(
            "这种方的原文",
            [result("太阳中风，桂枝汤主之。")],
        )

        self.assertIn(pdf_vector.FORMULA_DOSAGE_SAFETY_NOTICE, answer["safety_notice"])

    def test_product_formula_embeddings_in_evidence_do_not_trigger_safety(self) -> None:
        for text in ("桂枝汤圆新品。", "大承气汤锅介绍。", "五苓散装产品。", "肾气丸子包装。"):
            with self.subTest(text=text):
                answer = pdf_vector.synthesize_pdf_rag_answer("这种产品的原文", [result(text)])
                self.assertEqual(answer["safety_notice"], "")

    def test_source_filter_requires_primary_anchor_when_direct_evidence_exists(self) -> None:
        generic = result("用火温之，再以热熨法处理。", paragraph_id="p-generic")
        direct = result("木香饼（生地木香作饼），热熨贴之。", paragraph_id="p-direct")

        filtered = pdf_vector.filter_results_for_intent(
            "木香饼热熨法的出处在哪一段？",
            "source_lookup",
            [generic, direct],
        )

        self.assertEqual([item["paragraph_id"] for item in filtered], ["p-direct"])

    def test_source_filter_rejects_evidence_for_another_named_topic(self) -> None:
        unrelated = result("生地木香作饼，热熨贴之。", paragraph_id="p-unrelated")
        direct = result("太阳中风，桂枝汤主之。", paragraph_id="p-direct")

        filtered = pdf_vector.filter_results_for_intent(
            "桂枝汤的出处在哪本书？",
            "source_lookup",
            [unrelated, direct],
        )

        self.assertEqual([item["paragraph_id"] for item in filtered], ["p-direct"])

    def test_source_filter_rejects_product_embeddings_in_evidence(self) -> None:
        cases = (
            ("桂枝汤出处", "新品桂枝汤圆上市"),
            ("大承气汤出处", "厨房使用大承气汤锅"),
            ("五苓散出处", "这是五苓散装产品"),
            ("肾气丸出处", "儿童喜欢肾气丸子"),
            ("木香饼出处", "木香饼干上市"),
        )
        for query, text in cases:
            with self.subTest(query=query):
                evidence = result(text)
                self.assertEqual(
                    pdf_vector.filter_results_for_intent(query, "source_lookup", [evidence]),
                    [],
                )
                answer = pdf_vector.synthesize_pdf_rag_answer(query, [evidence])
                self.assertEqual(answer["citations"], [])
                self.assertIn("没有检索到足够可靠", answer["answer"])

    def test_source_filter_accepts_valid_formula_and_named_anchor_prose(self) -> None:
        cases = (
            ("桂枝汤出处", "太阳中风，桂枝汤主之。"),
            ("木香饼出处", "木香饼（生地木香作饼），热熨贴之。"),
            ("太阳病原文", "太阳病欲解时，从巳至未上。"),
            ("一钱原文", "一钱是5克。"),
        )
        for query, text in cases:
            with self.subTest(query=query):
                evidence = result(text)
                self.assertEqual(
                    pdf_vector.filter_results_for_intent(query, "source_lookup", [evidence]),
                    [evidence],
                )
                self.assertTrue(
                    pdf_vector.synthesize_pdf_rag_answer(query, [evidence])["citations"]
                )

    def test_named_anchor_evidence_accepts_ordinary_prose_continuations(self) -> None:
        cases = (
            ("木香饼出处", "木香饼外敷于患处。"),
            ("木香饼出处", "木香饼可用于热熨。"),
            ("太阳病原文", "太阳病发热汗出。"),
            ("太阳病原文", "太阳病有头痛发热。"),
            ("一钱原文", "一钱重五克。"),
            ("一钱原文", "一钱折合三点七五克。"),
            ("黄金比例原文", "黄金比例达到一比一。"),
        )
        for query, text in cases:
            with self.subTest(text=text):
                evidence = result(text)
                self.assertEqual(
                    pdf_vector.filter_results_for_intent(query, "source_lookup", [evidence]),
                    [evidence],
                )

    def test_derived_unit_fields_cannot_ground_source_anchor(self) -> None:
        evidence = result("普通课程介绍。")
        evidence["matched_knowledge_units"] = [
            {
                "unit_type": "formula_pattern",
                "subject": "桂枝汤",
                "predicate": "主治",
                "object": "太阳中风",
                "evidence_quote": "头痛者另论",
            }
        ]

        self.assertEqual(
            pdf_vector.filter_results_for_intent("桂枝汤出处", "source_lookup", [evidence]),
            [],
        )
        answer = pdf_vector.synthesize_pdf_rag_answer("桂枝汤出处", [evidence])
        self.assertEqual(answer["citations"], [])
        self.assertNotIn("原文摘录", answer["answer"])

    def test_primary_paragraph_or_contained_quote_can_ground_source_anchor(self) -> None:
        for paragraph, quote in (
            ("桂枝汤主之。", ""),
            ("课程原文说：太阳中风，桂枝汤主之。", "太阳中风，桂枝汤主之。"),
        ):
            with self.subTest(paragraph=paragraph, quote=quote):
                evidence = result(paragraph)
                evidence["matched_knowledge_units"] = [
                    {"subject": "桂枝汤", "evidence_quote": quote}
                ]
                answer = pdf_vector.synthesize_pdf_rag_answer("桂枝汤出处", [evidence])
                self.assertTrue(answer["citations"])
                self.assertIn("桂枝汤", answer["citations"][0]["evidence_quote"])

    def test_uncontained_derived_quote_cannot_assert_or_cite_clinical_formula(self) -> None:
        evidence = result("患者恶寒咳嗽、下利恶心，原文提醒仍需辨证。")
        evidence["matched_knowledge_units"] = [
            {
                "unit_type": "formula_pattern",
                "subject": "桂枝汤",
                "object": "恶寒咳嗽",
                "evidence_quote": "太阳中风，桂枝汤主之。",
            }
        ]

        answer = pdf_vector.synthesize_pdf_rag_answer(
            "患者恶寒咳嗽、下利恶心，开什么方？", [evidence]
        )

        self.assertNotIn("桂枝汤", answer["answer"])
        self.assertTrue(answer["citations"])
        self.assertNotIn("桂枝汤", answer["citations"][0]["evidence_quote"])

    def test_blank_paragraph_with_derived_quote_is_insufficient_evidence(self) -> None:
        evidence = result("")
        evidence["matched_knowledge_units"] = [
            {
                "unit_type": "formula_pattern",
                "subject": "桂枝汤",
                "object": "太阳中风",
                "evidence_quote": "太阳中风，桂枝汤主之。",
            }
        ]

        for query in ("桂枝汤出处", "课程如何理解"):
            with self.subTest(query=query):
                answer = pdf_vector.synthesize_pdf_rag_answer(query, [evidence])
                self.assertEqual(answer["citations"], [])
                self.assertIn("没有检索到足够可靠的原文证据", answer["answer"])
                self.assertNotIn("原文要点包括：。", answer["answer"])

    def test_uncontained_derived_dosage_quote_cannot_make_unrelated_paragraph_evidence(
        self,
    ) -> None:
        evidence = result("普通课程目录介绍。")
        evidence["matched_knowledge_units"] = [
            {
                "unit_type": "dosage",
                "subject": "一钱",
                "object": "99克",
                "evidence_quote": "一钱等于99克。",
            }
        ]

        answer = pdf_vector.synthesize_pdf_rag_answer("古时候一钱是多少克？", [evidence])

        self.assertEqual(answer["citations"], [])
        self.assertIn("没有检索到足够可靠的原文证据", answer["answer"])
        self.assertNotIn("99克", answer["answer"])

    def test_source_citation_prefers_verified_contained_quote(self) -> None:
        evidence = result("课程前言。太阳中风，桂枝汤主之。后续说明。")
        evidence["matched_knowledge_units"] = [{"evidence_quote": "太阳中风，桂枝汤主之。"}]

        answer = pdf_vector.synthesize_pdf_rag_answer("桂枝汤出处", [evidence])

        self.assertEqual(answer["citations"][0]["evidence_quote"], "太阳中风，桂枝汤主之。")

    def test_cross_script_derived_quote_is_not_emitted_as_literal_original(self) -> None:
        evidence = result("太陽中風，桂枝湯主之。")
        evidence["matched_knowledge_units"] = [{"evidence_quote": "太阳中风，桂枝汤主之。"}]

        answer = pdf_vector.synthesize_pdf_rag_answer("桂枝汤出处", [evidence])

        self.assertIn("桂枝湯", answer["citations"][0]["evidence_quote"])
        self.assertNotIn("桂枝汤", answer["citations"][0]["evidence_quote"])

    def test_unknown_explicit_formula_source_results_are_prioritized_and_visible(self) -> None:
        unrelated = result("普通课程介绍。", paragraph_id="p-unrelated", page=1)
        matching = result(
            "背景说明" * 80 + "。白虎加人参汤用于本段讨论。",
            paragraph_id="p-matching",
            page=2,
        )

        answer = pdf_vector.synthesize_pdf_rag_answer("白虎加人参汤出处", [unrelated, matching])

        self.assertEqual(answer["citations"][0]["paragraph_id"], "p-matching")
        self.assertIn("白虎加人参汤", answer["citations"][0]["evidence_quote"])

    def test_unknown_formula_like_source_topic_stays_neutral_and_prioritized(self) -> None:
        unrelated = result("普通课程介绍。", paragraph_id="p-unrelated", page=1)
        matching = result("本段逐字出现桂枝热汤这个词。", paragraph_id="p-topic", page=2)

        answer = pdf_vector.synthesize_pdf_rag_answer("桂枝热汤出处", [unrelated, matching])

        self.assertEqual(answer["citations"][0]["paragraph_id"], "p-topic")
        self.assertIn("桂枝热汤", answer["citations"][0]["evidence_quote"])
        self.assertIn("关于", answer["answer"])
        self.assertNotIn("方名", answer["answer"])

    def test_citation_uses_valid_later_anchor_span_after_product_mention(self) -> None:
        cases = (
            ("桂枝汤出处", "桂枝汤圆上市", "桂枝汤主之"),
            ("五苓散出处", "五苓散装产品介绍", "五苓散主之"),
            ("木香饼出处", "木香饼干上市", "木香饼外敷"),
            ("太阳病原文", "太阳病人", "太阳病发热"),
            ("一钱原文", "一钱包", "一钱重五克"),
        )
        for query, invalid, valid in cases:
            with self.subTest(query=query):
                paragraph = f"{invalid}。" + "背景说明" * 70 + f"。{valid}。"
                answer = pdf_vector.synthesize_pdf_rag_answer(query, [result(paragraph)])
                excerpt = answer["citations"][0]["evidence_quote"]
                self.assertIn(valid, excerpt)
                self.assertNotEqual(excerpt.strip("。"), invalid)
                self.assertLessEqual(len(excerpt), 220)

    def test_multi_anchor_fallback_uses_validated_offsets_after_invalid_first_match(self) -> None:
        query = "桂枝汤、麻黄汤出处"
        paragraph = (
            "桂枝汤圆上市。"
            + "背景说明" * 70
            + "。桂枝汤主之。"
            + "补充材料" * 70
            + "。麻黄汤主之。"
        )

        answer = pdf_vector.synthesize_pdf_rag_answer(query, [result(paragraph)])
        excerpt = answer["citations"][0]["evidence_quote"]

        self.assertLessEqual(len(excerpt), 220)
        self.assertIn("桂枝汤主之", excerpt)
        self.assertIn("麻黄汤主之", excerpt)
        self.assertNotIn("桂枝汤圆", excerpt)

    def test_cough_followups_do_not_inject_unseen_gastrointestinal_clues(self) -> None:
        questions = pdf_vector.build_followup_questions(
            "患者咳嗽、怕冷、无汗",
            "clinical",
            [{"content": "恶寒无汗而喘，麻黄汤主之。"}],
            [{"evidence_quote": "恶寒无汗而喘，麻黄汤主之。"}],
        )
        joined = "\n".join(questions)

        for clue in ("下利", "恶心", "腹痛", "心下痞"):
            self.assertNotIn(clue, joined)

    def test_followups_are_empty_without_a_differentiating_clue(self) -> None:
        questions = pdf_vector.build_followup_questions(
            "患者想了解课程相关线索",
            "clinical",
            [{"content": "麻黄汤主之。"}],
            [{"evidence_quote": "麻黄汤主之。"}],
        )

        self.assertEqual(questions, [])

    def test_followups_do_not_add_absent_differentiation_or_safety_facts(self) -> None:
        questions = pdf_vector.build_followup_questions(
            "患者下利",
            "clinical",
            [],
            [
                {
                    "subject": "某汤",
                    "predicate": "主治",
                    "object": "下利",
                    "evidence_quote": "下利，某汤主之。",
                }
            ],
        )
        joined = "\n".join(questions)

        self.assertIn("下利", joined)
        for absent in ("黄臭", "寒利", "完谷不化", "腹痛", "妊娠", "附子", "峻下"):
            self.assertNotIn(absent, joined)

    def test_followups_can_derive_a_question_from_guide_node_label(self) -> None:
        questions = pdf_vector.build_followup_questions(
            "患者情况待核对",
            "clinical",
            [{"label": "麻黄汤", "content": "", "path": "方证 > 麻黄汤"}],
            [],
        )

        self.assertTrue(any("麻黄汤" in question for question in questions))


class RetrievalAnswerabilityRegressionTests(unittest.TestCase):
    def test_sweat_comparison_clinical_answer_is_direct_and_quotes_original(self) -> None:
        evidence = result(
            "病人时常发热自汗而不愈，卫气不和，宜桂枝汤。麻黄汤一定是无汗，身痛、恶寒较重。"
        )

        answer = pdf_vector.synthesize_pdf_rag_answer(
            "感冒后怕冷，有汗和无汗在课程里分别该看哪些分水岭？",
            [evidence],
        )

        self.assertIn("有汗或汗出", answer["answer"])
        self.assertIn("核对桂枝汤证", answer["answer"])
        self.assertIn("核对麻黄汤证", answer["answer"])
        self.assertIn("发热自汗", answer["answer_sections"]["key_points"][0]["text"])
        self.assertIn("麻黄汤一定是无汗", answer["citations"][0]["evidence_quote"])
        self.assertIn("不能据此", answer["answer"])

    def test_three_grade_gap_names_primary_corpus_and_opt_in_reference_boundary(self) -> None:
        answer = pdf_vector.synthesize_pdf_rag_answer(
            "《神农本草》课程里上中下三品的分类重点是什么？",
            [],
        )

        self.assertIn("默认主课程语料", answer["answer"])
        self.assertIn("同时解释上、中、下三品", answer["answer"])
        self.assertIn("--include-references", answer["answer"])
        self.assertIn("非倪海厦著作", answer["answer"])
        self.assertEqual(answer["citations"], [])

    def test_four_seasons_answer_states_supported_mapping_and_missing_scope(self) -> None:
        long_summer = result(
            "如果我们把它分成春夏秋冬，中间就是所谓长夏，长夏就是节气交换时。",
            paragraph_id="p-long-summer",
            page=31,
        )
        organs = result(
            "春天就是肝脏，夏天就是心脏，秋天是肺脏，冬天是肾脏。",
            paragraph_id="p-organs",
            page=239,
        )

        answer = pdf_vector.synthesize_pdf_rag_answer(
            "《黄帝内经》课程怎样讲春夏秋冬与养生的对应关系？",
            [long_summer, organs],
        )

        self.assertIn("春、夏、秋、冬依次联系到肝、心、肺、肾", answer["answer"])
        self.assertIn("节气交换阶段称为“长夏”", answer["answer"])
        self.assertIn("没有完整列出", answer["answer"])
        self.assertIn("春天就是肝脏", answer["answer_sections"]["key_points"][0]["text"])
        self.assertNotIn("针", answer["answer_sections"]["key_points"][0]["text"])
        self.assertEqual(answer["answer_sections"]["citation_count"], 2)

    def test_chest_bi_learning_mainline_prefers_chapter_evidence(self) -> None:
        formula_detail = result(
            "胸痹之病，喘息咳唾，胸背痛，短气。",
            paragraph_id="p-formula",
            page=106,
        )
        chapter = result(
            "胸痹心痛短气病脉证第九篇，《金匮》第九篇。",
            paragraph_id="p-chapter",
            page=105,
        )

        answer = pdf_vector.synthesize_pdf_rag_answer(
            "《金匮要略》课程里胸痹的学习主线是什么？",
            [formula_detail, chapter],
        )

        self.assertEqual(
            [citation["paragraph_id"] for citation in answer["citations"]],
            ["p-chapter"],
        )
        self.assertIn("学习起点", answer["answer"])
        self.assertIn("第九篇", answer["answer_sections"]["key_points"][0]["text"])
        self.assertIn("不是心血管疾病诊断", answer["safety_notice"])

    def test_formula_comparison_answer_is_direct_and_citation_bound(self) -> None:
        evidence = result(
            "病人时常发热自汗而不愈，卫气不和，宜桂枝汤。麻黄汤一定是无汗，身痛、恶寒较重。"
        )

        answer = pdf_vector.synthesize_pdf_rag_answer(
            "桂枝汤和麻黄汤的方证如何鉴别？",
            [evidence],
        )

        self.assertIn("首要分水岭是汗", answer["answer"])
        self.assertIn("发热自汗", answer["citations"][0]["evidence_quote"])
        self.assertIn("无汗", answer["citations"][0]["evidence_quote"])
        self.assertIn("不是个人选方", answer["safety_notice"])

    def test_combination_answer_requires_both_entities_and_names_four_gates(self) -> None:
        incomplete = result("合谷是手阳明大肠经穴。", paragraph_id="p-incomplete")
        grounded = result("四关就是太冲还有合谷，合谷和太冲叫四关。", paragraph_id="p-grounded")

        answer = pdf_vector.synthesize_pdf_rag_answer(
            "合谷和太冲合称什么",
            [incomplete, grounded],
        )

        self.assertEqual([item["paragraph_id"] for item in answer["citations"]], ["p-grounded"])
        self.assertIn("合称“四关”", answer["answer"])
        self.assertIn("合谷和太冲叫四关", answer["citations"][0]["evidence_quote"])

    def test_urgent_symptoms_precede_insufficient_evidence(self) -> None:
        answer = pdf_vector.synthesize_pdf_rag_answer("60岁胸痛、气短能否直接选方？", [])

        self.assertTrue(answer["answer"].startswith(pdf_vector.EMERGENCY_SAFETY_NOTICE))
        self.assertIn("不要等待课程资料检索结果", answer["safety_notice"])

    def test_tianji_and_systematic_review_report_capability_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "rag.sqlite"
            store = pdf_vector.LocalVectorStore(db_path)
            store.recreate()
            store.insert_paragraphs(
                [pdf_vector.ParsedParagraph("p1", "doc", "/tmp/伤寒.pdf", "伤寒", 1, 1, "太阳病。")]
            )

            tianji_gap = pdf_vector.rag_capability_gap("天纪的先天卦与后天卦", db_path)
            learning_gap = pdf_vector.rag_capability_gap("系统复习伤寒论应该按什么顺序", db_path)

        self.assertIn("RAG PDF 语料不包含《天纪》", tianji_gap)
        self.assertIn("references/learning-entry.md", learning_gap)


if __name__ == "__main__":
    unittest.main()
