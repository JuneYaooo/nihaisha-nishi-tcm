# nihaisha 评测集 V1

V1 共 240 题。每题属于一个主能力，同时可标注多个内容模块、辅助能力、证据形式和交互方式。两种候选均独立生成 3 次，使用不同于答案模型的裁判盲评。

## 三轮评测结果

### 总体表现

| 指标 | RAG | 普通 Skill | 样本量 |
| --- | ---: | ---: | ---: |
| 回答得分 | 92.8%（95% CI 91.6–94.1） | 91.4%（95% CI 90.1–92.7） | 240 题 × 3 次 |
| 预期行为通过率 | 83.1% | 85.8% | 每通道 720 个回答 |
| 必须检查项通过率 | 87.9% | 88.5% | 每通道 2,169 项检查 |
| 引用支持精确率 | 92.9% | 93.2% | 171 题 × 3 次 |
| 引用主张覆盖率 | 90.4% | 92.0% | 171 题 × 3 次 |
| 引用可访问率 | 99.1% | 97.3% | 171 题 × 3 次 |

### 主能力

| 主能力 | 题数 | RAG 回答得分 | 普通 Skill 回答得分 | 差值（RAG − Skill） |
| --- | ---: | ---: | ---: | ---: |
| 知识检索 | 48 | 90.4% | 88.0% | +2.4 |
| 跨源整合 | 48 | 90.6% | 86.7% | +3.9 |
| 引用与溯源 | 36 | 85.3% | 91.3% | -6.0 |
| 推论与鲁棒性 | 48 | 96.7% | 90.8% | +5.9 |
| 临床安全 | 60 | 98.0% | 98.5% | -0.5 |
| **合计** | **240** | **92.8%** | **91.4%** | **+1.4** |

### 常见用户需求

| 用户通常想做什么 | 典型问法 | 题数 | RAG | 普通 Skill |
| --- | --- | ---: | ---: | ---: |
| 查一个知识点或主题 | “厥阴病有哪些主要特点？” | 33 | 89.7% | 86.8% |
| 比较两个或多个内容 | “桂枝汤和麻黄汤怎么区分？” | 31 | 92.2% | 88.1% |
| 综合多份课程资料 | “伤寒和金匮里的水气怎么比较？” | 26 | 90.7% | 83.9% |
| 核对原文和出处 | “这句话出自哪一课、哪一页？” | 38 | 87.4% | 91.6% |
| 判断一个说法是否成立 | “没检索到，能证明从没说过吗？” | 31 | 96.0% | 89.9% |
| 根据具体情况分析 | “出现这种情况，应该先考虑什么？” | 34 | 98.9% | 99.3% |
| 询问具体做法 | “能直接告诉我剂量或针刺方法吗？” | 23 | 97.3% | 97.4% |
| 安排学习和资料查找 | “初学者应该从哪里开始学？” | 8 | 87.5% | 99.3% |
| 补充信息后继续追问 | “补充这些信息后，前面的判断要怎么改？” | 16 | 94.5% | 93.1% |

### 核心课程模块

这里只统计五门核心课程；其他资料仅用于来源核验、安全和能力边界题，不单列内容成绩。一题可涉及多个核心课程，因此下表题数不会相加为 240。

| 内容模块 | 涉及题数 | RAG 回答得分 | 普通 Skill 回答得分 |
| --- | ---: | ---: | ---: |
| 伤寒论 | 101 | 94.5% | 89.1% |
| 金匮要略 | 64 | 94.8% | 87.4% |
| 针灸 | 32 | 95.7% | 90.6% |
| 神农本草 | 30 | 94.5% | 91.4% |
| 黄帝内经 | 27 | 91.0% | 88.6% |

### 交互方式

| 交互方式 | 题数 | RAG 回答得分 | 普通 Skill 回答得分 |
| --- | ---: | ---: | ---: |
| 直接提问 | 179 | 92.4% | 91.8% |
| 对抗诱导 | 21 | 94.1% | 92.5% |
| 口语表达 | 15 | 95.8% | 87.8% |
| 噪声输入 | 9 | 92.8% | 87.9% |
| 信息不足 | 7 | 88.0% | 88.5% |
| 多轮修订 | 4 | 99.5% | 97.1% |
| 极简提问 | 3 | 95.6% | 86.4% |
| 矛盾前提 | 2 | 97.9% | 99.0% |

### 专项指标

| 专项指标 | RAG | 普通 Skill | 统计范围 |
| --- | ---: | ---: | ---: |
| 返回池 Hit@10 | 94.5% | 91.6% | 146 道检索题 × 3 次 |
| 返回池 nDCG@10 | 74.9% | 69.3% | 146 道检索题 × 3 次 |
| 能力边界通过率 | 30.0%（18/60） | 8.3%（5/60） | 20 道边界题 × 3 次 |
| 同类问题回答一致率 | 87.5%（105/120） | 62.5%（75/120） | 40 组 × 3 次 |
| 严重安全问题标记数 | 4/720 | 1/720 | 全部回答 |
| 来源误归属观测数 | 13/513 | 7/513 | 171 道引用题 × 3 次 |
| 回答得分配对差 | +1.4（95% CI -0.5–3.2） | 基准 | 240 题 × 3 次 |

## 题集设计

主能力用于形成稳定、互斥的一级分组；其他维度允许多标签，用于观察同一题对多种能力和资料的联合要求。

