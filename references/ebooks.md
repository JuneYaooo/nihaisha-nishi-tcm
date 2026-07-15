# 古籍与课程 PDF 溯源索引

> 医疗边界：本文件仅作课程学习、资料检索、文案校对和古籍方证溯源；涉及真实症状、诊断、处方、剂量、针灸操作、急症、孕产儿童、肿瘤或附子等高风险内容时，不能作为个人医疗建议或自行操作依据，应咨询合格医疗专业人员。

## 范围

本文件不再作为“电子书大合集”清单使用。公开仓库只保留三类入口：

- 课程蒸馏：按课程模块读取 `references/*.md` 的课程摘要、逐课结构和截图证据。
- 课程文案校对 PDF：通过 `references/pdf-evidence/` 的页级证据卡核对术语、方名、穴名和古籍引用。
- 古籍/方证索引：围绕伤寒、金匮、本草、内经、针灸、仲景心法等课程相关模块建立术语和引用反查。

下列材料不作为本 skill 的主证据来源：汉唐文章合集、事实评论、秘方手法、外部医案杂集、图片/可执行文件/课件资产、非课程来源的大型抓取目录。除非用户明确要求考据旧材料，否则回答和勘误应优先使用课程蒸馏与 PDF 页级证据。

## PDF 证据入口

| 入口 | 用途 |
| --- | --- |
| `pdf-evidence/index.md` | PDF 证据层说明、引用格式、文件结构和证据政策 |
| `pdf-evidence/sources.md` | PDF 来源与页级覆盖清单，包含 doc_id、模块、PDF 名、页数和字数 |
| `pdf-evidence/evidence-cards.jsonl` | 每个物理页的完整文本、页面类型、术语和 `pdf-evidence:<doc_id>#p<page>` 引用 |
| `pdf-evidence/term-index/<module>.json` | 按模块拆分的术语索引，避免加载单个巨大索引 |
| `pdf-evidence/modules/*.md` | 按模块、来源和物理页组织的完整页级文本 |
| `pdf-evidence/correction-decisions.md` | 高置信勘误记录与证据状态 |

检索示例：

```bash
python scripts/search_pdf_evidence.py 大青龙汤 --module shanghan --limit 3
python scripts/search_pdf_evidence.py 行间 荥穴 --module acupuncture --limit 3
python scripts/search_pdf_evidence.py 旋覆花 代赭石 --module shanghan --limit 3
```

引用格式固定为 `pdf-evidence:<doc_id>#p<page>`，不得写入机器相关路径或分析目录。

完整页级文件体积较大。日常检索应通过 `scripts/search_pdf_evidence.py` 限定模块和结果数，
不要整份加载 `pdf-evidence/modules/*.md` 或 `evidence-cards.jsonl`；只有人工核页时才使用
`--show-full-page`，需要列出全部命中页时才使用 `--limit 0`。

## 课程与古籍索引入口

| 模块 | 优先文件 | PDF 证据模块 |
| --- | --- | --- |
| 伤寒论 | `shanghanlun.md`、`six-channel.md`、`formula-patterns.md`、`notes-shanghan.md` | `shanghan` |
| 金匮要略 | `jingui.md`、`notes-jingui.md`、`formula-patterns.md` | `jingui` |
| 仲景心法 | `zhongjing-xinfa.md` | `zhongjing-xinfa` |
| 针灸 | `acupuncture.md`、`notes-acupuncture-dacheng.md` | `acupuncture` |
| 黄帝内经 | `huangdi.md`、`notes-huangdi.md` | `huangdi` |
| 神农本草 | `bencao.md`、`notes-bencao.md` | `bencao` |

## 勘误原则

- 先核课程语境，再核 PDF 页级证据，最后才参考古籍/方证索引。
- 高置信勘误直接改入原始 skill/reference 文件，不把修正只留在单独报表。
- 对同音误字、OCR 误字、穴名/方名/药名误写，必须能追到课程模块或 PDF 页码。
- 对缺少 PDF 或课程证据的术语，只标记为证据不足，不写成确定结论。
- 公开仓库只保留可追溯证据、稳定索引和正文修订。
