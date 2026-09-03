# Fine-tuning OPF to annotate Leizilla normas

> **Status (2026-07-14): the GPU fine-tune (Phase 3) is REACTIVATED as a smoke test on
> gold v0.** The 2026-06-06 deferral (below) is superseded by maintainer decision, not by
> the evidence trigger it originally called for — the v0 gold is still single-fonte,
> clean-text federal Planalto (no OCR noise). `notebooks/opf_train_colab.ipynb` already
> points at `main` and gold v0 is already committed there; a code review of this
> reactivation also found and fixed three real CLI-argument bugs in the notebook itself
> (`--seed` doesn't exist — the real flag is `--shuffle-seed`; the Drive-persisted base
> model was never passed to `opf train` via `--checkpoint`; `opf eval` doesn't accept
> `--label-space-json`), all verified against a live install of `openai/privacy-filter`.
> Run it as a baseline/smoke test, not a production model. See ADR-0012
> "Atualização (2026-07-14)" for the full rationale and the recommended next step (expand
> gold with real, multi-fonte RO OCR before a production-grade run).

This is Leizilla's concrete recipe for the [`opf-finetune`
skill](https://github.com/franklinbaldo/skills/tree/main/opf-finetune). Read the skill
for the general method and the two load-bearing warnings; read [ADR-0012](adr/0012-opf-structural-span-tagging.md)
for *why* we do this and how it relates to the Claude parser. This doc is the **how**,
specialized to our corpus and repo.

## What we're building

OPF (`openai/privacy-filter`) is a **token/span classifier**, not a generator. We
fine-tune it to mark the **structural markers** of Brazilian legislation — the same
markers from which SCHEMA.md derives a dispositivo's rótulo (`Art. 5º`, `§ 2º`,
`III -`, `a)`), plus ementa / vigência / revogação cues. The clause *body* is the text
between consecutive markers, reconstructed in post-processing — never labeled
token-by-token (skill Warning 2: banded attention favors short anchors).

This **complements** the Claude-Haiku parser (`parser.py`); it does not replace it. See
ADR-0012 for the three candidate roles (cheap pre-pass / structural cross-check /
zero-cost local path).

## Ontology — `data/opf/label_space.json`

```json
{
  "category_version": "leizilla_normas_v1",
  "span_class_names": ["O", "ementa", "art_marcador", "par_marcador",
                       "inc_marcador", "ali_marcador", "vigencia", "revogacao"]
}
```

- `O` **must** be first (background class).
- `*_marcador` are **short anchors** — tag `Art. 5º`, not the article body.
- `ementa` / `vigencia` / `revogacao` are short, cue-driven spans (`entra em vigor…`,
  `revogam-se as disposições em contrário`).
- **Definitions are durable; volume is incremental.** A category with little support can
  be *staged* (annotated when seen, kept out of the trained label space) until it
  crosses ~25 spans, then *activated*. Record `active` vs `staged` in the manifest and
  always report per-category F1 **with support**.

## The four phases

```
Phase 1  prep foundation (this repo)   ── DONE: sampler + ontology + tooling + ADR
Phase 2  annotate (agent-driven)       ── DONE (v0): pool → subagent labels → gold splits in git
Phase 3  train + eval (Colab GPU)      ── opf train → PT-BR eval → tune toward precision
Phase 4  integrate                     ── reconstruct dispositivos from markers
```

> **Phase 2 status — gold v0 landed.** A first `data/opf/gold/` seed (6 real federal
> laws, 251 spans) was built with the `llm-work-via-subagents` flow: 6 labeling
> subagents (one per law) returned ordered `finds`, the orchestrator resolved offsets
> deterministically (sequential cursor — no subagent counts characters), and a 4-role
> evaluator ensemble (strict-boundary / category-disambiguation / blind-relabel /
> adversarial) verified the val+test slice. Because the IA has no published raw OCR yet,
> the text came from Planalto federal HTML (a stopgap; swap to `opf-sample` over IA once
> raw items exist). `manifest.json` records `test_verified_by` and the known limits.
> Scale = feed more docs through the same flow.

### Phase 1 — build the annotation pool (here)

The pool is a **stratified, seeded** sample of OCR text drawn from the per-source raw
items already on the Internet Archive (ADR-0010). Stratify by **fonte** — each
(assembleia / casacivil-lei / casacivil-lc / planalto) is its own sub-distribution
(skill Warning 1), so the eval set must cover every format. Equal allocation per fonte
(cover every format), not proportional.

```bash
uv run leizilla opf-sample --ente ro --fontes assembleia,casacivil --n 50 --seed 13
# -> data/opf/pool/pool.jsonl          (records with empty `label`, ready to annotate)
# -> data/opf/pool/sample_manifest.json (per-source counts, seed — reproducible)
```

