<div align="center">

# nihaisha

**Turn Ni Haisha's Traditional Chinese Medicine course materials into a searchable, traceable Agent Skill with clear safety boundaries.**

A Claude Code / Codex / OpenClaw Skill. Once installed in an agent, it lets you use natural language to search Ni Haisha course materials by symptom, formula, acupoint, course module, lesson, or board/PPT screenshot, then returns study-oriented pattern analysis, formula/acupoint/herb comparisons, lesson review plans, and screenshot evidence indexes.

[![GitHub stars](https://img.shields.io/github/stars/JuneYaooo/nihaisha-nishi-tcm?style=flat)](https://github.com/JuneYaooo/nihaisha-nishi-tcm/stargazers)
[![Skill](https://img.shields.io/badge/Agent-Skill-orange.svg)](../SKILL.md)
[![TCM](https://img.shields.io/badge/TCM-Ni%20Haisha-green.svg)](../references/index.md)
[![Course](https://img.shields.io/badge/course-multi--module-blue.svg)](../references/index.md)

**中文** → [../README.md](../README.md)

</div>

> **Note**: This project still has some known issues and is under active iteration. Please check back periodically for updates and install the latest version when available.

---

## Course Distillation Method

The course distillation method used in this project comes from the author's [lineage-skill](https://github.com/JuneYaooo/lineage-skill), which turns dense course materials into traceable, reusable Agent Skills.

## Update Log

### 2026-07-16

- Integrated all 11 recommended PDFs and the remaining legacy DOC from the supplied archive as a separately labeled Ni-recommended supplemental layer.
- The DOC archive name says *Otsuka Keisetsu Shanghan Commentary*, but its internal title and extracted content are *Otsuka Keisetsu Shanghan Clauses*: Zhang Zhongjing's preface plus 182 selected clauses/prompts. It is cited by 183 real sections, never by invented PDF pages.
- Primary course matches now automatically trigger a separate second pass across both PDF and non-PDF recommended supplements.

### 2026-06-25

- Based on course proofreading materials organized by Qihuang Shengxian Zhihui, this update corrects a set of terminology, formula-name, acupoint-name, and classical-citation errors that came from earlier video/audio transcription.
- Added page-level PDF evidence under [`references/pdf-evidence/`](../references/pdf-evidence/) so course-text corrections can be traced by source, page, and keyword.
- Added a classical-source, formula-pattern, and terminology index entry at [`references/ebooks.md`](../references/ebooks.md) for checking classical references mentioned in the courses.
- Term indexes are split by module, including Shang Han Lun, Jingui, Zhongjing Xinfa, acupuncture, Huangdi Neijing, and Shennong Bencao, so learners can search by topic.

## What it does

- **Plain-language entry point**: turns everyday descriptions such as "cold with chills", "cold hands and feet", "diarrhea", or "cannot sleep" into the differentiating questions used in the courses.
- **Multi-course retrieval**: covers Shang Han Lun, Jingui Yaolue, Zhongjing Xinfa, clinical cases, Bagang pattern identification, Fuyang Forum, Yijinjing, the Liang Dong interview, Stanford lecture, Tianji, Huangdi Neijing, Shennong Bencao, acupuncture courses, plus course handouts, study notes, and audio collection mappings.
- **Six-channel and formula-pattern navigation**: organizes the core Shang Han Lun material by six-channel patterns, symptoms, formulas, and disease-transmission logic.
- **Acupoint and herb study**: searches acupuncture channels and points, point-combination ideas, and Shennong Bencao course material on herb properties, dosage forms, compatibility, and single-herb clues.
- **Lesson-by-lesson review**: builds topic maps, keywords, and review questions by course module and lesson.
- **Screenshot evidence**: includes 2,986 screenshot evidence entries, with compressed WebP images stored in the repo. Search by formula name, acupoint, lesson, pathomechanism, Tianji keyword, or timestamp.
- **PDF source evidence**: includes 22 PDF sources, 10,538 physical-page records (10,461 complete text pages, 59 scanned visual/low-confidence pages without searchable OCR body text, 6 excluded non-content pages, and 12 native blank pages), plus 6 course-module term indexes and 1 full-text Ni-recommended supplemental module. A primary course match automatically triggers a separate second-pass search of recommended supplements.
- **Non-PDF text evidence**: includes 1 recommended DOC split into 183 preface/clause sections, cited as `text-evidence:<doc_id>#s<section>` and always kept separate from Ni Haisha's own material.
- **Safety boundary**: defaults to course study and TCM theory organization. It does not provide personal diagnosis, prescriptions, or dosage guidance.

## Best-fit use cases

| Use case | Fit | Notes |
| --- | --- | --- |
| Study Ni Haisha's courses | Strong | Review by course module, lesson, topic, and screenshot evidence. |
| Look up a formula pattern from the courses | Strong | Can return symptom clusters, pathomechanism layers, related formulas, and contraindication reminders. |
| Search acupuncture, channels, and points | Strong | Search by acupoint, channel, point-combination scenario, and practical screenshots. |
| Study materia medica or Neijing theory | Good | Enters the Shennong Bencao and Huangdi Neijing modules for course-based study notes. |
| Ask in plain language | Strong | First converts plain symptoms into pattern-identification decision points, then maps them to course terms. |
| Find board, PPT, or practical screenshots | Good | Search screenshot evidence by course module, keyword, formula, acupoint, lesson, or timestamp. |
| Check page-level PDF evidence | Good | Trace proofreading PDFs by course module, term, formula, acupoint, or classical-source keyword. |
| Organize study notes | Good | Can generate Markdown notes that can be appended to `references`. |
| Make real-world medication decisions | Not suitable | This skill does not provide personal diagnosis, prescriptions, dosage, or self-medication advice. |

## Course modules

| Module | Text material | Screenshot evidence |
| --- | --- | --- |
| Shang Han Lun | [`references/shanghanlun.md`](../references/shanghanlun.md), [`references/lesson-map.md`](../references/lesson-map.md), plus six-channel/formula/symptom submodules | [`references/screenshot-evidence.md`](../references/screenshot-evidence.md) 649 images |
| Jingui Yaolue | [`references/jingui.md`](../references/jingui.md) | [`references/jingui-screenshot-evidence.md`](../references/jingui-screenshot-evidence.md) 656 images |
| Zhongjing Xinfa | [`references/zhongjing-xinfa.md`](../references/zhongjing-xinfa.md) | [`references/zhongjing-xinfa-screenshot-evidence.md`](../references/zhongjing-xinfa-screenshot-evidence.md) 68 images |
| Clinical cases / Ni's medical cases | [`references/clinical-cases.md`](../references/clinical-cases.md) | [`references/clinical-cases-screenshot-evidence.md`](../references/clinical-cases-screenshot-evidence.md) 88 images |
| Bagang pattern identification | [`references/bagang.md`](../references/bagang.md) | [`references/bagang-screenshot-evidence.md`](../references/bagang-screenshot-evidence.md) 33 representative images |
| Fuyang Forum | [`references/fuyang.md`](../references/fuyang.md) | [`references/fuyang-screenshot-evidence.md`](../references/fuyang-screenshot-evidence.md) 37 images |
| Yijinjing | [`references/yijinjing.md`](../references/yijinjing.md) | [`references/yijinjing-screenshot-evidence.md`](../references/yijinjing-screenshot-evidence.md) 28 images |
| Liang Dong interview with Ni Haisha | [`references/liangdong.md`](../references/liangdong.md) | - |
| Stanford lecture | [`references/stanford.md`](../references/stanford.md) | - |
| Tianji | [`references/tianji.md`](../references/tianji.md) | [`references/tianji-screenshot-evidence.md`](../references/tianji-screenshot-evidence.md) 527 images |
| Huangdi Neijing | [`references/huangdi.md`](../references/huangdi.md) | [`references/huangdi-screenshot-evidence.md`](../references/huangdi-screenshot-evidence.md) 272 images |
| Shennong Bencao | [`references/bencao.md`](../references/bencao.md) | [`references/bencao-screenshot-evidence.md`](../references/bencao-screenshot-evidence.md) 127 images |
| Acupuncture course | [`references/acupuncture.md`](../references/acupuncture.md) | [`references/acupuncture-screenshot-evidence.md`](../references/acupuncture-screenshot-evidence.md) 501 images |

## Text material modules

| Module | File | Purpose |
| --- | --- | --- |
| Zhenjiu Dacheng notes | [`references/notes-acupuncture-dacheng.md`](../references/notes-acupuncture-dacheng.md) | Acupuncture transcripts, Zhenjiu Dacheng, and study-note supplements. |
| Huangdi Neijing notes | [`references/notes-huangdi.md`](../references/notes-huangdi.md) | Neijing transcripts, illustrated notes, and original-text supplements. |
| Shennong Bencao notes | [`references/notes-bencao.md`](../references/notes-bencao.md) | Materia medica transcripts, color notes, and single-herb illustrated references. |
| Shang Han Lun notes | [`references/notes-shanghan.md`](../references/notes-shanghan.md) | Shang Han Lun transcripts, illustrated notes, and study notes. |
| Jingui Yaolue notes | [`references/notes-jingui.md`](../references/notes-jingui.md) | Jingui organized drafts, handouts, and study notes. |
| Classical and course source index | [`references/ebooks.md`](../references/ebooks.md) | Course proofreading PDFs, the recommended DOC, classical citations, formula-pattern references, and terminology checks. |
| Page-level PDF evidence | [`references/pdf-evidence/index.md`](../references/pdf-evidence/index.md) | PDF source list, page evidence cards, module term indexes, and citation policy. |
| Non-PDF text evidence | [`references/text-evidence/index.md`](../references/text-evidence/index.md) | Source boundary, section-level cards, and citation policy for the recommended DOC. |
| Audio collection | [`references/audio-collection.md`](../references/audio-collection.md) | MP3/recording collection index and distilled course mappings. |

## Current coverage

- Screenshot images have been organized and integrated for: `01.针灸课程`, `03.黄帝内经课程`, `05.神农本草课程`, `07.伤寒论课程`, `09.金匮要略课程`, `11.仲景心法传讲`, `13.人纪之临床案例`, `14.人纪之八纲辨证`, `15.扶阳论坛`, `18.倪师易筋经`, `22.倪海厦天纪`.
- Text materials have been organized for: `02.针灸大成笔记`, `04.黄帝内经笔记`, `06.神农本草笔记`, `08.伤寒论笔记`, `10.金匮要略笔记`, `12.倪师音频合集`, `19.梁冬对话倪师`, `20.倪师斯坦福大学演讲`.
- PDF evidence layer: 22 PDF sources, 10,538 physical-page records (10,461 complete text pages, 59 scanned visual/low-confidence pages without searchable OCR body text, 6 excluded non-content pages, and 12 native blank pages), plus 6 course-module term indexes and 1 full-text Ni-recommended supplemental module. Recommended books are automatically searched after primary course material matches the same topic, while remaining separately labeled and cited.
- Non-PDF text evidence layer: 1 Ni-recommended DOC with 183 preface/clause sections. It participates in the same automatic second pass and is never represented as Ni-authored material.
- Ongoing maintenance focuses on source-traceable corrections across course distillation text, course handouts/notes, page-level PDF evidence, and classical formula-source indexes.

## Install

Paste this prompt into your AI assistant:

```text
Please install the nihaisha skill for me:
https://github.com/JuneYaooo/nihaisha-nishi-tcm
```

The agent can clone the repository and install the directory into the corresponding skills folder.

After installation, restart the corresponding agent so the skill metadata is reloaded.

## Usage examples

```text
Use nihaisha to explain the difference between taiyang wind-strike and taiyang cold-damage.
```

```text
Use nihaisha to compare the formula-pattern decision points for Guizhi Tang, Mahuang Tang, and Gegen Tang.
```

```text
Use nihaisha to explain in plain language: why do some people get chills without sweating during a cold, while others fear wind and sweat?
```

```text
Use nihaisha to find board-screenshot evidence related to Xiao Chaihu Tang.
```

```text
Use nihaisha to trace the Jingui course threads for chest impediment, water qi, and phlegm-rheum.
```

```text
Use nihaisha to summarize the acupuncture course material on the Ren/Du channels and common emergency acupoints.
```

```text
Use nihaisha to find Tianji board evidence related to ming gong and si hua.
```

> The screenshot index prefers relative paths under `assets/screenshots/...`. PDF evidence citations use `pdf-evidence:<doc_id>#p<page>`; non-PDF text evidence uses `text-evidence:<doc_id>#s<section>`. The Liang Dong interview and Stanford lecture are currently text-only modules.

## Safety notice

This project is only for studying Ni Haisha's courses, retrieving course material, and organizing Traditional Chinese Medicine theory. It is not for medical diagnosis, individualized treatment, prescribing formulas, purchasing herbs, dosage decisions, or self-medication. Chinese herbal medicine and classical formulas require careful judgment about pattern identification, dosage, processing, contraindications, constitution, disease stage, and medication interactions. Misuse can create serious health risks.

For topics involving Fuzi-class herbs, Sini Tang-family formulas, Da Chengqi Tang / urgent purging to preserve yin, Didang Tang, Da Xianxiong Tang, cancer/tumors, pregnancy, children, chest pain, altered consciousness, severe dehydration, or other urgent or severe conditions, consult a qualified physician or emergency service immediately.

See [`USE_AND_RISK_NOTICE.md`](./USE_AND_RISK_NOTICE.md) for the full usage, risk, and non-commercial-use boundaries.

## Copyright and usage notice

This project is for personal study, material organization, and technical exchange only. It is not for commercial use. Course names, screenshots, transcriptions, organized notes, and related materials involved in this project belong to their respective rights holders. If any content is infringing or unsuitable for public release, please contact the maintainer for removal. See [`USE_AND_RISK_NOTICE.md`](./USE_AND_RISK_NOTICE.md) for details.

## Origin

This project began as a family learning need. My father has recently been studying Ni Haisha's courses and wanted an easier way to search, review, and follow the course structure. I grew up with Chinese herbal medicine and have long had trust in Traditional Chinese Medicine. Since my background is computer science, and I had recently practiced course distillation methods in other domains with good results, I wanted to distill a Ni Haisha learning skill first for my father's study.

I open-sourced it in the hope that it can also help others who are studying Ni Haisha's courses, Chinese medical classics, and classical formula systems. The project is intended for deep study, source lookup, citation checking, and knowledge organization, not for diagnosis or prescription advice. For real health issues, consult a qualified clinician offline and avoid creating health risks by copying formulas, purchasing herbs, or adjusting dosages on your own.

## Acknowledgements and community

First, thanks to Master Ni Haisha for leaving behind a large body of Chinese medicine course teaching. His courses connect Shang Han Lun, Jingui, acupuncture, materia medica, Huangdi Neijing, Tianji, and clinical pattern thinking into a course system that learners can study, verify, and review by lesson, topic, and question. This project only organizes those materials for learning; its value starts from Master Ni's teaching and transmission.

Thanks also to Master Ni's students, fans, learners, and volunteers who have spent years transcribing, proofreading, organizing, and sharing course materials, subtitles, handouts, screenshots, and study notes. Without that long-running community effort, this project could not build further structured distillation, indexing, and correction on top of the course corpus.

Special thanks to Dr. Deyi Liu (Dee Liu) of Suzhou Yunzhengtang and members of the Qihuang Shengxian Zhihui group for supporting course-text proofreading and classical-source collation. The proofreading PDFs and related classical/formula reference materials used in this update were provided by Dr. Deyi Liu (Dee Liu). Many terminology corrections in earlier video/audio transcriptions were also made after Dr. Deyi Liu (Dee Liu) pointed out likely transcription errors. This support made the current page-level, source-traceable evidence layer possible.

Thanks to the [Datawhale community](https://github.com/datawhalechina) and [LINUX DO - Chinese Developer Community](https://linux.do/) for their long-running support of open learning, technical exchange, and collaborative knowledge building. This project shares the same open and mutual-help spirit and is for learning and exchange only.

TCM clinicians, students, and enthusiasts are welcome to help maintain this project. Corrections and additions are especially valuable for terminology errors in transcriptions, formula/acupoint/herb name corrections, classical-source checks, missing screenshot or PDF evidence, incomplete sections, and inaccurate wording. Contributions can come through issues, pull requests, or community feedback. All collaboration remains limited to course study, material lookup, and source verification; it does not provide personal diagnosis, prescriptions, dosage, or self-medication advice.
