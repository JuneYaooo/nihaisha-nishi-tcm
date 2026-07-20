---
name: nihaisha
description: Use this skill when the user asks about Ni Haisha / 倪海厦 TCM course material, especially Shang Han Lun / 伤寒论, Jingui / 金匮要略, Zhongjing Xinfa / 仲景心法, clinical cases / 临床案例 / 倪师医案, Bagang Bianzheng / 八纲辨证, Fuyang Forum / 扶阳论坛, Yijinjing / 易筋经, Liang Dong dialogue / 梁冬对话倪师, Stanford lecture / 斯坦福大学演讲, Tianji / 天纪 / 易经 / 阳宅 / 紫微斗数, Huangdi Neijing / 黄帝内经, Shennong Bencao / 神农本草, acupuncture / 针灸, meridians, acupoints, six-channel pattern identification, symptom-to-formula routing, formula comparison, lesson review, board/PPT screenshot evidence, or course-derived study notes. This skill is for educational distillation and study support only, not medical diagnosis, prescriptions, dosage, or individualized treatment.
metadata:
  short-description: 倪海厦《伤寒论》《金匮要略》《仲景心法》《临床案例》《八纲辨证》《扶阳论坛》《易筋经》《梁冬对话》《斯坦福演讲》《天纪》《黄帝内经》《神农本草》《针灸》课程学习、方证穴位辨析和板书证据索引
---

# Nihaisha 中医课程资料

## Scope

Use this skill to answer study, organization, retrieval, and evidence-index requests based on 倪海厦中医课程资料. Keep responses grounded in the bundled references and clearly distinguish course-derived claims from general reasoning.

This skill is educational. Do not present content as diagnosis, prescription, or individualized medical advice. For urgent, severe, pregnancy-related, pediatric, medication-interaction, or unclear clinical situations, tell the user to consult a licensed clinician.

## Workflow

### Default Retrieval Policy

- The default path is the lightweight bundled Skill: read `references/index.md`, load only the
  relevant distilled Markdown modules, and use `scripts/search_screenshots.py` or
  `scripts/search_pdf_evidence.py` when source evidence is needed.
- Do not create a virtual environment, install the RAG runtime, invoke `nihaisha_kg`, or download
  RAG assets for ordinary course questions, symptom-study questions, formula comparisons, lesson
  review, screenshot lookup, or PDF/page evidence lookup.
- Full-corpus RAG is explicit opt-in only. If the user asks to use RAG and verified assets are
  already present, it may be used for that request. If assets are missing, explain the approximate
  3.68 GB size, public Hugging Face source, and local destination, but do not download anything.
  A request to use RAG is not permission to download its data; download only when the user
  separately and explicitly asks to download the RAG assets. Lightweight retrieval being
  insufficient never authorizes an automatic download.
- Formula-pattern comparisons stay on `references/formula-patterns.md` plus
  `references/six-channel.md` by default. Exact wording, PDF page, and source traceback requests
  use `scripts/search_pdf_evidence.py` first.

