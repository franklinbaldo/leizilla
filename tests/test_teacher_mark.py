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
def test_a_and_b_right_use_b_and_agree() -> None:
    conv = tm.convert_response(TEXT, _base(), tipo="lei", numero=1)
    _check(conv.xml, TEXT)
    assert conv.problems == []
    for row in conv.anchors:
        assert row["used"] == "B"
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
        _mark(2, "art", 1, "Art. 5º", "5"),
    ]
    # line 1 has no "Art. 1º": tolerant fails too, A decides; line 2 is tolerant
    conv = tm.convert_response(text, marks)
    _check(conv.xml, text)
    by_line = {a["line"]: a for a in conv.anchors}
    assert by_line[2]["b_method"] == "tolerant" and by_line[2]["used"] == "B"
    assert by_line[2]["offset"] == text.index("Art.  5o")
    assert by_line[1]["b_method"] == "none" and by_line[1]["used"] == "A"


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


def test_a_only_is_used_when_b_does_not_resolve() -> None:
    marks = _base()
    marks[0]["t"] = "Artigo 1"
    conv = tm.convert_response(TEXT, marks)
    _check(conv.xml, TEXT)
    assert conv.anchors[0]["used"] == "A" and conv.anchors[0]["b_method"] == "none"
    assert conv.problems == []


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
    assert tm.MARK_PROMPT_VERSION == "teacher-mark-v1"
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
