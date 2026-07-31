# nihaisha 评测集 V1

V1 共 100 题，覆盖知识检索、跨源整合、引用与溯源、推论与鲁棒性、临床安全。当前协议为
`answer-eval-v1.1`，包含适用维度评分、双方证据核验、三次采样、盲化裁判、置信区间和安全硬门槛。

## 三轮评测结果

### 总体表现

| 指标 | RAG | 普通 Skill | 样本量 |
| --- | ---: | ---: | ---: |
| 回答得分 | 91.9%（95% CI 89.8–94.0） | 90.1%（95% CI 87.8–92.1） | 100 题 × 3 次 |
| 预期行为通过率 | 82.0% | 85.0% | 300 个回答 |
| 必须检查项通过率 | 87.3% | 87.5% | 909 项检查 |
| 引用支持率 | 91.9% | 94.8% | 73 题 × 3 次 |
| 引用主张覆盖率 | 89.6% | 93.7% | 73 题 × 3 次 |
| 引用可访问率 | 99.8% | 97.4% | 73 题 × 3 次 |

### 五类题表现

| 评测类别 | 题数 | RAG 回答得分 | 普通 Skill 回答得分 | 差值（RAG − Skill） |
| --- | ---: | ---: | ---: | ---: |
| 知识检索 | 20 | 90.8% | 87.6% | +3.2 |
| 跨源整合 | 20 | 88.6% | 84.0% | +4.6 |
| 引用与溯源 | 15 | 81.3% | 93.9% | -12.6 |
| 推论与鲁棒性 | 20 | 95.8% | 85.8% | +10.0 |
| 临床安全 | 25 | 98.8% | 98.0% | +0.8 |
| **合计** | **100** | **91.9%** | **90.1%** | **+1.8** |

### 专项评测

| 专项指标 | RAG | 普通 Skill | 统计范围 |
| --- | ---: | ---: | ---: |
| 前 10 条检索命中率 | 94.9% | 87.0% | 59 道检索题 × 3 次 |
| 前 10 条检索排序质量 | 77.6% | 68.7% | 59 道检索题 × 3 次 |
| 能力边界通过率 | 40.7% | 11.1% | 9 道边界题 × 3 次 |
| 同类问题回答一致率 | 75.0%（9/12） | 100.0%（12/12） | 4 组 × 3 次 |
| 安全门槛通过数 | 152/153 | 153/153 | 34 道高风险题 × 3 次 |
| 严重安全问题标记数 | 1/300 | 0/300 | 全部回答 |
| 来源误归属题数 | 4/73 | 1/73 | 需要引用的题 |
| 回答得分配对差 | +1.9（95% CI -1.2–5.1） | 基准 | 100 组配对题 |

## 题集字段

| 字段 | 含义 |
| --- | --- |
| `case_id` | 稳定、唯一的 case 标识 |
| `suite` | `knowledge` / `integration` / `citation` / `reasoning` / `safety` |
| `modules` | 预期涉及的课程或资料模块 |
| `task_type` | 任务类型 |
| `difficulty` | `easy` / `medium` / `hard` |
| `risk_level` | `low` / `medium` / `high` / `critical` |
| `query` | 发送给被测系统的用户问题 |
| `expected_behavior` | `answer` / `clarify` / `abstain` / `safe_redirect` |
| `citation_required` | 是否要求可核验引用 |
| `reference_targets` | 仅用于人工核验路由；正式回答生成禁止据此缩小检索范围 |
| `required_checks` | 合格回答必须逐项满足的原子检查项 |
| `forbidden_content` | 出现即扣分或触发安全失败的内容 |
| `dimensions` | 本题实际进入归一化分数的标准维度 |
| `retrieval_evaluation` | `evidence_required` / `capability_gap` / `not_applicable` |
| `safety_gates` | high/critical 题适用的安全硬门槛 |
| `pair_id` | 可选；同义、对抗或多轮改写组 |

当前分层为：59 道证据检索题、9 道能力边界题、32 道不计检索分的题；34 道 high/critical 题全部
进入安全门槛，其中 8 道要求紧急转介。题集仍是高难挑战集，不代表真实用户流量分布。

## 评测口径

### 适用维度

汇总只使用题目声明的 `dimensions`，引用维度与 `citation_required` 严格一致，同时保存全部原始分供审计。

### 公平性

正式轻量评测默认检索全部 references，不读取每题 `reference_targets`。`--lightweight-oracle-targets`
只用于诊断性上限实验，结果必须标为 Oracle，不能与 RAG 端到端能力直接比较。

### 引用

盲评裁判同时收到候选自己的实际证据正文，分别计算引用支持精确率、主张覆盖率、可访问率和来源误归属。
只给裁判文件名、不给正文时不再生成引用指标。

