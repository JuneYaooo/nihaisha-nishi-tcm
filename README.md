<div align="center">

# nihaisha

**把倪海厦中医课程整理成可检索、可追溯、有安全边界的 Agent Skill。**

Claude Code / Codex / OpenClaw Skill。装进 agent 后，可以用自然语言按症状、方剂、穴位、课程模块、课次或板书截图检索倪海厦课程资料，输出学习型辨证梳理、方证/穴位/药性对比、逐课复习计划和截图证据索引。

[![GitHub stars](https://img.shields.io/github/stars/JuneYaooo/nihaisha-nishi-tcm?style=flat)](https://github.com/JuneYaooo/nihaisha-nishi-tcm/stargazers)
[![Skill](https://img.shields.io/badge/Agent-Skill-orange.svg)](./SKILL.md)
[![TCM](https://img.shields.io/badge/TCM-%E5%80%AA%E6%B5%B7%E5%8E%A6-green.svg)](./references/index.md)
[![Course](https://img.shields.io/badge/course-multi--module-blue.svg)](./references/index.md)

**English** → [docs/README.en.md](./docs/README.en.md)

</div>

> **提示**：目前项目还存在一些问题，正在持续迭代中，建议大家每过一段时间来看看是否有更新，并下载安装最新版本。

---

## 课程蒸馏方法

本项目的课程蒸馏方法来自作者维护的 [lineage-skill](https://github.com/JuneYaooo/lineage-skill)：把高密度课程材料整理成可溯源、可迁移、可产出的 Agent Skill。

## 更新记录

### 2026-07-16

- 新增《四圣心源》《医宗金鉴·伤寒论三阴病篇》《针灸大成》3 个倪师相关推荐古籍 PDF，并明确标记为“倪师推荐补充资料”，不是倪师本人资料。
- 使用本地 PaddleOCR v6 tiny 完整提取《世补斋医书全集》《徐灵胎医书全集》1596 个扫描页，并接入同一推荐补充层；OCR 平均置信度分别为 0.9607、0.9775。
- 完成《石室秘录》OCR，并接入《血证论》《证因方论集要》《医学衷中参西录直书》《医宗金鉴·金匮要略直书》《黄帝外经》；“倪推荐的医书”压缩包内 11 个 PDF 已全部接入。
- 提取压缩包内最后一个旧 DOC《大塚敬節傷寒論解說》；根据内题和实际内容以《大塚敬節傷寒論條文》接入 183 个章节/条文文本块，不虚构 PDF 页码。至此压缩包内 11 个 PDF 和 1 个 DOC 已全部接入。
- PDF 证据层扩展至 22 个来源、10538 条物理页记录；课程主资料命中同题后会自动开启推荐补充资料二次检索，补充结果仍单独标注；另排除 6 个含个人联系方式的非正文推广页。
- 为字符间带空格的横排古籍增加按来源启用的 CJK 间距归一化，改善方名、穴名和篇名的连续关键词检索。

### 2026-07-15

- 将文字整理层中的可执行剂量、煎服、针刺、放血、灸法和剧毒药操作移回 PDF/截图证据层；证据层保留源画面/原文，但统一标明不可照做。
- 修正麦冬、瓦楞子、ALS、栀子豉汤、郁金、经方、金匮方、炮附子等旧 ASR/整理层术语，并收紧癌症、急症、孕产、儿童、附子和针灸操作边界。

### 2026-06-25

- 根据岐黄圣贤智慧整理的课程校对资料，对此前由视频/音频转写产生的一批术语、方名、穴名和古籍引用误差做了系统勘误。
- 新增课程校对 PDF 的页级证据层：[`references/pdf-evidence/`](./references/pdf-evidence/)，便于按课程、页码和关键词追溯校对依据。
- 新增与课程内容相关的古籍、方证和术语索引入口：[`references/ebooks.md`](./references/ebooks.md)，用于辅助核对课程中提到的经典出处和方证线索。
- 术语索引已按伤寒、金匮、仲景心法、针灸、黄帝内经、神农本草等模块拆分，方便学习时按主题检索。

## 能做什么

- **白话问题入口**：把“感冒怕冷”“手脚冷”“拉肚子”“睡不着”等普通表达转成课程里的分水岭问题。
- **多课程检索**：覆盖伤寒论、金匮要略、仲景心法、临床案例、八纲辨证、扶阳论坛、易筋经、梁冬对话、斯坦福演讲、天纪、黄帝内经、神农本草、针灸课程，以及课程讲稿、学习笔记、音频合集映射。
- **六经与方证导航**：按六经、症状、方剂和传变逻辑整理《伤寒论》核心内容。
- **穴位与药性学习**：可检索针灸经络穴位、配穴思路，以及神农本草课程里的药性、剂型、配伍与单味药线索。
- **逐课复习**：按课程模块和课次整理主题地图、关键词和适合复习的问题。
- **截图证据**：已接入 2986 条截图证据索引，对应图片均已压缩为仓库内 WebP，可按方名、穴位、课次、病机、术数关键词或时间点检索。
- **PDF 溯源证据**：已接入 22 个 PDF 来源、10538 条物理页记录（10461 个完整文本页、59 个无 OCR 正文或低置信字符的扫描视觉页、6 个已排除非正文页、12 个原生空白页）、6 个课程模块术语索引和 1 个推荐补充全文模块；课程正文命中后自动执行补充层二次检索，结果分开引用。
- **非 PDF 文本证据**：已接入 1 个推荐 DOC、183 个自序/条文文本块；使用 `text-evidence:<doc_id>#s<section>` 定位，与倪师本人资料分层展示。
- **安全边界**：默认作为课程学习与中医理论整理，不做个人诊断、处方或剂量指导。

## 可选：本地证据型 RAG

项目提供可回溯到原始段落、PDF 页码、`paragraph_id`、`evidence_id` 及前后文的本地 RAG。
5 个生产资产单独托管在公开的
[Hugging Face Dataset](https://huggingface.co/datasets/JuneYao/nihaisha-rag-assets)，固定版本为
`production-2026-07-15`，共 3,679,424,241 字节（约 3.68 GB），不再塞进 GitHub 或 Git LFS。

首次使用：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[runtime]"
python3 -m nihaisha_kg download-assets
python3 -m nihaisha_kg doctor
```

下载命令不需要 Hugging Face 账号、Token 或 CLI，支持 `.part` 断点续传；完整下载后逐文件核验
大小和 SHA256，重复运行会直接跳过已验证文件。`doctor` 返回 `status: ok` 后即可查询：

```bash
python3 -m nihaisha_kg search "木香饼" --mode text --limit 5
python3 -m nihaisha_kg answer "桂枝汤和麻黄汤的方证如何鉴别？" --mode hybrid --limit 8
```

RAG 默认只用主资料形成结论。12 份关联资料属于 `reference_secondary`，只有显式使用
`--include-references` 才检索其正文，并始终标注为“关联参考资料（非倪海厦著作）”。

## 适合哪些场景

| 场景 | 适合程度 | 说明 |
| --- | --- | --- |
| 学习倪海厦课程 | 很适合 | 从课程模块、课次、主题、截图证据几个入口复习。 |
| 查某个方的课程方证 | 很适合 | 可返回症状群、病机层次、相关方和禁忌提醒。 |
| 查针灸、经络、穴位 | 很适合 | 可按穴位、经络、配穴场景和实操截图检索。 |
| 查本草药性或内经理论 | 适合 | 可进入神农本草、黄帝内经模块做课程学习整理。 |
| 用白话提问 | 很适合 | 先转成辨证分水岭，再进入课程术语。 |
| 找板书、PPT 或实操截图 | 适合 | 可按课程模块、关键词、方名、穴位、课次或时间点检索截图证据。 |
| 核对 PDF 页级证据 | 适合 | 可按课程模块、术语、方名、穴名或古籍关键词追溯课程校对 PDF。 |
| 整理学习笔记 | 适合 | 可生成可追加到 references 的 Markdown。 |
| 真实病情用药决策 | 不适合 | 本 skill 不提供个人诊断、处方、剂量或自我用药建议。 |

## 课程模块

| 模块 | 文本资料 | 截图证据 |
| --- | --- | --- |
| 伤寒论 | [`references/shanghanlun.md`](./references/shanghanlun.md)、[`references/lesson-map.md`](./references/lesson-map.md)、六经/方证/症状细分模块 | [`references/screenshot-evidence.md`](./references/screenshot-evidence.md) 649 张 |
| 金匮要略 | [`references/jingui.md`](./references/jingui.md) | [`references/jingui-screenshot-evidence.md`](./references/jingui-screenshot-evidence.md) 656 张 |
| 仲景心法 | [`references/zhongjing-xinfa.md`](./references/zhongjing-xinfa.md) | [`references/zhongjing-xinfa-screenshot-evidence.md`](./references/zhongjing-xinfa-screenshot-evidence.md) 68 张 |
| 临床案例/倪师医案 | [`references/clinical-cases.md`](./references/clinical-cases.md) | [`references/clinical-cases-screenshot-evidence.md`](./references/clinical-cases-screenshot-evidence.md) 88 张 |
| 八纲辨证 | [`references/bagang.md`](./references/bagang.md) | [`references/bagang-screenshot-evidence.md`](./references/bagang-screenshot-evidence.md) 33 张代表画面 |
| 扶阳论坛 | [`references/fuyang.md`](./references/fuyang.md) | [`references/fuyang-screenshot-evidence.md`](./references/fuyang-screenshot-evidence.md) 37 张 |
| 易筋经 | [`references/yijinjing.md`](./references/yijinjing.md) | [`references/yijinjing-screenshot-evidence.md`](./references/yijinjing-screenshot-evidence.md) 28 张 |
| 梁冬对话倪师 | [`references/liangdong.md`](./references/liangdong.md) | - |
| 斯坦福大学演讲 | [`references/stanford.md`](./references/stanford.md) | - |
| 天纪 | [`references/tianji.md`](./references/tianji.md) | [`references/tianji-screenshot-evidence.md`](./references/tianji-screenshot-evidence.md) 527 张 |
| 黄帝内经 | [`references/huangdi.md`](./references/huangdi.md) | [`references/huangdi-screenshot-evidence.md`](./references/huangdi-screenshot-evidence.md) 272 张 |
| 神农本草 | [`references/bencao.md`](./references/bencao.md) | [`references/bencao-screenshot-evidence.md`](./references/bencao-screenshot-evidence.md) 127 张 |
| 针灸课程 | [`references/acupuncture.md`](./references/acupuncture.md) | [`references/acupuncture-screenshot-evidence.md`](./references/acupuncture-screenshot-evidence.md) 501 张 |

## 文字资料模块

| 模块 | 文件 | 用途 |
| --- | --- | --- |
| 针灸大成笔记 | [`references/notes-acupuncture-dacheng.md`](./references/notes-acupuncture-dacheng.md) | 针灸讲稿、针灸大成和学习笔记补充。 |
| 黄帝内经笔记 | [`references/notes-huangdi.md`](./references/notes-huangdi.md) | 内经讲稿、图文笔记和原著补充。 |
| 神农本草笔记 | [`references/notes-bencao.md`](./references/notes-bencao.md) | 本草讲稿、彩版笔记和单味药图文资料。 |
| 伤寒论笔记 | [`references/notes-shanghan.md`](./references/notes-shanghan.md) | 伤寒讲稿、图文笔记和学习笔记。 |
| 金匮要略笔记 | [`references/notes-jingui.md`](./references/notes-jingui.md) | 金匮整理稿、讲义和学习笔记。 |
| 古籍与课程文献溯源索引 | [`references/ebooks.md`](./references/ebooks.md) | 课程校对 PDF、推荐 DOC、古籍引用、方证和术语核对入口。 |
| PDF 页级证据 | [`references/pdf-evidence/index.md`](./references/pdf-evidence/index.md) | PDF 来源清单、页级证据卡、模块术语索引和引用规范。 |
| 非 PDF 文本证据 | [`references/text-evidence/index.md`](./references/text-evidence/index.md) | 推荐 DOC 的来源边界、章节/条文证据卡和引用规范。 |
| 音频合集 | [`references/audio-collection.md`](./references/audio-collection.md) | MP3/录音合集索引和已蒸馏课程映射。 |

## 当前覆盖

- 已整理并接入截图图片：`01.针灸课程`、`03.黄帝内经课程`、`05.神农本草课程`、`07.伤寒论课程`、`09.金匮要略课程`、`11.仲景心法传讲`、`13.人纪之临床案例`、`14.人纪之八纲辨证`、`15.扶阳论坛`、`18.倪师易筋经`、`22.倪海厦天纪`。
- 已整理文字资料：`02.针灸大成笔记`、`04.黄帝内经笔记`、`06.神农本草笔记`、`08.伤寒论笔记`、`10.金匮要略笔记`、`12.倪师音频合集`、`19.梁冬对话倪师`、`20.倪师斯坦福大学演讲`。
- 已整理 PDF 证据层：22 个 PDF 来源、10538 条物理页记录（10461 个完整文本页、59 个无 OCR 正文或低置信字符的扫描视觉页、6 个已排除非正文页、12 个原生空白页）、6 个课程模块术语索引和 1 个倪师推荐补充全文模块；推荐资料在课程正文命中同题后自动二次检索，但不并入倪师原话或本人资料。
- 已整理非 PDF 文本证据层：1 个倪师推荐 DOC、183 个自序/条文文本块；同样参与默认二次检索，并始终标注为非倪师本人资料。
- 持续维护方向：围绕课程蒸馏正文、课程讲稿/笔记、PDF 页级证据和古籍方证索引做可溯源勘误。

## 安装

把下面这段 prompt 丢给你的 AI 助手：

```text
帮我安装 nihaisha skill：
https://github.com/JuneYaooo/nihaisha-nishi-tcm
```

agent 可以 clone 仓库，再把目录安装到对应的 skills 目录。

装完后重启对应 agent，让 skill 元数据重新加载。

## 使用示例

```text
用 nihaisha 帮我整理太阳中风和太阳伤寒的区别。
```

```text
用 nihaisha 查桂枝汤、麻黄汤、葛根汤的方证分水岭。
```

```text
用 nihaisha 按白话解释：为什么有的人感冒怕冷无汗，有的人怕风有汗？
```

```text
用 nihaisha 找小柴胡汤相关的板书截图证据。
```

```text
用 nihaisha 查金匮里胸痹、水气、痰饮相关课程脉络。
```

```text
用 nihaisha 整理针灸课程里任督二脉和常用急救穴位。
```

```text
用 nihaisha 找天纪里命宫、四化相关板书证据。
```

> 截图索引优先返回仓库内 `assets/screenshots/...` 相对路径。PDF 证据引用格式为 `pdf-evidence:<doc_id>#p<page>`；非 PDF 文本证据使用 `text-evidence:<doc_id>#s<section>`。梁冬对话和斯坦福演讲目前为文本整理模块。

## 安全说明

本项目只用于倪海厦课程学习、资料检索和中医理论整理，不用于医疗诊断、个体化治疗、开方、抓药、剂量判断或自我用药决策。中药和经方使用需要辨证、剂量、炮制、禁忌、体质、病程和合并用药等多重判断，误用可能带来严重健康风险。

涉及附子类、四逆汤辈、大承气汤/急下存阴、抵当汤、大陷胸汤、癌症/肿瘤、妊娠、儿童、胸痛、意识改变、严重脱水或其他急危重症时，应立即咨询合格医生或急诊处理。

更完整的用途、风险和非商业使用边界见 [`docs/USE_AND_RISK_NOTICE.md`](./docs/USE_AND_RISK_NOTICE.md)。

## 版权与用途说明

本项目仅作个人学习、资料整理与技术交流使用，不作商业用途。项目中涉及的课程名称、截图、转写整理与相关资料版权归原权利人所有；如有侵权或不适宜公开的内容，请联系删除。详细说明见 [`docs/USE_AND_RISK_NOTICE.md`](./docs/USE_AND_RISK_NOTICE.md)。

## 项目缘起

这个项目最初来自一个家庭学习需求：我的父亲最近在系统学习倪师课程，我本身学计算机，前不久又在其他领域实践了课程蒸馏方法，看到它对复杂知识整理很有效，于是想着帮父亲蒸馏一个便于学习倪师课程的 skill。

开源出来，是希望它也能帮助更多正在学习倪师课程、中医经典和经方体系的人。本项目的初衷是帮助深度学习、检索资料、核对出处和建立知识结构，不是提供诊断或处方建议。真实健康问题请线下咨询合格医师，避免因为自行照方、抓药或调整剂量而引发健康风险。

## 致谢

首先感谢倪海厦老师留下的大量中医课程讲解。倪师把伤寒、金匮、针灸、本草、内经、天纪以及临床辨证思路，用大量课程、案例和板书讲成了便于普通学习者按课程、主题和问题反复学习、查证和复盘的课程体系；这些内容让很多人重新看见中医经典、经方和临床思维的生命力。本项目只是站在这些课程资料之上做学习型整理，所有学习价值首先来自倪师本人的讲授与传承。

也感谢倪师的弟子、粉丝、学习者和志愿者们长期转写、校对、整理、分享课程资料、字幕、讲稿、截图和学习笔记。没有这些持续多年的民间整理与传播，本项目无法站在现有课程资料基础上继续做结构化蒸馏、索引和勘误。

特别感谢苏州允正堂刘德毅医生 Dee Liu（岐黄圣贤智慧组员）对课程资料校对与古籍资料整理的支持。课程文案校对所用的 PDF、相关古籍与方证参考资料由刘德毅医生 Dee Liu 提供；此前许多视频/音频转写中的术语误写，也是在刘德毅医生 Dee Liu 提醒下进一步核对并修正。没有这些校对与资料支持，本项目很难完成现在这种页级可溯源的证据整理。

感谢 [Datawhale 社区](https://github.com/datawhalechina) 与 [LINUX DO — 中文开发者社区](https://linux.do/) 对开源学习、技术交流和知识共创氛围的长期推动。本项目的整理和分享也希望延续这种开放互助的社区精神，仅供学习交流使用。

## 共建邀请

欢迎中医师、中医学习者、中医爱好者，以及对知识蒸馏、Agent Skill、资料检索和 AI 辅助学习感兴趣的 AI 从业者共同维护本项目。

尤其是课程转写中的术语误差、方名/穴名/药名勘误、古籍出处核对、截图或 PDF 证据补充、内容不完整或表述不准确之处，以及检索体验、提示词、索引结构和使用流程优化，都欢迎通过 issue、PR 或社群反馈协助修正。

所有共建内容仍以课程学习、资料检索和出处校对为边界，不提供个人诊断、处方、剂量或自我用药建议。

## 交流社群

欢迎扫码加入微信交流群，交流倪海厦课程学习、中医理论整理、Agent Skills 使用、资料检索与学习笔记共建等相关内容。

本群仅用于非商业的学习交流与技术讨论，不提供个人诊断、处方、剂量或自我用药建议。

<p align="center">
  <img src="./docs/wechat_group_qr_20260714.jpg" alt="nihaisha 微信交流群二维码" width="260">
</p>