1. Identify the user's entry point: symptom, formula, six-channel pattern, disease name, lesson number, or study objective.
2. Open `references/index.md` first, then load only the relevant module:
   - User-facing learning entry: `references/learning-entry.md`.
   - Beginner/plain-language questions: `references/beginner-questions.md`.
   - Detailed scenario routing: `references/usage-scenarios.md`.
   - Symptoms or cases: `references/symptom-index.md`, then `references/six-channel.md`, then `references/formula-patterns.md` if a formula comparison is needed.
   - Formula queries: `references/formula-patterns.md`, with `references/six-channel.md` for context.
   - Six-channel review: `references/six-channel.md`.
   - Lesson review or learning plans: `references/lesson-map.md`.
   - Jingui / 金匮要略 questions: `references/jingui.md`; use `references/jingui-screenshot-evidence.md` for board, acupuncture-demo, or source-evidence lookups.
   - Zhongjing Xinfa / 仲景心法 questions: `references/zhongjing-xinfa.md`; use `references/zhongjing-xinfa-screenshot-evidence.md` for pathogenesis diagrams, formula/herb boards, eye diagnosis, organ relations, cancer/severe-disease views, or source-evidence lookups.
   - Clinical cases / 临床案例 / 倪师医案 questions: `references/clinical-cases.md`; use `references/clinical-cases-screenshot-evidence.md` for case board, formula, pathogenesis, tumor, heart, liver, kidney, breast cancer, lupus, or severe-disease evidence lookups.
   - Bagang Bianzheng / 八纲辨证 questions: `references/bagang.md`; use `references/bagang-screenshot-evidence.md` for representative lecture frames/subtitle evidence. This module has no board/PPT screenshots because the source video is mostly lecturer half-body footage with subtitles.
   - Fuyang Forum / 扶阳论坛 questions: `references/fuyang.md`; use `references/fuyang-screenshot-evidence.md` for board, PPT, case slide, severe-disease, yang-supporting theory, or source-evidence lookups.
   - Yijinjing / 易筋经 questions: `references/yijinjing.md`; use `references/yijinjing-screenshot-evidence.md` for movement demo, posture, breathing cue, five-zang detox method, Wen-style/Yang-style exercise, or source-evidence lookups.
   - Liang Dong dialogue / 梁冬对话倪师 questions: `references/liangdong.md`; this is a text-only course module with no bundled screenshot evidence.
   - Stanford lecture / 斯坦福大学演讲 questions: `references/stanford.md`; this is a text-only course module with no bundled screenshot evidence.
   - Tianji / 天纪 / 易经 / 阳宅 / 紫微斗数 questions: `references/tianji.md`; use `references/tianji-screenshot-evidence.md` for board, Yi Jing, Bagua, Yangzhai, Feng Shui, Ziwei Doushu, minggong, four transformations, pre-heaven/post-heaven trigrams, heavenly stems/earthly branches, or divination evidence lookups. Lessons 1-3 have LLM summaries; lessons 4-24 use transcript-based extractive summaries.
   - Huangdi Neijing / 黄帝内经 questions: `references/huangdi.md`; use `references/huangdi-screenshot-evidence.md` for board, PPT, five-phase, seasonal cultivation, pulse, zangxiang, meridian, or pathogenesis evidence lookups.
   - Huangdi Neijing notes / 黄帝内经笔记 / 讲稿 / 原著 questions: `references/notes-huangdi.md`; use after `references/huangdi.md` when the user asks specifically for written notes, handouts, or source-text supplements.
   - Shennong Bencao / 神农本草 questions: `references/bencao.md`; use `references/bencao-screenshot-evidence.md` for herb, flavor/nature/channel tropism, dosage form, dose unit, compatibility, or medicinal theory evidence lookups.
   - Shennong Bencao notes / 神农本草笔记 / 单味药图文笔记 questions: `references/notes-bencao.md`; use after `references/bencao.md` for written note or herb-note supplement lookups.
   - Acupuncture / 针灸 questions: `references/acupuncture.md`; use `references/acupuncture-screenshot-evidence.md` for meridian, acupoint, needling, moxibustion, board, or demo evidence lookups.
   - Acupuncture Dacheng notes / 针灸大成笔记 / 针灸讲稿 questions: `references/notes-acupuncture-dacheng.md`; use after `references/acupuncture.md` for written note or handout supplement lookups.
   - Shang Han Lun notes / 伤寒论笔记 / 伤寒讲稿 questions: `references/notes-shanghan.md`; use after `references/shanghanlun.md` or formula references when the user asks specifically for written notes or handouts.
   - Jingui notes / 金匮要略笔记 / 金匮讲稿 questions: `references/notes-jingui.md`; use after `references/jingui.md` when the user asks specifically for written notes or handouts.
   - Course PDF/DOC / 古籍方证溯源 / 文案校对 questions: `references/ebooks.md`, `references/pdf-evidence/index.md`, and `references/text-evidence/index.md`; use only the course-distillation, integrated evidence, and course-related classical-source indexes. Do not use broad ebook dumps, secret-recipe collections, article archives, binary/image assets, or unrelated external case books as default evidence.
   - Ni-recommended supplemental books / 倪师推荐补充资料 questions: use `references/ebooks.md` to check source role and edition/OCR/extraction caveats. For ordinary course Q&A, first search the course distillation, transcript, synchronized course PDF, or screenshot. Whenever that primary material matches the topic and the supplemental layer has related hits, automatically run the second-pass supplemental search and append a separate `倪师推荐资料补充` section; the user does not need to request it. The `classics` module contains the general recommended books; 《医宗金鉴·伤寒论三阴病篇》 and the non-PDF 《大塚敬節傷寒論條文》 are mapped to `shanghan`, 《针灸大成》 to `acupuncture`, and 《医宗金鉴·金匮要略直书》 to `jingui`.
   - Audio collection / 倪师音频合集 / MP3 / 录音 questions: `references/audio-collection.md`; use to map local audio files to already-distilled course modules.
   - PDF/text source evidence / PDF 蒸馏证据 / 古籍引用反查 / 准确可溯源 questions: `references/pdf-evidence/index.md` and, for non-PDF supplements, `references/text-evidence/index.md`; use `python scripts/search_pdf_evidence.py <term...> --module <module>`. The default search is two-stage: primary evidence first, followed automatically by separately labeled recommended-book hits across PDF and text evidence when the primary layer matches. Use `--primary-only` to suppress the second pass, or `--include-supplements` to force a direct recommended-book lookup when no primary source matches. Add `--show-full-page` only when the whole page/section is needed. Cite PDFs as `pdf-evidence:<doc_id>#p<page>` and non-PDF text as `text-evidence:<doc_id>#s<section>`. Do not open large evidence-card files wholesale. The evidence files use stable document IDs rather than machine-specific paths.
   - Optional full-corpus RAG: only after explicit user opt-in and only when verified local assets are already present, use the local `nihaisha_kg` runtime described in **Optional RAG Runtime Assets** below for cross-corpus semantic retrieval or deeper original-paragraph exploration. Prefer `text` for exact wording and `hybrid` for semantic questions. Keep `reference_secondary` results separate and label them `关联参考资料（非倪海厦著作）`.
   - Course overview or integrated lookup: `references/shanghanlun.md`.
   - Board/PPT/source evidence: use `python scripts/search_screenshots.py <query or terms...>` for ranked results across all screenshot evidence files. The script normalizes natural-language queries and compound terms; use `--show-terms` when checking how a query was split.
