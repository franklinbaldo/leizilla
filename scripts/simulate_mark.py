"""Dry local simulation of a mark run (no API, no network).

For every norm of an ids file, the rule reader's marks are turned into the answer a
perfect model would give (`teacher_mark.response_from_marks`), anchors are perturbed at
known rates (column +-1 on SHIFT_RATE of the marks; the marker snippet with a dropped
accent on ACCENT_RATE), and the answers go through the real pipeline: the request plan,
the manifest, ``collect_mark`` (interpretation, conversion, build, verify, files) and
``score_mark``. A fake client plays the Message Batches API. The score must recover the
injected rates: that proves the pipeline end to end.

    uv run scripts/simulate_mark.py --textos textos.parquet \\
        --ids-file docs/okf/review-samples/mark-pilot-2026-11.txt --out OUT_DIR
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import unicodedata
from pathlib import Path
from typing import Any, Optional

import score_mark

from leizilla import marcacao
from leizilla import teacher_batch as tb
from leizilla import teacher_mark as tm
from leizilla.hierarchy_sequence import read_hierarchy

SHIFT_RATE = 0.05
ACCENT_RATE = 0.03


def drop_accent(t: str) -> str:
    """``t`` without accents; ordinal signs become letters (``5º`` -> ``5o``)."""
    t = t.translate(str.maketrans({"º": "o", "°": "o", "ª": "a"}))
    return "".join(
        c for c in unicodedata.normalize("NFD", t) if not unicodedata.combining(c)
    )


class _Batches:
    def __init__(self, entries: list[dict[str, Any]]) -> None:
        self._entries = entries

    def results(self, batch_id: str) -> list[dict[str, Any]]:
        return self._entries


class _Messages:
    def __init__(self, entries: list[dict[str, Any]]) -> None:
        self.batches = _Batches(entries)


class FakeClient:
    """Plays ``client.messages.batches.results`` with canned answers."""

    def __init__(self, entries: list[dict[str, Any]]) -> None:
        self.messages = _Messages(entries)


def simulate(
    plan: tm.MarkPlan,
    *,
    seed: str,
    shift_rate: float = SHIFT_RATE,
    accent_rate: float = ACCENT_RATE,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fake batch results for ``plan`` and the injected-error counts."""
    rng = random.Random(seed)
    responses: dict[str, list[dict[str, Any]]] = {}
    for norm in plan.norms:
        marks = marcacao.from_hierarchy(norm.text, read_hierarchy(norm.text))
        responses[norm.ref.key] = tm.response_from_marks(norm.text, marks)["marks"]
    everything = [(k, i) for k, marks in responses.items() for i in range(len(marks))]
    rng.shuffle(everything)
    total = len(everything)
    shifted = set()
    for key, i in everything:
        if len(shifted) >= round(shift_rate * total):
            break
        mark = responses[key][i]
        lines = tb.split_lines(next(n.text for n in plan.norms if n.ref.key == key))
        shown = lines[mark["l"] - 1].strip()
        step = rng.choice((-1, 1))
        if not 1 <= mark["c"] + step <= len(shown):
            step = -step
        if 1 <= mark["c"] + step <= len(shown):
            mark["c"] += step
            shifted.add((key, i))
    accent = set()
    eligible = 0
    for key, i in everything:
        if (key, i) in shifted:
            continue
        if drop_accent(responses[key][i]["t"]) != responses[key][i]["t"]:
            eligible += 1
            if len(accent) < round(accent_rate * total):
                responses[key][i]["t"] = drop_accent(responses[key][i]["t"])
                accent.add((key, i))
    entries: list[dict[str, Any]] = []
    for req in plan.requests:
        norms = []
        for slot in req.slots:
            owned = set(slot.chunk.owned)
            marks = [m for m in responses[slot.norm.ref.key] if int(m["l"]) in owned]
            norms.append({"id": slot.rid, "marks": marks})
        body = json.dumps({"norms": norms}, ensure_ascii=False, separators=(",", ":"))
        entries.append(
            {
                "custom_id": req.custom_id,
                "result": {
                    "type": "succeeded",
                    "message": {
                        "stop_reason": "end_turn",
                        "usage": {
                            "input_tokens": tb.estimate_tokens(len(req.user_text)),
                            "output_tokens": tb.estimate_tokens(len(body)) + 2000,
                            "cache_creation_input_tokens": 0,
                            "cache_read_input_tokens": 0,
                        },
                        "content": [{"type": "text", "text": body}],
                    },
                },
            }
        )
    injected = {
        "marks": total,
        "shifted_by_1": len(shifted),
        "shift_rate_target": shift_rate,
        "accent_dropped": len(accent),
        "accent_eligible_marks": eligible,
        "accent_rate_target": accent_rate,
    }
    return entries, injected


def run(
    textos: Path,
    ids_file: Path,
    out_dir: Path,
    seed: str = "20261118",
    shift_rate: float = SHIFT_RATE,
    accent_rate: float = ACCENT_RATE,
) -> dict[str, Any]:
    plan = tm.prepare_mark(
        ente="ro",
        tipo=None,
        limit=None,
        shuffle_seed=seed,
        text_source="textos",
        textos=textos,
        select="ids-file",
        ids_file=ids_file,
        budget_chars=tm.DEFAULT_MARK_BUDGET_CHARS,
        max_norms=tm.DEFAULT_MARK_MAX_NORMS,
        max_lines=tm.MARK_MAX_LINES,
        max_chars=tm.MARK_MAX_CHARS,
        max_tokens_cap=tm.MARK_MAX_TOKENS_CAP,
    )
    spec = tb.resolve_model(tb.DEFAULT_MODEL)
    estimate = tm.estimate_mark_cost(plan, spec, "medium", True)
    manifest = tm.build_mark_manifest(
        plan,
        estimate,
        ente="ro",
        effort="medium",
        cache=True,
        max_usd=1.0,
        guard="ceiling",
    )
    manifest["batches"].append(
        {
            "id": "msgbatch_simulated",
            "created_at": tb._now(),
            "request_count": len(plan.requests),
            "custom_ids": [r.custom_id for r in plan.requests],
        }
    )
    entries, injected = simulate(
        plan, seed=seed, shift_rate=shift_rate, accent_rate=accent_rate
    )
    collect_dir = out_dir / "collect"
    summary = tm.collect_mark(FakeClient(entries), manifest, collect_dir)
    result = score_mark.run(collect_dir, out_dir / "score")
    return {
        "plan_estimate_usd": estimate.estimate_usd,
        "plan_ceiling_usd": estimate.ceiling_usd,
        "injected": injected,
        "collect_states": summary["states"],
        "collect_dropped": summary["dropped_by_reason"],
        "score": result,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--textos", type=Path, required=True)
    parser.add_argument("--ids-file", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", default="20261118")
    args = parser.parse_args(argv)
    result = run(args.textos, args.ids_file, args.out, args.seed)
    (args.out / "simulation.json").write_text(
        json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    ca = result["score"]["column_accuracy"]
    inj = result["injected"]
    print(f"injected: {inj}")
    print(f"states: {result['collect_states']}; dropped: {result['collect_dropped']}")
    print(
        f"B methods {ca['b_methods']}; reference {ca['reference_n']}; "
        f"A exact {ca['a_exact_rate']}; deltas {ca['delta_distribution']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
