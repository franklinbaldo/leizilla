# Fine-tuning OPF to annotate Leizilla normas

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

```bash
git clone https://github.com/openai/privacy-filter && cd privacy-filter && pip install -e .
opf train train.jsonl \
  --validation-dataset val.jsonl \
  --label-space-json /path/to/data/opf/label_space.json \
  --output-dir ./ckpt_leizilla_v1
opf eval test.jsonl --label-space-json /path/to/data/opf/label_space.json
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
| `scripts/opf_annotate.py` | vendored validate / from-spans / preview helper |
| `notebooks/opf_train_colab.ipynb` | Phase 3 GPU training + eval notebook |
| `docs/adr/0012-opf-structural-span-tagging.md` | the decision record |
