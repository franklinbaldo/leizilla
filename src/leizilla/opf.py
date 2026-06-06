"""OPF fine-tuning data prep for Leizilla normas (structural span tagging).

OPF (OpenAI Privacy Filter, ``openai/privacy-filter``) is a small *bidirectional
token-classifier* — it labels every token in one forward pass and decodes BIOES
spans, rather than generating text. We fine-tune it to mark the **structural
markers** of Brazilian legislation (``Art. 5º``, ``§ 2º``, ``III -``, ``a)``, plus
ementa / vigência / revogação cues) — Pattern B in the ``opf-finetune`` skill. It
*complements* the Claude-Haiku parser (``parser.py``): Claude does generative
extraction into Leizilla XML; OPF cheaply/locally tags regions and is a candidate
pre-pass / cross-check (cost-zero principle). See ADR-0012 and docs/opf-finetune.md.

This module covers the first prep stage only: building the **annotation pool** — a
stratified, seeded sample of OCR text drawn from the per-source raw items already on
the Internet Archive. The pool records carry empty ``label`` lists; LLM-subagent
annotation (Phase 2, see the skill) fills them, an evaluator ensemble verifies the
gold slice, and the reviewed splits are committed to git under ``data/opf/gold/``.

Two load-bearing warnings from the skill drive the downstream design (recorded here
so the prep stage doesn't fight them):

1. **OPF is English-primary; our corpus is PT-BR.** PT-BR validation is mandatory and
   the annotation budget is larger than English benchmarks suggest. The sampler
   therefore stratifies across *fontes* (each is a sub-distribution) so the eval set
   covers every format.
2. **Banded attention favors short anchors, not giant regions.** We tag short
   structural *markers*, not whole clauses; dispositivo bodies are reconstructed in
   post from consecutive markers. That choice lives downstream (annotation +
   inference), but it is why the ontology is marker-centric.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from leizilla.ocr import fetch_and_clean_ocr
from leizilla.publisher import list_raw_ids

# Default activated ontology (mirrors data/opf/label_space.json — the file is the
# source of truth; this constant is a convenience for code that doesn't load it).
CATEGORY_VERSION = "leizilla_normas_v1"

# Type aliases for the injectable IO seams (kept offline/deterministic in tests,
# matching the repo convention of passing functions, e.g. discovery year_lookup_fn).
ListRawIdsFn = Callable[[str, str], "set[str] | List[str]"]
FetchOcrFn = Callable[[str], Optional[str]]


@dataclass(frozen=True)
class Source:
    """A (ente, fonte) sub-distribution to sample from (e.g. ro/casacivil)."""

    ente: str
    fonte: str

    @property
    def label(self) -> str:
        return f"{self.ente}/{self.fonte}"


@dataclass
class PoolResult:
    """Output of :func:`build_annotation_pool`: records + a reproducible manifest."""

    records: List[Dict[str, object]] = field(default_factory=list)
    manifest: Dict[str, object] = field(default_factory=dict)


def parse_sources(ente: str, fontes: str) -> List[Source]:
    """Parse a comma-separated ``--fontes`` string into :class:`Source` list.

    ``parse_sources("ro", "assembleia, casacivil")`` -> [ro/assembleia, ro/casacivil].
    Blank entries are dropped; order is preserved; duplicates are de-duplicated.
    """
    seen: set[str] = set()
    out: List[Source] = []
    for raw in fontes.split(","):
        fonte = raw.strip()
        if not fonte or fonte in seen:
            continue
        seen.add(fonte)
        out.append(Source(ente=ente, fonte=fonte))
    return out


def sample_raw_ids(ids: Sequence[str], n: int, seed: int) -> List[str]:
    """Deterministically pick up to ``n`` ids from ``ids`` for a fixed ``seed``.

    Sorts first so the input set's iteration order can't perturb the draw, then uses a
    seeded ``random.Random``. Taking all when ``len(ids) <= n`` is the natural floor.
    """
    pool = sorted(ids)
    if n >= len(pool):
        return pool
    rng = random.Random(seed)
    return sorted(rng.sample(pool, n))


def build_annotation_pool(
    sources: Sequence[Source],
    *,
    n_per_source: int,
    seed: int = 13,
    floor: int = 0,
    cap: Optional[int] = None,
    min_chars: int = 200,
    list_fn: ListRawIdsFn = list_raw_ids,
    fetch_fn: FetchOcrFn = fetch_and_clean_ocr,
) -> PoolResult:
    """Build a stratified, seeded annotation pool from per-source IA raw items.

    Equal allocation per source (the skill's default — cover every format rather than
    match production proportions), clamped to ``[floor, cap]``. For each source the raw
    ids are listed from the IA, a seeded subset is drawn, and each item's OCR text is
    fetched and cleaned. Items with no OCR yet, or shorter than ``min_chars`` (cover
    pages, failed scans), are skipped — recorded in the manifest as ``skipped``.

    Network IO is isolated behind ``list_fn`` / ``fetch_fn`` so tests stay offline.

    Returns a :class:`PoolResult` whose ``records`` are OPF-schema dicts with an empty
    ``label`` (ready for annotation) and an ``info`` trace back to the raw item.
    """
    target = max(n_per_source, floor)
    if cap is not None:
        target = min(target, cap)

    records: List[Dict[str, object]] = []
    per_source: Dict[str, Dict[str, int]] = {}

    for src in sources:
        available = list(list_fn(src.ente, src.fonte))
        picked = sample_raw_ids(available, target, seed)
        kept = 0
        skipped = 0
        for raw_id in picked:
            text = fetch_fn(raw_id)
            if text is None or len(text) < min_chars:
                skipped += 1
                continue
            records.append(
                {
                    "text": text,
                    "label": [],
                    "info": {
                        "raw_id": raw_id,
                        "ente": src.ente,
                        "fonte": src.fonte,
                    },
                }
            )
            kept += 1
        per_source[src.label] = {
            "available": len(available),
            "picked": len(picked),
            "kept": kept,
            "skipped": skipped,
        }

    manifest: Dict[str, object] = {
        "category_version": CATEGORY_VERSION,
        "seed": seed,
        "allocation": {
            "n_per_source": n_per_source,
            "floor": floor,
            "cap": cap,
            "effective_target": target,
            "policy": "equal-per-source",
        },
        "min_chars": min_chars,
        "total_records": len(records),
        "per_source": per_source,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    return PoolResult(records=records, manifest=manifest)


def write_pool(records: Sequence[Dict[str, object]], path: Path) -> int:
    """Write pool ``records`` as JSONL (UTF-8, no ASCII escaping). Returns the count."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return len(records)


def write_manifest(manifest: Dict[str, object], path: Path) -> None:
    """Write the sampling ``manifest`` as pretty JSON (reproducibility record)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def load_label_space(path: Path) -> Tuple[str, List[str]]:
    """Load ``label_space.json`` → (category_version, span_class_names).

    Raises ``ValueError`` if ``O`` is not the first category (OPF requires the
    background class first; the validator enforces the same rule).
    """
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    names: List[str] = data.get("span_class_names") or data.get("category_names") or []
    if not names:
        raise ValueError(f"{path}: label space has no span_class_names")
    if names[0] != "O":
        raise ValueError(f"{path}: 'O' must be the first span class (got {names[0]!r})")
    version: str = data.get("category_version", "")
    return version, names
