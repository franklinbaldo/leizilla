# ADR-0019 — Targeted re-OCR via Kreuzberg where the reader does not close

Status: accepted, 2026-11-16. Implemented in `src/leizilla/reocr.py`; first publication pending.

Relates to: [ADR-0001](0001-projeto-estatico-duckdb-torrent.md) (IA as the pillar),
[ADR-0015](0015-camada-de-texto-desacoplada.md) (text layer), front `ocr-engine-benchmark`
in `docs/okf/project-dag.md`, `docs/SCHEMA.md` 3.5.1.

## Context

The text layer (`textos`) carries the OCR that the Internet Archive derives from the
preserved PDFs (`_djvu.txt`, Tesseract, or a conversion of the PDF's own text layer).
`leizilla.hierarchy_sequence.read_hierarchy` self-certifies a norm when the article level
closes (a full 1..N chain, nothing unexplained, the closing clause where an article
starts). On 2086 cached IA texts it closes 1790; 296 do not.

A 20-norm pilot (2026-11-16; norms where the reader did not close) re-read the PDFs with
Kreuzberg 4.10.4 (`force_ocr=True`, `use_cache=False`):

- PaddleOCR backend (`language="pt"`): 15 of 20 closed with the reference article set;
- Tesseract backend: 7 of 20;
- about 1.4 s/page on 4 CPUs.

The same engine must not replace the IA text wholesale: on 5 control norms that already
closed, PaddleOCR broke 2. Some PDFs are stored with `/Rotate 180`; Kreuzberg's OCR path
reads them upside down and its auto-rotate options do not help (the Tesseract one
crashes). Rasterizing the pages ourselves with poppler, which honors `/Rotate`, fixes it.

## Decision

1. **Queue.** Norms with text in the published `textos` whose `read_hierarchy` article
   level does not close, ordered by `texto_id`, minus norms already attempted with the
   same PDF (`sha256_fonte`) and engine version. `--limit` and `--max-pages` (default 40;
   larger PDFs are recorded as `excede-max-paginas` and retried only if the limit grows).
2. **Re-OCR.** Download the PDF from IA (sequential, at least 1 s apart, project
   User-Agent), rasterize every page at 300 dpi with `pdftoppm`, run each page image
   through Kreuzberg with the PaddleOCR backend, concatenate the pages in order.
   Kreuzberg is the entry point and lives in the optional extra `reocr`; it is imported
   lazily, so the default install and CI do not carry it.
3. **Acceptance gate (deterministic, no LLM).** The new text is accepted only if
   `read_hierarchy(new)` closes the article level **and** its own-article count is at
   least the one read from the IA text. Otherwise the IA text stays and the reason is
   recorded (`nao-fecha`, `menos-artigos`, `pdf-sha256-diverge`, `ocr-vazio`,
   `ocr-falhou`, `excede-max-paginas`). The downloaded bytes must match `sha256_fonte`.
4. **Storage.** One dataset `reocr.parquet`, one row per attempt (identifier, pdf sha256,
   pages, engine, engine version, Kreuzberg version, accepted, reason, article counts
   before/after, seconds); accepted rows carry the text, rejected rows carry none. It is
   published to `leizilla-reocr-{ente}-v{N}-{revision}` (immutable) and `-latest`
   (pointer), uploaded with `--no-derive` like the other datasets. Runs are incremental
   against the previous `-latest`. Nothing in the raw items is deleted or overwritten.
5. **Overlay.** `build-textos --reocr` replaces the text of a norm by its accepted re-OCR
   when the re-OCR's `sha256_fonte` is that of the row's source file. The origin goes in
   the existing `ocr_motor` column (value `kreuzberg+paddleocr (re-OCR direcionado,
   ADR-0019)`; Kreuzberg version in `ocr_modulo_versao`); no new column. `texto_url` still
   points to the original `_djvu.txt`. Without the dataset, `build-textos` is unchanged.

A scheduled workflow (`reocr.yml`, 06:27 UTC, after the 05:13 text-layer release) runs
the command; the next day's text-layer build applies the overlay.

## Consequences

- IA OCR remains the default text source. Own OCR is a gated fallback that can only add
  texts the reader can certify; it cannot take a closing text away.
- The gate measures closure of the reader, not fidelity to the paper: an accepted text
  is as good as the reader's certificate, not proof of character-level accuracy.
- Rotation is handled by our rasterizer, not by the OCR engine; `poppler-utils` becomes a
  runtime requirement of this command only.
- The 20-norm pilot is small; the numbers above are indicative. The queue size and the
  acceptance rate on the full backlog are measured by the daily run itself
  (`reocr.parquet` rows).
- Weight: the `reocr` extra is one wheel (Kreuzberg, about 98 MB installed) plus about
  19 MB of ONNX models downloaded on first use and cached in CI.
- A norm with an accepted re-OCR is re-downloaded from IA by `build-textos` each day
  (its row has no `sha1_texto_ia`), which keeps the overlay reversible.
- **Patient upload (operation).** The first real run lost its OCR work to an IA queue
  throttle (`total_tasks_queued exceeds global_limit`): the account's task queue is full
  for minutes to tens of minutes, and the short retry of the shared upload helper gives up
  in about 30 s. `reocr --upload` now waits out that throttle (and `bucket_tasks_queued
  exceeds rationed amount`) with a capped backoff of 60, 120, 240 s and then 300 s per
  attempt, up to `--upload-wait-minutes` (default 45; 0 restores the short retry). The
  budget is shared by the dated item and `-latest`; other errors keep the short retry. A
  run whose `-latest` pointer fails exits 1 with a message, because `build-textos` reads
  `-latest`; the dated release stays on IA and a rerun publishes a new revision. The job
  timeout of 120 min is kept, but a full batch of 60 norms plus the default 45 min wait
  can approach it. A run killed by the timeout publishes nothing (its candidate Parquet
  is still kept as an artifact); the lever is `--limit` or `--upload-wait-minutes`.
- **Queue order (operation).** The queue puts norms that already read at least one own
  article on IA's text first (the partial chains that the pilot re-OCR fixed), then norms
  that read zero, each class in `texto_id` order. Nothing is dropped; the `Fila:` line
  reports both class sizes, so a run's acceptance rate can be read against the class it
  started with.
