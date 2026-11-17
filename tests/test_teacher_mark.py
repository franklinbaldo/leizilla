"""Tests for the mark mode of the teacher batch — offline and deterministic.

No API call: the converter is tested on hand-made responses, the plan/collect on a fake
client that plays the Message Batches API, and the answers of a "perfect model" are
built from the rule reader (``response_from_marks``).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from typer.testing import CliRunner

from leizilla import marcacao as M
from leizilla import teacher_batch as tb
from leizilla import teacher_mark as tm
from leizilla.hierarchy_sequence import read_hierarchy

ROOT = Path(__file__).parents[1]
_SCRIPTS = ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import score_mark  # noqa: E402
import simulate_mark  # noqa: E402

ITEM = "leizilla_ro_casacivil_lei_0001-1000"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _mark(
    line: int,
    kind: str,
    col: int,
    t: str,
    n: Optional[str] = None,
    *,
    le: Optional[int] = None,
    s: Optional[str] = None,
    x: bool = False,
    e: Optional[str] = None,
    nota: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "l": line,
        "k": kind,
        "c": col,
        "t": t,
        "n": n,
        "s": s,
        "le": le,
        "x": x,
        "e": e,
        "nota": nota,
    }


def _check(xml: Optional[str], text: str) -> str:
    """Every built document keeps the strip invariant and passes verify."""
    assert xml is not None
    assert M.strip(xml) == text
    assert M.verify(xml, text) == []
    return xml


def _rows(xml: str) -> Dict[str, Dict[str, Any]]:
    return {r["path"]: r for r in M.to_rows(xml)}


TEXT = (
    "Art. 1º Caput da lei.\n"  # 1
    "I - um;\n"  # 2
    "II - dois.\n"  # 3
    "§ 1º Parágrafo.\n"  # 4
    "Art. 2º Fim."  # 5
)


def _base() -> List[Dict[str, Any]]:
    return [
        _mark(1, "art", 1, "Art. 1º", "1"),
        _mark(2, "inc", 1, "I -", "1"),
        _mark(3, "inc", 1, "II -", "2"),
        _mark(4, "par", 1, "§ 1º", "1"),
        _mark(5, "art", 1, "Art. 2º", "2"),
    ]


# --- anchors ---------------------------------------------------------------------
def test_a_and_b_right_use_a_and_agree() -> None:
    conv = tm.convert_response(TEXT, _base(), tipo="lei", numero=1)
    _check(conv.xml, TEXT)
    assert conv.problems == []
    for row in conv.anchors:
        assert row["used"] == "A" and row["a_confirm"] is True
        assert row["agree"] is True and row["delta"] == 0
        assert row["b_method"] == "exact"
        assert row["a_off"] == row["b_off"] == row["offset"]
    assert '<lei tipo="lei" numero="1">' in conv.xml  # type: ignore[operator]


def test_a_off_by_one_b_right_builds_with_b_and_records_the_delta() -> None:
    marks = _base()
    marks[1]["c"] = 2  # "I -": column 2 is the space
    conv = tm.convert_response(TEXT, marks)
    _check(conv.xml, TEXT)
    row = conv.anchors[1]
    assert row["used"] == "B" and row["agree"] is False and row["delta"] == 1
    assert row["a_off"] == row["b_off"] + 1
    assert _rows(conv.xml or "")["art-1-inc-1"]["marker"] == "I -"


def test_b_ambiguous_in_the_line_falls_back_to_a() -> None:
    text = "a) x a) y\nArt. 1º Fim."
    marks = [
        _mark(1, "art", 1, "a)", "1", x=True),
        _mark(1, "art", 6, "a)", "2", x=True),
    ]
    conv = tm.convert_response(text, marks)
    _check(conv.xml, text)
    first, second = conv.anchors
    assert first["b_method"] == "ambiguous" and first["b_candidates"] == 2
    assert first["used"] == "A" and first["offset"] == 0
    assert second["used"] == "A" and second["offset"] == 5
    assert second["a_in_candidates"] is True


def test_b_needing_the_tolerant_match() -> None:
    text = "Parágrafo único - Fica criada.\nArt.  5o - Texto.\n"
    marks = [
        _mark(1, "art", 1, "Art. 1º", "1", x=True),
        _mark(2, "art", 3, "Art. 5º", "5"),
    ]
    # line 1 has no "Art. 1º" and its column 1 does not confirm: dropped; line 2's
    # column is wrong (3), so the tolerant match of the text decides
    conv = tm.convert_response(text, marks)
    _check(conv.xml, text)
    by_line = {a["line"]: a for a in conv.anchors}
    assert by_line[2]["b_method"] == "tolerant" and by_line[2]["used"] == "B"
    assert by_line[2]["offset"] == text.index("Art.  5o")
    assert by_line[1]["b_method"] == "none" and by_line[1]["used"] is None
    assert by_line[1]["drop_reason"] == "no_anchor"


def test_tolerant_folds_accents_case_and_punctuation() -> None:
    assert tm.locate("PARÁGRAFO ÚNICO - x", "Parágrafo unico")[0] == "tolerant"
    assert tm.locate("Art. 5º - x", "Art 5o")[0] == "tolerant"
    assert tm.locate("Art. 5º - x", "Art. 6º")[0] == "none"
    assert tm.locate("x", "§")[0] == "none"  # folds to nothing: too short


def test_both_anchors_failing_drops_the_mark_with_a_reason() -> None:
    marks = _base() + [
        _mark(2, "inc", 99, "ZZZ -", "9"),  # no column, no text
        _mark(40, "art", 1, "Art. 9º", "9"),  # no such line
    ]
    conv = tm.convert_response(TEXT, marks)
    _check(conv.xml, TEXT)
    reasons = sorted(p["reason"] for p in conv.problems)
    assert reasons == ["bad_line", "no_anchor"]
    assert [a["drop_reason"] for a in conv.anchors if a["drop_reason"]] == [
        "no_anchor",
        "bad_line",
    ]
    assert len(_rows(conv.xml or "")) == 5


def test_an_unconfirmed_column_with_no_resolving_snippet_is_dropped() -> None:
    marks = _base()
    marks[4]["t"] = "Artigo 2"  # copied wrong: column 1 does not confirm it either
    conv = tm.convert_response(TEXT, marks)
    _check(conv.xml, TEXT)
    assert conv.anchors[4]["used"] is None and conv.anchors[4]["b_method"] == "none"
    assert [p["reason"] for p in conv.problems] == ["no_anchor"]


def test_the_column_is_primary_even_when_the_snippet_resolves_elsewhere() -> None:
    text = "x Art. 1º y Art. 1º z\nArt. 2º Fim."
    marks = [_mark(1, "art", 13, "Art. 1º", "1"), _mark(2, "art", 1, "Art. 2º", "2")]
    conv = tm.convert_response(text, marks)
    _check(conv.xml, text)
    first = conv.anchors[0]
    assert first["b_method"] == "ambiguous" and first["used"] == "A"
    assert first["offset"] == 12 and first["a_confirm"] is True


def test_a_snippet_copied_across_a_line_break_still_confirms_the_column() -> None:
    text = "LEI Nº 5\nDispõe sobre isso.\nArt. 1º Texto."
    marks = [
        _mark(1, "epigrafe", 1, "LEI Nº 5 Dispõe sobre", le=1),  # t crossed the break
        _mark(3, "art", 1, "Art. 1º", "1"),
    ]
    conv = tm.convert_response(text, marks)
    _check(conv.xml, text)
    row = conv.anchors[0]
    assert row["b_method"] == "none" and row["used"] == "A"
    assert row["a_confirm"] is True and conv.problems == []


def test_the_tolerant_match_never_skips_a_quote_character() -> None:
    # a curly quote and a straight one meet; the quote itself is never folded away
    assert tm.locate("\u201cArt. 5º - x", '"Art. 5o') == ("tolerant", [(0, 8)])
    assert tm.locate("Art. 5º - x", '"Art. 5º')[0] == "none"
    # lc-00074 line 51: block at column 1, snippet "Art. 75 - ...." with the quote
    text = 'Art. 1º Passa a vigorar:\n"Art. 75 - Fica criado.\nArt. 2º Outro.'
    marks = [
        _mark(1, "art", 1, "Art. 1º", "1"),
        _mark(2, "alteracao", 1, '"Art. 75 - ....', le=2),
        _mark(2, "art", 2, "Art. 75 -", "75"),
        _mark(3, "art", 1, "Art. 2º", "2"),
    ]
    conv = tm.convert_response(text, marks)
    _check(conv.xml, text)
    block = conv.anchors[1]
    assert block["used"] == "A" and block["offset"] == text.index('"Art. 75')
    assert block["b_col"] == 1  # the tolerant match no longer lands on column 2


# --- ends, nesting, blocks -------------------------------------------------------
def test_ends_are_derived_from_the_next_sibling_or_ancestor() -> None:
    conv = tm.convert_response(TEXT, _base())
    rows = _rows(_check(conv.xml, TEXT))
    assert TEXT[rows["art-1"]["start"] : rows["art-1"]["end"]].endswith("Parágrafo.")
    assert rows["art-1-inc-1"]["end"] == TEXT.index("II -") - 1  # trailing blank
    assert rows["art-1-inc-2"]["end"] == TEXT.index("§ 1º") - 1
    assert rows["art-1-par-1"]["end"] == rows["art-1"]["end"]
    assert rows["art-2"]["end"] == len(TEXT)
    # inciso under the article, paragraph a sibling: inc nests in art, not in par
    assert rows["art-1-par-1"]["parent_path"] == "art-1"


def test_block_kind_with_end_line_and_tail_outside_the_lei() -> None:
    text = (
        "LEI Nº 5\nDispõe sobre isso\ne aquilo.\nArt. 1º Texto.\n"
        "Porto Velho, 1985.\nJOÃO\nGovernador"
    )
    marks = [
        _mark(1, "epigrafe", 1, "LEI Nº 5", le=1),
        _mark(2, "ementa", 1, "Dispõe sobre", le=3),
        _mark(4, "art", 1, "Art. 1º", "1"),
        _mark(5, "fecho", 1, "Porto Velho", le=5),
        _mark(6, "assinatura", 1, "JOÃO", le=7),
    ]
    conv = tm.convert_response(text, marks, tipo="lei", numero=5)
    xml = _check(conv.xml, text)
    assert "<ementa>Dispõe sobre isso\ne aquilo.</ementa>" in xml
    assert xml.index("</lei>") < xml.index("<fecho>")
    assert '<art n="1"><m>Art. 1º</m> Texto.</art></lei>' in xml
    _, parsed = M.parse(xml)
    lei = next(m for m in parsed if m.kind == "lei")
    assert text[lei.end - 5 : lei.end] == "exto."


def test_alteracao_nests_quoted_devices_and_the_own_one_follows() -> None:
    text = (
        "Art. 1º O art. 5º passa a vigorar assim:\n"  # 1
        '"Art. 5º Fica proibido.\n'  # 2
        'Parágrafo único - Multa." (NR)\n'  # 3
        "Art. 2º Esta Lei vale.\n"  # 4
        "Art. 3º Revogam-se."
    )
    marks = [
        _mark(1, "art", 1, "Art. 1º", "1"),
        _mark(2, "alteracao", 1, '"Art. 5º Fica', le=3),
        _mark(2, "art", 2, "Art. 5º", "5"),
        _mark(3, "par", 1, "Parágrafo único", "unico"),
        _mark(4, "art", 1, "Art. 2º", "2"),
        _mark(5, "art", 1, "Art. 3º", "3"),
    ]
    conv = tm.convert_response(text, marks)
    xml = _check(conv.xml, text)
    assert conv.problems == []
    rows = M.to_rows(xml)
    quoted = [r["path"] for r in rows if r["quoted"]]
    own = [r["path"] for r in rows if not r["quoted"]]
    assert quoted == ["art-5", "art-5-par-unico"]
    assert own == ["art-1", "art-2", "art-3"]
    # the quote sits under art 1, and art 1 ends where art 2 starts
    assert "<alteracao>" in xml and xml.index("<alteracao>") < xml.index("</art>")
    a1 = next(r for r in rows if r["path"] == "art-1")
    assert a1["end"] == text.index("Art. 2º") - 1


def test_device_without_a_readable_marker_has_no_m() -> None:
    text = "Art. 1º Um.\nEsta Lei entra em vigor."
    marks = [
        _mark(1, "art", 1, "Art. 1º", "1"),
        _mark(2, "art", 1, "Esta Lei entra", "2", x=True, nota="marcador perdido"),
    ]
    conv = tm.convert_response(text, marks)
    xml = _check(conv.xml, text)
    assert (
        '<art n="2"><nota por="modelo" tipo="teacher-mark">marcador perdido</nota>Esta'
        in xml
    )
    row = _rows(xml)["art-2"]
    assert row["marker"] == "" and row["start"] == text.index("Esta Lei")


def test_nesting_conflict_drops_one_mark_and_still_builds() -> None:
    # a ruido that crosses the start of article 2: the ruido is dropped, the articles stay
    marks = _base() + [_mark(4, "ruido", 1, "§ 1º Parág", le=5)]
    conv = tm.convert_response(TEXT, marks)
    _check(conv.xml, TEXT)
    assert [p["reason"] for p in conv.problems] == ["conflict"]
    assert conv.problems[0]["kind"] == "ruido"
    assert len(_rows(conv.xml or "")) == 5
    assert [a["drop_reason"] for a in conv.anchors].count("conflict") == 1


def test_a_device_that_cannot_nest_is_dropped_not_the_norm() -> None:
    text = "I - solto\nArt. 1º Corpo.\n"
    marks = [_mark(1, "inc", 1, "I -", "1"), _mark(2, "art", 1, "Art. 1º", "1")]
    conv = tm.convert_response(text, marks)
    _check(conv.xml, text)
    assert [p["kind"] for p in conv.problems] == ["inc"]
    assert list(_rows(conv.xml or "")) == ["art-1"]


def test_bad_numbers_shapes_and_duplicates_are_dropped_with_reasons() -> None:
    marks = _base() + [
        _mark(5, "art", 1, "Art. 2º", "2"),  # same kind and start
        _mark(1, "art", 1, "Art. 1º", "XX"),  # same start as the first (dup first)
        {**_mark(1, "art", 1, "x"), "k": "nope"},
        {"l": 1, "k": "art"},
        _mark(2, "par", 1, "I -", "zz"),
        "garbage",
    ]
    conv = tm.convert_response(TEXT, marks)
    _check(conv.xml, TEXT)
    reasons = {p["reason"] for p in conv.problems}
    assert {"duplicate", "bad_shape", "bad_kind"} <= reasons
    assert len(_rows(conv.xml or "")) == 5


def test_roman_and_unico_numbers_are_interpreted() -> None:
    text = "Art. 1º A.\nIII - tres\n§ único - p\n"
    marks = [
        _mark(1, "art", 1, "Art. 1º", "1"),
        _mark(2, "inc", 1, "III -", "III"),
        _mark(3, "par", 1, "§ único", "único"),
    ]
    conv = tm.convert_response(text, marks)
    rows = _rows(_check(conv.xml, text))
    assert "art-1-inc-3" in rows and "art-1-par-unico" in rows


def test_hostile_text_keeps_the_strip_invariant() -> None:
    text = "Art. 1º a < b & c > d\x0c\r\nArt. 2º \x00 fim"
    marks = [_mark(1, "art", 1, "Art. 1º", "1"), _mark(2, "art", 1, "Art. 2º", "2")]
    conv = tm.convert_response(text, marks)
    _check(conv.xml, text)


def test_marks_from_response_returns_marks_and_problems() -> None:
    marks, problems = tm.marks_from_response(TEXT, {"id": "N01", "marks": _base()})
    assert marks[0].kind == "lei" and problems == []
    assert [m.kind for m in marks].count("art") == 2


def test_owned_lines_limit_where_a_mark_may_start() -> None:
    conv = tm.convert_response(TEXT, _base(), owned={1, 2, 3})
    reasons = [p["reason"] for p in conv.problems]
    assert reasons == ["line_not_owned", "line_not_owned"]


# --- the prompt and the schema ---------------------------------------------------
def test_the_example_in_the_prompt_round_trips_with_agreeing_anchors() -> None:
    text = "\n".join(tm.EXAMPLE_LINES.get(i, "") for i in range(1, 22))
    entry = tm.example_response()["norms"][0]
    conv = tm.convert_response(text, entry, tipo="lei", numero=7)
    _check(conv.xml, text)
    assert conv.problems == []
    assert all(a["agree"] is True for a in conv.anchors)
    # the example is not only column 1/2: one genuine mid-line marker
    assert any(m["c"] > 2 for m in entry["marks"])
    assert tm.example_json() in tm.MARK_SYSTEM_PROMPT
    assert tm.example_listing() in tm.MARK_SYSTEM_PROMPT


def test_schema_fields_and_versions() -> None:
    item = tm.MARK_SCHEMA["properties"]["norms"]["items"]["properties"]["marks"][
        "items"
    ]
    assert list(item["properties"]) == list(tm.MARK_FIELDS)
    assert item["required"] == list(tm.MARK_FIELDS)
    assert item["additionalProperties"] is False
    assert set(item["properties"]["k"]["enum"]) == set(tm.MARK_KINDS)
    assert tm.MARK_PROMPT_VERSION == "teacher-mark-v2"
    assert len(tm.mark_prompt_sha256()) == 64
    # every kind the converter builds is one the grammar knows
    assert set(tm.MARK_KINDS) <= set(M.KINDS)


SMALL_TEXTS = [
    (
        "LEI Nº 1\n\nDispõe sobre a coisa.\n\nArt. 1º - A coisa será gerida.\n"
        "I - pela Secretaria;\nII - pelo Conselho.\n§ 1º - Prazo de 30 dias.\n"
        "Art. 2º - Esta Lei entra em vigor.\n\nPorto Velho, 1985.\n"
    ),
    (
        "LEI Nº 2\nDispõe.\nArt. 1º - O art. 5º da Lei nº 100 passa a vigorar assim:\n"
        '"Art. 5º - Fica proibido o fogo.\n§ 1º - Exceção:\nI - pequena propriedade."\n'
        "Art. 2º - Revogam-se as disposições em contrário.\n"
    ),
    (
        "LEI Nº 3\nDispõe.\nArt. 1º - Fica criado.\na) um;\nb) dois.\n"
        "Art. 2º - Esta Lei entra em vigor na data de sua publicação.\n"
    ),
]


@pytest.mark.parametrize("text", SMALL_TEXTS)
def test_round_trip_reader_to_response_to_converter(text: str) -> None:
    """Reader marks -> response format -> converter -> the same device structure."""
    reader_marks = M.from_hierarchy(text, read_hierarchy(text), tipo="lei", numero=1)
    reader_xml = M.build(text, reader_marks)
    response = tm.response_from_marks(text, reader_marks)
    conv = tm.convert_response(text, response, tipo="lei", numero=1)
    xml = _check(conv.xml, text)
    assert conv.problems == []

    def shape(x: str) -> List[Any]:
        return [
            (r["path"], r["kind"], r["quoted"], r["start"], r["end"], r["marker"])
            for r in M.to_rows(x)
        ]

    assert shape(xml) == shape(reader_xml)
    assert all(a["agree"] is True for a in conv.anchors)


# --- plan, collect, score ---------------------------------------------------------
def _record(numero: int, text: str) -> tb.TextoRecord:
    uuid5 = f"{numero:08x}"
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


def _long_text(n_articles: int) -> str:
    lines = ["LEI Nº 9", "Dispõe sobre a coisa."]
    for n in range(1, n_articles + 1):
        lines.append(f"Art. {n}º - A Secretaria regulamentará a matéria {n}.")
        lines.append(f"I - item {n};")
    lines.append("Porto Velho, 1985.")
    return "\n".join(lines)


def _plan(texts: List[str], **kwargs: Any) -> tm.MarkPlan:
    return tm.build_mark_plan(
        [_record(i + 1, t) for i, t in enumerate(texts)], seed="s", **kwargs
    )


def _manifest(plan: tm.MarkPlan) -> Dict[str, Any]:
    spec = tb.resolve_model("claude-haiku-5-5")
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
            "id": "msgbatch_x",
            "created_at": "now",
            "request_count": len(plan.requests),
            "custom_ids": [r.custom_id for r in plan.requests],
        }
    )
    return manifest


def test_plan_packs_small_norms_and_chunks_long_ones() -> None:
    plan = _plan([*SMALL_TEXTS, _long_text(120)], budget_chars=4000, max_norms=3)
    sizes = sorted(len(r.slots) for r in plan.requests)
    assert plan.requests and max(sizes) <= 3
    long_norm = plan.norms[-1]
    assert len(long_norm.chunks) > 1
    solo = [r for r in plan.requests if any(s.chunk.total > 1 for s in r.slots)]
    assert all(len(r.slots) == 1 for r in solo)
    # each norm's lines are marked exactly once across its parts
    owned = [n for c in long_norm.chunks for n in c.owned]
    assert owned == sorted(set(owned))
    user = plan.requests[0].user_text
    assert user.startswith("Requisição com") and "### fim N01" in user
    assert "<norma" not in user and "[art" not in user  # no reader tags


def test_ceiling_is_the_sum_of_max_tokens_and_the_estimate_is_below_it() -> None:
    plan = _plan(SMALL_TEXTS)
    spec = tb.resolve_model("claude-haiku-5-5")
    est = tm.estimate_mark_cost(plan, spec, "medium", True)
    assert est.ceiling_output_tokens == sum(r.max_tokens for r in plan.requests)
    assert est.estimate_usd <= est.ceiling_usd
    assert all(r.max_tokens <= tm.MARK_MAX_TOKENS_CAP for r in plan.requests)
    with pytest.raises(tb.TeacherBatchError):
        tb.check_cost_guard(est, spec, 0.0000001, "ceiling")


class _Fake:
    def __init__(self, entries: List[Dict[str, Any]]) -> None:
        self.messages = simulate_mark._Messages(entries)


def _entry(cid: str, norms: Any, stop: str = "end_turn") -> Dict[str, Any]:
    body = json.dumps({"norms": norms}, ensure_ascii=False)
    return {
        "custom_id": cid,
        "result": {
            "type": "succeeded",
            "message": {
                "stop_reason": stop,
                "usage": {"input_tokens": 1000, "output_tokens": 500},
                "content": [{"type": "text", "text": body}]
                if norms is not None
                else [],
            },
        },
    }


def _perfect(plan: tm.MarkPlan) -> List[Dict[str, Any]]:
    entries, _ = simulate_mark.simulate(plan, seed="s", shift_rate=0, accent_rate=0)
    return entries


def test_collect_builds_one_document_per_norm_and_the_anchor_table(
    tmp_path: Path,
) -> None:
    plan = _plan(SMALL_TEXTS)
    manifest = _manifest(plan)
    summary = tm.collect_mark(_Fake(_perfect(plan)), manifest, tmp_path)
    assert summary["states"]["ok"] == 3 and summary["norms_failed"] == 0
    docs = sorted((tmp_path / "marked").rglob("*.xml"))
    assert len(docs) == 3
    for path in docs:
        xml = path.read_text(encoding="utf-8")
        text = M.strip(xml)
        assert M.verify(xml, text) == []
        assert _sha(text) in {n.text_sha256 for n in plan.norms}
    rows = score_mark.load_anchors(tmp_path / "anchors.jsonl")
    assert len(rows) == summary["marks_answered"] == summary["marks_used"]
    assert (tmp_path / "failures.jsonl").read_text() == ""
    assert summary["measured_usd"] > 0
    manifest_out = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest_out["truncated_requests"] == []


def test_collect_states_truncated_invalid_partial_and_degraded(tmp_path: Path) -> None:
    plan = _plan([SMALL_TEXTS[0], SMALL_TEXTS[1], _long_text(120)], max_lines=60)
    manifest = _manifest(plan)
    entries = _perfect(plan)
    by_cid = {e["custom_id"]: e for e in entries}
    small0, small1, long_norm = (n.ref.key for n in plan.norms)
    # find the requests of each norm
    where: Dict[str, List[str]] = {}
    for r in plan.requests:
        for s in r.slots:
            where.setdefault(s.norm.ref.key, []).append(r.custom_id)
    assert len(where[long_norm]) >= 2
    # long norm: first part truncated, rest valid -> partial
    cut = by_cid[where[long_norm][0]]
    cut["result"]["message"]["stop_reason"] = "max_tokens"
    cut["result"]["message"]["content"] = []
    inv = by_cid[where[small1][0]]
    # small0: add a mark that cannot nest -> degraded
    ok = by_cid[where[small0][0]]
    body0 = json.loads(ok["result"]["message"]["content"][0]["text"])
    slot_small0 = next(
        s for r in plan.requests for s in r.slots if s.norm.ref.key == small0
    )
    for entry in body0["norms"]:
        if entry["id"] == slot_small0.rid:
            entry["marks"].append(_mark(8, "inc", 1, "pela Secretaria", "9"))
    ok["result"]["message"]["content"][0]["text"] = json.dumps(body0)
    # small1: drop its id from the answer -> invalid (silence is not approval)
    slot_small1 = next(
        s for r in plan.requests for s in r.slots if s.norm.ref.key == small1
    )
    body1 = json.loads(inv["result"]["message"]["content"][0]["text"])
    body1["norms"] = [e for e in body1["norms"] if e["id"] != slot_small1.rid]
    inv["result"]["message"]["content"][0]["text"] = json.dumps(body1)
    summary = tm.collect_mark(_Fake(entries), manifest, tmp_path)
    records = {r["key"]: r for r in score_mark.load_records(tmp_path)}
    assert records[long_norm]["state"] == "partial"
    assert records[long_norm]["missing_parts"][0]["status"] == "truncated"
    assert records[small1]["state"] == "invalid"
    assert records[small0]["state"] in ("ok", "degraded")
    assert summary["requests_truncated"] == 1
    manifest_out = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest_out["truncated_requests"] == [where[long_norm][0]]


def test_a_fully_truncated_norm_is_truncated_and_retryable(tmp_path: Path) -> None:
    plan = _plan([SMALL_TEXTS[0]])
    manifest = _manifest(plan)
    cid = plan.requests[0].custom_id
    cut = {
        "custom_id": cid,
        "result": {
            "type": "succeeded",
            "message": {
                "stop_reason": "max_tokens",
                "usage": {"input_tokens": 10, "output_tokens": 99},
                "content": [],
            },
        },
    }
    summary = tm.collect_mark(_Fake([cut]), manifest, tmp_path)
    assert summary["states"]["truncated"] == 1
    base = json.loads((tmp_path / "manifest.json").read_text())
    retry = tm.build_retry_plan(plan, base, depth=1, max_tokens_cap=32_000)
    assert len(retry.requests) == 1
    assert retry.requests[0].max_tokens >= plan.requests[0].max_tokens
    assert retry.requests[0].custom_id == "t1-00000"
    # the retry's answer replaces the truncated request in the merge
    retry_manifest = _manifest(retry)
    retry_manifest["batches"] = [
        {
            "id": "msgbatch_retry",
            "created_at": "now",
            "request_count": 1,
            "custom_ids": ["t1-00000"],
        }
    ]
    from leizilla import teacher_review as tr

    tr.attach_retry(retry_manifest, base, depth=1, plan=retry)  # type: ignore[arg-type]
    answer = _perfect(retry)
    out = tmp_path / "second"
    summary2 = tm.collect_mark(_Fake(answer), retry_manifest, out)
    assert summary2["states"]["ok"] == 1 and summary2["requests_truncated"] == 0


def test_a_changed_text_refuses_the_retry() -> None:
    plan = _plan([SMALL_TEXTS[0]])
    base = {
        "truncated_requests": ["m00000"],
        "requests": {
            "m00000": {
                "slots": {
                    "N01": {
                        "entry": plan.norms[0].ref.key,
                        "chunk": 0,
                        "text_sha256": "0" * 64,
                    }
                }
            }
        },
    }
    with pytest.raises(tb.TeacherBatchError, match="text changed"):
        tm.build_retry_plan(plan, base, depth=1, max_tokens_cap=32_000)


def test_score_script_on_a_synthetic_collected_set(tmp_path: Path) -> None:
    """Inject a known error rate and check that the score recovers it."""
    texts = [_long_text(30), *SMALL_TEXTS, _long_text(25)]
    plan = _plan(texts)
    entries, injected = simulate_mark.simulate(
        plan, seed="7", shift_rate=0.10, accent_rate=0.05
    )
    out = tmp_path / "collect"
    summary = tm.collect_mark(_Fake(entries), _manifest(plan), out)
    result = score_mark.run(out, tmp_path / "score")
    assert (tmp_path / "score" / "score_mark.md").is_file()
    ca = result["column_accuracy"]
    total = injected["marks"]
    assert ca["marks_answered"] == total == summary["marks_answered"]
    # A shifted by one on 10%: the exact rate is 1 - shifted/reference
    expect = 1 - injected["shifted_by_1"] / ca["reference_n"]
    assert ca["a_exact_rate"] == pytest.approx(expect, abs=1e-3)
    assert (
        sum(ca["delta_distribution"][k] for k in ("-1", "+1"))
        == injected["shifted_by_1"]
    )
    # dropped accent: those marks resolve tolerant, and only those
    assert ca["b_methods"].get("tolerant", 0) == injected["accent_dropped"]
    # the shift is a constant: correcting the most common error delta gives 100%
    assert ca["systematic"]["accuracy_if_that_delta_is_corrected"] == 1.0
    assert ca["check_4_chars"]["wrong_a_detection_rate"] == 1.0
    assert result["reader_reference"]["b_exact_rate"] == 1.0
    assert result["outcomes"]["states"] == {"ok": 5}
    agree = result["agreement_with_reader"]
    assert agree["art/own"]["only_model"] == 0 == agree["art/own"]["only_reader"]
    assert result["coverage"]["model_kinds"]["art"] > 0
    assert ca["token_cost"]["t_tokens"] > ca["token_cost"]["c_tokens"]


def test_coverage_counts_unowned_text_and_ruido() -> None:
    text = "HEADER\nArt. 1º Um.\nsolto aqui\nArt. 2º Dois.\n"
    marks = [
        _mark(1, "ruido", 1, "HEADER", le=1),
        _mark(2, "art", 1, "Art. 1º", "1"),
        _mark(4, "art", 1, "Art. 2º", "2"),
    ]
    conv = tm.convert_response(text, marks)
    cov = score_mark.coverage(_check(conv.xml, text))
    assert cov["kinds"]["ruido"] == 1 and cov["has_lei"]
    assert cov["ruido_share"] == pytest.approx(
        6 / len(text.replace("\n", "").replace(" ", "")), abs=1e-3
    )
    assert cov["unowned_share"] == 0.0  # art 1 swallows "solto aqui" up to art 2


# --- CLI glue -----------------------------------------------------------------------
def test_cli_mode_mark_refuses_canary_options() -> None:
    result = CliRunner().invoke(
        tb.app,
        ["plan", "--mode", "mark", "--canary-share", "0.2", "--text-source", "textos"],
    )
    assert result.exit_code == 2
    assert "do not apply with --mode mark" in result.output


def test_label_set_main_is_refused_in_mark_mode() -> None:
    assert tm.check_mark_label_set(None) == "mark"
    with pytest.raises(tb.TeacherBatchError):
        tm.check_mark_label_set("main")


def test_pilot_sample_file_is_valid() -> None:
    from leizilla import teacher_review as tr

    ids = tr.read_ids_file(ROOT / "docs/okf/review-samples/mark-pilot-2026-11.txt")
    assert len(ids) == 60 and len(set(ids)) == 60


def test_a_norm_with_a_dropped_mark_is_degraded_and_the_reason_is_recorded(
    tmp_path: Path,
) -> None:
    plan = _plan([SMALL_TEXTS[2]])
    entries = _perfect(plan)
    body = json.loads(entries[0]["result"]["message"]["content"][0]["text"])
    body["norms"][0]["marks"].append(_mark(999, "art", 1, "Art. 9º", "9"))
    entries[0]["result"]["message"]["content"][0]["text"] = json.dumps(body)
    summary = tm.collect_mark(_Fake(entries), _manifest(plan), tmp_path)
    assert summary["states"]["degraded"] == 1 and summary["norms_failed"] == 0
    assert summary["dropped_by_reason"] == {"bad_line": 1}
    record = score_mark.load_records(tmp_path)[0]
    assert record["dropped"][0]["reason"] == "bad_line"
    assert summary["marks_dropped"] == 1


def test_workflow_offers_the_mark_mode_and_keeps_the_auth_part() -> None:
    import yaml

    path = ROOT / ".github/workflows/teacher-batch.yml"
    text = path.read_text(encoding="utf-8")
    wf = yaml.safe_load(text)
    assert wf[True]["workflow_dispatch"]["inputs"]["mode"]["options"] == [
        "label",
        "review",
        "mark",
    ]
    assert text.count("scripts/anthropic_wif.py run -- -m leizilla.teacher_batch") == 3
    assert wf["permissions"]["id-token"] == "write"
    for artifact in ("out/marked", "out/records", "out/anchors.jsonl"):
        assert artifact in text
    assert '--mode "$IN_MODE"' in text


# --- several acts, tails and annexes between devices (teacher-mark-v2) ------------
def _leis(xml: str) -> List[M.Mark]:
    return [m for m in M.parse(xml)[1] if m.kind == "lei"]


def test_annex_and_signature_between_articles_do_not_close_the_lei() -> None:
    text = (
        "LEI Nº 9\nDispõe.\n"  # 1-2
        "Art. 1º Um.\n"  # 3
        "QUADRO I\nlinha a\nlinha b\n"  # 4-6
        "Art. 2º Dois.\n"  # 7
        "Porto Velho, 1985.\nJOÃO\n"  # 8-9
        "Art. 3º Três.\n"  # 10
        "ANEXO II\ntabela\n"  # 11-12
    )
    marks = [
        _mark(1, "epigrafe", 1, "LEI Nº 9", le=1),
        _mark(2, "ementa", 1, "Dispõe", le=2),
        _mark(3, "art", 1, "Art. 1º", "1"),
        _mark(4, "anexo", 1, "QUADRO I", le=4),  # le too early: ends at art 2
        _mark(7, "art", 1, "Art. 2º", "2"),
        _mark(8, "fecho", 1, "Porto Velho", le=8),
        _mark(9, "assinatura", 1, "JOÃO", le=9),
        _mark(10, "art", 1, "Art. 3º", "3"),
        _mark(11, "anexo", 1, "ANEXO II", le=11),
    ]
    conv = tm.convert_response(text, marks, tipo="lei", numero=9)
    xml = _check(conv.xml, text)
    assert conv.problems == [] and conv.suspects == []
    assert [r["path"] for r in M.to_rows(xml) if not r["quoted"]] == [
        "art-1",
        "art-2",
        "art-3",
    ]
    (lei,) = _leis(xml)
    assert text[lei.end - 5 : lei.end] == "Três."  # ends after the last device
    _, parsed = M.parse(xml)
    first = next(m for m in parsed if m.kind == "anexo")
    assert text[first.start : first.end] == "QUADRO I\nlinha a\nlinha b"
    last = [m for m in parsed if m.kind == "anexo"][-1]
    assert last.start >= lei.end and text[last.start : last.end].endswith("tabela")


def test_annex_between_paragraphs_of_an_article_stays_inside_it() -> None:
    text = "Art. 1º Caput:\n§ 1º Um.\nQUADRO\nx y z\n§ 2º Dois.\nArt. 2º Fim."
    marks = [
        _mark(1, "art", 1, "Art. 1º", "1"),
        _mark(2, "par", 1, "§ 1º", "1"),
        _mark(3, "anexo", 1, "QUADRO", le=3),
        _mark(5, "par", 1, "§ 2º", "2"),
        _mark(6, "art", 1, "Art. 2º", "2"),
    ]
    conv = tm.convert_response(text, marks)
    xml = _check(conv.xml, text)
    assert conv.problems == []
    assert "<anexo>QUADRO\nx y z</anexo>" in xml
    rows = _rows(xml)
    assert {"art-1-par-1", "art-1-par-2", "art-2"} <= set(rows)
    assert rows["art-1-par-2"]["parent_path"] == "art-1"


def test_a_law_followed_by_copies_of_the_bill_is_one_lei_per_act() -> None:
    text = (
        "LEI Nº 1\nDispõe.\nArt. 1º Um.\nArt. 2º Dois.\n"  # 1-4
        "Porto Velho, 1985.\nJOÃO\n"  # 5-6
        "PROJETO DE LEI\nDispõe.\nArt. 1º Um.\nArt. 2º Dois.\n"  # 7-10
        "Porto Velho, 1985.\nJOÃO\n"  # 11-12
        "Art. 1º Um.\nArt. 2º Dois.\n"  # 13-14 restart, no front matter
    )
    marks = [
        _mark(1, "epigrafe", 1, "LEI Nº 1", le=1),
        _mark(2, "ementa", 1, "Dispõe", le=2),
        _mark(3, "art", 1, "Art. 1º", "1"),
        _mark(4, "art", 1, "Art. 2º", "2"),
        _mark(5, "fecho", 1, "Porto Velho", le=5),
        _mark(6, "assinatura", 1, "JOÃO", le=6),
        _mark(7, "epigrafe", 1, "PROJETO DE LEI", le=7),
        _mark(8, "ementa", 1, "Dispõe", le=8),
        _mark(9, "art", 1, "Art. 1º", "1"),
        _mark(10, "art", 1, "Art. 2º", "2"),
        _mark(11, "fecho", 1, "Porto Velho", le=11),
        _mark(12, "assinatura", 1, "JOÃO", le=12),
        _mark(13, "art", 1, "Art. 1º", "1"),
        _mark(14, "art", 1, "Art. 2º", "2"),
    ]
    conv = tm.convert_response(text, marks, tipo="lei", numero=1)
    xml = _check(conv.xml, text)
    assert conv.problems == [] and conv.suspects == []
    leis = _leis(xml)
    assert len(leis) == 3
    starts = [text.index("LEI Nº 1"), text.index("PROJETO"), text.rindex("Art. 1º")]
    assert [m.start for m in leis] == starts
    assert text[leis[0].end - 5 : leis[0].end] == "Dois."
    # the fecho/assinatura between the acts sit outside every lei
    assert all(text[m.end - 5 : m.end] == "Dois." for m in leis)


def test_numbers_going_back_flag_the_alteracao_before_them() -> None:
    text = (
        "Art. 1º Um.\n"  # 1
        "Art. 2º Muda:\n"  # 2
        '"Art. 9º Nove.\n'  # 3
        "Art. 10 Dez.\n"  # 4  (really quoted, the block was cut short)
        "Art. 3º Três.\n"  # 5
        "Art. 4º Quatro.\n"  # 6
    )
    marks = [
        _mark(1, "art", 1, "Art. 1º", "1"),
        _mark(2, "art", 1, "Art. 2º", "2"),
        _mark(3, "alteracao", 1, '"Art. 9º', le=3),  # no closing quote on its line
        _mark(3, "art", 2, "Art. 9º", "9"),
        _mark(4, "art", 1, "Art. 10", "10"),
        _mark(5, "art", 1, "Art. 3º", "3"),
        _mark(6, "art", 1, "Art. 4º", "4"),
    ]
    conv = tm.convert_response(text, marks)
    _check(conv.xml, text)
    assert [x["type"] for x in conv.suspects] == ["suspect_alteracao"]
    flag = conv.suspects[0]
    assert flag["line"] == 3 and flag["closing_quote"] is False and flag["n"] == 3


def test_a_clean_alteracao_and_sequence_flag_nothing() -> None:
    text = (
        "Art. 1º Muda:\n"
        '"Art. 9º Nove." (NR)\n'
        "Art. 2º Dois.\n"
        "Art. 3º Três.\n"
        "Art. 3º-A Três A.\n"
        "Art. 4º Quatro.\n"
    )
    marks = [
        _mark(1, "art", 1, "Art. 1º", "1"),
        _mark(2, "alteracao", 1, '"Art. 9º', le=2),
        _mark(2, "art", 2, "Art. 9º", "9"),
        _mark(3, "art", 1, "Art. 2º", "2"),
        _mark(4, "art", 1, "Art. 3º", "3"),
        _mark(5, "art", 1, "Art. 3º-A", "3", s="A"),
        _mark(6, "art", 1, "Art. 4º", "4"),
    ]
    conv = tm.convert_response(text, marks)
    _check(conv.xml, text)
    assert conv.suspects == []


def test_an_ordinal_read_as_a_digit_is_flagged_not_repaired() -> None:
    text = "".join(f"Art. {n} Texto.\n" for n in (8, 92, 102, 11))
    marks = [
        _mark(1, "art", 1, "Art. 8", "8"),
        _mark(2, "art", 1, "Art. 92", "92"),
        _mark(3, "art", 1, "Art. 102", "102"),
        _mark(4, "art", 1, "Art. 11", "11"),
    ]
    conv = tm.convert_response(text, marks)
    xml = _check(conv.xml, text)
    flags = [(x["type"], x["n"], x["previous"]) for x in conv.suspects]
    assert flags == [("suspect_number", 92, 8), ("suspect_number", 102, 9)]
    assert 'n="92"' in xml  # kept as the model gave it


# --- the stress variant (re-flowed lines) -----------------------------------------
def test_reflow_keeps_the_length_and_is_reversible_and_deterministic() -> None:
    text = _long_text(40)
    flowed, joined = tm.reflow_text(text, "k")
    assert len(flowed) == len(text) and flowed != text
    assert tm.unflow_text(flowed, joined) == text
    assert tm.reflow_text(text, "k") == (flowed, joined)
    assert tm.reflow_text(text, "other")[0] != flowed
    # only newlines changed, only into spaces
    assert {(a, b) for a, b in zip(text, flowed) if a != b} == {("\n", " ")}
    lengths = [len(line) for line in flowed.split("\n")]
    assert max(lengths) <= tm.REFLOW_MAX_CHARS and len(lengths) < 20
    assert tm.reflow_text("", "k") == ("", [])


def test_reflow_variant_has_its_own_identity_and_the_base_expected_marks() -> None:
    record = _record(5, _long_text(30))
    variant, meta = tm.reflow_record(record)
    assert variant.texto_id == str(record.texto_id) + "~reflow"
    assert variant.ref.key != record.ref.key and variant.ref.uuid5.endswith("-reflow")
    assert variant.text_sha256 == _sha(variant.text) != record.text_sha256
    assert meta["base_text_sha256"] == record.text_sha256 and meta["synthetic"]
    plan = tm.build_mark_plan([variant], seed="s", reflows={variant.ref.key: meta})
    norm = plan.norms[0]
    base = tm.make_norm(record)
    assert norm.expected_marks == base.expected_marks and norm.reflow == meta
    # the ceiling counts marks, not the (few) long lines
    ceiling = plan.requests[0].max_tokens
    assert ceiling > tm.mark_max_tokens([tm.MarkSlot(norm=base, chunk=norm.chunks[0])])


def test_reflow_budget_shares_the_expected_marks_over_non_blank_lines() -> None:
    # OCR texts put a blank line between text lines; the stress run (2026-11-17)
    # divided by every line, blanks included, and granted about half the marks.
    base = _long_text(30).replace("\n", "\n\n")
    record = _record(6, base)
    variant, meta = tm.reflow_record(record)
    plan = tm.build_mark_plan([variant], seed="s", reflows={variant.ref.key: meta})
    (norm,) = plan.norms
    nonblank = sum(1 for line in norm.lines if line.strip())
    assert len(norm.lines) > nonblank  # the blanks are still there
    (slot,) = plan.requests[0].slots
    assert len(slot.chunk.owned) == nonblank  # unchunked: the whole norm
    assert tm._slot_marks(slot) == int(norm.expected_marks * 1.5)
    # a part gets its proportional share of the non-blank lines, not of all lines
    assert tm._share_marks(norm, 2) == norm.expected_marks * 2 // nonblank


def test_ids_file_with_the_reflow_suffix_selects_the_variant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _record(7, _long_text(12))
    corpus = tb.TextosCorpus(file_sha256="f" * 64, records=[record])
    monkeypatch.setattr(tb, "_load_textos_corpus", lambda path: corpus)
    ids = tmp_path / "ids.txt"
    ids.write_text(f"{record.texto_id}~reflow\n", encoding="utf-8")
    plan = tm.prepare_mark(
        ente="ro",
        tipo=None,
        limit=None,
        shuffle_seed="s",
        text_source="textos",
        textos=None,
        select="ids-file",
        ids_file=ids,
        budget_chars=tm.DEFAULT_MARK_BUDGET_CHARS,
        max_norms=4,
        max_lines=tm.MARK_MAX_LINES,
        max_chars=tm.MARK_MAX_CHARS,
        max_tokens_cap=tm.MARK_MAX_TOKENS_CAP,
    )
    (norm,) = plan.norms
    assert norm.texto_id.endswith("~reflow") and norm.reflow
    assert tm.unflow_text(norm.text, norm.reflow["joined"]) == record.text
    # the base id and the variant id may both be asked for
    ids.write_text(f"{record.texto_id}\n{record.texto_id}~reflow\n", encoding="utf-8")
    plan = tm.prepare_mark(
        ente="ro",
        tipo=None,
        limit=None,
        shuffle_seed="s",
        text_source="textos",
        textos=None,
        select="ids-file",
        ids_file=ids,
        budget_chars=tm.DEFAULT_MARK_BUDGET_CHARS,
        max_norms=4,
        max_lines=tm.MARK_MAX_LINES,
        max_chars=tm.MARK_MAX_CHARS,
        max_tokens_cap=tm.MARK_MAX_TOKENS_CAP,
    )
    assert sorted(n.texto_id for n in plan.norms) == [
        str(record.texto_id),
        str(record.texto_id) + "~reflow",
    ]


def test_stress_score_reports_column_accuracy_by_bucket(tmp_path: Path) -> None:
    base = _record(3, _long_text(40))
    variant, meta = tm.reflow_record(base)
    plan = tm.build_mark_plan([variant], seed="s", reflows={variant.ref.key: meta})
    entries, _ = simulate_mark.simulate(plan, seed="1", shift_rate=0, accent_rate=0)
    out = tmp_path / "collect"
    summary = tm.collect_mark(_Fake(entries), _manifest(plan), out)
    assert summary["states"]["ok"] == 1
    record = json.loads(next((out / "records").rglob("*.json")).read_text("utf-8"))
    assert record["reflow"]["base_texto_id"] == base.texto_id
    result = score_mark.run(out, tmp_path / "score")
    stress = result["stress"]
    assert stress["devices_matched_to_reader"] >= 40
    assert stress["a_exact_rate"] == 1.0 and stress["used_offset_exact_rate"] == 1.0
    assert set(stress["by_true_column"]) - {"0-10"}  # markers well past column 10
    assert (tmp_path / "score" / "score_mark.md").read_text().count("Stress set") == 1


def test_a_dropped_article_is_not_a_closed_chain() -> None:
    xml_rows = [
        {"kind": "art", "n": "1", "quoted": False, "start": 0},
        {"kind": "art", "n": "2", "quoted": False, "start": 10},
    ]
    text = "Art. 1º a\nArt. 2º b"
    assert score_mark.model_closes(xml_rows, text)
    # per act: a restart after the first act is a closed chain in each
    rows = xml_rows + [
        {"kind": "art", "n": "1", "quoted": False, "start": 20},
        {"kind": "art", "n": "2", "quoted": False, "start": 30},
    ]
    long_text = text + "\nArt. 1º c\nArt. 2º d"
    assert not score_mark.model_closes(rows, long_text)
    assert score_mark.model_closes(rows, long_text, [(0, 19), (20, 40)])


def test_stress_sample_file_is_valid_and_points_at_pilot_norms() -> None:
    from leizilla import teacher_review as tr

    stress = tr.read_ids_file(
        ROOT / "docs/okf/review-samples/mark-stress-reflow-2026-11.txt"
    )
    pilot = set(
        tr.read_ids_file(ROOT / "docs/okf/review-samples/mark-pilot-2026-11.txt")
    )
    assert len(stress) == 40 and len(set(stress)) == 40
    assert all(i.endswith(tm.REFLOW_SUFFIX) for i in stress)
    assert {i[: -len(tm.REFLOW_SUFFIX)] for i in stress} <= pilot


# --- snippet anchor mode (teacher-mark-v2s): no column, ``t`` and ``o`` ------------
def _snip(
    line: int,
    kind: str,
    t: str,
    n: Optional[str] = None,
    *,
    o: Optional[int] = None,
    le: Optional[int] = None,
    x: bool = False,
) -> Dict[str, Any]:
    return {
        "l": line,
        "k": kind,
        "t": t,
        "o": o,
        "n": n,
        "s": None,
        "le": le,
        "x": x,
        "e": None,
        "nota": None,
    }


def test_snippet_schema_prompt_and_version_have_no_column() -> None:
    item = tm.mark_schema("snippet")["properties"]["norms"]["items"]["properties"][
        "marks"
    ]["items"]
    assert list(item["properties"]) == list(tm.SNIPPET_FIELDS)
    assert "c" not in item["properties"] and "o" in item["properties"]
    assert item["required"] == list(tm.SNIPPET_FIELDS)
    assert tm.prompt_version("snippet") == "teacher-mark-v2s"
    assert tm.prompt_version() == tm.MARK_PROMPT_VERSION == "teacher-mark-v2"
    prompt = tm.mark_system_prompt("snippet")
    assert "`c`" not in prompt and "COLUNA" not in prompt and '"c":' not in prompt
    assert "`o`" in prompt and '"o":null' in prompt
    assert tm.example_json("snippet") in prompt
    # the default contract is untouched by the new mode
    assert tm.mark_system_prompt() == tm.MARK_SYSTEM_PROMPT
    assert '"c":1' in tm.MARK_SYSTEM_PROMPT and "COLUNA" in tm.MARK_SYSTEM_PROMPT
    assert tm.mark_prompt_sha256("snippet") != tm.mark_prompt_sha256()
    with pytest.raises(tb.TeacherBatchError):
        tm.check_anchors("column")


def test_the_snippet_example_round_trips_through_the_converter() -> None:
    text = "\n".join(tm.EXAMPLE_LINES.get(i, "") for i in range(1, 22))
    entry = tm.example_response("snippet")["norms"][0]
    conv = tm.convert_response(text, entry, tipo="lei", numero=7, anchors="snippet")
    _check(conv.xml, text)
    assert conv.problems == []
    assert all(a["used"] == "B" and a["a_off"] is None for a in conv.anchors)
    # same document as the column mode builds from the same example
    col = tm.convert_response(
        text, tm.example_response()["norms"][0], tipo="lei", numero=7
    )
    assert conv.xml == col.xml


def test_prompt_examples_of_o_resolve_as_written() -> None:
    text = (
        "Art. 1º - Lista:\n"
        "I - a cultura; II - o esporte; III - a saúde.\n"
        "§ 1º - Veja o § 2º. § 2º - O prazo."
    )
    marks = [
        _snip(1, "art", "Art. 1º", "1"),
        _snip(2, "inc", "I -", "1", o=1),
        _snip(2, "inc", "II -", "2", o=1),
        _snip(2, "inc", "III -", "3"),
        _snip(3, "par", "§ 1º", "1"),
        _snip(3, "par", "§ 2º", "2", o=2),
    ]
    conv = tm.convert_response(text, marks, anchors="snippet")
    assert conv.problems == []
    line2 = text.index("I - a")
    assert [a["offset"] for a in conv.anchors] == [
        0,
        line2,
        text.index("II -"),
        text.index("III -"),
        text.index("§ 1º"),
        text.rindex("§ 2º"),
    ]
    assert [a["used"] for a in conv.anchors] == ["B", "O", "O", "B", "B", "O"]


def test_snippet_ties_need_o_and_o_is_checked() -> None:
    text = "Art. 1º - Veja o Art. 1º.\nI - um; II - dois."
    cases = [
        (_snip(1, "art", "Art. 1º", "1"), "ambiguous_snippet"),
        (_snip(1, "art", "Art. 1º", "1", o=3), "bad_occurrence"),
        (_snip(2, "inc", "II -", "2", o=2), "bad_occurrence"),  # unique: o must be 1
        (_snip(2, "inc", "XX -", "20"), "no_anchor"),
    ]
    for mark, reason in cases:
        conv = tm.convert_response(text, [mark], anchors="snippet")
        assert conv.anchors[0]["drop_reason"] == reason, (mark, reason)
        assert conv.anchors[0]["used"] is None
    ok = tm.convert_response(
        text, [_snip(1, "art", "Art. 1º", "1", o=1)], anchors="snippet"
    )
    assert ok.anchors[0]["used"] == "O" and ok.anchors[0]["offset"] == 0
    bad = tm.convert_response(
        text,
        [{**_snip(1, "art", "Art. 1º", "1"), "o": 0}],
        anchors="snippet",
    )
    assert bad.anchors[0]["drop_reason"] == "bad_occurrence"


def test_snippet_mark_without_o_field_or_with_a_column_only_is_bad_shape() -> None:
    text = "Art. 1º - Um.\n"
    no_o = _snip(1, "art", "Art. 1º", "1")
    del no_o["o"]
    conv = tm.convert_response(text, [no_o], anchors="snippet")
    assert conv.anchors[0]["drop_reason"] == "bad_shape"
    # and the column mode refuses a snippet mark (no ``c``)
    conv = tm.convert_response(text, [_snip(1, "art", "Art. 1º", "1")])
    assert conv.anchors[0]["drop_reason"] == "bad_shape"


def test_snippet_t_copied_across_a_line_break_resolves_by_its_prefix() -> None:
    text = "Art. 5º - Fica o\nbloco aqui.\nArt. \n6º Dois.\n"
    marks = [
        _snip(1, "art", "Art. 5º", "5"),
        _snip(3, "art", "Art. 6º", "6"),  # the model joined "Art." and "6º"
    ]
    conv = tm.convert_response(text, marks, anchors="snippet")
    assert conv.problems == []
    assert [a["b_method"] for a in conv.anchors] == ["exact", "prefix"]
    assert conv.anchors[1]["offset"] == text.index("Art. \n6º")
    # the prefix must END the line: a stray unrelated "Art." mid-line is not used
    stray = tm.convert_response(
        "Veja Art. 3 e mais.\n", [_snip(1, "art", "Art. 9º", "9")], anchors="snippet"
    )
    assert stray.anchors[0]["drop_reason"] == "no_anchor"


def test_snippet_plan_manifest_params_and_collect(tmp_path: Path) -> None:
    plan = _plan(SMALL_TEXTS, anchors="snippet")
    assert plan.anchors == "snippet" and plan.packing["anchors"] == "snippet"
    spec = tb.resolve_model("claude-haiku-5-5")
    params = tm.build_mark_params(plan.requests[0], spec, "medium", True, plan.anchors)
    assert params["system"][0]["text"] == tm.SNIPPET_SYSTEM_PROMPT
    schema = params["output_config"]["format"]["schema"]
    assert schema == tm.SNIPPET_SCHEMA
    est = tm.estimate_mark_cost(plan, spec, "medium", True)
    est_col = tm.estimate_mark_cost(_plan(SMALL_TEXTS), spec, "medium", True)
    assert est.system_tokens != est_col.system_tokens
    manifest = _manifest(plan)
    assert manifest["anchors"] == "snippet"
    assert manifest["prompt_version"] == "teacher-mark-v2s"
    assert manifest["prompt_sha256"] == tm.mark_prompt_sha256("snippet")
    summary = tm.collect_mark(_Fake(_perfect(plan)), manifest, tmp_path)
    assert summary["anchors"] == "snippet"
    assert summary["states"]["ok"] == 3 and summary["marks_dropped"] == 0
    assert set(summary["anchors_used"]) <= {"B", "O"}
    rec = score_mark.load_records(tmp_path)[0]
    assert rec["anchors"] == "snippet" and rec["prompt_version"] == "teacher-mark-v2s"
    result = score_mark.run(tmp_path, tmp_path / "score")
    snip = result["snippet_resolution"]
    assert snip["resolved_rate"] == 1.0 and snip["dropped_by_reason"] == {}
    assert result["column_accuracy"]["reference_n"] == 0
    assert result["reader_reference"]["devices_matched_to_reader"] > 0
    assert result["reader_reference"]["used_offset_exact_rate"] == 1.0
    assert "snippet mode" in (tmp_path / "score" / "score_mark.md").read_text()


def test_a_column_run_has_no_snippet_block(tmp_path: Path) -> None:
    plan = _plan(SMALL_TEXTS)
    tm.collect_mark(_Fake(_perfect(plan)), _manifest(plan), tmp_path)
    assert score_mark.run(tmp_path, tmp_path / "s")["snippet_resolution"] is None


def test_snippet_stress_scores_used_offsets_by_column_bucket(tmp_path: Path) -> None:
    base = SMALL_TEXTS[0]
    variant, meta = tm.reflow_record(_record(1, base))
    plan = tm.build_mark_plan(
        [_record(1, base)],
        seed="s",
        reflows={_record(1, base).ref.key: meta},
        anchors="snippet",
    )
    assert plan.norms[0].reflow is not None
    tm.collect_mark(_Fake(_perfect(plan)), _manifest(plan), tmp_path)
    stress = score_mark.run(tmp_path, tmp_path / "s")["stress"]
    assert stress is not None and stress["devices_matched_to_reader"] > 0
    assert stress["used_offset_exact_rate"] == 1.0 and stress["a_exact_rate"] is None
    assert stress["by_true_column"]


def test_retry_must_keep_the_anchor_mode() -> None:
    plan = _plan([SMALL_TEXTS[0]], anchors="snippet")
    base = {"anchors": "col+snippet", "truncated_requests": ["m00000"]}
    with pytest.raises(tb.TeacherBatchError, match="--anchors"):
        tm.build_retry_plan(plan, base, depth=1, max_tokens_cap=32_000)
    # an old manifest without the field is a column run
    plan2 = _plan([SMALL_TEXTS[0]])
    with pytest.raises(tb.TeacherBatchError, match="no truncated_requests"):
        tm.build_retry_plan(plan2, {}, depth=1, max_tokens_cap=32_000)


def test_cli_anchors_only_in_mark_mode() -> None:
    result = CliRunner().invoke(
        tb.app, ["plan", "--mode", "review", "--anchors", "snippet"]
    )
    assert result.exit_code == 2 and "only applies with --mode mark" in result.output
    result = CliRunner().invoke(
        tb.app,
        ["plan", "--mode", "mark", "--anchors", "nope", "--text-source", "textos"],
    )
    assert result.exit_code == 2 and "--anchors must be one of" in result.output


def test_workflow_offers_the_anchor_choice() -> None:
    import yaml

    text = (ROOT / ".github/workflows/teacher-batch.yml").read_text(encoding="utf-8")
    inputs = yaml.safe_load(text)[True]["workflow_dispatch"]["inputs"]
    assert inputs["anchors"]["options"] == ["col+snippet", "snippet"]
    assert inputs["anchors"]["default"] == "col+snippet"
    assert text.count('--anchors "$IN_ANCHORS"') == 2