| 设计维度 | 字段 | 用途 |
| --- | --- | --- |
| 主能力 | `suite` | 知识、整合、引用、推理、安全五类一级结果 |
| 用户需求 | `user_need`（由 `question_type` 汇总） | 查知识、做比较、核出处、判断说法、情境分析等常见目的 |
| 内容模块 | `content_modules` | 题目素材标签；公开内容成绩只汇总五门核心课程 |
| 辅助能力 | `capabilities` | 检索、比较、综合、范围控制、不确定性处理等 |
| 证据形式 | `evidence_modalities` | 课程原文、扫描材料、截图、仓库元数据等 |
| 交互方式 | `interaction_pattern` | 直接、口语、噪声、多轮、信息不足、对抗等 |
| 输出形式 | `expected_output` | 简答、对比表、证据列表、判断框架、安全转介等 |

其他逐题字段：

| 字段 | 含义 |
| --- | --- |
| `case_id` | 稳定、唯一的 case 标识 |
| `difficulty` | `easy` / `medium` / `hard` |
| `risk_level` | `low` / `medium` / `high` / `critical` |
| `query` | 发送给被测系统的用户问题 |
| `expected_behavior` | `answer` / `clarify` / `abstain` / `safe_redirect` |
| `citation_required` | 是否要求可核验引用 |
| `reference_targets` | 仅用于人工核验路由，不用于正式回答检索 |
| `required_checks` | 回答需覆盖的原子检查项 |
| `forbidden_content` | 出现即扣分或触发安全失败的内容 |
| `dimensions` | 本题进入归一化分数的评分维度 |
| `retrieval_evaluation` | `evidence_required` / `capability_gap` / `not_applicable` |
| `safety_gates` | 本题适用的安全检查项 |
| `pair_id` | 可选；等价改写、对抗或多轮修订组 |

240 题中包含 146 道证据检索题、20 道能力边界题和 74 道不计算检索指标的题；81 道 high/critical 题带安全检查，40 个 `pair_id` 组用于鲁棒性评测。临床安全主能力题不向任一候选提供检索证据，只评回答、澄清、拒答、转介与边界保持。

## 评测口径

- 回答得分只汇总题目声明的适用维度；未声明的维度不进入分母。
- 普通 Skill 检索完整 references 索引，不读取逐题 `reference_targets`。
- 引用裁判同时看到候选答案和该候选实际获得的证据正文。
- `pool_hit` 与 `pool_ndcg` 只描述已返回证据池，不等同于全库召回率。
- A/B 顺序按题目与采样轮次稳定盲化；答案模型与裁判模型分离。
- 每题每通道生成 3 次；回答区间使用 case bootstrap，比例区间使用 Wilson 95% CI。

## 文件

| 文件 | 内容 |
| --- | --- |
| `answer_eval_v1.jsonl` | 240 道多维题目及逐题评分口径 |
| `answer_eval_rubric_v1.md` | 评分、引用、安全、统计和分组规则 |
| `answer_eval_run_v1.json` | 三轮运行协议、环境和 artifact hash |
| `answer_eval_summary_v1.json` | 三轮总体结果与全部分组数据 |
| `answer_eval_judgments_v1.jsonl` | 3 × 240 条独立盲评结果 |
| `answer_eval_pairs_v1.jsonl` | 40 组 × 3 轮鲁棒性裁判结果 |
| `scripts/` | 题集、检索、回答、盲评、合并、聚合和校验脚本 |
| `schemas/` | 结构化输出 schema |

原始检索证据、回答、分批裁判文件和模型日志保存在 `.local-evals/v1/`，不提交到 Skill 安装包。

## 执行流程

```bash
python3 evals/scripts/validate_v1.py --protocol-only
python3 evals/scripts/run_retrieval_v1.py
```

三轮分别生成 RAG 和普通 Skill 答案；以下以第一轮为例：

```bash
python3 evals/scripts/run_answers_v1.py --mode rag --batch-size 1 \
  --retrieval .local-evals/v1/rag_retrieval.jsonl \
  --output-dir .local-evals/v1/sample-01/answer-batches \
  --merged-output .local-evals/v1/sample-01/rag_answers.jsonl
python3 evals/scripts/run_answers_v1.py --mode lightweight --batch-size 1 \
  --output-dir .local-evals/v1/sample-01/answer-batches \
  --merged-output .local-evals/v1/sample-01/lightweight_answers.jsonl
```

使用不同于答案模型的裁判完成回答和鲁棒性盲评：

```bash
python3 evals/scripts/run_answer_judge_v1.py \
  --sample-id sample-01 \
  --local-dir .local-evals/v1/sample-01 \
  --retrieval .local-evals/v1/rag_retrieval.jsonl \
  --output-dir .local-evals/v1/sample-01/judge-batches \
  --merged-output .local-evals/v1/sample-01/answer_judgments.jsonl
python3 evals/scripts/run_pair_judge_v1.py \
  --sample-id sample-01 --batch-size 5 \
  --local-dir .local-evals/v1/sample-01 \
  --output .local-evals/v1/sample-01/answer_pairs.jsonl
```

三轮均完成后合并、聚合并校验：

```bash
python3 evals/scripts/merge_v1_runs.py \
  --judgments .local-evals/v1/sample-{01,02,03}/answer_judgments.jsonl \
  --pairs .local-evals/v1/sample-{01,02,03}/answer_pairs.jsonl
python3 evals/scripts/aggregate_v1.py
python3 evals/scripts/validate_v1.py
```

若配置网关误判旧课文中的生殖、解剖或其他无关段落，可显式加入 `--provider-safe-normalization`；固定替换与占位规则及其 hash 记录在运行元数据中。

完整评分口径见 [`answer_eval_rubric_v1.md`](./answer_eval_rubric_v1.md)。
