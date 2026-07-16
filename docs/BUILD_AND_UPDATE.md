# Build And Update Guide

生产数据库的构建与增量更新以独立的 `nihaisha-rag-builder` 仓库/Skill 为唯一权威入口。它通常是同级 clone `../nihaisha-rag-builder`，也可以位于配置路径。这个 runtime 仓库负责读取和发布成品，不直接重建或修改生产数据库。

## 增量资料

PDF 可以以后分批加入，不要求一次提供全部资料。每批资料在 builder 中使用可移植的逻辑来源标识（例如 `pdfs/<basename>`），内部审计记录可保留受控原始位置，但公开 manifest、搜索、回答和引用不得暴露机器目录或用户名。

Builder 的生产流程必须是：

1. 把新 PDF 放入 builder 的隔离 incoming 区；记录许可、版本、文件哈希和来源。
2. 在新的 staging 目录构建完整候选集，不修改已发布资产。
3. 审计 OCR、页码、段落与 ID 稳定性、重复文档、embedding 模型/维度、知识抽取版本和来源路径。
4. 验证全文/知识/向量检索、golden evaluation、FAISS 映射、自检和隐私扫描。
5. 将同一代的 `rag.sqlite`、`manifest.json`、`vectors.faiss`、`vector_ids.jsonl` 和 `knowledge_structure_report.json` 作为**完整资产集**原子发布；禁止混用不同代文件。
6. 保留上一代资产以便回滚，发布后再次运行 runtime `doctor` 和代表性查询。

解析、chunking、embedding 或抽取规则变化时应完整重建候选集。窄幅增量也必须重新验证既有 ID、向量规格、FTS/知识索引和 FAISS 一致性；失败即丢弃 staging，不在生产库上修补。

## Runtime 兼容命令

runtime 仍保留 `build`、`augment-questions`、`rebuild-*` 和 `build-faiss`，仅用于开发/兼容性实验。不得把它们指向 `data/pdf_rag_bge_m3`。如需调试，只能写入明确的非生产 scratch 目录：

```bash
python3 -m nihaisha_kg build \
  --pdf-dir <portable-source-dir> \
  --out <scratch-root>/rag-candidate \
  --embedding siliconflow \
  --model BAAI/bge-m3 \
  --trace-dir <scratch-root>/traces
python3 -m nihaisha_kg build-faiss --db <scratch-root>/rag-candidate/rag.sqlite
```

Scratch/traces 可能包含课程正文或内部路径，必须留在受控环境且不得提交。生产构建请回到 builder 工作流。

## 知识结构迁移

可移植资产完成后，在 builder 中运行 `scripts/migrate_knowledge_structure.py` 生成独立 staging。迁移器建立文档层、逐段证据、规范实体、别名和类型化关系，并生成 `knowledge_structure_report.json`。旧知识单元只有在证据摘录逐字存在于原始段落且主体满足基本结构要求时才进入候选关系；具有直接方剂结构信号的关系，以及原文逐字出现的症状/剂量关系可标记为 `auto_accepted`，其余保持 `needs_review`。自动接纳只表示抽取结构检查通过，不得宣称已经专家审核。

质量报告至少核对文档、证据、实体、别名、关系、拒绝候选、孤立实体、关系证据覆盖率、谓词分布和审核状态。Runtime 只读这些结构，不在生产 SQLite 中补写或提升审核状态。

## 发布校验

- 运行 builder 全套测试、编译、质量评测、资产哈希与 manifest schema 校验。
- 核对文档/段落/检索单元/知识单元/guide/FAISS 数量与向量维度。
- 验证 `vector_ids.jsonl` 与 SQLite/FAISS 一一对应，抽样确认最近邻映射。
- 扫描凭据、环境转储、绝对 POSIX/Windows 路径和私密来源信息。
- 在 runtime 安装 `.[runtime]`，运行 `python3 -m nihaisha_kg doctor`、完整测试和代表性 JSON 查询。
- 用 `git lfs ls-files` 检查 `rag.sqlite`、`vectors.faiss`；暂存后用 `git cat-file -s :<path>` 确认 Git 对象是小型 LFS pointer。
- 确认五项完整资产来自同一 staging generation，且 incoming、scratch、trace、WAL/SHM 和 `.env` 未进入提交。

LFS 上传或任一校验失败时不得发布部分资产。不要提交真实 API key。
