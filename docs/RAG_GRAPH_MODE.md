# RAG + 知识图谱模式

RAG + 知识图谱是 `nihaisha` 的可选增强模式，用于从已发布的 PDF 语料中检索原文、定位页码，并用结构化关系辅助导航。它不是默认轻量模式，也不是让模型脱离资料自由回答的“万能知识库”。

核心原则只有一句：

> BM25、Embedding、FAISS、知识单元和图谱都负责找路；最终能够支撑回答的，是检索到的 PDF 原始段落。

![RAG + 知识图谱检索与证据链](./rag-graph-mode.svg)

## 什么时候使用

| 需求 | 推荐模式 | 原因 |
| --- | --- | --- |
| 普通课程复习、逐课地图、截图检索 | 默认轻量模式 | 仓库内模块更完整，不需要约 3.68 GB RAG 资产 |
| 精确方名、穴位、书名、原句或出处 | `text`，必要时再比较 `hybrid` | BM25/FTS 更擅长稀有原词和精确短语 |
| 白话表达与原文措辞差异较大 | `hybrid` | Embedding 可以补充语义召回 |
| 查询方证、症状、实体关系 | `graph` 或 `hybrid` | 图谱用于扩展关系，再回到原文核验 |
| 查询数据库未收录的课程或学习路线 | 轻量模式或明确能力缺口 | 不应拿其他课程的相似段落拼答案 |

普通问题不会自动下载 RAG 资产。只有用户明确选择 RAG，并且本地资产已经准备好时，才应进入该模式。

## 四路召回分别做什么

### Text：BM25 / FTS 精确召回

适合方名、穴位、古籍条文、完整短语和页级出处。当前实现使用正文优先的 SQLite FTS5/trigram 检索，并增加：

- 精确短语和核心实体加分；
- 标题命中不能单独支撑回答；
- 目录、版权页、导航噪声和重复 OCR 内容降权；
- 出处问题先跑可靠完整锚点，再考虑宽松查询。

Embedding 只能判断语义接近，不能保证结果真的包含“太阳病欲解时”“合谷”“太冲”或某个准确方名，因此 BM25 仍然不可替代。

### Vector：BGE-M3 + FAISS 语义召回

Embedding 把查询和检索单元编码成 1024 维向量；FAISS 负责在 359,557 个已发布向量中高效寻找相近候选。

两者职责不同：

- BGE-M3 负责“如何表示语义”；
- FAISS 负责“如何从大量向量中找到邻近项”；
- 两者都不负责证明医学事实正确。

当前大规模 dense 数据库没有 SQLite 全量向量扫描降级路径，因此 `vector` 和 `hybrid` 必须具备可读的 FAISS 索引。`text`、`knowledge` 和 `graph` 不需要 FAISS。

### Knowledge：规则知识单元

旧 `knowledge_units` 保存从原文抽取的方证、症状、比较、剂量和方法线索，用来增加可解释候选。它是导航层，最终引用仍须绑定原始段落。

### Graph：受控关系导航

图谱只读取通过结构检查的 `auto_accepted` 关系，以及未来人工确认的 `reviewed` 关系。实体、别名、关系和 guide nodes 可以帮助找到关联段落，但：

- `auto_accepted` 只表示抽取结构通过确定性检查，不代表专家审核；
- `needs_review` 关系不能自动成为结论；
- 图谱三元组、guide node 和扩展问题不能脱离原文独立引用；
- 图谱候选必须回到包含核心实体的 PDF 段落。

因此当前实现是“证据型知识结构 + RAG”，不是已经由专家审核完成的医学知识图谱，也不是全局 GraphRAG。

## Hybrid 如何形成答案

`hybrid` 的运行顺序如下：

1. 规范化查询，识别出处、比较、临床信息、剂量或一般问题。
2. 抽取方名、穴位、症状、课程范围和可靠完整短语。
3. 并行执行 text、vector、knowledge、graph 四路召回。
4. 通过 RRF 融合排名；graph 以较低的 `0.35` 权重参与导航。
5. 如果启用 reranker，再对候选进行重排；失败时保留原召回并记录降级状态。
6. 执行核心实体、正文可回答性、来源层和噪声门控。
7. 从通过门控的 PDF 段落中生成短摘录和详细依据。
8. 输出结论、原文摘录、PDF 文件名、页码、段落 ID 和上下文导航。
9. 对证据不足、语料缺失和医疗高风险问题执行拒答或安全分流。

一个高分向量、图谱关系或标题命中都不能跳过第 6 步直接进入答案。

## 证据和语料边界

发布资产按来源分层：

| 来源层 | 含义 | 默认规则 |
| --- | --- | --- |
| `course_primary` | 课程讲义、同步文稿和教程 | 可以作为课程主张的原文证据 |
| `classic_primary` | 当前候选经典文档 | 可检索，但不代表版本已经独立校勘 |
| `reference_secondary` | 外部关联参考资料 | 正文默认排除；必须显式使用 `--include-references`，并标为“非倪海厦著作” |
| `derived` | 实体、候选关系、扩展问题等派生数据 | 只用于导航，不能独立作证 |

