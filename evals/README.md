# nihaisha 评测集 V1

V1 共 100 题，覆盖知识检索、跨源整合、引用与溯源、推论与鲁棒性、临床安全。当前协议为
`answer-eval-v1.1`：保留原题集和文件名，原地修正旧版评测的公平性、引用核验、适用维度、统计和
可复现性问题。

## 当前状态

**协议和运行器已就绪，新口径结果待重跑。** 2026-07-30 尝试独立盲评时，本地 Codex CLI
连续发生传输超时；项目没有把旧裁判结果机械补字段后冒充新结果。

旧版单轮数字仍保存在 `answer_eval_summary_v1.json` 的 `legacy_single_run`，仅用于历史定位：

- 它比较的是两种不同检索辅助条件下的冻结证据回答，不是公平端到端 A/B；
- 普通轻量证据曾被每题 `reference_targets` 限定，相当于 Oracle 路由；
- 旧裁判没有看到轻量证据正文，因此轻量引用支持率不可验证；
- 答案和裁判使用同一模型，每题只生成一次；
- nDCG 只在 RAG 自己返回的 Top-10 内计算；
- 旧汇总器把鲁棒结果和总安全违规率写死。

所以旧版 `87.6%` 与 `88.3%` 不能解释为产品性能差异，`0/25` 也不能证明安全违规率为零。

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

## V1.1 修正了什么

### 适用维度

旧汇总固定把六项相加除以 20，忽略每题 `dimensions`。新汇总只使用题目声明的维度，引用维度与
`citation_required` 严格一致，同时保存全部原始分供审计。

### 公平性

正式轻量评测默认检索全部 references，不读取每题 `reference_targets`。`--lightweight-oracle-targets`
只用于复现历史上限实验，结果必须标为 Oracle，不能与 RAG 端到端能力直接比较。

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
| `answer_eval_run_v1.json` | 新协议与历史运行 provenance/hash |
| `answer_eval_summary_v1.json` | 当前状态和明确降级的历史单轮结果 |
| `answer_eval_judgments_v1.jsonl` | 旧版逐题结果；新独立裁判完成后由运行器原位替换 |
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

分别生成三轮答案。下面展示单轮命令；每轮必须使用独立输出目录并记录 seed/运行信息：

```bash
python3 evals/scripts/run_answers_v1.py --mode rag
python3 evals/scripts/run_answers_v1.py --mode lightweight
```

轻量模式默认搜索全部 references。不得在正式结果中加入 `--lightweight-oracle-targets`。

使用不同于答案模型的裁判，按 case 隐藏 A/B 名称并核验双方实际证据：

```bash
python3 evals/scripts/run_answer_judge_v1.py \
  --local-dir .local-evals/v1 \
  --output-dir .local-evals/v1/judge-batches
python3 evals/scripts/run_pair_judge_v1.py --local-dir .local-evals/v1
```

人工复核完成并更新 `answer_eval_run_v1.json` 后，再聚合和校验：

```bash
python3 evals/scripts/aggregate_v1.py
python3 evals/scripts/validate_v1.py
```

## 发布检查

发布报告至少包含：

- 按 suite、module、task_type、risk_level、difficulty 分组的结果；
- 适用维度分、逐项检查通过率、预期行为正确率；
- 引用精确率、主张覆盖率、可访问率、来源误归属；
- 检索 returned-pool 指标与能力边界正确率；有 gold qrels 时另报 Recall/MRR/Forbidden Hits；
- 所有安全失败和紧急转介失败 case ID；
- 配对差异、case bootstrap 区间、三次生成方差；
- 独立人工分歧和第三人裁决；
- 代码、题集、资产、模型、prompt、参数、环境和 artifact hash。

完整门槛见 [`answer_eval_rubric_v1.md`](./answer_eval_rubric_v1.md)。任何安全严重失败、引用不可访问、
Oracle 条件冒充端到端结果或缺少独立专业复核的运行，都不得标记为 release eligible。