### 检索

安全拒答、产品规则和学习计划不再进入检索总分。没有完整 qrels 时只报告 `pool_hit` 和
`pool_ndcg`，不再将返回池排序写成全库召回。

### 安全与统计

安全覆盖所有 high/critical 题并逐门槛记录；结果按 `0/34` 等计数和置信区间展示。鲁棒性按组数
展示。每题目标为三次采样，A/B 顺序稳定随机化，答案与裁判模型分离。

## 文件

| 文件 | 内容 |
| --- | --- |
| `answer_eval_v1.jsonl` | 100 道题及适用维度、检索口径、安全门槛 |
| `answer_eval_rubric_v1.md` | 新评分、引用、安全、统计和发布规则 |
| `answer_eval_run_v1.json` | 协议与当前三轮运行 provenance/hash |
| `answer_eval_summary_v1.json` | 当前三轮结果汇总、区间和分组数据 |
| `answer_eval_judgments_v1.jsonl` | 3 × 100 条独立盲评结果 |
| `answer_eval_pairs_v1.jsonl` | 4 个配对组 × 3 轮的鲁棒性裁判结果 |
| `scripts/` | 检索、回答、盲评、鲁棒性、聚合和校验脚本 |
| `schemas/` | Codex 结构化输出 schema |

原始证据和模型日志默认保存在 `.local-evals/v1/`，不会进入 Skill 安装包。正式发布结果时应提交稳定
evidence ID、source/page、hash 和重建脚本；原文是否提交需同时考虑体积与资料授权。

## 执行流程

先验证协议：

```bash
python3 evals/scripts/validate_v1.py --protocol-only
```

确认完整 RAG 资产和 embedding 可用后，冻结 Hybrid Top-10：

```bash
python3 evals/scripts/run_retrieval_v1.py
```

分别生成三轮答案。每轮必须使用独立输出目录；以下以第一轮为例：

```bash
python3 evals/scripts/run_answers_v1.py --mode rag --batch-size 1 \
  --retrieval .local-evals/v1/rag_retrieval.jsonl \
  --output-dir .local-evals/v1/sample-01/answer-batches \
  --merged-output .local-evals/v1/sample-01/rag_answers.jsonl
python3 evals/scripts/run_answers_v1.py --mode lightweight --batch-size 1 \
  --output-dir .local-evals/v1/sample-01/answer-batches \
  --merged-output .local-evals/v1/sample-01/lightweight_answers.jsonl
```

轻量模式默认搜索全部 references。不得在正式结果中加入 `--lightweight-oracle-targets`。

使用不同于答案模型的裁判，按 case 隐藏 A/B 名称并核验双方实际证据：

```bash
python3 evals/scripts/run_answer_judge_v1.py \
  --sample-id sample-01 \
  --local-dir .local-evals/v1/sample-01 \
  --retrieval .local-evals/v1/rag_retrieval.jsonl \
  --output-dir .local-evals/v1/sample-01/judge-batches \
  --merged-output .local-evals/v1/sample-01/answer_judgments.jsonl
python3 evals/scripts/run_pair_judge_v1.py \
  --sample-id sample-01 \
  --local-dir .local-evals/v1/sample-01 \
  --output .local-evals/v1/sample-01/answer_pairs.jsonl
```

三轮均完成后，先合并裁判产物，再更新 `answer_eval_run_v1.json`、聚合和校验：

```bash
python3 evals/scripts/merge_v1_runs.py \
  --judgments .local-evals/v1/sample-{01,02,03}/answer_judgments.jsonl \
  --pairs .local-evals/v1/sample-{01,02,03}/answer_pairs.jsonl
python3 evals/scripts/aggregate_v1.py
python3 evals/scripts/validate_v1.py
```

若 provider 对旧医学、生殖或解剖词发生误判，可显式加入 `--provider-safe-normalization`；它会使用
`v1_evidence.py` 中的固定替换表，并在运行元数据中记录 hash。

## 结果记录

评测报告记录：

- 按 suite、module、task_type、risk_level、difficulty 分组的结果；
- 适用维度分、逐项检查通过率、预期行为正确率；
- 引用精确率、主张覆盖率、可访问率、来源误归属；
- 检索 returned-pool 指标与能力边界正确率；有 gold qrels 时另报 Recall/MRR/Forbidden Hits；
- 所有安全失败和紧急转介失败 case ID；
- 配对差异、case bootstrap 区间、三次生成方差；
- 独立人工分歧和第三人裁决；
- 代码、题集、资产、模型、prompt、参数、环境和 artifact hash。

完整评分口径见 [`answer_eval_rubric_v1.md`](./answer_eval_rubric_v1.md)。
