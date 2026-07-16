# PDF Evidence Index

This directory contains complete page-level text evidence extracted from the Nihaisha PDF source set. It is intended for source-grounded correction and citation inside the skill references.

## Citation Format

- Use `pdf-evidence:<doc_id>#p<page>` for page-level citations.
- Resolve `<doc_id>` in `source-manifest.json` or `sources.md`.
- Use `evidence-cards.jsonl` for complete page text and detected terms.
- Use `python scripts/search_pdf_evidence.py <term...>` or `rg` to search `evidence-cards.jsonl` / `term-index/<module>.json`; use `--doc-id <doc_id>` to limit a lookup to one source. The default CLI behavior is two-stage: print primary course evidence first, then automatically print separately labeled `ni-recommended-supplement` hits when the primary layer matched. The CLI also includes `references/text-evidence/` in that supplemental pass. Use `--primary-only` to suppress the second pass, or `--include-supplements` to force direct supplemental lookup without a primary match.
- Add `--show-full-page` to print complete stored page text and use `--limit 0` to return every matching page.

Example: `pdf-evidence:58423f817a06#p52` means page 52 of the PDF whose `doc_id` is `58423f817a06`.

## Files

| File | Purpose |
| --- | --- |
| `sources.md` | Human-readable PDF source and page-coverage list. |
| `source-manifest.json` | Machine-readable PDF source manifest. |
| `evidence-cards.jsonl` | One complete evidence record per physical PDF page. |
| `term-index/index.json` | Module index manifest for term lookup files. |
| `term-index/<module>.json` | Module-scoped term-to-card lookup with short snippets. |
| `modules/*.md` | Module-level complete page text, grouped by source PDF and collapsed by default. |
| `page-overrides.json` | Human-reviewed descriptions for pages that contain visuals but no text layer. |
| `correction-decisions.md` | High-confidence corrections and evidence status notes. |

## Evidence Policy

- These files use stable document IDs rather than machine-specific paths.
- `source_role: ni-recommended-supplement` means “倪师推荐补充资料”, not 倪师本人资料. Search and answers must label it separately from course-derived evidence.
- Every physical PDF page is represented. Text pages contain the complete extracted text layer, image-only pages use a human-reviewed override, unrelated promotional/privacy pages use an explicit exclusion marker, and blank pages are explicitly marked.
- No character limit or representative-card limit is applied to stored page text.
- Repeated source watermarks are stripped from page text; the original PDF source may contain the watermark `学习资料成本价打印公益流通禁止加价贩卖 微信公众号:岐黄圣贤智慧、岐黄传承道法自然`.
- Images and PDF layout are not embedded; consult the original PDF when typography, diagrams, seals, or page geometry matter.
- Course-derived medical content remains educational and is not individualized medical advice.

## Coverage

- PDF sources with extractable text: 22
- Physical page records: 10538
- Complete text pages: 10461
- Visual/scanned low-confidence pages without searchable text: 59
- Excluded non-content/privacy pages: 6
- Explicit blank pages: 12
- Course-module term indexes: 6
- Full-text classical-source modules: 1

## Rebuild

```bash
python scripts/build_pdf_evidence.py --source-root /path/to/nihaisha-pdfs
```

For scanned supplemental books, create or resume local OCR caches first:

```bash
python scripts/ocr_pdf_text.py --input /path/to/book.pdf --doc-id <doc_id> \
  --output output/pdf-ocr-cache/<doc_id>.jsonl --model v6-tiny
python scripts/build_pdf_evidence.py --source-root /path/to/nihaisha-pdfs \
  --ocr-cache-root output/pdf-ocr-cache
```

The committed page cards retain `text_method: paddleocr-v6-tiny`, so a normal rebuild can reuse existing OCR text when the ignored local cache is unavailable.