The pool stays **gitignored** (`data/opf/pool/`); only the reviewed gold is committed.

### Phase 2 — annotate (LLM subagents, no human team)

Per the skill, annotation is **fully LLM-driven**: a capable model labels, an
independent/stronger model verifies. When an agent runs this, **spawn subagents** (the
`llm-work-via-subagents` skill), not an API-key script:

- **Labeling → shard across parallel subagents**, one per batch of pool documents. Each
  returns sentinel/`(match, category)` spans; the orchestrator converts to offsets with
  the bundled helper so no subagent counts characters:
  ```bash
  python scripts/opf_annotate.py from-spans labeled_raw.jsonl --output train.jsonl
  python scripts/opf_annotate.py validate  train.jsonl --label-space data/opf/label_space.json
  python scripts/opf_annotate.py preview    train.jsonl   # eyeball boundaries
  ```
- **The eval gold slice** is the one place model-checks-model isn't enough: keep the
  evaluators' errors **decorrelated** from the labeler's — an ensemble of subagents with
  differentiated framings (strict-boundary, category-disambiguation, blind-relabel,
  adversarial). Record how the gold was verified in `manifest.json` (`test_verified_by`).

Commit `data/opf/gold/{train,val,test}.jsonl` + `data/opf/gold/manifest.json` to git
(the `.gitignore` whitelist already allows `data/opf/gold/**`). The split must be
PT-BR, in-domain, and leak-free (no same/near-duplicate doc across splits).

### Phase 3 — train + eval (Colab GPU)

Training needs a GPU and the OPF CLI; CI does not run it. The ready-to-run notebook is
**[`notebooks/opf_train_colab.ipynb`](../notebooks/opf_train_colab.ipynb)** — it pulls the
gold from git (the frozen contract), restores/persists the base model and checkpoints on
Drive, validates the gold, trains, evaluates the held-out PT-BR test slice, and writes a
run manifest. It bakes in the skill's gotchas (mount Drive first; `sys.executable -m opf`,
never `uv run`; persist base once; save checkpoint immediately; push `--n-ctx` up). It is
safe to run on the v0 gold as a smoke test + baseline. See the skill's `colab-and-drive.md`
for the Drive-layout rationale.

> **Measured T4/Colab lessons (2026-07-16)** — from real `opf train` runs on the same
> free-tier target (T4 GPU, ~13 GB host RAM), sibling project causaganha's segmenter:
>
> 1. **One `opf train` process must never run more than 1 epoch.** The runner clones the
>    *entire* model to host RAM every time validation loss improves and holds the clone
>    until the process exits (`opf/_train/runner.py`, `best_state`). On a ~13 GB Colab
>    host this SIGKILLs (-9) mid-epoch-2/3 — reproduced twice with 3-second RAM traces
>    (2.9 GB steady → 8.3 GB after epoch 1 → 10.6 GB, killed). Multi-epoch training must
>    be a **chain of single-epoch processes**, each resumed via `--checkpoint` from the
>    previous epoch's `--output-dir` (fresh process = RAM back to ~1.1 GB; validated
>    over 16 consecutive epoch-processes). The notebook's train cell does this.
> 2. **`--batch-size 1` on a T4.** The opf default (4) CUDA-OOMs: batch=1 already uses
>    12.4/15.4 GB VRAM with ~10k-token windows; batch=2 died inside the first forward
>    pass. Prefer more epochs over gradient accumulation — with a tiny gold, optimizer
>    steps per epoch are the scarce resource (grad-accum 4 cut steps to 19/epoch and
>    measurably slowed convergence).
> 3. **`--learning-rate 5e-5`, not the 1e-5 default.** A custom label space rebuilds the
>    output head with nearly every row randomly initialized (`fallback=…` in the train
>    log); measured head-to-head, lr 5e-5 reached val_loss 0.419 in 2 epochs where
>    lr 1e-5 needed 4 epochs to reach only 0.531.
> 4. **Early epochs report token accuracy ≈ 92% with span F1 = exactly 0 for every
>    category** — the all-background ("O") regime under class imbalance, not a broken
>    model. Evaluate every ~2 epochs to see when span predictions lift off, and never
>    compare an early-epoch 0 against the regex baseline's 0.95 as if it were final.
> 5. `finetune_summary.json`'s per-epoch metrics live under the `epoch_metrics` key
>    (`best_metric`/`best_epoch` are top-level). opf has **no** W&B/tensorboard
>    integration (verified: zero references in the repo) — wire dashboards yourself by
>    parsing that file per epoch-process.

