# Teacher labels: line-level structural gold from a batch run

This is the operating guide for `src/leizilla/teacher_batch.py` and the
`Teacher Batch` workflow (`.github/workflows/teacher-batch.yml`). It serves the
`boundary-decision-parser` node of the project DAG: the labels are the
independent gold against which the deterministic reader is measured and the
cheap decision models are calibrated.

## What it does

A generative model labels every Rondônia norm that has OCR text on the Internet
Archive. The model is a **classifier, not a rewriter**:

- Input: the `_djvu.txt` text with numbered lines.
- Output: compact JSON, with one entry only for each line that **starts** a
  structural element. The norm text is never sent back.

Requests go through the Message Batches API, which is asynchronous and costs
half the standard price. A batch can take up to 24 hours, so the work is split
into three steps that run separately:

| Step | What it does | Spends API credit |
|---|---|---|
| `plan` | Enumerates the norms, builds the requests, prints the estimated cost per model | No |
| `submit` | Repeats the enumeration, applies the cost guard, creates the batch(es), writes the manifest | Yes |
| `collect` | Fetches the results, validates them, merges chunks, writes the labels | No |

## Run it: pilot, full run, collect

All three steps are dispatched from **Actions → Teacher Batch → Run workflow**.
The workflow has no schedule: it runs only when you dispatch it.

On `main`, authentication uses GitHub OIDC through the existing Google/Anthropic
federation, with automatic token renewal and no `ANTHROPIC_API_KEY` secret.
First run **Check Anthropic federation** to test models access and free token
counting without submitting a batch. See [ADR-0018](adr/0018-anthropic-google-federation.md)
for the exact trust restrictions and repository variables. Other branches and
pull requests cannot use this identity.

### 1. Plan

