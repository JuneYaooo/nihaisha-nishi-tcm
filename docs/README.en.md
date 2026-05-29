<div align="center">

# nihaixia

**Turn Ni Haixia's Traditional Chinese Medicine course materials into a searchable, traceable Agent Skill with clear safety boundaries.**

A Claude Code / Codex / OpenClaw Skill. Once installed in an agent, it lets you use natural language to search Ni Haixia course materials by symptom, formula, acupoint, course module, lesson, or board/PPT screenshot, then returns study-oriented pattern analysis, formula/acupoint/herb comparisons, lesson review plans, and screenshot evidence indexes.

[![GitHub stars](https://img.shields.io/github/stars/JuneYaooo/nihaixia?style=flat)](https://github.com/JuneYaooo/nihaixia/stargazers)
[![Skill](https://img.shields.io/badge/Agent-Skill-orange.svg)](../SKILL.md)
[![TCM](https://img.shields.io/badge/TCM-Ni%20Haixia-green.svg)](../references/index.md)
[![Course](https://img.shields.io/badge/course-multi--module-blue.svg)](../references/index.md)

**中文** → [../README.md](../README.md)

</div>

---

## What it does

- **Plain-language entry point**: turns everyday descriptions such as "cold with chills", "cold hands and feet", "diarrhea", or "cannot sleep" into the differentiating questions used in the courses.
- **Multi-course retrieval**: covers Shang Han Lun, Jingui Yaolue, Zhongjing Xinfa, clinical cases, Bagang pattern identification, Fuyang Forum, Yijinjing, the Liang Dong interview, Stanford lecture, Tianji, Huangdi Neijing, Shennong Bencao, acupuncture courses, plus lecture notes, Han-Tang TCM materials, diagnostic logs, ebook indexes, and audio collection indexes.
- **Six-channel and formula-pattern navigation**: organizes the core Shang Han Lun material by six-channel patterns, symptoms, formulas, and disease-transmission logic.
- **Acupoint and herb study**: searches acupuncture channels and points, point-combination ideas, and Shennong Bencao course material on herb properties, dosage forms, compatibility, and single-herb clues.
- **Lesson-by-lesson review**: builds topic maps, keywords, and review questions by course module and lesson.
- **Screenshot evidence**: includes 2,986 screenshot evidence entries, with compressed WebP images stored in the repo. Search by formula name, acupoint, lesson, pathomechanism, Tianji keyword, or timestamp.
- **Safety boundary**: defaults to course study and TCM theory organization. It does not provide personal diagnosis, prescriptions, or dosage guidance.

## Best-fit use cases

| Use case | Fit | Notes |
| --- | --- | --- |
| Study Ni Haixia's courses | Strong | Review by course module, lesson, topic, and screenshot evidence. |
| Look up a formula pattern from the courses | Strong | Can return symptom clusters, pathomechanism layers, related formulas, and contraindication reminders. |
| Search acupuncture, channels, and points | Strong | Search by acupoint, channel, point-combination scenario, and practical screenshots. |
| Study materia medica or Neijing theory | Good | Enters the Shennong Bencao and Huangdi Neijing modules for course-based study notes. |
| Ask in plain language | Strong | First converts plain symptoms into pattern-identification decision points, then maps them to course terms. |
| Find board, PPT, or practical screenshots | Good | Use `scripts/search_screenshots.py` to search screenshot indexes across modules. |
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
| Liang Dong interview with Ni Haixia | [`references/liangdong.md`](../references/liangdong.md) | - |
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
| Han-Tang TCM | [`references/hantang.md`](../references/hantang.md) | Han-Tang articles, formula explanations, collected cases, and topic comments. |
| Diagnostic logs | [`references/diagnostic-logs.md`](../references/diagnostic-logs.md) | Diagnostic logs, case records, and Human Discipline class cases. |
| Ebook collection | [`references/ebooks.md`](../references/ebooks.md) | Ebook, classical text, secret method, and large collection indexes. |
| Audio collection | [`references/audio-collection.md`](../references/audio-collection.md) | MP3/recording collection index and distilled course mappings. |

## Install

### Option 1: let your AI install it

Paste this prompt into your AI assistant:

```text
Please install the nihaixia skill for me:
https://github.com/JuneYaooo/nihaixia
```

The agent can clone the repository and install the directory into the corresponding skills folder.

### Option 2: manual install

```bash
git clone git@github.com:JuneYaooo/nihaixia.git
cd nihaixia
bash install_as_skill.sh --target codex    # Codex
# or
bash install_as_skill.sh --target claude   # Claude Code
```

The script installs the skill into:

- Codex: `~/.codex/skills/nihaixia/`
- Claude Code: `~/.claude/skills/nihaixia/`
- OpenClaw: `~/skills/nihaixia/`

After installation, restart the corresponding agent so the skill metadata is reloaded.

## Usage examples

```text
Use nihaixia to explain the difference between taiyang wind-strike and taiyang cold-damage.
```

```text
Use nihaixia to compare the formula-pattern decision points for Guizhi Tang, Mahuang Tang, and Gegen Tang.
```

```text
Use nihaixia to explain in plain language: why do some people get chills without sweating during a cold, while others fear wind and sweat?
```

```text
Use nihaixia to find board-screenshot evidence related to Xiao Chaihu Tang.
```

```text
Use nihaixia to trace the Jingui course threads for chest impediment, water qi, and phlegm-rheum.
```

```text
Use nihaixia to summarize the acupuncture course material on the Ren/Du channels and common emergency acupoints.
```

```text
Use nihaixia to find Tianji board evidence related to ming gong and si hua.
```

You can also run screenshot search directly:

```bash
python3 scripts/search_screenshots.py Xiao Chaihu Tang modifications
python3 scripts/search_screenshots.py shaoyin diarrhea
python3 scripts/search_screenshots.py Tianji ming gong
python3 scripts/search_screenshots.py acupuncture Zusanli
```

> The screenshot index prefers relative paths under `assets/screenshots/...`. Screenshot evidence for the Liang Dong interview and Stanford lecture has not been indexed yet.

## Safety notice

This project is for studying Ni Haixia's courses, retrieving course material, and organizing Traditional Chinese Medicine theory. It is not intended for medical diagnosis or individualized treatment.

For topics involving Fuzi-class herbs, Sini Tang-family formulas, Da Chengqi Tang / urgent purging to preserve yin, Didang Tang, Da Xianxiong Tang, cancer/tumors, pregnancy, children, chest pain, altered consciousness, severe dehydration, or other urgent or severe conditions, consult a qualified physician or emergency service immediately.

## Copyright and usage notice

This project is for personal study, material organization, and technical exchange only. It is not for commercial use. Course names, screenshots, transcriptions, organized notes, and related materials involved in this project belong to their respective rights holders. If any content is infringing or unsuitable for public release, please contact the maintainer for removal.

## Acknowledgements and community

Thanks to the [Datawhale community](https://github.com/datawhalechina) and [LINUX DO - Chinese Developer Community](https://linux.do/) for their long-running support of open learning, technical exchange, and collaborative knowledge building. This project shares the same open and mutual-help spirit and is for learning and exchange only.

## Current coverage

- Screenshot images have been organized and integrated for: `01.针灸课程`, `03.黄帝内经课程`, `05.神农本草课程`, `07.伤寒论课程`, `09.金匮要略课程`, `11.仲景心法传讲`, `13.人纪之临床案例`, `14.人纪之八纲辨证`, `15.扶阳论坛`, `18.倪师易筋经`, `22.倪海厦天纪`.
- Text materials have been organized for: `02.针灸大成笔记`, `04.黄帝内经笔记`, `06.神农本草笔记`, `08.伤寒论笔记`, `10.金匮要略笔记`, `12.倪师音频合集`, `16.倪师汉唐中医`, `17.倪师绝版诊疗日志`, `21.倪师电子书合集`.
- Text has been organized, with screenshot evidence still pending, for: `19.梁冬对话倪师`, `20.倪师斯坦福大学演讲`.
- Planned expansion: other materials that have not yet been distilled or whose screenshot evidence has not yet been indexed.
