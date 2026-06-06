# notebooks/

Colab/Jupyter notebooks that run **outside** CI (they need a GPU or external services).

| Notebook | Purpose |
|---|---|
| `opf_train_colab.ipynb` | OPF fine-tune **Phase 3** — train + eval the structural-marker token-classifier on the committed gold (`data/opf/gold/`). GPU runtime. See [`docs/opf-finetune.md`](../docs/opf-finetune.md) and [ADR-0012](../docs/adr/0012-opf-structural-span-tagging.md). |

These are deliberately not part of the pytest/CI suite — they orchestrate GPU training and
Drive persistence, and consume the version-controlled gold as a frozen contract. Pin
`GOLD_GIT_REF` to a merged commit for a reproducible run.
