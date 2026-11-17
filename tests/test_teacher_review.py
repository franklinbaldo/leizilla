"""Tests for the review mode of the teacher batch — offline and deterministic.

The Anthropic client is a plain fake (batches.create / results / retrieve); the
text layer is a parquet written into ``tmp_path``; nothing touches the network
and the Internet Archive upload is patched at ``_run_ia_upload``.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional
from unittest.mock import MagicMock, patch

import duckdb
import pytest
import yaml
from typer.testing import CliRunner

from leizilla import teacher_batch as tb
from leizilla import teacher_review as tr

ROOT = Path(__file__).parents[1]
_SCRIPTS = ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import compare_teacher_reader as cmp  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "score_review", _SCRIPTS / "score_review.py"
)
assert _spec is not None and _spec.loader is not None
sr = importlib.util.module_from_spec(_spec)
sys.modules["score_review"] = sr
_spec.loader.exec_module(sr)

ITEM = "leizilla_ro_casacivil_lei_0001-1000"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _law(n_articles: int = 6, *, quoted: bool = False, tag: str = "") -> str:
    """A small norm that the reader closes: 1..n articles, final clause last."""
    lines = [
        "GOVERNO DO ESTADO DE RONDONIA",
        "",
        f"LEI Nº {n_articles}{tag} DE 5 DE ABRIL DE 1985",
        "",
        "Dispõe sobre a coisa.",
        "O GOVERNADOR DO ESTADO DE RONDÔNIA faz saber:",
        "",
    ]
    n = 0
    if quoted:
        n += 1
        lines += [
            f"Art. {n}º - O art. 5º da Lei nº 100 passa a vigorar com a "
            "seguinte redação:",
            '"Art. 5º - Fica proibido o uso de fogo na zona rural do Estado.',
            "§ 1º - Exceção para a agricultura familiar:",
            'I - pequena propriedade."',
        ]
    while n < n_articles - 2:
        n += 1
        lines.append(
            f"Art. {n}º - A Secretaria regulamentará a matéria {n}, nos termos"
        )
        lines.append(f"do art. {n + 20} da Lei Federal, no que couber ao Estado.")
        lines.append("")
    n += 1
    lines.append(f"Art. {n}º - Esta Lei entra em vigor na data de sua publicação.")
    n += 1
    lines.append(f"Art. {n}º - Revogam-se as disposições em contrário.")
    lines += ["", "Porto Velho, 5 de abril de 1985."]
    return "\n".join(lines)


def _record(
    numero: int, text: Optional[str] = None, uuid5: Optional[str] = None
) -> tb.TextoRecord:
    uuid5 = uuid5 or f"{numero:08x}"
    text = text if text is not None else _law(6, tag=f".{numero}")
    ref = tb.NormRef(
        item=ITEM,
        fonte="casacivil",
        tipo="lei",
        numero=numero,
        uuid5=uuid5,
        txt_name=f"lei-{numero:05d}_{uuid5}_djvu.txt",
    )
    return tb.TextoRecord(
        ref=ref,
        text=text,
        text_sha256=_sha(text),
        ocr_motor="tesseract",
        texto_id=f"leizilla-raw-ro-casacivil-lei-{numero:05d}",
    )


_COLS = [
    "texto_id",
    "ia_item",
    "fonte",
    "tipo",
    "numero",
    "texto_url",
    "pdf_url",
    "sha256_texto",
    "ocr_motor",
    "texto",
]


def _write_textos(path: Path, records: List[tb.TextoRecord]) -> Path:
    con = duckdb.connect()
    try:
        con.execute(
            "create table t (texto_id varchar, ia_item varchar, fonte varchar, "
            "tipo varchar, numero integer, texto_url varchar, pdf_url varchar, "
            "sha256_texto varchar, ocr_motor varchar, texto varchar)"
        )
        for r in records:
            base = r.ref.txt_name.removesuffix("_djvu.txt")
            con.execute(
                "insert into t values (?,?,?,?,?,?,?,?,?,?)",
                [
                    r.texto_id,
                    r.ref.item,
                    "casacivil",
                    r.ref.tipo,
                    r.ref.numero,
                    f"https://archive.org/download/{r.ref.item}/{base}_djvu.txt",
                    f"https://archive.org/download/{r.ref.item}/{base}.pdf",
                    r.text_sha256,
                    r.ocr_motor,
                    r.text,
                ],
            )
        con.execute(f"copy t to '{path}' (format parquet)")
    finally:
        con.close()
    return path


def _plan(
    reals: List[tb.TextoRecord],
    canaries: Optional[List[tb.TextoRecord]] = None,
    **kw: Any,
) -> tr.ReviewPlan:
    return tr.build_review_plan(reals, canaries or [], **kw)


# --------------------------------------------------------------------------
# Label mode is untouched
# --------------------------------------------------------------------------

_LABEL_TEXT = "\n".join(
    [
        "GOVERNO DO ESTADO DE RONDONIA",
        "",
        "LEI Nº 7 DE 5 DE ABRIL DE 1985",
        "",
        "Dispõe sobre coisa alguma.",
        "O GOVERNADOR, faço saber:",
        "Art. Io - Fica criada a coisa.",
        "Art. 22 - Esta Lei entra em vigor.",
        "",
        "Porto Velho, 5 de abril de 1985.",
    ]
)

# Computed on the code before the review mode existed (commit c2d7d4c).
GOLDEN_PROMPT_SHA = "962850f96c95518bf724af35ba93009f16ce2a8d9cd8188715a9a79ce2234d12"
GOLDEN_PARAMS_SHA = "26d6c056470bd49dc5e5858d8a564a0a6d7f0c387ed52766106c12fe17a12e13"
GOLDEN_MANIFEST_SHA = "78d70fee462b0dd256beba0507029dc477052370342ddebd5e2639074a042887"


class TestLabelModeUnchanged:
    def _plan(self) -> tb.Plan:
        ref = tb.NormRef(
            item=ITEM,
            fonte="casacivil",
            tipo="lei",
            numero=7,
            uuid5="aaaaaaaa",
            txt_name="lei-00007_aaaaaaaa_djvu.txt",
        )
        return tb.build_plan([ref], lambda r: _LABEL_TEXT)

    def test_prompt_and_request_params_are_byte_identical(self) -> None:
        plan = self._plan()
        params = tb.build_request_params(
            plan.requests[0], tb.MODELS["claude-haiku-5-5"], "medium", True
        )
        blob = json.dumps(params, sort_keys=True, ensure_ascii=False)
        assert tb.prompt_sha256() == GOLDEN_PROMPT_SHA
        assert hashlib.sha256(blob.encode()).hexdigest() == GOLDEN_PARAMS_SHA

    def test_manifest_has_no_review_keys(self) -> None:
        plan = self._plan()
        est = tb.estimate_cost(plan, tb.MODELS["claude-haiku-5-5"], "medium", True)
        manifest = tb.build_manifest(
            plan,
            est,
            ente="ro",
            effort="medium",
            cache=True,
            max_usd=1.0,
            guard="ceiling",
        )
        manifest.pop("created_at")
        manifest["git_sha"] = None
        blob = json.dumps(manifest, sort_keys=True, ensure_ascii=False)
        assert hashlib.sha256(blob.encode()).hexdigest() == GOLDEN_MANIFEST_SHA
        assert "mode" not in manifest

    def test_review_only_options_are_refused_in_label_mode(
        self, tmp_path: Path
    ) -> None:
        result = CliRunner().invoke(
            tb.app, ["plan", "--select", "closed", "--text-source", "textos"]
        )
        assert result.exit_code == 2
        assert "only apply with --mode review" in result.output

    def test_textos_record_keeps_the_text_id(self, tmp_path: Path) -> None:
        rec = _record(1)
        path = _write_textos(tmp_path / "t.parquet", [rec])
        corpus = tb.load_textos(path)
        assert corpus.records[0].texto_id == rec.texto_id


# --------------------------------------------------------------------------
# The reader's reading as tags, and the rendered request
# --------------------------------------------------------------------------


class TestRendering:
    def test_tags_land_on_the_lines_where_nodes_start(self) -> None:
        text = _law(5, quoted=True)
        view = tr.build_view(text)
        lines = text.split("\n")
        art = {line: n for line, n, _q in view.articles()}
        for line, number in art.items():
            assert lines[line - 1].startswith(f"Art. {number}º") or number == "5"
        quoted = [(line, n) for line, n, q in view.articles() if q]
        assert [n for _l, n in quoted] == ["5"]
        assert lines[quoted[0][0] - 1].startswith('"Art. 5º')
        labels = {
            line: [t.label for t in tags] for line, tags in sorted(view.tags.items())
        }
        assert "art 5 Q" in labels[quoted[0][0]]
        assert any("§ 1 Q" in tags for tags in labels.values())
        assert any("inc I Q" in tags for tags in labels.values())

    def test_listing_keeps_original_line_numbers_and_drops_blanks(self) -> None:
        text = _law(4)
        view = tr.build_view(text)
        lines = tb.split_lines(text)
        nonblank = [i for i, line in enumerate(lines, 1) if line.strip()]
        out = tr._listing(lines, view, nonblank).split("\n")
        assert len(out) == len(nonblank)
        for shown, n in zip(out, nonblank):
            number, rest = shown.split("\t", 1)
            assert int(number) == n
            assert rest.endswith(lines[n - 1].strip())
        art1 = next(row for row in out if "Art. 1º" in row)
        assert art1.split("\t", 1)[1].startswith("[art 1] Art. 1º")
        # the citation in the middle of a sentence has no tag of its own
        assert all(row.count("[art") <= 1 for row in out)

    def test_header_summarises_the_reading(self) -> None:
        plan = _plan([_record(1)])
        text = plan.requests[0].user_text
        assert "### N01 | lei 1 | reader: 6 own articles" in text
        # the header never says closes/last: they would give canaries away
        assert "closes=" not in text and "last=" not in text
        assert "### fim N01" in text
        assert text.startswith("Requisição com 1 norma(s): N01.")

    def test_ids_are_mapped_in_the_manifest_not_echoed_from_text(self) -> None:
        recs = [_record(n) for n in (1, 2, 3)]
        plan = _plan(recs)
        est = tr.estimate_review_cost(
            plan, tb.MODELS["claude-haiku-5-5"], "medium", True
        )
        manifest = tr.build_review_manifest(
            plan,
            est,
            ente="ro",
            effort="medium",
            cache=True,
            max_usd=1,
            guard="ceiling",
        )
        seen = set()
        for cid, req in manifest["requests"].items():
            for rid, meta in req["slots"].items():
                assert rid.startswith("N") and len(rid) == 3
                seen.add(meta["texto_id"])
                assert meta["text_sha256"] == _sha(
                    next(r.text for r in recs if r.texto_id == meta["texto_id"])
                )
                assert meta["key"] == f"{ITEM}/{meta['uuid5']}"
        assert seen == {r.texto_id for r in recs}

    def test_chunked_norm_is_one_request_per_part_with_a_note(self) -> None:
        big = "\n".join(
            [
                "LEI Nº 9",
                "Art. 1º - Primeiro artigo da lei grande.",
                '"Art. 7º - Texto transcrito de outra lei.',
            ]
            + [f"linha de transcrição {i} " + "x" * 60 for i in range(40)]
            + ['fim da transcrição."', "Art. 2º - Esta Lei entra em vigor."]
        )
        plan = _plan([_record(9, big)], max_chars=1200)
        parts = [r for r in plan.requests]
        assert len(parts) > 2 and all(len(r.slots) == 1 for r in parts)
        second = parts[1].user_text
        assert f"parte 2/{len(parts)}" in second
        assert "Antes desta parte o último artigo próprio é o 1" in second
        assert "HÁ bloco citado aberto" in second
        assert "[contexto, somente leitura]" in second
        assert "[linhas a revisar]" in second

    def test_params_shape_and_schema_is_strict(self) -> None:
        plan = _plan([_record(1)])
        params = tr.build_review_params(
            plan.requests[0], tb.MODELS["claude-haiku-5-5"], "medium", cache=True
        )
        assert params["system"] == [
            {
                "type": "text",
                "text": tr.REVIEW_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral", "ttl": "1h"},
            }
        ]
        assert params["output_config"]["format"]["schema"] == tr.REVIEW_SCHEMA
        assert params["output_config"]["effort"] == "medium"

        def objects(node: Any) -> List[Dict[str, Any]]:
            found = []
            if isinstance(node, dict):
                if node.get("type") == "object":
                    found.append(node)
                for v in node.values():
                    found += objects(v)
            elif isinstance(node, list):
                for v in node:
                    found += objects(v)
            return found

        objs = objects(tr.REVIEW_SCHEMA)
        assert len(objs) == 3
        for obj in objs:
            assert obj["additionalProperties"] is False
            assert sorted(obj["required"]) == sorted(obj["properties"])

    def test_prompt_documents_every_op_and_tag(self) -> None:
        for op in tr.OPS:
            assert f"`{op}`" in tr.REVIEW_SYSTEM_PROMPT
        for tag in (
            "[art 5]",
            "[art 5 Q]",
            "[§ 2]",
            "[inc III]",
            "[ali a]",
            "[item 1]",
        ):
            assert tag in tr.REVIEW_SYSTEM_PROMPT or tag.replace(" Q", "") in (
                tr.REVIEW_SYSTEM_PROMPT
            )
        assert tr.review_prompt_sha256() != tb.prompt_sha256()


# --------------------------------------------------------------------------
# Packing
# --------------------------------------------------------------------------


def _slots(sizes: List[int], canary_at: tuple[int, ...] = ()) -> List[tr.ReviewSlot]:
    out = []
    for i, size in enumerate(sizes):
        rec = _record(i + 1)
        norm = tr.make_norm(rec)
        norm.chunks = tb.chunk_document(norm.lines)
        if i in canary_at:
            norm.canary = tr.CanaryPlan("renumber", 1, "set_number")
        out.append(tr.ReviewSlot(norm=norm, chunk=norm.chunks[0], size=size))
    return out


class TestPacking:
    def test_respects_budget_and_max_norms(self) -> None:
        slots = _slots([5000] * 10)
        groups = tr.pack_slots(slots, budget_chars=12000, max_norms=8, seed="s")
        assert sum(len(g) for g in groups) == 10
        assert all(sum(s.size for s in g) <= 12000 for g in groups)
        groups = tr.pack_slots(_slots([100] * 20), budget_chars=10**6, max_norms=8)
        assert max(len(g) for g in groups) == 8

    def test_large_norm_goes_alone(self) -> None:
        slots = _slots([30000, 3000, 3000, 3000])
        groups = tr.pack_slots(slots, budget_chars=24000, max_norms=8, seed="s")
        alone = [g for g in groups if g[0].size == 30000]
        assert len(alone) == 1 and len(alone[0]) == 1

    def test_is_deterministic_and_seed_dependent(self) -> None:
        def ids(seed: str) -> List[List[str]]:
            return [
                [s.norm.ref.key for s in g]
                for g in tr.pack_slots(
                    _slots([2000] * 12), budget_chars=9000, seed=seed
                )
            ]

        assert ids("a") == ids("a")
        assert ids("a") != ids("b")

    def test_at_most_one_canary_per_request_and_never_the_same_norm(self) -> None:
        for canary_at in ((1, 5), tuple(range(8))):
            groups = tr.pack_slots(
                _slots([2000] * 12, canary_at=canary_at),
                budget_chars=24000,
                max_norms=8,
                seed="s",
            )
            assert sum(len(g) for g in groups) == 12
            assert all(sum(1 for s in g if s.norm.canary) <= 1 for g in groups)
        plan = _plan(
            [_record(n) for n in range(1, 7)],
            canary_share=0.5,
            seed="x",
            budget_chars=100000,
        )
        for request in plan.requests:
            keys = [s.norm.ref.key for s in request.slots]
            assert len(keys) == len(set(keys))

    def test_many_canaries_leave_no_real_norm_without_one(self) -> None:
        groups = tr.pack_slots(
            _slots([2000] * 12, canary_at=tuple(range(6))),
            budget_chars=24000,
            max_norms=8,
            seed="s",
        )
        assert all(any(s.norm.canary for s in g) for g in groups)

    def test_plan_is_deterministic(self) -> None:
        recs = [_record(n) for n in range(1, 9)]
        a = _plan(recs, canary_share=0.25, seed="7")
        b = _plan(recs, canary_share=0.25, seed="7")
        assert [r.user_text for r in a.requests] == [r.user_text for r in b.requests]
        assert [r.custom_id for r in a.requests] == [r.custom_id for r in b.requests]


# --------------------------------------------------------------------------
# Canaries
# --------------------------------------------------------------------------


def _view_and_lines(text: str) -> tuple[tr.ReaderView, List[str]]:
    return tr.build_view(text), tb.split_lines(text)


class TestCanaries:
    def test_drop_last_removes_the_last_own_tag(self) -> None:
        view, lines = _view_and_lines(_law(6))
        mutated, plan = tr.plant_canary(view, lines, "drop_last", tr.rng_for("s"))
        last_line = view.own_articles()[-1][0]
        assert plan.line == last_line and plan.op == "add_own_article"
        assert plan.number == "6"
        assert last_line not in mutated.tags
        assert len(mutated.own_articles()) == 5
        assert view.own_articles()[-1][0] == last_line  # original untouched

    def test_drop_middle_removes_a_middle_tag(self) -> None:
        view, lines = _view_and_lines(_law(6))
        mutated, plan = tr.plant_canary(view, lines, "drop_middle", tr.rng_for("s"))
        own_lines = [line for line, _n in view.own_articles()]
        assert plan.line in own_lines[1:-1]
        assert plan.line not in mutated.tags
        assert mutated.closes is False  # the chain 1..N now has a gap

    def test_renumber_changes_only_one_number(self) -> None:
        view, lines = _view_and_lines(_law(6))
        mutated, plan = tr.plant_canary(view, lines, "renumber", tr.rng_for("s"))
        before = dict((line, n) for line, n in view.own_articles())
        after = dict((line, n) for line, n in mutated.own_articles())
        changed = [line for line in before if before[line] != after[line]]
        assert changed == [plan.line] and plan.op == "set_number"
        assert after[plan.line] == str(int(before[plan.line]) + 1)
        assert plan.number == before[plan.line]
        assert set(before) == set(after)

    def test_flip_quoted_flips_exactly_one_article(self) -> None:
        view, lines = _view_and_lines(_law(6, quoted=True))
        assert "flip_quoted" in tr.feasible_kinds(view, lines)
        seen = set()
        for seed in range(12):
            mutated, plan = tr.plant_canary(
                view, lines, "flip_quoted", tr.rng_for(str(seed))
            )
            before = {a[0]: a[2] for a in view.articles()}
            after = {a[0]: a[2] for a in mutated.articles()}
            changed = [line for line in before if before[line] != after[line]]
            assert changed == [plan.line] and plan.op == "set_quoted"
            assert plan.quoted == before[plan.line]  # the value that repairs it
            seen.add(plan.detail)
        assert seen == {"own->quoted", "quoted->own"}

    def test_flip_quoted_needs_a_quoted_block(self) -> None:
        view, lines = _view_and_lines(_law(6))
        assert "flip_quoted" not in tr.feasible_kinds(view, lines)

    def test_spurious_adds_a_tag_on_a_citation_line(self) -> None:
        view, lines = _view_and_lines(_law(6))
        mutated, plan = tr.plant_canary(view, lines, "spurious", tr.rng_for("s"))
        assert plan.op == "remove_article"
        assert plan.line not in view.tags and plan.line in mutated.tags
        assert tr._CITATION_RE.search(lines[plan.line - 1])
        extra = [a for a in mutated.articles() if a[0] == plan.line]
        assert extra == [(plan.line, plan.number, False)]
        assert len(mutated.own_articles()) == len(view.own_articles()) + 1

    def test_the_text_is_never_touched_and_header_follows_the_tags(self) -> None:
        recs = [_record(n) for n in range(1, 7)]
        plan = _plan(recs, canary_share=0.5, seed="9")
        canaries = plan.canary_norms
        assert canaries
        for norm in canaries:
            real = next(r for r in recs if r.ref.key == norm.ref.key)
            assert norm.text == real.text and norm.lines == tb.split_lines(real.text)
            assert norm.view.mutated
            slot = tr.ReviewSlot(norm, norm.chunks[0], rid="N01")
            head = tr.render_slot(slot).split("\n", 1)[0]
            s = norm.view.summary()
            assert f"reader: {s['own_articles']} own articles" in head

    def test_kinds_are_balanced_and_seeded(self) -> None:
        recs = [_record(n) for n in range(1, 21)]
        a = _plan(recs, canary_share=1.0, seed="3")
        kinds = [n.canary.kind for n in a.canary_norms if n.canary]
        assert len(kinds) == 20
        counts = {k: kinds.count(k) for k in set(kinds)}
        assert max(counts.values()) - min(counts.values()) <= 1
        b = _plan(recs, canary_share=1.0, seed="3")
        assert [n.canary for n in a.canary_norms] == [n.canary for n in b.canary_norms]

    def test_canary_ids_file_sources_are_all_planted_and_extra(self) -> None:
        reals = [_record(n) for n in (1, 2)]
        sources = [_record(n) for n in (10, 11, 12)]
        plan = _plan(reals, sources, canary_share=0.9, seed="1")
        assert len(plan.real_norms) == 2 and len(plan.canary_norms) == 3
        assert {n.texto_id for n in plan.canary_norms} == {s.texto_id for s in sources}

    def test_scoring_caught_partly_missed_invalid(self) -> None:
        planned = {"kind": "renumber", "line": 9, "op": "set_number"}
        hit = {"op": "set_number", "line": 9}
        assert tr.score_canary(planned, [hit]) == "caught"
        assert tr.score_canary(planned, [{"op": "set_number", "line": 12}]) == "partly"
        assert (
            tr.score_canary(planned, [{"op": "remove_article", "line": 9}]) == "partly"
        )
        assert tr.score_canary(planned, []) == "missed"
        assert tr.score_canary(planned, None) == "invalid"


# --------------------------------------------------------------------------
# Response validation
# --------------------------------------------------------------------------


def _meta_for(text: str) -> Dict[str, Any]:
    plan = _plan([_record(1, text)])
    return tr._slot_meta(plan.requests[0].slots[0]) | {"_plan": plan}


def _adj(op: str, line: int, text_lines: List[str], **over: Any) -> Dict[str, Any]:
    base = {
        "op": op,
        "line": line,
        "number": None,
        "suffix": None,
        "level": None,
        "quoted": None,
        "evidence": text_lines[line - 1].strip()[:60],
        "reason": "porque sim",
    }
    base.update(over)
    return base


class TestValidation:
    text = _law(6)
    lines = tb.split_lines(text)

    def meta(self) -> Dict[str, Any]:
        meta = _meta_for(self.text)
        meta.pop("_plan")
        return meta

    def test_ok_and_valid_adjustment(self) -> None:
        meta = self.meta()
        assert tr.validate_entry(
            {"id": "N01", "verdict": "ok", "adjustments": []}, meta
        ) == ("ok", [], [])
        line = next(i for i, ln in enumerate(self.lines, 1) if "entra em vigor" in ln)
        art = [a for a in meta["reader"]["articles"] if a[0] == line][0]
        adj = _adj("set_number", line, self.lines, number="9")
        verdict, adjustments, problems = tr.validate_entry(
            {"id": "N01", "verdict": "ajuste", "adjustments": [adj]}, meta
        )
        assert (verdict, problems) == ("ajuste", [])
        assert adjustments[0]["number"] == "9" and art[1] == "5"

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda a: {**a, "line": 2},  # blank line: not listed
            lambda a: {**a, "line": 9999},  # beyond the text
            lambda a: {**a, "op": "dance"},  # unknown op: malformed
            lambda a: {k: v for k, v in a.items() if k != "reason"},  # wrong shape
        ],
    )
    def test_structural_problems_invalidate_the_norm(self, mutate: Callable) -> None:
        meta = self.meta()
        line = next(i for i, ln in enumerate(self.lines, 1) if "entra em vigor" in ln)
        adj = mutate(_adj("set_number", line, self.lines, number="9"))
        verdict, adjustments, problems = tr.validate_entry(
            {"id": "N01", "verdict": "ajuste", "adjustments": [adj]}, meta
        )
        assert problems and adjustments == []

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda a: {**a, "evidence": "texto que não está na linha"},
            lambda a: {**a, "evidence": ""},
            lambda a: {**a, "evidence": "A"},  # too short to identify the line
            lambda a: {**a, "number": "cinco"},  # not an arabic numeral
        ],
    )
    def test_bad_individual_adjustment_is_dropped_and_downgraded(
        self, mutate: Callable
    ) -> None:
        # Measured on the first run: a bad evidence or a number that does not parse
        # no longer voids the norm; the adjustment is dropped with its reason, and an
        # ajuste left with nothing becomes ok, flagged downgraded.
        meta = self.meta()
        line = next(i for i, ln in enumerate(self.lines, 1) if "entra em vigor" in ln)
        adj = mutate(_adj("set_number", line, self.lines, number="9"))
        check = tr.check_entry(
            {"id": "N01", "verdict": "ajuste", "adjustments": [adj]}, meta
        )
        assert check.problems == []
        assert check.adjustments == []
        assert check.verdict == "ok" and check.downgraded is True
        assert len(check.dropped) == 1 and check.dropped[0]["reason"]
        assert check.dropped[0]["index"] == 0 and check.dropped[0]["op"] == "set_number"

    def test_verdict_must_match_adjustments(self) -> None:
        meta = self.meta()
        line = next(i for i, ln in enumerate(self.lines, 1) if "Art. 1º" in ln)
        adj = _adj("set_number", line, self.lines, number="9")
        assert tr.validate_entry(
            {"id": "N01", "verdict": "ok", "adjustments": [adj]}, meta
        )[2]
        assert tr.validate_entry(
            {"id": "N01", "verdict": "ajuste", "adjustments": []}, meta
        )[2]

    def test_ops_must_fit_the_tags_the_model_saw(self) -> None:
        meta = self.meta()
        art_line = meta["reader"]["articles"][0][0]
        plain = next(
            i
            for i, ln in enumerate(self.lines, 1)
            if ln.strip() and str(i) not in meta["tags"] and i > art_line
        )
        cases = [
            _adj("add_own_article", art_line, self.lines, number="1"),  # already tagged
            _adj("remove_article", plain, self.lines),  # nothing to remove
            _adj("set_number", plain, self.lines, number="3"),  # no tag there
            _adj("set_quoted", art_line, self.lines, quoted=False),  # no change
            _adj("remove_node", art_line, self.lines, level="inciso"),
            _adj("add_node", plain, self.lines, level="artigo"),
        ]
        for adj in cases:
            # A misfit is dropped (with its reason), not structural: the norm stays
            # valid and, with nothing kept, the ajuste is downgraded to ok.
            check = tr.check_entry(
                {"id": "N01", "verdict": "ajuste", "adjustments": [adj]}, meta
            )
            assert check.problems == [] and check.adjustments == [], adj["op"]
            assert check.dropped and check.downgraded, adj["op"]
        good = tr.validate_entry(
            {
                "id": "N01",
                "verdict": "ajuste",
                "adjustments": [
                    _adj("add_own_article", plain, self.lines, number="5-a"),
                    _adj("add_node", plain, self.lines, level="inciso", number="II"),
                ],
            },
            meta,
        )
        assert good[2] == []
        assert good[1][0]["number"] == "5-A" or good[1][1]["number"] == "5-A"

    def test_duplicates_and_conflicts_are_invalid(self) -> None:
        meta = self.meta()
        line = meta["reader"]["articles"][1][0]
        a = _adj("set_number", line, self.lines, number="9")
        assert tr.validate_entry(
            {"id": "N01", "verdict": "ajuste", "adjustments": [a, dict(a)]}, meta
        )[2]
        r = _adj("remove_article", line, self.lines)
        assert tr.validate_entry(
            {"id": "N01", "verdict": "ajuste", "adjustments": [r, a]}, meta
        )[2]

    def _request(self, entries: List[Any]) -> tuple[Dict[str, Any], Any]:
        recs = [_record(n) for n in (1, 2, 3)]
        plan = _plan(recs, budget_chars=10**6)
        est = tr.estimate_review_cost(
            plan, tb.MODELS["claude-haiku-5-5"], "medium", True
        )
        manifest = tr.build_review_manifest(
            plan,
            est,
            ente="ro",
            effort="medium",
            cache=True,
            max_usd=1,
            guard="ceiling",
        )
        ((cid, meta),) = manifest["requests"].items()
        outcome = tr.ReviewRequestOutcome(cid, True, entries=entries)
        return meta, tr.evaluate_request(cid, meta, outcome)

    def test_missing_duplicate_and_unknown_ids(self) -> None:
        ok = lambda rid: {"id": rid, "verdict": "ok", "adjustments": []}  # noqa: E731
        meta, (results, extra) = self._request(
            [ok("N01"), ok("N01"), ok("N03"), ok("N09")]
        )
        by = {r.rid: r for r in results}
        assert by["N01"].problems == ["duplicate_id"] and not by["N01"].valid
        assert by["N02"].problems == ["missing_id"] and not by["N02"].valid
        assert by["N03"].valid and by["N03"].verdict == "ok"
        assert extra == ["N09"]

    def test_failed_request_invalidates_every_slot(self) -> None:
        recs = [_record(n) for n in (1, 2)]
        plan = _plan(recs, budget_chars=10**6)
        est = tr.estimate_review_cost(
            plan, tb.MODELS["claude-haiku-5-5"], "medium", True
        )
        manifest = tr.build_review_manifest(
            plan,
            est,
            ente="ro",
            effort="medium",
            cache=True,
            max_usd=1,
            guard="ceiling",
        )
        ((cid, meta),) = manifest["requests"].items()
        results, _ = tr.evaluate_request(
            cid, meta, tr.ReviewRequestOutcome(cid, False, "stop_reason_max_tokens")
        )
        assert [r.valid for r in results] == [False, False]
        assert results[0].problems == ["stop_reason_max_tokens"]

    def test_apply_adjustments_to_the_article_set(self) -> None:
        articles = [[3, "1", False], [5, "2", False], [7, "9", True]]
        fixed = tr.apply_adjustments(
            articles,
            [
                {"op": "add_own_article", "line": 9, "number": "3"},
                {"op": "set_number", "line": 5, "number": "4"},
                {"op": "set_quoted", "line": 7, "quoted": False},
                {"op": "remove_article", "line": 3, "number": None},
                {"op": "add_node", "line": 3, "level": "inciso"},
            ],
        )
        assert fixed == [(5, "4", False), (7, "9", False), (9, "3", False)]


# --------------------------------------------------------------------------
# Cost
# --------------------------------------------------------------------------


class TestCost:
    def test_estimate_ceiling_and_label_comparison(self) -> None:
        recs = [_record(n) for n in range(1, 9)]
        plan = _plan(recs, canary_share=0.25, seed="1")
        spec = tb.MODELS["claude-haiku-5-5"]
        est = tr.estimate_review_cost(plan, spec, "medium", True)
        assert est.requests == len(plan.requests)
        assert est.norms == len(plan.norms)
        assert 0 < est.estimate_usd < est.ceiling_usd
        # the ceiling assumes 5 adjustments on every norm, the estimate ~39 tokens
        per_request = [tr.review_max_tokens(len(r.slots)) for r in plan.requests]
        assert est.ceiling_output_tokens == sum(per_request)
        assert tr.review_max_tokens(8) >= 3072 + 8 * (15 + 5 * 60)
        assert tr.expected_tokens_per_norm() == 39
        label = tr.label_mode_estimate(plan, spec, "medium", True)
        assert label.norms == len(plan.real_norms)
        assert label.estimate_usd > 0
        # fewer, denser requests: review is cheaper than labelling every line
        assert est.estimate_usd < label.estimate_usd * 3

    def test_guard_refuses_and_accepts(self) -> None:
        plan = _plan([_record(n) for n in range(1, 4)])
        spec = tb.MODELS["claude-haiku-5-5"]
        est = tr.estimate_review_cost(plan, spec, "medium", True)
        with pytest.raises(tb.TeacherBatchError, match="cost guard"):
            tb.check_cost_guard(est, spec, est.ceiling_usd / 2, "ceiling")
        tb.check_cost_guard(est, spec, est.ceiling_usd * 2, "ceiling")
        tb.check_cost_guard(est, spec, est.estimate_usd * 2, "estimate")

    def test_count_tokens_sample_uses_the_review_params(self) -> None:
        plan = _plan([_record(n) for n in range(1, 4)])
        client = MagicMock()
        client.messages.count_tokens.return_value = SimpleNamespace(input_tokens=1000)
        sample = tr.count_tokens_sample_review(
            client, plan, tb.MODELS["claude-haiku-5-5"], "medium", 2
        )
        assert sample is not None and sample["sampled_requests"] >= 1
        sent = client.messages.count_tokens.call_args.kwargs
        assert sent["system"][0]["text"] == tr.REVIEW_SYSTEM_PROMPT


# --------------------------------------------------------------------------
# Selection (text layer, --select, --ids-file) and the CLI
# --------------------------------------------------------------------------


def _layer(tmp_path: Path) -> tuple[Path, Dict[str, tb.TextoRecord]]:
    # article 3 is gone: the chain has a gap and the reader does not close
    open_text = "\n".join(
        line
        for line in _law(6).split("\n")
        if not line.startswith("Art. 3º") and "art. 23" not in line
    )
    records = [
        _record(1, _law(6, tag=".1")),
        _record(2, _law(5, tag=".2")),
        _record(3, open_text),
        _record(4, _law(7, tag=".4")),
    ]
    path = _write_textos(tmp_path / "t.parquet", records)
    return path, {r.texto_id: r for r in records if r.texto_id}


def _prepare(path: Path, **over: Any) -> tr.ReviewPlan:
    kwargs: Dict[str, Any] = dict(
        ente="ro",
        tipo=None,
        limit=None,
        shuffle_seed="1",
        text_source="textos",
        textos=path,
        exclude_labelled=None,
        select="all",
        ids_file=None,
        canary_share=0.0,
        canary_ids_file=None,
        budget_chars=tr.DEFAULT_BUDGET_CHARS,
        max_norms=tr.DEFAULT_MAX_NORMS,
        max_chars=tr.DEFAULT_REVIEW_MAX_CHARS,
        max_tokens_cap=tb.MAX_TOKENS_CAP,
    )
    kwargs.update(over)
    return tr.prepare_review(**kwargs)


class TestSelection:
    def test_select_all_closed_open(self, tmp_path: Path) -> None:
        path, recs = _layer(tmp_path)
        ids = lambda p: {n.texto_id for n in p.real_norms}  # noqa: E731
        assert len(_prepare(path).real_norms) == 4
        closed = ids(_prepare(path, select="closed"))
        opened = ids(_prepare(path, select="open"))
        assert opened == {"leizilla-raw-ro-casacivil-lei-00003"}
        assert closed == set(recs) - opened

    def test_ids_file_with_comments_and_limit(self, tmp_path: Path) -> None:
        path, recs = _layer(tmp_path)
        ids_file = tmp_path / "ids.txt"
        ids_file.write_text(
            "# a sample\n\n"
            "leizilla-raw-ro-casacivil-lei-00002\n"
            "leizilla-raw-ro-casacivil-lei-00004\n"
            "leizilla-raw-ro-casacivil-lei-00002\n",
            encoding="utf-8",
        )
        plan = _prepare(path, select="ids-file", ids_file=ids_file)
        assert {n.texto_id for n in plan.real_norms} == {
            "leizilla-raw-ro-casacivil-lei-00002",
            "leizilla-raw-ro-casacivil-lei-00004",
        }
        assert plan.selection["ids_file"]["ids"] == 2
        assert (
            len(_prepare(path, select="ids-file", ids_file=ids_file, limit=1).norms)
            == 1
        )

    def test_unknown_id_and_misused_ids_file_are_errors(self, tmp_path: Path) -> None:
        path, _ = _layer(tmp_path)
        ids_file = tmp_path / "ids.txt"
        ids_file.write_text("nao-existe\n", encoding="utf-8")
        with pytest.raises(tb.TeacherBatchError, match="not in the text layer"):
            _prepare(path, select="ids-file", ids_file=ids_file)
        with pytest.raises(tb.TeacherBatchError, match="needs --ids-file"):
            _prepare(path, select="ids-file")
        with pytest.raises(tb.TeacherBatchError, match="only used with"):
            _prepare(path, select="all", ids_file=ids_file)
        with pytest.raises(tb.TeacherBatchError, match="textos"):
            _prepare(path, text_source="ia")

    def test_tipo_filter_and_exclude_labelled(self, tmp_path: Path) -> None:
        path, _ = _layer(tmp_path)
        assert _prepare(path, tipo="decreto").real_norms == []
        labels = tmp_path / "labels"
        header = {
            "record": "norm",
            "item": ITEM,
            "uuid5": f"{1:08x}",
            "text_sha256": _record(1, _law(6, tag=".1")).text_sha256,
        }
        (labels / ITEM).mkdir(parents=True)
        (labels / ITEM / "lei-00001.jsonl").write_text(json.dumps(header) + "\n")
        plan = _prepare(path, exclude_labelled=str(labels))
        assert len(plan.real_norms) == 3

    def test_canary_share_adds_copies_of_closed_norms(self, tmp_path: Path) -> None:
        path, _ = _layer(tmp_path)
        plan = _prepare(path, canary_share=0.5)
        assert len(plan.real_norms) == 4 and len(plan.canary_norms) == 2
        assert all(n.reader_closes for n in plan.canary_norms)

    def test_canary_ids_file(self, tmp_path: Path) -> None:
        path, _ = _layer(tmp_path)
        cfile = tmp_path / "c.txt"
        cfile.write_text("leizilla-raw-ro-casacivil-lei-00004\n", encoding="utf-8")
        plan = _prepare(path, canary_ids_file=cfile, canary_share=0.9)
        assert [n.texto_id for n in plan.canary_norms] == [
            "leizilla-raw-ro-casacivil-lei-00004"
        ]


class TestCLI:
    runner = CliRunner()

    def test_plan_prints_estimate_ceiling_and_label_comparison_without_api(
        self, tmp_path: Path
    ) -> None:
        path, _ = _layer(tmp_path)
        out = tmp_path / "plan.json"
        factory = MagicMock(side_effect=AssertionError("no API client"))
        with patch("leizilla.teacher_batch._client", factory):
            result = self.runner.invoke(
                tb.app,
                [
                    "plan",
                    "--mode",
                    "review",
                    "--text-source",
                    "textos",
                    "--textos",
                    str(path),
                    "--canary-share",
                    "0.5",
                    "--model",
                    "claude-haiku-5-5",
                    "--out",
                    str(out),
                ],
            )
        assert result.exit_code == 0, result.output
        factory.assert_not_called()
        assert "review: 4 norms + 2 canaries" in result.output
        assert "claude-haiku-5-5 effort=medium" in result.output
        assert "same norms in label mode" in result.output
        saved = json.loads(out.read_text(encoding="utf-8"))
        assert saved["mode"] == "review" and saved["label_set"] == "review"
        assert saved["label_mode_estimates"][0]["norms"] == 4
        assert (
            saved["estimates"][0]["ceiling_usd"] > saved["estimates"][0]["estimate_usd"]
        )

    def test_review_never_uses_the_main_label_set(self, tmp_path: Path) -> None:
        path, _ = _layer(tmp_path)
        result = self.runner.invoke(
            tb.app,
            [
                "plan",
                "--mode",
                "review",
                "--text-source",
                "textos",
                "--textos",
                str(path),
                "--label-set",
                "main",
            ],
        )
        assert (
            result.exit_code == 2
            and "must not use the 'main' label set" in result.output
        )

    def test_submit_guard_refuses_before_any_batch(self, tmp_path: Path) -> None:
        path, _ = _layer(tmp_path)
        manifest = tmp_path / "m.json"
        factory = MagicMock(side_effect=AssertionError("no API client"))
        with patch("leizilla.teacher_batch._client", factory):
            result = self.runner.invoke(
                tb.app,
                [
                    "submit",
                    "--mode",
                    "review",
                    "--text-source",
                    "textos",
                    "--textos",
                    str(path),
                    "--max-usd",
                    "0.0000001",
                    "--manifest",
                    str(manifest),
                ],
            )
        assert result.exit_code == 2 and "cost guard" in result.output
        assert not manifest.exists()

    def test_submit_writes_a_review_manifest(self, tmp_path: Path) -> None:
        path, _ = _layer(tmp_path)
        manifest = tmp_path / "m.json"
        client = MagicMock()
        client.messages.batches.create.return_value = SimpleNamespace(id="msgbatch_1")
        with patch("leizilla.teacher_batch._client", lambda: client):
            result = self.runner.invoke(
                tb.app,
                [
                    "submit",
                    "--mode",
                    "review",
                    "--text-source",
                    "textos",
                    "--textos",
                    str(path),
                    "--max-usd",
                    "5",
                    "--manifest",
                    str(manifest),
                    "--canary-share",
                    "0.5",
                ],
            )
        assert result.exit_code == 0, result.output
        data = json.loads(manifest.read_text(encoding="utf-8"))
        assert data["mode"] == "review" and data["label_set"] == "review"
        assert data["batches"][0]["id"] == "msgbatch_1"
        sent = client.messages.batches.create.call_args.kwargs["requests"]
        assert [r["custom_id"] for r in sent] == data["batches"][0]["custom_ids"]
        assert sent[0]["params"]["system"][0]["text"] == tr.REVIEW_SYSTEM_PROMPT
        assert data["prompt_sha256"] == tr.review_prompt_sha256()


# --------------------------------------------------------------------------
# Collect: validation, canary scoring, unverified, outputs
# --------------------------------------------------------------------------


def _entry(cid: str, payload: Any, stop: str = "end_turn") -> Dict[str, Any]:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return {
        "custom_id": cid,
        "result": {
            "type": "succeeded",
            "message": {
                "content": [
                    {"type": "thinking", "thinking": ""},
                    {"type": "text", "text": text},
                ],
                "stop_reason": stop,
                "usage": {"input_tokens": 1000, "output_tokens": 100},
            },
        },
    }


def _fake_client(results: Dict[str, List[Dict[str, Any]]]) -> Any:
    client = MagicMock()
    client.messages.batches.results.side_effect = lambda batch_id: results[batch_id]
    return client


def _submitted(tmp_path: Path, plan: tr.ReviewPlan) -> Dict[str, Any]:
    spec = tb.MODELS["claude-haiku-5-5"]
    est = tr.estimate_review_cost(plan, spec, "medium", True)
    manifest = tr.build_review_manifest(
        plan, est, ente="ro", effort="medium", cache=True, max_usd=1, guard="ceiling"
    )
    client = MagicMock()
    client.messages.batches.create.return_value = SimpleNamespace(id="msgbatch_1")
    tr.submit_review_batches(
        client, plan, spec, manifest, tmp_path / "m.json", effort="medium", cache=True
    )
    return manifest


def _answers(
    manifest: Dict[str, Any],
    decide: Callable[[str, str, Dict[str, Any]], Optional[List[Dict[str, Any]]]],
) -> Dict[str, List[Dict[str, Any]]]:
    out = []
    for cid, req in manifest["requests"].items():
        reviews = []
        for rid, meta in req["slots"].items():
            adjustments = decide(cid, rid, meta) or []
            reviews.append(
                {
                    "id": rid,
                    "verdict": "ajuste" if adjustments else "ok",
                    "adjustments": adjustments,
                }
            )
        out.append(_entry(cid, {"reviews": reviews}))
    return {"msgbatch_1": out}


def _expected_adjustment(meta: Dict[str, Any]) -> List[Dict[str, Any]]:
    plan = meta["canary"]
    line = plan["line"]
    evidence = meta["lines"][str(line)][:60]
    return [
        {
            "op": plan["op"],
            "line": line,
            "number": plan["number"] if plan["op"] != "remove_article" else None,
            "suffix": None,
            "level": None,
            "quoted": plan["quoted"] if plan["op"] == "set_quoted" else None,
            "evidence": evidence,
            "reason": "erro plantado",
        }
    ]


class TestCollect:
    def _setup(self, tmp_path: Path) -> tuple[Dict[str, Any], tr.ReviewPlan]:
        reals = [_record(n) for n in range(1, 5)]
        sources = [_record(n) for n in range(10, 12)]
        plan = _plan(reals, sources, seed="5", max_norms=3)
        return _submitted(tmp_path, plan), plan

    def test_caught_canaries_and_clean_ok_verdicts(self, tmp_path: Path) -> None:
        manifest, plan = self._setup(tmp_path)
        results = _answers(
            manifest,
            lambda cid, rid, meta: _expected_adjustment(meta)
            if meta["canary"]
            else None,
        )
        out = tmp_path / "out"
        summary = tr.collect_review(_fake_client(results), manifest, out)
        assert summary["canaries"]["total"] == 2 and summary["canaries"]["caught"] == 2
        assert summary["canaries"]["recall"] == 1.0
        assert summary["verdicts"] == {"ok": 4, "ajuste": 0}
        assert summary["unverified"] == 0 and summary["invalid"] == 0
        assert summary["norms_total"] == 4
        assert summary["usage"]["output_tokens"] == 100 * len(manifest["requests"])
        assert summary["measured_usd"] > 0
        assert summary["measured_usd_per_norm"] == pytest.approx(
            summary["measured_usd"] / 4, abs=1e-6
        )
        files = sorted((out / "reviews").rglob("*.json"))
        assert len(files) == 6  # 4 real + 2 canaries
        canary_files = [f for f in files if f.stem.endswith("_canary")]
        assert len(canary_files) == 2
        review = json.loads(canary_files[0].read_text(encoding="utf-8"))
        assert review["canary"] and review["canary_outcome"] == "caught"
        assert review["texto_id"].startswith("leizilla-raw-ro-casacivil-lei-")
        assert review["text_sha256"] and review["reader"]["articles"]
        real = json.loads(
            next(f for f in files if not f.stem.endswith("_canary")).read_text()
        )
        assert real["verdict"] == "ok" and real["unverified"] is False
        assert (out / "summary.json").is_file() and (out / "manifest.json").is_file()
        adj = json.loads((out / "review-adjustments.json").read_text())
        assert adj["corrections"] == [] and "NOT applied" in adj["status"]

    def test_a_missed_canary_marks_the_ok_verdicts_of_its_request_unverified(
        self, tmp_path: Path
    ) -> None:
        manifest, plan = self._setup(tmp_path)
        canary_requests = [
            cid for cid, req in manifest["requests"].items() if req["has_canary"]
        ]
        assert len(canary_requests) == 2
        missed_request = canary_requests[0]
        results = _answers(
            manifest,
            lambda cid, rid, meta: (
                _expected_adjustment(meta)
                if meta["canary"] and cid != missed_request
                else None
            ),
        )
        out = tmp_path / "out"
        summary = tr.collect_review(_fake_client(results), manifest, out)
        assert summary["canaries"]["missed"] == 1 and summary["canaries"]["caught"] == 1
        assert summary["unverified_requests"] == [missed_request]
        reviews = [json.loads(f.read_text()) for f in (out / "reviews").rglob("*.json")]
        flagged = [r for r in reviews if r["unverified"]]
        assert flagged
        assert all(
            missed_request in r["request_ids"] and not r["canary"] for r in flagged
        )
        others = [
            r
            for r in reviews
            if not r["canary"] and missed_request not in r["request_ids"]
        ]
        assert all(not r["unverified"] for r in others)
        assert summary["unverified"] == len(flagged)

    def test_invalid_results_land_in_failures_and_never_as_ok(
        self, tmp_path: Path
    ) -> None:
        manifest, plan = self._setup(tmp_path)

        def decide(cid: str, rid: str, meta: Dict[str, Any]) -> Any:
            return _expected_adjustment(meta) if meta["canary"] else None

        results = _answers(manifest, decide)
        # drop one id from the first request that has a real norm, duplicate another
        first = results["msgbatch_1"][0]
        payload = json.loads(first["result"]["message"]["content"][1]["text"])
        victim = payload["reviews"].pop()
        first["result"]["message"]["content"][1]["text"] = json.dumps(payload)
        out = tmp_path / "out"
        summary = tr.collect_review(_fake_client(results), manifest, out)
        failures = [
            json.loads(line)
            for line in (out / "failures.jsonl").read_text().splitlines()
        ]
        assert any(
            any("missing_id" in p for p in f.get("problems", [])) for f in failures
        )
        assert summary["failure_reasons"]["missing_id"] >= 1
        rid = victim["id"]
        meta = manifest["requests"][first["custom_id"]]["slots"][rid]
        path = next(
            f
            for f in (out / "reviews").rglob("*.json")
            if json.loads(f.read_text())["key"] == meta["key"]
            and (f.stem.endswith("_canary") == bool(meta["canary"]))
        )
        assert json.loads(path.read_text())["verdict"] == "invalid"
        if not meta["canary"]:
            assert summary["invalid"] == 1 and summary["norms_failed"] == 1
        else:
            assert summary["canaries"]["invalid"] == 1

    def test_candidate_adjustments_are_written_for_real_norms_only(
        self, tmp_path: Path
    ) -> None:
        manifest, plan = self._setup(tmp_path)

        def decide(cid: str, rid: str, meta: Dict[str, Any]) -> Any:
            if meta["canary"]:
                return _expected_adjustment(meta)
            line = meta["reader"]["articles"][0][0]
            return [
                {
                    "op": "remove_article",
                    "line": line,
                    "number": None,
                    "suffix": None,
                    "level": None,
                    "quoted": None,
                    "evidence": meta["lines"][str(line)][:60],
                    "reason": "teste",
                }
            ]

        out = tmp_path / "out"
        summary = tr.collect_review(
            _fake_client(_answers(manifest, decide)), manifest, out
        )
        adj = json.loads((out / "review-adjustments.json").read_text())
        assert len(adj["corrections"]) == 4 == summary["verdicts"]["ajuste"]
        entry = adj["corrections"][0]
        assert entry["op"] == "remove_article" and entry["errata_compatible"] is False
        assert entry["text_sha256"] and entry["norm"].startswith(ITEM)
        assert summary["adjustments_by_op"] == {"remove_article": 4}

    def test_upload_uses_the_label_set_naming(self, tmp_path: Path) -> None:
        manifest, plan = self._setup(tmp_path)
        results = _answers(manifest, lambda c, r, m: None)
        out = tmp_path / "out"
        summary = tr.collect_review(_fake_client(results), manifest, out)
        with patch("leizilla.publisher.InternetArchivePublisher") as pub:
            result = tr.upload_review_to_ia(out, summary, revision="20261117t000000z")
        assert result == {
            "success": True,
            "ia_id": "leizilla-teacher-labels-ro-review-20261117t000000z",
        }
        args = pub.return_value._run_ia_upload.call_args.args[0]
        assert args[:2] == ["ia", "upload"]
        assert any(a.endswith("reviews.tar.gz") for a in args)
        assert any(a.endswith("review-adjustments.json") for a in args)

    def test_collect_command_dispatches_on_the_manifest_mode(
        self, tmp_path: Path
    ) -> None:
        manifest, plan = self._setup(tmp_path)
        results = _answers(manifest, lambda c, r, m: None)
        client = _fake_client(results)
        client.messages.batches.retrieve.return_value = SimpleNamespace(
            processing_status="ended",
            request_counts=SimpleNamespace(
                processing=0, succeeded=1, errored=0, canceled=0, expired=0
            ),
        )
        manifest_path = tmp_path / "m.json"
        manifest_path.write_text(json.dumps(manifest))
        out = tmp_path / "out"
        with patch("leizilla.teacher_batch._client", lambda: client):
            result = CliRunner().invoke(
                tb.app,
                [
                    "collect",
                    "--manifest",
                    str(manifest_path),
                    "--out-dir",
                    str(out),
                    "--label-set",
                    "review",
                ],
            )
        assert result.exit_code == 0, result.output
        assert "norms reviewed" in result.output and "canaries 0/2" in result.output
        assert (out / "reviews").is_dir() and not (out / "labels").exists()
        with patch("leizilla.teacher_batch._client", lambda: client):
            wrong = CliRunner().invoke(
                tb.app,
                [
                    "collect",
                    "--manifest",
                    str(manifest_path),
                    "--out-dir",
                    str(tmp_path / "o2"),
                    "--label-set",
                    "main",
                ],
            )
        assert wrong.exit_code == 2 and "does not match" in wrong.output


# --------------------------------------------------------------------------
# Scoring script (synthetic reviews)
# --------------------------------------------------------------------------


def _label_dir(
    root: Path, text: str, uuid5: str, numero: int, numbers: List[str]
) -> Any:
    lines = tb.split_lines(text)
    header = {
        "record": "norm",
        "ente": "ro",
        "fonte": "casacivil",
        "item": ITEM,
        "uuid5": uuid5,
        "tipo": "lei",
        "numero": numero,
        "txt_name": f"lei-{numero:05d}_{uuid5}_djvu.txt",
        "text_sha256": _sha(text),
        "n_lines": len(lines),
        "chunks": 1,
    }
    arts = [
        i for i, line in enumerate(lines, 1) if line.startswith("Art. ") and "º" in line
    ]
    path = root / "labels" / ITEM / f"lei-{numero:05d}_{uuid5}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [json.dumps(header)]
    for line, number in zip(arts, numbers):
        rows.append(
            json.dumps(
                {
                    "record": "label",
                    "line": line,
                    "category": "artigo",
                    "number": number,
                    "quoted": False,
                }
            )
        )
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return header


def _review(
    rec: tb.TextoRecord,
    verdict: str,
    adjustments: Optional[List[Dict[str, Any]]] = None,
    *,
    reader_numbers: Optional[List[str]] = None,
    canary: Optional[Dict[str, Any]] = None,
    outcome: Optional[str] = None,
    unverified: bool = False,
) -> Dict[str, Any]:
    view = tr.build_view(rec.text)
    summary = view.summary()
    if reader_numbers is not None:
        summary["articles"] = [
            [a[0], n, a[2]] for a, n in zip(summary["articles"], reader_numbers)
        ]
    return {
        "record": "review",
        "key": rec.ref.key,
        "texto_id": rec.texto_id,
        "item": rec.ref.item,
        "uuid5": rec.ref.uuid5,
        "text_sha256": rec.text_sha256,
        "reader": summary,
        "verdict": verdict,
        "adjustments": adjustments or [],
        "canary": canary is not None,
        "canary_plan": canary,
        "canary_outcome": outcome,
        "unverified": unverified,
    }


class TestScoreReview:
    def _world(self, tmp_path: Path) -> Dict[str, Any]:
        text = _law(6)
        recs = {n: _record(n, _law(6, tag=f".{n}")) for n in range(1, 7)}
        labels = tmp_path / "labels_root"
        texts = tmp_path / "texts"
        for n, rec in recs.items():
            nums = [str(i) for i in range(1, 7)]
            header = _label_dir(labels, rec.text, rec.ref.uuid5, n, nums)
            cache = cmp._cache_file(texts, header)
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(rec.text.encode("utf-8"))
        return {"recs": recs, "labels": labels, "texts": texts, "text": text}

    def _adj(
        self, rec: tb.TextoRecord, op: str, line: int, **kw: Any
    ) -> Dict[str, Any]:
        return {
            "op": op,
            "line": line,
            "number": kw.get("number"),
            "suffix": None,
            "level": None,
            "quoted": kw.get("quoted"),
            "evidence": rec.text.split("\n")[line - 1].strip()[:40],
            "reason": "r",
        }

    def test_outcomes_false_alarms_canaries_and_cost(self, tmp_path: Path) -> None:
        w = self._world(tmp_path)
        recs = w["recs"]
        line_of = lambda rec, number: next(  # noqa: E731
            ln for ln, n, _q in tr.build_view(rec.text).articles() if n == number
        )
        reviews = []
        # 1: reader == teacher, ok -> true_ok
        reviews.append(_review(recs[1], "ok"))
        # 2: reader == teacher, ajuste that breaks the set -> false_alarm
        l2 = line_of(recs[2], "3")
        reviews.append(
            _review(
                recs[2], "ajuste", [self._adj(recs[2], "set_number", l2, number="9")]
            )
        )
        # 3: reader wrong (art 3 read as 8), reviewer fixes it -> fully_fixed
        l3 = line_of(recs[3], "3")
        reviews.append(
            _review(
                recs[3],
                "ajuste",
                [self._adj(recs[3], "set_number", l3, number="3")],
                reader_numbers=["1", "2", "8", "4", "5", "6"],
            )
        )
        # 4: reader wrong, reviewer says ok -> missed (unverified)
        reviews.append(
            _review(
                recs[4],
                "ok",
                reader_numbers=["1", "2", "8", "4", "5", "6"],
                unverified=True,
            )
        )
        # 5: reader wrong, reviewer moves it the wrong way
        l5 = line_of(recs[5], "3")
        reviews.append(
            _review(
                recs[5],
                "ajuste",
                [self._adj(recs[5], "set_number", l5, number="7")],
                reader_numbers=["1", "2", "8", "4", "5", "6"],
            )
        )
        # 6: invalid
        reviews.append(_review(recs[6], "invalid"))
        # canaries
        plan = {"kind": "renumber", "line": 3, "op": "set_number"}
        reviews.append(_review(recs[1], "ajuste", canary=plan, outcome="caught"))
        reviews.append(
            _review(
                recs[2], "ok", canary={**plan, "kind": "spurious"}, outcome="missed"
            )
        )
        wanted = {(r["item"], r["uuid5"]) for r in reviews if not r["canary"]}
        teachers = sr.teacher_sets(w["labels"], w["texts"], None, None, wanted)
        summary = {
            "measured_usd": 0.012,
            "measured_usd_per_norm": 0.002,
            "measured_usd_per_entry": 0.0015,
        }
        result = sr.score(reviews, teachers, summary)
        assert result["scored"] == 6 and result["not_scored"] == {}
        outcomes = {r["key"].split("/")[1]: r["outcome"] for r in result["rows"]}
        assert outcomes[recs[1].ref.uuid5] == "true_ok"
        assert outcomes[recs[2].ref.uuid5] == "false_alarm"
        assert outcomes[recs[3].ref.uuid5] == "fully_fixed"
        assert outcomes[recs[4].ref.uuid5] == "missed"
        assert outcomes[recs[5].ref.uuid5] == "no_change"  # 8 -> 7 is one line off
        assert outcomes[recs[6].ref.uuid5] == "invalid"
        dis = result["reader_disagrees"]
        assert dis["norms"] == 3 and dis["invalid"] == 0
        assert dis["outcomes"]["fully_fixed"] == 1 and dis["outcomes"]["missed"] == 1
        assert dis["unverified_ok"] == 1
        closed = result["reader_agrees"]["agree_closed"]
        assert closed["norms"] == 2 and closed["ajuste"] == 1
        assert closed["false_alarm_rate"] == 0.5
        assert closed["alarms"][0]["key"] == recs[2].ref.key
        assert result["canaries"]["renumber"]["recall"] == 1.0
        assert result["canaries"]["spurious"]["missed"] == 1
        assert result["canaries"]["all"]["recall"] == 0.5
        assert result["cost"]["ratio_to_label_mode"] == pytest.approx(3.175, abs=1e-3)
        md = sr.to_markdown(result)
        assert "false alarms" in md and "Canary recall" in md and "fully_fixed" in md

    def test_adjustments_that_break_an_agreeing_norm_are_a_false_alarm(
        self, tmp_path: Path
    ) -> None:
        w = self._world(tmp_path)
        rec = w["recs"][1]
        l1 = next(ln for ln, n, _q in tr.build_view(rec.text).articles() if n == "3")
        review = _review(
            rec,
            "ajuste",
            [
                self._adj(rec, "set_number", l1, number="7"),
                self._adj(rec, "set_quoted", l1, quoted=True),
            ],
        )
        ident = (review["item"], review["uuid5"])
        teachers = sr.teacher_sets(w["labels"], w["texts"], None, None, {ident})
        row = sr.score_norm(review, teachers[ident])
        assert row["group"] == "agree_closed" and row["outcome"] == "false_alarm"
        assert row["gap_after_adjustments"] > row["reader_gap"] == 0

    def test_not_scored_when_the_text_differs_or_no_label(self, tmp_path: Path) -> None:
        w = self._world(tmp_path)
        rec = w["recs"][1]
        changed = _review(rec, "ok")
        changed["text_sha256"] = "0" * 64
        stranger = _review(_record(99), "ok")
        wanted = {
            (changed["item"], changed["uuid5"]),
            (stranger["item"], stranger["uuid5"]),
        }
        teachers = sr.teacher_sets(w["labels"], w["texts"], None, None, wanted)
        result = sr.score([changed, stranger], teachers, None)
        assert result["scored"] == 0
        assert result["not_scored"] == {"not_labelled": 1, "sha_differs_from_label": 1}

    def test_end_to_end_through_collect_output(self, tmp_path: Path) -> None:
        w = self._world(tmp_path)
        out = tmp_path / "collected"
        (out / "reviews" / ITEM).mkdir(parents=True)
        for i, rec in w["recs"].items():
            review = _review(rec, "ok")
            (out / "reviews" / ITEM / f"r{i}.json").write_text(json.dumps(review))
        (out / "summary.json").write_text(
            json.dumps({"measured_usd": 0.01, "measured_usd_per_norm": 0.001})
        )
        score_out = tmp_path / "score"
        code = sr.main(
            [
                "--reviews",
                str(out),
                "--labels",
                str(w["labels"]),
                "--texts",
                str(w["texts"]),
                "--out",
                str(score_out),
                "--no-errata",
            ]
        )
        assert code == 0
        data = json.loads((score_out / "score_review.json").read_text())
        assert data["scored"] == 6
        assert data["reader_agrees"]["agree_closed"]["false_alarm_rate"] == 0.0
        assert (score_out / "score_review.md").is_file()


# --------------------------------------------------------------------------
# Workflow
# --------------------------------------------------------------------------


class TestWorkflow:
    def _wf(self) -> Dict[Any, Any]:
        return yaml.safe_load(
            (ROOT / ".github/workflows/teacher-batch.yml").read_text(encoding="utf-8")
        )

    def test_inputs_keep_the_old_ones_and_add_the_review_ones(self) -> None:
        wf = self._wf()
        inputs = wf[True]["workflow_dispatch"]["inputs"]
        for old in (
            "step",
            "model",
            "effort",
            "limit",
            "tipo",
            "shuffle_seed",
            "max_usd",
            "guard",
            "manifest_run_id",
            "wait_minutes",
            "upload_ia",
            "text_source",
            "exclude_labelled",
            "label_set",
        ):
            assert old in inputs
        for new in ("mode", "select", "ids_file", "canary_share", "canary_ids_file"):
            assert new in inputs
        assert inputs["mode"]["default"] == "label"
        assert inputs["mode"]["options"] == ["label", "review", "mark"]

    def test_authentication_and_permissions_are_untouched(self) -> None:
        wf = self._wf()
        assert wf["permissions"] == {
            "contents": "read",
            "id-token": "write",
            "issues": "write",
            "actions": "read",
        }
        text = (ROOT / ".github/workflows/teacher-batch.yml").read_text()
        assert (
            text.count("scripts/anthropic_wif.py run -- -m leizilla.teacher_batch") == 3
        )
        assert "ANTHROPIC_GOOGLE_WIF_PROVIDER" in text

    def test_sample_files_are_valid_and_disjoint(self) -> None:
        d = ROOT / "docs/okf/review-samples"
        reviewed = tr.read_ids_file(d / "eval-2026-11.txt")
        canaries = tr.read_ids_file(d / "eval-2026-11-canaries.txt")
        assert len(reviewed) == 200 and len(canaries) == 100
        assert not set(reviewed) & set(canaries)


# --------------------------------------------------------------------------
# Review v2: budget, truncation and retry, partial norms, validator leniencies,
# hint, canary chain split, scoring of the new outcomes
# --------------------------------------------------------------------------


def _truncated(cid: str) -> Dict[str, Any]:
    """A reply that spent its whole budget on thinking: no text block."""
    return {
        "custom_id": cid,
        "result": {
            "type": "succeeded",
            "message": {
                "content": [{"type": "thinking", "thinking": ""}],
                "stop_reason": "max_tokens",
                "usage": {"input_tokens": 1000, "output_tokens": 16000},
            },
        },
    }


class TestBudget:
    def test_review_max_tokens_arithmetic(self) -> None:
        per_norm = tr.REVIEW_THINKING_PER_NORM + tr.CEILING_TOKENS_PER_NORM
        assert tr.CEILING_TOKENS_PER_NORM == 465
        assert tr.review_max_tokens(1) == 8192 + per_norm == 10705
        assert tr.review_max_tokens(2) == 8192 + 2 * per_norm == 13218
        assert tr.review_max_tokens(8) == 16000  # capped
        assert tr.review_max_tokens(1, cap=5000) == 5000

    def test_every_request_stays_under_the_cap(self) -> None:
        recs = [_record(n) for n in range(1, 13)]
        plan = _plan(recs, budget_chars=10**6, max_norms=12)
        assert plan.requests
        assert all(r.max_tokens <= tr.REVIEW_MAX_TOKENS_CAP for r in plan.requests)

    def test_estimate_uses_the_measured_base_and_the_ceiling_bounds_it(self) -> None:
        plan = _plan([_record(n) for n in (1, 2, 3)], budget_chars=10**6)
        spec = tb.MODELS["claude-haiku-5-5"]
        est = tr.estimate_review_cost(plan, spec, "medium", True)
        expected = sum(
            min(
                r.max_tokens,
                tr.MEASURED_OUTPUT_TOKENS_PER_REQUEST
                + tr.expected_tokens_per_norm() * len(r.slots),
            )
            for r in plan.requests
        )
        assert est.estimated_output_tokens == expected
        assert est.ceiling_output_tokens == sum(r.max_tokens for r in plan.requests)
        assert est.estimated_output_tokens <= est.ceiling_output_tokens
        assert est.ceiling_usd >= est.estimate_usd


class TestTruncation:
    def test_cut_reply_is_truncated_not_invalid(self) -> None:
        outcome = tr.interpret_review_result(_truncated("r00000"))
        assert outcome.ok is False and outcome.truncated is True
        assert outcome.reason == "stop_reason_max_tokens"

    def test_thinking_only_end_turn_is_truncated_too(self) -> None:
        entry = _entry("r00000", "", stop="end_turn")
        entry["result"]["message"]["content"] = [{"type": "thinking", "thinking": ""}]
        outcome = tr.interpret_review_result(entry)
        assert outcome.truncated is True and outcome.reason == "no_text_block"

    def test_invalid_json_is_not_truncation(self) -> None:
        outcome = tr.interpret_review_result(_entry("r00000", "não é json"))
        assert outcome.ok is False and outcome.truncated is False

    def test_truncated_request_gives_truncated_slots(self) -> None:
        recs = [_record(n) for n in (1, 2)]
        plan = _plan(recs, budget_chars=10**6)
        est = tr.estimate_review_cost(
            plan, tb.MODELS["claude-haiku-5-5"], "medium", True
        )
        manifest = tr.build_review_manifest(
            plan,
            est,
            ente="ro",
            effort="medium",
            cache=True,
            max_usd=1,
            guard="ceiling",
        )
        ((cid, meta),) = manifest["requests"].items()
        outcome = tr.interpret_review_result(_truncated(cid))
        results, _ = tr.evaluate_request(cid, meta, outcome)
        assert all(r.truncated and not r.valid for r in results)
        assert tr._merge_entry([results[0]]).verdict == "truncated"


class TestRetry:
    def _world(
        self, tmp_path: Path
    ) -> tuple[Dict[str, Any], Callable[[], tr.ReviewPlan]]:
        reals = [_record(n) for n in range(1, 5)]
        sources = [_record(n) for n in range(10, 12)]
        make = lambda: _plan(reals, sources, seed="5", max_norms=3)  # noqa: E731
        return _submitted(tmp_path, make()), make

    def _first_run(self, tmp_path: Path) -> tuple[Dict[str, Any], str, Path]:
        manifest, make = self._world(tmp_path)
        cut = next(iter(manifest["requests"]))

        def answer(cid: str) -> Dict[str, Any]:
            if cid == cut:
                return _truncated(cid)
            reviews = [
                {"id": rid, "verdict": "ok", "adjustments": []}
                for rid in manifest["requests"][cid]["slots"]
            ]
            return _entry(cid, {"reviews": reviews})

        results = {"msgbatch_1": [answer(cid) for cid in manifest["requests"]]}
        out = tmp_path / "out1"
        summary = tr.collect_review(_fake_client(results), manifest, out)
        assert summary["truncated_requests"] == [cut]
        return json.loads((out / "manifest.json").read_text()), cut, out

    def test_retry_selects_only_truncated_requests_and_unpacks_them(
        self, tmp_path: Path
    ) -> None:
        base, cut, _out = self._first_run(tmp_path)
        _, make = self._world(tmp_path)
        plan = make()
        retry = tr.build_retry_plan(plan, base, depth=1, max_tokens_cap=16000)
        original = base["requests"][cut]["slots"]
        assert len(retry.requests) == len(original) >= 1
        for req in retry.requests:
            assert len(req.slots) == 1 and req.custom_id.startswith("t1-")
            assert req.max_tokens == tr.review_max_tokens(1)
        assert sorted(
            (int(s.chunk.index), s.norm.entry) for r in retry.requests for s in r.slots
        ) == sorted((int(m["chunk"]), m["entry"]) for m in original.values())

    def test_retry_is_refused_when_the_inputs_changed(self, tmp_path: Path) -> None:
        base, _cut, _out = self._first_run(tmp_path)
        changed = [_record(n, _law(6, tag=".x")) for n in range(1, 5)]
        plan = _plan(
            changed, [_record(n) for n in range(10, 12)], seed="5", max_norms=3
        )
        with pytest.raises(tb.TeacherBatchError):
            tr.build_retry_plan(plan, base, depth=1, max_tokens_cap=16000)

    def test_retry_manifest_merges_over_the_original(self, tmp_path: Path) -> None:
        base, cut, _out = self._first_run(tmp_path)
        _, make = self._world(tmp_path)
        plan = make()
        retry = tr.build_retry_plan(plan, base, depth=1, max_tokens_cap=16000)
        est = tr.estimate_review_cost(
            retry, tb.MODELS["claude-haiku-5-5"], "medium", True
        )
        manifest = tr.build_review_manifest(
            retry,
            est,
            ente="ro",
            effort="medium",
            cache=True,
            max_usd=1,
            guard="ceiling",
        )
        tr.attach_retry(manifest, base, depth=1, plan=retry)
        client = MagicMock()
        client.messages.batches.create.return_value = SimpleNamespace(id="msgbatch_2")
        tr.submit_review_batches(
            client,
            retry,
            tb.MODELS["claude-haiku-5-5"],
            manifest,
            tmp_path / "retry.json",
            effort="medium",
            cache=True,
        )
        retry_results = _answers(manifest, lambda c, r, m: None)["msgbatch_1"]
        base_results = {
            "msgbatch_1": [
                _truncated(cid)
                if cid == cut
                else _entry(
                    cid,
                    {
                        "reviews": [
                            {"id": rid, "verdict": "ok", "adjustments": []}
                            for rid in base["requests"][cid]["slots"]
                        ]
                    },
                )
                for cid in base["requests"]
            ]
        }
        results = {**base_results, "msgbatch_2": retry_results}
        out = tmp_path / "out2"
        summary = tr.collect_review(_fake_client(results), manifest, out)
        assert summary["truncated"] == 0 and summary["norms_truncated"] == 0
        assert summary["requests_total"] == len(base["requests"]) - 1 + len(
            retry.requests
        )
        assert cut not in summary["truncated_requests"]
        assert summary["norms_total"] == 4 and summary["canaries"]["total"] == 2
        assert summary["retry"]["truncated_requests"] == [cut]
        assert summary["verdicts"]["ok"] == 4
        assert summary["norms_ok"] == 4


class TestPartialNorm:
    def test_a_missing_part_makes_the_norm_partial_not_ok(self, tmp_path: Path) -> None:
        text = _law(8)
        plan = _plan([_record(1, text)], max_chars=200, budget_chars=10**6)
        chunks = plan.norms[0].chunks
        assert len(chunks) > 1, "the fixture must split into parts"
        manifest = _submitted(tmp_path, plan)
        second = [
            cid
            for cid, req in manifest["requests"].items()
            if any(m["chunk"] == 1 for m in req["slots"].values())
        ]
        assert len(second) == 1
        results = []
        for cid, req in manifest["requests"].items():
            if cid in second:
                results.append(_truncated(cid))
                continue
            reviews = [
                {"id": rid, "verdict": "ok", "adjustments": []} for rid in req["slots"]
            ]
            results.append(_entry(cid, {"reviews": reviews}))
        out = tmp_path / "out"
        summary = tr.collect_review(
            _fake_client({"msgbatch_1": results}), manifest, out
        )
        (record,) = [
            json.loads(f.read_text()) for f in (out / "reviews").rglob("*.json")
        ]
        assert record["verdict"] == "partial" and record["partial"] is True
        assert record["missing_parts"][0]["status"] == "truncated"
        assert record["verdict"] != "ok"
        assert summary["partial"] == 1 and summary["norms_ok"] == 0
        assert summary["norms_partial"] == 1

    def test_a_valid_part_adjustment_survives_a_missing_part(self) -> None:
        meta_a = {"chunk": 0, "entry": "e", "key": "k"}
        meta_b = {"chunk": 1, "entry": "e", "key": "k"}
        adj = {
            "op": "set_number",
            "line": 3,
            "number": "9",
            "suffix": None,
            "level": None,
            "quoted": None,
            "evidence": "x" * 15,
            "reason": "r",
        }
        good = tr.SlotResult("N01", "r0", meta_a, True, "ajuste", [adj], [])
        missing = tr.SlotResult(
            "N02", "r1", meta_b, False, problems=["x"], truncated=True
        )
        merged = tr._merge_entry([missing, good])
        assert merged.verdict == "ajuste" and merged.partial
        assert merged.adjustments == [adj]


class TestValidatorLeniency:
    def test_whitespace_runs_fold(self) -> None:
        assert tr._evidence_matches(
            "Art. 1º -  Fica criada", "Art. 1º - Fica criada a coisa."
        )

    def test_quotes_and_dashes_normalise(self) -> None:
        assert tr._evidence_matches(
            "“Art. 5º – Fica proibido”", '"Art. 5º - Fica proibido"'
        )

    def test_copied_tag_prefix_is_stripped(self) -> None:
        assert tr._evidence_matches(
            "[art 4 Q] Art. 4º - Revogam-se as disposições",
            "Art. 4º - Revogam-se as disposições em contrário.",
        )

    def test_evidence_running_into_the_next_line_is_accepted(self) -> None:
        assert tr._evidence_matches(
            "Revogam-se as disposições em contrário.", "Revogam-se as disposições em"
        )

    def test_a_different_line_is_still_refused(self) -> None:
        assert not tr._evidence_matches(
            "Art. 9º - Outra coisa inteira aqui", "Art. 1º - Fica criada a coisa."
        )

    def test_evidence_with_a_copied_tag_is_kept_end_to_end(self) -> None:
        text = _law(6)
        lines = tb.split_lines(text)
        meta = _meta_for(text)
        meta.pop("_plan")
        line = next(i for i, ln in enumerate(lines, 1) if "entra em vigor" in ln)
        adj = _adj("set_number", line, lines, number="9")
        adj["evidence"] = "[art 5] " + adj["evidence"]
        check = tr.check_entry(
            {"id": "N01", "verdict": "ajuste", "adjustments": [adj]}, meta
        )
        assert check.problems == [] and len(check.adjustments) == 1
        assert check.dropped == []


class TestHint:
    def test_untagged_article_line_gets_the_hint_and_others_do_not(self) -> None:
        text = _law(6)
        lines = tb.split_lines(text)
        view = tr.build_view(text)
        line = next(i for i, ln in enumerate(lines, 1) if ln.startswith("Art. 3º"))
        view.tags.pop(line)
        rendered = tr._listing(lines, view, [line])
        assert rendered.startswith(f"{line}\t[?art] Art. 3º")
        untagged_plain = next(
            i
            for i, ln in enumerate(lines, 1)
            if ln.strip() == "Porto Velho, 5 de abril de 1985."
        )
        assert "[?art]" not in tr._listing(lines, view, [untagged_plain])

    def test_canary_that_dropped_a_tag_looks_like_a_real_miss(self) -> None:
        text = _law(6)
        lines = tb.split_lines(text)
        view = tr.build_view(text)
        mutated, plan = tr.plant_canary(view, lines, "drop_last", tr.rng_for("s", "k"))
        real_miss = tr.build_view(text)
        real_miss.tags.pop(plan.line)
        assert tr._listing(lines, mutated, [plan.line]) == tr._listing(
            lines, real_miss, [plan.line]
        )
        assert "[?art]" in tr._listing(lines, mutated, [plan.line])

    def test_prompt_explains_the_flag_and_v2_rules(self) -> None:
        prompt = tr.REVIEW_SYSTEM_PROMPT
        assert "[?art]" in prompt and "Art. 4o" in prompt
        assert "closes=" not in prompt and "last=" not in prompt
        assert tr.REVIEW_PROMPT_VERSION == "teacher-review-v2"


class TestCanaryChainSplit:
    def test_summary_splits_canary_recall_by_chain(self, tmp_path: Path) -> None:
        reals = [_record(n) for n in range(1, 5)]
        sources = [_record(n) for n in range(10, 14)]
        plan = _plan(reals, sources, seed="5", max_norms=3)
        manifest = _submitted(tmp_path, plan)
        results = _answers(
            manifest,
            lambda cid, rid, meta: _expected_adjustment(meta)
            if meta["canary"]
            else None,
        )
        out = tmp_path / "out"
        summary = tr.collect_review(_fake_client(results), manifest, out)
        intact = summary["canary_recall_chain_intact"]
        broken = summary["canary_recall_chain_broken"]
        assert intact["n"] + broken["n"] == summary["canaries"]["total"] == 4
        assert intact["recall"] in (None, 1.0) and broken["recall"] in (None, 1.0)
        flags = [
            json.loads(f.read_text())["canary_chain_intact"]
            for f in (out / "reviews").rglob("*_canary.json")
        ]
        assert all(isinstance(flag, bool) for flag in flags)


class TestRetryCLI:
    def test_retry_truncated_is_refused_in_label_mode(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(
            tb.app,
            [
                "submit",
                "--max-usd",
                "1",
                "--manifest",
                str(tmp_path / "m.json"),
                "--retry-truncated",
                str(tmp_path / "x.json"),
            ],
        )
        assert result.exit_code == 2
        assert "only applies with --mode review" in result.output


class TestScoreTruncatedAndPartial:
    def _teacher(self, rec: tb.TextoRecord) -> Dict[str, Any]:
        view = tr.build_view(rec.text)
        own = {
            (ln, sr.cmp.normalize_number(n)) for ln, n, q in view.articles() if not q
        }
        return {"text_sha256": rec.text_sha256, "own": own, "consistent": True}

    def test_truncated_and_partial_have_their_own_outcomes(self) -> None:
        r1, r2, r3 = _record(1), _record(2), _record(3)
        reviews = [
            _review(r1, "truncated"),
            {
                **_review(
                    r2, "ajuste", [{"op": "set_number", "line": 1, "number": "9"}]
                ),
                "partial": True,
            },
            {
                **_review(r3, "ok"),
                "canary": True,
                "canary_plan": {
                    "kind": "drop_last",
                    "line": 5,
                    "op": "add_own_article",
                },
                "canary_outcome": "truncated",
                "canary_chain_intact": False,
            },
        ]
        teachers = {(r.ref.item, r.ref.uuid5): self._teacher(r) for r in (r1, r2, r3)}
        result = sr.score(reviews, teachers, None)
        assert result["by_group"]["agree_closed"]["truncated"] == 1
        assert result["partial"]["norms"] == 1
        assert result["partial"]["with_adjustments"] == 1
        assert result["reader_agrees"]["agree_closed"]["norms"] == 0
        assert result["reader_disagrees"]["truncated"] == 0
        assert result["canaries"]["drop_last"]["truncated"] == 1
        assert result["canaries"]["chain_broken"]["n"] == 1
        assert result["canaries"]["chain_intact"]["n"] == 0
        assert result["canaries"]["all"]["truncated"] == 1
        assert result["dropped"]["adjustments"] == 0
        dropped_review = {
            **_review(r3, "ok"),
            "dropped": [{"index": 0, "op": "set_number", "line": 1, "reason": "x"}],
            "downgraded": True,
        }
        again = sr.score([dropped_review], teachers, None)
        assert again["dropped"] == {
            "adjustments": 1,
            "downgraded_norms": 1,
            "note": again["dropped"]["note"],
        }
