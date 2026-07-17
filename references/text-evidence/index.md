# Text Evidence Index

This directory contains section-level evidence extracted from non-PDF recommended supplemental material.

## Citation format

- Use `text-evidence:<doc_id>#s<section>` for a coherent text section.
- Resolve `<doc_id>` in `source-manifest.json`.
- A section locator follows the source structure, such as `太陽病上篇 · 第1条`.
- `source_role: ni-recommended-supplement` means “倪师推荐补充资料（非倪师本人资料）”.

Example: `text-evidence:77af3a7c9960#s002` identifies the first numbered clause in the extracted DOC source.

## Files

| File | Purpose |
| --- | --- |
| `source-manifest.json` | Machine-readable source identity, content caveat, and hash. |
| `evidence-cards.jsonl` | One complete record per preface or numbered clause. |

## Source boundary

The source filename and internal title differ. The internal title is `大塚敬節傷寒論條文`, and the content consists of Zhang Zhongjing's preface and selected clauses/prompts; no systematic commentary body is present. Search results therefore use the internal title and actual content as evidence.

This source is a recommended supplement, not a Ni Haisha-authored or Ni Haisha-spoken source. Course distillation, transcripts, synchronized course PDFs, and screenshots remain primary. When primary evidence matches the topic, `scripts/search_pdf_evidence.py` automatically runs the separately labeled supplemental second pass across both PDF and text evidence.
