# PDF Term Indexes

Term indexes are split by source module to keep each lookup file smaller and easier to review.

These indexes are lookup accelerators with concise snippets. They are not the complete content layer
and may cap common-term citations. Complete page text lives in `../evidence-cards.jsonl` and
`../modules/*.md`; the search script scans the complete page text instead of returning only indexed hits.

Use:

```bash
python scripts/search_pdf_evidence.py 大青龙汤 --module shanghan
python scripts/search_pdf_evidence.py 行间 荥穴 --module acupuncture
```

`index.json` lists the available module index files and term counts.