```bash
git clone https://github.com/openai/privacy-filter && cd privacy-filter && pip install -e .
# Multi-epoch = chain of single-epoch processes (lesson 1 above); epoch 1 starts
# from the base checkpoint, epoch N+1 resumes from epoch N's output.
opf train train.jsonl \
  --validation-dataset val.jsonl \
  --label-space-json /path/to/data/opf/label_space.json \
  --epochs 1 --batch-size 1 --learning-rate 5e-5 \
  --output-dir ./ckpt_leizilla_v1_e1
opf train train.jsonl \
  --validation-dataset val.jsonl \
  --epochs 1 --batch-size 1 --learning-rate 5e-5 \
  --checkpoint ./ckpt_leizilla_v1_e1 \
  --output-dir ./ckpt_leizilla_v1_e2
# ... repeat (no --label-space-json once --checkpoint is set — same reasoning
# as `opf eval` below: the checkpoint already encodes the label space, and
# re-passing it every epoch risks rebuilding the head on every resume); then
# evaluate:
opf eval test.jsonl --checkpoint ./ckpt_leizilla_v1_e2 --per-class
```

Confirm flags with `opf train --help`. Watch **span-level F1 split into exact vs.
partial/overlap** (boundary drift is OPF's failure mode on formatted text) and the
**per-category** breakdown. For legal text a false positive usually costs more than a
miss a reviewer catches, so **bias the Viterbi operating point toward precision** (no
retrain needed) and keep a review path. Archive `finetune_summary.json` + the seed per
run.

### Phase 4 — integrate

Load the checkpoint, get marker spans, and **reconstruct dispositivos** as the text
between consecutive markers — this is where it can feed/cross-check the XML pipeline.
Role in production (pre-pass vs. cross-check vs. per-source substitute) is decided with
metrics in hand (ADR-0012, "fora de escopo").

## Files in this repo

| Path | What |
|---|---|
| `data/opf/label_space.json` | the activated ontology (gold, committed) |
| `data/opf/gold/` | reviewed `train/val/test.jsonl` + `manifest.json` (committed, Phase 2) |
| `data/opf/pool/` | sampled annotation pool (gitignored cache) |
| `src/leizilla/opf.py` | the stratified, seeded sampler → pool + manifest |
| `src/leizilla/segmenter.py` | regex baseline segmenter + `evaluate_against_gold` |
| `scripts/opf_annotate.py` | vendored validate / from-spans / preview helper |
| `notebooks/opf_train_colab.ipynb` | Phase 3 GPU training + eval notebook |
| `docs/adr/0012-opf-structural-span-tagging.md` | the decision record |

## Regex baseline — the bar OPF must beat

Pattern B is explicit that a **regex baseline on the markers is strong** for a known
formatting regime; OPF only earns its keep on the messy cases. `src/leizilla/segmenter.py`
is that baseline, scored against the same gold:

```bash
uv run leizilla opf-regex-eval --splits val,test     # per-category exact + overlap P/R/F1
```

On all six v0 gold docs it gets **exact micro-F1 0.95 / overlap 0.99** — `art`/`par`/`inc`/
`ali` *and* `vigencia`/`revogacao` at or near exact 1.00. That comes from rules beyond naive
matching: markers exclude the trailing period (a consistent gold convention), an
**abbreviation/number-aware sentence splitter** (so `art.`, `nº 8.069`, `13.07.1990` don't
end a clause), an **operative-verb filter** on revogação (compiled-text `(Revogado pela
Lei…)` history notes excluded — precision 0.33 → 1.00 on compiled statutes), a
**leading-marker strip** (so `Art. 3º Esta Lei entra em vigor…` yields the clause), and a
right-context guard (`§ 7º do art. 226`, `§ 2º (VETADO)`).

Two companion tools turn the eval into a debugging loop:

```bash
uv run leizilla opf-regex-eval --splits train,val,test --errors   # list every FP/FN/boundary with context
uv run leizilla opf-segment-check --splits train,val,test         # whole-norma sanity: did we find every Art. boundary?
```

`--errors` drove the rule improvements above (it surfaced the trailing-period gold drift and
even a probable gold omission). `opf-segment-check` validates a whole norma *without* gold —
it flags gaps in the article numbering (`missing_articles`), `out_of_order` numbers, and
absent ementa/vigência — so a freshly-segmented law can be triaged for review on its own.

The residual is exactly the model's territory: `par_marcador` `§` in citation lists (`§ 1º e
alíneas e § 2º`), and the `ementa` preamble over-capture (`Mensagem de veto …`) — references
and boundaries that need sentence understanding, not a local pattern. Read it two ways: a
zero-cost segmenter that already suffices for the easy markers (a pre-filter / cross-check),
and a quantified target the fine-tuned model has to clear to justify itself.
