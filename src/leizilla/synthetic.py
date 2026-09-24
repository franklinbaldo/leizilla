"""Synthetic norma generator for OPF training (Phase 2.5, Path 4).

Deterministic renderer that writes fictional-but-well-formed Brazilian
legislation and records every label's character offsets **at the moment of
insertion** — ``text[start:end] == surface`` holds by construction, never by
post-hoc search. The approach (and its guard-rails) is ported from the sibling
causaganha project's synthetic segmenter (RFC 0011 there), where it was
validated against a real fine-tune run on 2026-07-16.

Why synthetic earns a place next to the real-data paths (docs/opf-finetune.md,
Phase 2.5): legislative structure is highly templated, so a renderer can

- feed the **starved categories on demand** (``ali_marcador``, ``vigencia``,
  ``revogacao`` — one per document in real laws, any density here);
- inject **hard negatives** as first-class citizens: surfaces that *look* like
  markers but must NOT be labeled, drawn from the regex baseline's own audited
  failure modes (lowercase ``art.`` cross-references, ``§`` inside citation
  chains, compiled-text ``(Revogado pela Lei …)`` history notes). A model only
  learns the distinction if training data contains the confusable case.
- rehearse **OCR-degraded marker surfaces** the regex misses by construction
  (dropped period in ``Art 5º``, ``§`` misread as ``S``) — the messy cases are
  exactly where OPF must earn its keep over the 0.95-F1 regex baseline.

Ground rules (same as every weak-supervision source in this repo):

- Synthetic records go into the **training mix only** — never ``val``/``test``
  (eval must stay real, PT-BR, ensemble-verified).
- Every record carries ``info.source = "synthetic"`` + the generator seed, so
  synthetic data stays distinguishable end to end.
- Surfaces are register-consistent with the real corpus conventions the gold
  follows (markers exclude the trailing period; vigência/revogação spans are
  sentence units with the leading marker stripped) — kept aligned with
  ``segmenter.py``'s cue patterns by test.
"""

from __future__ import annotations

import random
from typing import Dict, List, Tuple

from leizilla.opf import CATEGORY_VERSION
from leizilla.segmenter import Span

# --- phrase banks (fictional subject matter; structure mirrors real normas) -----------

_SUBJECTS = [
    "o Programa Estadual de Incentivo à Leitura",
    "a Política de Preservação dos Rios",
    "o Fundo de Apoio ao Artesanato Regional",
    "o Conselho de Transparência Administrativa",
    "a Semana de Prevenção de Acidentes Domésticos",
    "o Cadastro de Feiras Livres",
]

_CLAUSES = [
    "compete ao órgão gestor definir as diretrizes de execução",
    "os recursos serão aplicados exclusivamente na finalidade prevista",
    "a participação social será assegurada em todas as etapas",
    "o regulamento disporá sobre os critérios de habilitação",
    "as despesas correrão à conta de dotações orçamentárias próprias",
    "fica autorizada a celebração de convênios com entidades civis",
]

_VIGENCIA_SENTENCES = [
    "Esta Lei entra em vigor na data de sua publicação.",
    "Esta Lei entra em vigor após decorridos 90 dias de sua publicação oficial.",
]

_REVOGACAO_SENTENCES = [
    "Revogam-se as disposições em contrário.",
    "Fica revogada a Lei nº 1.234, de 5 de junho de 1990.",
]

# Hard negatives: marker-shaped surfaces that must NOT be labeled. Each is a
# (filler sentence, rationale) pair; rationales document the regex-audit finding
# the negative rehearses.
_HARD_NEGATIVES = [
    (
        "O disposto aplica-se na forma do art. 233 da Lei nº 8.069, "
        "de 13 de julho de 1990.",
        "lowercase art. cross-reference (capitalisation filter)",
    ),
    (
        "Observa-se o previsto no § 2º do art. 5º desta Lei.",
        "§ citation chain (xref left/right context)",
    ),
    (
        "O benefício anterior foi extinto. (Revogado pela Lei nº 9.999, de 2001)",
        "compiled-text history note, not an operative revogação",
    ),
    (
        "Aplica-se, no caso do inciso XII, o rito simplificado.",
        "spelled inciso reference, not a marker",
    ),
]

_ORDINALS = ["º", "°", " o"]  # all three tolerated by the regex regime (_ORD)

# Genuinely off-regex OCR degradations — surfaces the regex baseline misses BY
# CONSTRUCTION (verified against segmenter.py's patterns: _ART requires the
# period after "Art"; _PAR_NUM requires the literal §). Real OCR drops the
# period and misreads § as a letter; a human annotating degraded OCR gold would
# still tag these as markers, so the model must learn them — this residual is
# exactly where OPF earns its keep over the 0.95-F1 regex.
#
# Deliberately single-template (not a period-preserving/period-dropping pair):
# segmenter._ORD already tolerates every ordinal variant in _ORDINALS, so a
# pair would let the ordinal-only branch roll a still-regex-matching "Art. 5º"
# surface half the time under a doc flagged ocr_noise=True, diluting the
# off-regex training signal the noise regime exists to provide.
_ART_TEMPLATES_NOISE = ["Art {n}{o}"]
_PAR_TEMPLATES_NOISE = ["S {n}{o}"]


class _Builder:
    """Append-only text buffer that records offsets as it grows."""

    def __init__(self) -> None:
        self._parts: List[str] = []
        self._length = 0
        self.spans: List[Span] = []

    def write(self, text: str) -> None:
        self._parts.append(text)
        self._length += len(text)

    def write_labeled(self, text: str, category: str) -> None:
        start = self._length
        self.write(text)
        self.spans.append({"category": category, "start": start, "end": self._length})

    def build(self) -> str:
        return "".join(self._parts)


