# 古籍与课程文献溯源索引

> 医疗边界：本文件仅作课程学习、资料检索、文案校对和古籍方证溯源；涉及真实症状、诊断、处方、剂量、针灸操作、急症、孕产儿童、肿瘤或附子等高风险内容时，不能作为个人医疗建议或自行操作依据，应咨询合格医疗专业人员。

## 范围

本文件不再作为“电子书大合集”清单使用。公开仓库只保留三类入口：

- 课程蒸馏：按课程模块读取 `references/*.md` 的课程摘要、逐课结构和截图证据。
- 课程文案校对 PDF：通过 `references/pdf-evidence/` 的页级证据卡核对术语、方名、穴名和古籍引用。
- 非 PDF 推荐资料：通过 `references/text-evidence/` 的章节/条文证据卡定位，不虚构 PDF 页码。
- 古籍/方证索引：围绕伤寒、金匮、本草、内经、针灸、仲景心法等课程相关模块建立术语和引用反查。

下列材料不作为本 skill 的主证据来源：汉唐文章合集、事实评论、秘方手法、外部医案杂集、图片/可执行文件/课件资产、非课程来源的大型抓取目录。除非用户明确要求考据旧材料，否则回答和勘误应优先使用课程蒸馏与已接入的 PDF/文本证据。

## 文献证据入口

| 入口 | 用途 |
| --- | --- |
| `pdf-evidence/index.md` | PDF 证据层说明、引用格式、文件结构和证据政策 |
| `pdf-evidence/sources.md` | PDF 来源与页级覆盖清单，包含 doc_id、模块、PDF 名、页数和字数 |
| `pdf-evidence/evidence-cards.jsonl` | 每个物理页的完整文本、页面类型、术语和 `pdf-evidence:<doc_id>#p<page>` 引用 |
| `pdf-evidence/term-index/<module>.json` | 按模块拆分的术语索引，避免加载单个巨大索引 |
| `pdf-evidence/modules/*.md` | 按模块、来源和物理页组织的完整页级文本 |
| `pdf-evidence/correction-decisions.md` | 高置信勘误记录与证据状态 |
| `text-evidence/index.md` | 非 PDF 推荐资料的章节级证据说明与引用规范 |
| `text-evidence/evidence-cards.jsonl` | 按真实篇名/条文切分的完整文本，引用格式为 `text-evidence:<doc_id>#s<section>` |

检索示例：

```bash
python scripts/search_pdf_evidence.py 大青龙汤 --module shanghan --limit 3
python scripts/search_pdf_evidence.py 行间 荥穴 --module acupuncture --limit 3
python scripts/search_pdf_evidence.py 旋覆花 代赭石 --module shanghan --limit 3
# 主资料命中后自动执行补充层二次检索；只看主资料时：
python scripts/search_pdf_evidence.py 足三里 --module acupuncture --primary-only --limit 3
# 直接查询某本推荐书时强制开启补充层：
python scripts/search_pdf_evidence.py 足三里 --doc-id 0fd559f91c46 --include-supplements --limit 3
# 直接查旧 DOC 推荐资料：
python scripts/search_pdf_evidence.py 太陽病提綱 --doc-id 77af3a7c9960 --include-supplements --limit 3
```

PDF 引用格式为 `pdf-evidence:<doc_id>#p<page>`；非 PDF 文本引用格式为
`text-evidence:<doc_id>#s<section>`，不得写入机器相关路径或虚构页码。

完整页级文件体积较大。日常检索应通过 `scripts/search_pdf_evidence.py` 限定模块和结果数，
不要整份加载 `pdf-evidence/modules/*.md` 或 `evidence-cards.jsonl`；只有人工核页时才使用
`--show-full-page`，需要列出全部命中页时才使用 `--limit 0`。

## 已接入的倪师推荐补充资料