Dispatch with `step=plan`. Leave `limit` empty to size the full run. The step
summary shows, for each model with a price on file, the request count, the token
estimate, and two dollar figures (see [Cost guard](#cost-guard)). It also calls
the free token counting endpoint on 20 requests and prints the measured
characters-per-token ratio next to the conservative one the estimate assumes.

### 2. Pilot

Dispatch with:

- `step=submit`
- `limit=50` and `shuffle_seed=pilot` (a reproducible sample spread across items
  and decades; without the seed you get the first 50 norms in catalog order)
- optionally `tipo=lei` (or `lc`, `decreto`; comma-separated) to restrict by type
- `max_usd=1`

Note the run id printed in the step summary. Then dispatch `step=collect` with
`manifest_run_id=<that run id>`. If the batch has not ended within
`wait_minutes`, the job ends green with a warning; dispatch `collect` again
later.

Read `summary.json` in the `teacher-batch-labels` artifact before the full run:

- `measured_usd` and `measured_usd_per_request` are computed from the token
  usage the API reported. Multiply by the full request count from `plan` to
  replace the estimate with a measurement.
- `failure_reasons` shows why any norm was not labelled.
- Open a few `labels/**/*.jsonl` files next to their texts and check the labels.

### 3. Full run

Dispatch `step=submit` with `limit` empty and a `max_usd` you chose from the
pilot's measurement. Collect as in the pilot. To publish the result on the
Internet Archive, set `upload_ia=true` on the `collect` dispatch.

For double annotation, submit again with a different `model`. Each submit has
its own manifest and produces its own label set; the model id is recorded in
every output file.

### 4. Retry failures

Norms that failed are listed in `failures.jsonl`. To resubmit only those,
dispatch `step=submit` with `manifest_run_id=<run id of the collect run>`; the
workflow downloads that run's `failures.jsonl` and passes it as
`--retry-failures`. Collect the retry as usual.

### Locally

```bash
uv run python -m leizilla.teacher_batch plan --limit 50 --shuffle-seed pilot \
  --cache-dir data/teacher/texts
uv run python -m leizilla.teacher_batch submit --limit 50 --shuffle-seed pilot \
  --cache-dir data/teacher/texts --max-usd 1 --manifest data/teacher/manifest.json
uv run python -m leizilla.teacher_batch collect \
  --manifest data/teacher/manifest.json --out-dir data/teacher/out --wait-minutes 30
```

`submit` and `collect` need `ANTHROPIC_API_KEY`. `plan` needs it only with
`--count-sample`.

## Cost guard

`submit` requires `--max-usd` and has no default. It computes two figures at
batch prices and refuses to create any batch when the guarded one is above
`--max-usd`:

- **ceiling** (the default guard): every request spends its whole `max_tokens`
  and the shared prompt prefix pays the cache-write premium with no cache hit.
- **estimate** (`--guard estimate`, an explicit choice): a conservative
  expectation, with a thinking allowance per request and a label on half of all
  lines. Use it for a more expensive model, where the ceiling is far above what
  a run really costs, and only after a pilot.

Both figures count input tokens at 2 characters per token, which is denser than
this corpus tokenizes; `plan` reports the measured ratio. Other safeguards:

- A model without a price in `MODELS` is refused. Prices in that table were
  copied from the public pricing page on 2026-11-14; check them before a large
  run.
- A request large enough to reach a model's higher long-prompt price tier is
  refused.
- `submit` refuses to overwrite an existing manifest, so a rerun cannot create a
  second set of batches by accident. In the workflow, the `teacher-batch`
  concurrency group also prevents two submits from running at once.
- `submit` refuses to run on incomplete inputs (an Internet Archive listing or a
  text download failed) unless you pass `--allow-partial`.

The guard is a pre-flight check on our own estimate. A spend limit on the API
workspace is the only enforcement on the provider's side.

## Long documents

A document is cut into chunks of at most 250 non-blank lines or 20,000
characters. Each line belongs to exactly one chunk. Later chunks also carry, as
read-only context, the first 10 lines of the document and the 15 lines before
the chunk; the model may label only the lines the chunk owns. Because owned
ranges do not overlap, merging is concatenation in chunk order, and `amends` is
the ordered union across chunks.

`max_tokens` is sized from the chunk (room for a label on every line, plus
thinking), so a response is not expected to hit the limit. If one does, or the
model refuses, the result is rejected, not parsed.

## Label schema

Schema version `1`, prompt version `teacher-labels-v1`. The model answers each
chunk with this object, enforced by the API as a strict JSON schema and checked
again by `collect`:

```json
{
  "labels": [
    {"line": 7, "category": "artigo", "number": "1", "quoted": false}
  ],
  "amends": [
    {"action": "altera", "tipo": "lei", "numero": "123", "ano": 1990}
  ]
}
```

| Field | Meaning |
|---|---|
| `line` | 1-based index into `text.split("\n")` of the exact `_djvu.txt` content. Blank lines are not sent to the model but still count. |
| `category` | `ementa`, `preambulo`, `artigo`, `paragrafo`, `inciso`, `alinea`, `item`, `vigencia`, `revogacao`, `assinatura` or `anexo`. |
| `number` | For `artigo`, `paragrafo`, `inciso` and `alinea`: the number or letter as it should be read in context, not as the OCR printed it (`"Art. Io"` is `"1"`; `"Art. 42"` between articles 3 and 5 is `"4"`). Articles and paragraphs use Arabic digits (`"5-A"`, `"unico"`), incisos use upper-case Roman numerals, alíneas use a lower-case letter. `null` when it cannot be determined, and always `null` for the other categories. |
| `quoted` | `true` when the element belongs to another norm that this one transcribes (the new wording inside an amending law). Those elements are outside this norm's own numbering sequence. |
| `amends` | Norms this one expressly amends (`altera`) or revokes (`revoga`): `tipo` in lower case, `numero` and `ano` when stated, otherwise `null`. |

Only lines that start an element get a label. Continuation lines, page headers,
tables and OCR noise get none.

## Output files

`collect` writes to `--out-dir`:

```
labels/{ia_item}/{tipo}-{numero}_{uuid5}.jsonl   one file per norm
failures.jsonl                                   one line per norm not labelled
summary.json                                     counts, usage, measured cost, provenance
manifest.json                                    copy of the submit manifest
raw/{batch_id}.jsonl                             API results as received
```

Each norm file starts with a header record, followed by one record per label:

```json
{"record": "norm", "item": "leizilla_ro_casacivil_lei_0001-1000", "uuid5": "12db9ee8", "tipo": "lei", "numero": 7, "text_sha256": "…", "n_lines": 131, "chunks": 1, "n_labels": 9, "amends": [], "model": "…", "effort": "medium", "prompt_version": "teacher-labels-v1", "prompt_sha256": "…", "label_schema_version": "1", "git_sha": "…", "batch_ids": ["…"]}
{"record": "label", "line": 7, "category": "artigo", "number": "1", "quoted": false}
```

The files hold line numbers, not text. To use them, fetch the same `_djvu.txt`
(`item` and `txt_name` are in the header) and check its SHA-256 against
`text_sha256` before joining by line number.

A norm file exists only when **every** chunk of the norm succeeded: the batch
result was `succeeded`, the stop reason was `end_turn`, the JSON parsed, and the
labels passed validation (known category, line inside the chunk's owned range,
one label per line). Otherwise the norm is in `failures.jsonl` with one of these
reasons per chunk:

| Reason | Meaning |
|---|---|
| `stop_reason_max_tokens` | The response was cut off. Retry with a higher `--max-tokens-cap` or a lower `--max-lines`. |
| `stop_reason_refusal` | The model declined the request. |
| `result_errored`, `result_expired`, `result_canceled` | The batch did not produce a response for the request. Expired requests are not billed. |
| `invalid_json`, `no_text_block`, `schema_violation` | The response broke the output contract. |
| `missing_result`, `not_submitted` | No result for a planned request (the second means its batch was never created). |

With `--upload-ia`, the labels (as one `labels.tar.gz`), `failures.jsonl`,
`summary.json` and `manifest.json` go to a new Internet Archive item named
`leizilla-teacher-labels-{ente}-{revision}`. Each collect creates a new item; an
existing one is never overwritten.

## Where the state lives

The only state between `submit` and `collect` is the manifest: the batch ids and
the map from each request's `custom_id` to its norm, chunk and owned line range.
The workflow stores it as the `teacher-batch-manifest` artifact of the submit
run, kept for 30 days. Batch results are available for 29 days, so the manifest
outlives them. An Actions cache was not used because it is evicted after seven
days without access and is scoped to a branch; the manifest is not committed
because it is transient run state, not project state.

The manifest artifact is uploaded even when `submit` fails partway, because the
manifest is rewritten after each batch is created: it then lists the batches
that were created, which can still be collected.