def _ordinal(rng: random.Random, *, noise: bool) -> str:
    if noise:
        return rng.choice(_ORDINALS)
    return rng.choice(_ORDINALS[:2])


def build_norma(
    seed: int,
    *,
    n_articles: int = 4,
    ali_per_inciso: int = 2,
    hard_negatives: bool = True,
    ocr_noise: bool = False,
) -> Tuple[str, List[Span]]:
    """Render one synthetic norma. Returns ``(text, spans)`` with exact offsets.

    ``ali_per_inciso`` directly controls ``ali_marcador`` density — the starved
    category real Planalto laws rarely feed. ``ocr_noise`` enables marker
    surfaces from the OCR regime (spaced ordinals) that the regex baseline
    misses by design.
    """
    rng = random.Random(seed)
    b = _Builder()

    year = rng.randint(1995, 2024)
    b.write(
        f"LEI Nº {rng.randint(100, 9999)}, DE {rng.randint(1, 28)} DE JANEIRO DE {year}.\n"
    )

    subject = rng.choice(_SUBJECTS)
    b.write_labeled(f"Dispõe sobre {subject} e dá outras providências.", "ementa")
    b.write(
        "\nO PRESIDENTE DA REPÚBLICA Faço saber que o Congresso Nacional decreta e eu sanciono a seguinte Lei:\n"
    )

    for art_n in range(1, n_articles + 1):
        is_last = art_n == n_articles
        art_tpl = rng.choice(_ART_TEMPLATES_NOISE) if ocr_noise else "Art. {n}{o}"
        b.write_labeled(
            art_tpl.format(n=art_n, o=_ordinal(rng, noise=ocr_noise)), "art_marcador"
        )
        if is_last:
            # closing article: vigência clause (sentence span, leading marker
            # stripped — the marker was emitted separately above).
            b.write(" ")
            b.write_labeled(rng.choice(_VIGENCIA_SENTENCES), "vigencia")
            b.write("\n")
            b.write_labeled(rng.choice(_REVOGACAO_SENTENCES), "revogacao")
            b.write("\n")
            continue

        b.write(f" Fica instituído {rng.choice(_SUBJECTS)}.\n")
        if hard_negatives and art_n == 1:
            neg, _why = rng.choice(_HARD_NEGATIVES)
            b.write(neg + "\n")

        par_tpl = rng.choice(_PAR_TEMPLATES_NOISE) if ocr_noise else "§ {n}{o}"
        b.write_labeled(
            par_tpl.format(n=1, o=_ordinal(rng, noise=ocr_noise)), "par_marcador"
        )
        b.write(f" Para os fins desta Lei, {rng.choice(_CLAUSES)}.\n")
        if rng.random() < 0.3:
            b.write_labeled("Parágrafo único", "par_marcador")
            b.write(f". Na hipótese do caput, {rng.choice(_CLAUSES)}.\n")

        for inc_i, roman in enumerate(["I", "II"], start=1):
            b.write_labeled(f"{roman} -", "inc_marcador")
            b.write(
                f" {rng.choice(_CLAUSES)}:\n"
                if inc_i == 1
                else f" {rng.choice(_CLAUSES)};\n"
            )
            if inc_i == 1:
                for ali_i in range(ali_per_inciso):
                    letter = chr(ord("a") + ali_i)
                    b.write_labeled(f"{letter})", "ali_marcador")
                    b.write(f" {rng.choice(_CLAUSES)};\n")

    text = b.build()
    spans = sorted(b.spans, key=lambda s: (s["start"], s["end"]))
    return text, spans


def build_dataset(
    n: int,
    *,
    seed: int = 13,
    ali_per_inciso: int = 2,
    ocr_noise_fraction: float = 0.3,
) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    """Render ``n`` synthetic records (OPF schema) + a per-category manifest.

    A deterministic fraction of documents uses the OCR-noise marker regime.
    Records carry ``info.source="synthetic"`` — training-mix only, never gold.
    """
    records: List[Dict[str, object]] = []
    totals: Dict[str, int] = {}
    noise_rng = random.Random(seed)
    for i in range(n):
        doc_seed = seed * 100_000 + i
        # A per-doc draw (not an index-prefix cutoff) so noisy docs are spread
        # across the dataset instead of all clustering at the head of the file.
        noise = noise_rng.random() < ocr_noise_fraction
        text, spans = build_norma(
            doc_seed, ali_per_inciso=ali_per_inciso, ocr_noise=noise
        )
        for sp in spans:
            totals[sp["category"]] = totals.get(sp["category"], 0) + 1
        records.append(
            {
                "text": text,
                "label": list(spans),
                "info": {
                    "source": "synthetic",
                    "generator": "leizilla.synthetic.build_norma",
                    "seed": doc_seed,
                    "ocr_noise": noise,
                },
            }
        )
    manifest: Dict[str, object] = {
        "category_version": CATEGORY_VERSION,
        "source": "synthetic",
        "generator": "leizilla.synthetic.build_norma",
        "n": n,
        "seed": seed,
        "ali_per_inciso": ali_per_inciso,
        "ocr_noise_fraction": ocr_noise_fraction,
        "spans_per_category": dict(sorted(totals.items())),
        "usage": "training-mix only; never val/test (eval stays real + verified)",
    }
    return records, manifest