3. Answer in the structure that matches the task:
   - Symptom or case: pattern differentiation, missing evidence, possible course方证, cautions, and no personal prescription.
   - Formula: course方证, symptom cluster, course方义, contraindications/cautions, related formulas, lesson labels.
   - Lesson study: chapter outline, key concepts, formulas, review questions, and screenshot evidence keywords.
   - Evidence request: return course, timestamp/page/section, brief note, relative screenshot path, `pdf-evidence:<doc_id>#p<page>`, or `text-evidence:<doc_id>#s<section>` citation. Prefer results that match all important query terms.
   - Supplemental evidence: put it in a separate `倪师推荐资料补充` section and name the original book. Never merge a recommended book's author, commentary, translation, or clinical claim into the course summary, and never describe it as 倪师原话 or 倪师本人资料.
   - Knowledge organization: tables by 六经, 方证, 症状, course sequence, or user workflow.
4. Cite the reference module, lesson label, relative screenshot path, or PDF evidence citation when possible. Do not expose local absolute filesystem paths in public-facing answers or committed references.

Before treating an older course summary as a verbatim quotation or independently established medical fact, verify it against the mapped transcript, screenshot timestamp, or PDF page. Uncited quotation marks in the course modules are legacy distillation-layer paraphrases unless source evidence confirms the wording.

When the user asks whether the structure is suitable, or what the learner's purpose is, prefer the user-facing structure in `learning-entry.md` over the course sequence. Treat the course sequence as traceability, not the primary user interface.

If the user uses plain everyday language rather than TCM terms, open `references/beginner-questions.md` first. Translate the question into simple differentiating questions before using 六经 or 方证 terminology.

## Optional RAG Runtime Assets

This runtime is an advanced, non-default capability. Its presence in the repository does not
authorize automatic installation, download, or invocation. Do not route ordinary formula
comparisons, course questions, screenshots, or PDF/page lookups here.

The five production runtime files are published separately as the public Hugging Face Dataset
`JuneYao/nihaisha-rag-assets`, pinned to `production-2026-07-15` (3,679,424,241 bytes, about
3.68 GB). They are intentionally not committed to GitHub.

