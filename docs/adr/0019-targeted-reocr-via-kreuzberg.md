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

## Fila sem-texto (addendum, 2026-11-17)

### Context

The text layer depends on the IA's `_djvu.txt`, and the IA produces it only when a derive
runs on the item. Under [ADR-0016](0016-colheita-em-lote-wayback-best-effort.md) the
harvest requests the derive only when an item has no pending resource left; with thousands
of norms still queued, every large item ends each run with `derive adiado`. Norms
preserved today therefore get no IA text for weeks. Measured on 2026-11-16: 3,796 norms
preserved, about 2,070 with text. On the published ledger of 2026-11-17 (public data
only), 1,445 preserved norms have no row in `textos`: 1,424 with no IA text yet, 14 whose
derive arrived after the last `textos` build, 7 outside the official index (by decade
1980s 111 · 1990s 47 · 2000s 484 · 2010s 81 · 2020s 715; lei 747 · lc 350 · decreto 279 ·
decreto-lei 69). The own OCR of this ADR (about 3.6 s/page on a runner, about 5 pages per
norm) can give those norms a searchable text now.

### Decisions

1. **Second queue.** `reocr` has two queues, named the same in code, logs and the
   `reocr.parquet` column `fila`: `nao-fecha` (decisions 1-5 above) and `sem-texto`:
   preserved PDFs with no `_djvu.txt` in their IA item and no row with text in the
   published `textos`. They are enumerated with the same walk as `build-textos`
   (range items → `index.csv` → item files; `textlayer.collect_sem_texto`), newest capture
   with its PDF in the item. `--queue nao-fecha|sem-texto|ambas` (default `ambas`);
   `--limit` is the total: `sem-texto` first, up to 2/3 (rounded down, at least 1), the
   rest to `nao-fecha`, and whatever one queue does not use flows to the other
   (`split_limit`). Inside `sem-texto` the order is norm year descending (from the
   published completeness ledger; no year goes last, and without the ledger the order is
   by number), then number descending, tipo, `texto_id`: deterministic.
2. **Acceptance for `sem-texto`.** There is no IA text to compare with, so ADR-0019's gate
   (which protects against *replacing* a text) does not apply: nothing is replaced. The OCR
   is accepted when, after whitespace normalisation, it is non-empty and has at least
   **150 non-blank characters per page on average** (`MIN_CHARS_POR_PAGINA`); otherwise
   `texto-trivial` (or `ocr-vazio`). The bar comes from the 25 pilot texts (PaddleOCR):
   legible texts run at 350-2,300 characters per page (lowest: Lei 65, 706 characters on 2
   pages), the three upside-down or unreadable ones at 26-41. 150 sits between the two
   groups with margin on both sides. Whether the reader closes on the text (`fecha_novo`)
   and the own-article count (`artigos_novo`) are recorded in the attempt row but not
   required, so the portal's "fecha" flag stays honest (`textos.artigos_fecham` is
   recomputed from the text): a searchable text that does not close is still far better
   than no text. `artigos_ia` / `fecha_ia` are NULL in this queue.
3. **The IA text wins when it arrives**, unless the gate's spirit says otherwise: when a
   later `build-textos` finds an IA `_djvu.txt` for a norm that so far had only our OCR,
   it uses the IA text if the reader closes on it or if ours did not close; it keeps ours
   only if ours closes and the IA's does not. One function decides, `textlayer.choose_text_source`
   (tests cover the four combinations). The origin stays in `ocr_motor` /
   `ocr_modulo_versao` exactly as in the overlay of decision 5.
4. **Storage.** Same `reocr.parquet` and items (`leizilla-reocr-{ente}-v{N}-*`), one row
   per attempt, new column `fila`. Rows published before the column exist are read as
   `nao-fecha`. The incremental skip stays per (PDF sha256, engine versions), not per
   queue: the same OCR output is not recomputed for the other queue. New reason
   `texto-trivial`.
5. **Text layer.** `build-textos --reocr` adds a `textos` row for an accepted `sem-texto`
   attempt whose `sha256_fonte` is a capture of the norm in the item and whose IA text is
   still absent: `texto_url` and `sha1_texto_ia` are NULL, `ocr_motor` is the re-OCR
   origin, identity, `rendicao` and capture date come from the `index.csv`. A kept row of
   an earlier release is reused as before (`_keep_previous`). Consumers must not assume
   `texto_url` / `sha1_texto_ia` are set (see `docs/SCHEMA.md` 3.5); in the ledger,
   `legivel` can now be true while `com_texto` (IA text) is false.
6. **Throughput (operation).** `reocr.yml` runs twice a day (06:27 and 18:41 UTC) as 4
   parallel shards (`reocr --shard i/4`, a stable hash of `texto_id`: disjoint and
   complete even if shards list the acervo at different moments). Shards only OCR and keep
   their new attempts as artifacts; one `publish` job runs `reocr-merge` (shards + the
   published history) and uploads once with the patient upload, so no two uploads race on
   the same IA item. Each shard downloads PDFs sequentially, at least 1 s apart.
   Default 100 norms per shard, about 400 per run: about 100 × (5 pages × 3.6 s + 2 s) ≈
   35 min plus about 30 s of model load and the acervo walk, under the 90 min job limit.

### Consequences

- A norm preserved today has a searchable text within a day or two instead of weeks; the
  1,424-norm backlog drains in about 2-3 days of runs at 800 norms/day (two thirds of the
  limit goes to `sem-texto`).
- The own text of `sem-texto` is not certified by the reader: it can contain OCR noise
  that the IA's Tesseract would not. It is labelled by `ocr_motor` and replaced by the
  IA's as soon as that exists and closes, or does not close when ours does not either.
- A norm whose own text is in `textos` has no `sha1_texto_ia`: when the IA text appears it
  is downloaded and the decision of item 3 runs every build until the overlay settles
  (the same daily re-download documented for the `nao-fecha` overlay).
- The `sem-texto` enumeration costs about one metadata request per range item at each
  shard start (the same walk `build-textos` does), without touching the government site.
- Residual risk: a PDF the IA never derives (rejected content, rotation) stays on our OCR
  with the `texto-trivial` bar as the only quality check.

## Addendum 2026-11-18 — source defects leave the `nao-fecha` queue

A norm can fail to close because the **official file** is incomplete, not because of the OCR.
Lei ordinária 1296/2003 (RO) is the case: the preserved PDF has 3 scanned pages, page 1 ends
at Art. 2, page 2 is a blank verso with the publication stamp, page 3 starts at "Art. 6º Esta
Lei entra em vigor" and carries the signature; no page image has the text of arts. 3 to 5
(a missing sheet, or a numbering gap in the law itself). The OCR reads exactly what the images
show, so re-OCR cannot gain anything, and the norm would return to the queue at each engine
version bump.

`docs/okf/defeitos-da-fonte.json` (loaded by `leizilla.defeitos`) lists such norms with the
reason, the evidence and who checked, each bound to the **sha256 of the inspected capture**.
`select_queue` skips a row whose `texto_id` and `sha256_fonte` both match an entry (counted in
`ReocrStats.defeitos_da_fonte` and printed by `reocr`); a new capture with other bytes returns
to the queue, because the source may have fixed the file. The list never marks a norm as
closing and is not an acceptance path: the gate of decision 3 is unchanged. The same entry
feeds the `textos.defeito_fonte` column (ADR-0015, addendum 2026-11-18), shown on the text
page. A malformed list aborts `reocr` and `build-textos` instead of being ignored.
