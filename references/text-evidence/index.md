# Text Evidence Index

This directory contains section-level evidence extracted from non-PDF recommended supplemental material.

## Citation format

- Use `text-evidence:<doc_id>#s<section>` for a coherent text section.
- Resolve `<doc_id>` in `source-manifest.json`.
- A section locator names the real source structure, such as `太陽病上篇 · 第1条`; it is not a fabricated PDF page number.
- `source_role: ni-recommended-supplement` means “倪师推荐补充资料（非倪师本人资料）”.

Example: `text-evidence:77af3a7c9960#s002` identifies the first numbered clause in the extracted DOC source.

## Files

| File | Purpose |
| --- | --- |
| `source-manifest.json` | Machine-readable source identity, extraction method, content caveat, and hash. |
| `evidence-cards.jsonl` | One complete record per preface or numbered clause. |
| `source-text/<doc_id>.txt` | Normalized complete text used to rebuild and audit the cards. |

## Source boundary

The archive filename is `02.大塚敬節傷寒論解說.doc`, while the internal title is `大塚敬節傷寒論條文`. The extracted content consists of Zhang Zhongjing's preface and 182 selected clauses/prompts; no systematic commentary body is present. Search results must therefore use the internal title and content as evidence, while retaining the archive filename only for provenance.

This source is a recommended supplement, not a Ni Haisha-authored or Ni Haisha-spoken source. Course distillation, transcripts, synchronized course PDFs, and screenshots remain primary. When primary evidence matches the topic, `scripts/search_pdf_evidence.py` automatically runs the separately labeled supplemental second pass across both PDF and text evidence.

## Coverage

- DOC sources: 1
- Coherent sections: 183
- Numbered clauses: 182
- Normalized characters: 9,174
- Privacy/promotional scan: passed

## Rebuild

```bash
python scripts/build_text_evidence.py /path/to/02.大塚敬節傷寒論解說.doc
```

LibreOffice performs the legacy DOC extraction. The build verifies an ordered clause sequence from 1 through 182 and rejects text that matches deterministic privacy or promotional-data patterns.