| 文献 | Doc ID | 来源层级 | 模块 | 定位单位 | 用途与版本边界 |
| --- | --- | --- | --- | ---: | --- |
| 《四圣心源》 | `90a0473d9b3b` | 倪师推荐补充资料 | `classics` | 146 | 用于黄元御理论、伤寒金匮相关术语与古籍出处反查。PDF 正文和内题可确认书名，但文件元数据误写为其他书名，不采用元数据题名；2 个重复推广页因含个人联系方式与外链，仅保留排除标记。 |
| 《医宗金鉴·伤寒论三阴病篇》 | `da46832bcbe0` | 倪师推荐补充资料 | `shanghan` | 364 | 用于太阴、少阴、厥阴条文及注释线索。该文件混合原文、集注、翻译与后加“讲解”，不能把整页都当作清代原典逐字文本或倪海厦课程原话。 |
| 《针灸大成》 | `0fd559f91c46` | 倪师推荐补充资料 | `acupuncture` | 569 | 用于经络、穴名、针灸歌赋和原典出处反查。该横排本已做字符间距归一化；其中操作性内容只作页码定位，不转写为自行针灸说明。 |
| 《世补斋医书全集》 | `77e0693e8795` | 倪师推荐补充资料 | `classics` | 300 | PaddleOCR v6 tiny 完整提取：279 个文本页、21 个无 OCR 正文或低置信字符的扫描视觉页，页面平均置信度 0.9607；扫描页中的“更多相关资源”推广水印已移除。 |
| 《徐灵胎医书全集》 | `d2b093656655` | 倪师推荐补充资料 | `classics` | 1296 | PaddleOCR v6 tiny 完整提取：1259 个文本页、37 个无 OCR 正文或低置信字符的扫描视觉页，页面平均置信度 0.9775；用于徐灵胎相关医论与古籍出处补充。 |
| 《石室秘录》 | `a60ecf5c4021` | 倪师推荐补充资料 | `classics` | 366 | PaddleOCR v6 tiny 提取：362 个文本页、4 个含推广/联系方式的排除页，页面平均置信度 0.9489；原书内容只作陈士铎相关补充。 |
| 《血证论》 | `4fd1b745d42f` | 倪师推荐补充资料 | `classics` | 185 | 原生文本层：184 个文本页、1 个空白页；用于唐容川气血、水火、脏腑及血证论述补充。 |
| 《证因方论集要》 | `f988e5bb830a` | 倪师推荐补充资料 | `classics` | 166 | 原生文本层完整；用于证因、方论与古方线索补充，不作为课程处方依据。 |
| 《医学衷中参西录直书》 | `a3551879ed76` | 倪师推荐补充资料 | `classics` | 2150 | 原生文本层完整，已做 CJK 字符间距归一化；篇幅大且含后人整理/讲解，只按关键词局部检索。 |
| 《医宗金鉴·金匮要略直书》 | `64bc78fc08a4` | 倪师推荐补充资料 | `jingui` | 1831 | 原生文本层完整，已做 CJK 字符间距归一化；混合原文、注释、翻译与讲解，不能整体视为清代原典或倪师原话。 |
| 《黄帝外经》 | `942ab5422229` | 倪师推荐补充资料 | `classics` | 85 | 原 PDF 有四重叠字层，改用 PaddleOCR v6 tiny 重提取，页面平均置信度 0.9862；版本与真伪问题只作课程推荐背景，不写成独立定论。 |
| 《大塚敬節傷寒論條文》（压缩包名《大塚敬節傷寒論解說》） | `77af3a7c9960` | 倪师推荐补充资料 | `shanghan` | 183 节 | 旧 DOC 已转为章节级文本证据；内题及实际内容是张仲景自序和 182 条伤寒条文节录/提示，未见系统解说正文。按 `s001`—`s183` 引用，不使用页码，也不把文件名扩大解释成完整解说。 |

以上 11 个 PDF 和 1 个 DOC 是倪师相关推荐资料，不是倪师本人撰写或讲授资料。课程问答先回到课程蒸馏正文、转写、同步文稿、截图或课程 PDF；主资料命中同一话题且补充层有结果时，默认自动执行二次检索，并单列“倪师推荐资料补充”。原书作者、注者、译者、OCR/抽取文本或后加讲解的观点不得归到倪师名下。

## 课程与古籍索引入口

| 模块 | 优先文件 | PDF 证据模块 |
| --- | --- | --- |
| 伤寒论 | `shanghanlun.md`、`six-channel.md`、`formula-patterns.md`、`notes-shanghan.md` | `shanghan` |
| 金匮要略 | `jingui.md`、`notes-jingui.md`、`formula-patterns.md` | `jingui` |
| 仲景心法 | `zhongjing-xinfa.md` | `zhongjing-xinfa` |
| 针灸 | `acupuncture.md`、`notes-acupuncture-dacheng.md` | `acupuncture` |
| 黄帝内经 | `huangdi.md`、`notes-huangdi.md` | `huangdi` |
| 神农本草 | `bencao.md`、`notes-bencao.md` | `bencao` |
| 倪师推荐补充资料 | 本文件的来源边界与版本说明 | `classics`（另有映射到课程模块的补充书） |

## 勘误原则

- 先核课程语境，再核 PDF 页级证据，最后才参考古籍/方证索引。
- 高置信勘误直接改入原始 skill/reference 文件，不把修正只留在单独报表。
- 对同音误字、OCR 误字、穴名/方名/药名误写，必须能追到课程模块或 PDF 页码。
- 对缺少 PDF 或课程证据的术语，只标记为证据不足，不写成确定结论。
- 公开仓库只保留可追溯证据、稳定索引和正文修订。