若默认主语料没有完整证据，系统应明确说“证据不足”；若问题属于《天纪》或学习路线等当前 RAG 未覆盖模块，应返回能力缺口并转到轻量资料，不能借其他课程的语义相似段落替代。

## 安装与启用

需要 Python 3.11+ 和约 3.7 GB 可用空间：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[runtime]"
python3 -m nihaisha_kg download-assets
python3 -m nihaisha_kg doctor
```

`doctor` 顶层状态应为 `ok`。它会检查 SQLite、schema、dense 元数据、FAISS 文件、ID 映射、Python FAISS 模块和索引可读性。

### 使用远程查询 Embedding

复制示例文件，并只在本机填写 Key：

```bash
cp .env.example .env
```

```dotenv
SILICONFLOW_API_KEY=你的_API_Key
```

推荐模型为 `BAAI/bge-m3`。`.env` 已被 Git 忽略；不要把 Key 写进问题、trace、Markdown 或提交记录。程序解析距离当前目录最近的 `.env`，已经导出的同名环境变量优先。

### 使用本地 Embedding

```bash
python -m pip install -e ".[local]"
python3 -m nihaisha_kg search "桂枝汤和麻黄汤如何鉴别？" \
  --mode hybrid --embedding local-bge-m3 --limit 8
```

## 常用命令

```bash
# 精确原词
python3 -m nihaisha_kg search "太阳病欲解时" --mode text --limit 5

# 图谱导航回原文
python3 -m nihaisha_kg search "麻黄汤对应什么方证？" --mode graph --limit 5

# 四路融合并生成带引用回答
python3 -m nihaisha_kg answer "桂枝汤和麻黄汤的方证如何鉴别？" \
  --mode hybrid --limit 8

# 检查查询改写、通道排名和最终证据
python3 -m nihaisha_kg answer "问题" \
  --mode hybrid --limit 8 --json --trace --reranker none
```

每条 citation 应包含可移植的 `source_path`、页码、`paragraph_id`、短摘录、完整原段和前后文 evidence ID。trace 只是检索诊断信息，不是证据，也不是机密信息保护边界。

## 是否能适用于任何问题

不能。Hybrid 提高的是召回覆盖和安全失败能力，不是对任意问题的正确性保证。以下情况仍可能失败：

- PDF 本身没有相关课程或原文；
- OCR 错字、断句或重复内容严重；
- 用户主语和任务不明确；
- 冷门实体、异体字或别名尚未规范化；
- 问题需要跨多个章节推理；
- 学习计划、个性化诊断等任务本来就不是原文检索。

现有 golden 和冒烟案例用于发现回归，样本量不足以证明系统全面准确。评估时应分别检查召回、首个正确证据排名、上下文精度、禁止命中、引用完整性、能力缺口和医疗安全，而不能只看命令是否成功。

## 诊断常见问题

### `doctor` 提示 FAISS Python module unavailable

说明当前执行命令的 Python 环境没有安装运行依赖。检查 `which python3`，并在同一个环境安装 `.[runtime]`。不要只确认磁盘上存在 `vectors.faiss`；索引文件和可用的 Python FAISS 模块缺一不可。

### Hybrid 能运行，但答案被语义相似内容带偏

使用 trace 检查：

1. 精确实体是否出现在 `normalized_query` 和 query plan；
2. text、vector、knowledge、graph 各通道的排名；
3. 最终 `selected_paragraph_ids`；
4. citation 是否真的包含核心实体；
5. 是否误命中标题、目录、参考资料或其他课程。

精确出处问题应同时用 `text` 对照。Embedding 是补充召回，不应覆盖可靠的完整短语和正文证据。

### 没有 Key 是否完全不能用

不是。`text`、`knowledge` 和 `graph` 可完全离线运行。只有远程 `vector`/`hybrid` 查询 Embedding 需要 Key；也可以安装本地 BGE-M3 后端。

## 医疗安全

本模式只用于课程学习、原文核对和资料研究，不提供个人诊断、处方、剂量决策、购药建议、针灸或外治操作指导。胸痛、呼吸困难、意识改变、疑似中风、大出血等急重症信息必须先提示联系当地急救或前往急诊，不能等待课程检索结果。

涉及剂量、方药或处方线索时，必须考虑个体体质、病情阶段、兼证、年龄、基础病、用药史，以及现代药材来源、炮制、浓度和药效差异。真实健康问题请通过正规医疗渠道面诊。

## 相关文档

- [项目 README](../README.md)
- [RAG 构建与更新](./BUILD_AND_UPDATE.md)
- [用途与风险说明](./USE_AND_RISK_NOTICE.md)
- [RAG prototype README](https://github.com/JuneYaooo/nihaisha-nishi-tcm)