Before an explicitly requested RAG lookup, check for `data/pdf_rag_bge_m3/rag.sqlite`. If the
asset set is missing or incomplete, tell the user that the complete download is about 3.68 GB,
comes from the public Hugging Face Dataset above, and will be stored under
`data/pdf_rag_bge_m3/`. Stop without downloading. Only run the following commands after the user
separately and explicitly asks to download the RAG assets:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[runtime]"
python3 -m nihaisha_kg download-assets
python3 -m nihaisha_kg doctor
```

The downloader needs no Hugging Face account, token, CLI, or Git LFS. It resumes `.part` files,
replaces final files only after a complete download, and verifies the expected byte count and
SHA256 for all five assets. Re-running it verifies and skips intact files. Retrieve only after
`doctor` reports `status: ok`.

Useful commands:

```bash
python3 -m nihaisha_kg search "原词" --mode text --limit 5
python3 -m nihaisha_kg search "麻黄汤对应什么方证" --mode graph --limit 5
python3 -m nihaisha_kg answer "桂枝汤和麻黄汤的方证如何鉴别？" --mode hybrid --limit 8
python3 -m nihaisha_kg answer "关联资料中的相关原文" --mode text --limit 8 --include-references
```

`text`, `knowledge`, and `graph` need no API key. `vector` and `hybrid` require FAISS plus a
query embedding backend. Every visible answer citation must point to an original paragraph with
portable source, page, paragraph ID, evidence ID, and previous/next context. Graph relations,
guide nodes, linked-reference cards, and other derived records are navigation only. They cannot
replace original evidence or enter the primary conclusion on their own.

## Safety Requirements

- Always frame the content as 倪海厦课程学习 or 中医理论整理, not medical diagnosis.
- Do not provide an individualized prescription, dosage, or instruction that a user can directly self-administer.
- Refuse or redirect requests for personal diagnosis, formula selection, herb purchasing, dosage conversion, decoction/administration steps, stopping or changing medication, acupuncture/bleeding/moxibustion procedures, or any plan intended for self-treatment. Offer a study-oriented explanation of the course concept instead.
- Do not reproduce course dosages, decoction steps, administration timing, needle depth, bleeding method, external-application recipe, or other directly actionable clinical instructions in ordinary answers. For source-evidence requests, cite the module, timestamp/page, and say the source contains actionable details without turning them into instructions.
- Do not discourage or replace standard medical care. Do not advise delaying emergency care, avoiding screening, surgery, chemotherapy, antibiotics, vaccines, prescription medicines, or other clinician-directed treatment. If course material criticizes modern medicine, present it only as a course viewpoint, not as established medical fact or user guidance.
- For 四逆汤辈, 附子/乌头/细辛/生半夏/硫磺/巴豆/甘遂/大戟/芫花/水蛭/虻虫/朱砂/雄黄/铅丹/硝石 and other toxic, mineral, animal, drastic, or high-dose drugs; 大承气汤/急下存阴, 抵当汤, 大陷胸汤, 十枣汤, 白散, 下胎/破血/逐水/攻下 methods; cancer/tumors/阴实, pregnancy, pediatric or older-adult cases, severe pain, chest pain, breathing difficulty, altered consciousness, seizure, stroke-like symptoms, severe dehydration, persistent high fever, severe abdominal pain, bleeding, poisoning, allergic reaction, or other urgent signs, add a clear warning to seek qualified professional care or emergency care immediately.
- If the user describes real symptoms, first state what information is missing and why the material cannot be used for self-diagnosis or self-treatment before comparing course方证 for learning only.
- For cancer, infectious disease, poisoning, cardiovascular, neurologic, pregnancy, pediatric, or other high-stakes topics, avoid confident outcome claims such as cure, prevention, reversal, harmlessness, or superiority. Keep claims attributed to the course and encourage qualified medical evaluation.

## Style

Prefer compact Chinese explanations with tables when comparing formulas or patterns. Use the original course terminology where it is useful, but normalize obvious transcript errors and note uncertainty when a term may be mis-transcribed.

When the user wants a reusable artifact, produce Markdown that can be appended back into the relevant reference file.
