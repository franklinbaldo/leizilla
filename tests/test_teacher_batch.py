"""Tests for leizilla.teacher_batch — offline and deterministic.

The Anthropic API is exercised through the real SDK client wired to an
in-process mock transport (no network): this checks the wire shape the SDK
produces from our request dicts, not just our own dict building. Internet
Archive access is mocked at the ``publisher`` wrappers and ``urlopen``.
"""

from __future__ import annotations

import json
import re
import random
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import anthropic
import httpx2
import pytest
from anthropic import DefaultHttpxClient
from typer.testing import CliRunner

from leizilla import teacher_batch as tb

_INDEX_HEADER = "tipo,numero,rendicao,formato,uuid5,sha256,captured_at,source\n"
_ITEM = "leizilla_ro_casacivil_lei_0001-1000"

SIMPLE_LAW = "\n".join(
    [
        "GOVERNO DO ESTADO DE RONDONIA",  # 1
        "",  # 2
        "LEI Nº 7 DE 5 DE ABRIL DE 1985",  # 3
        "",  # 4
        "Dispõe sobre coisa alguma.",  # 5
        "O GOVERNADOR DO ESTADO DE RONDÔNIA, faço saber:",  # 6
        "Art. Io - Fica criada a coisa.",  # 7
        "Art. 22 - Esta Lei entra em vigor na data de sua publicação.",  # 8
        "",  # 9
        "Porto Velho, 5 de abril de 1985.",  # 10
    ]
)


def _ref(numero: int = 7, uuid5: str = "aaaaaaaa", tipo: str = "lei") -> tb.NormRef:
    return tb.NormRef(
        item=_ITEM,
        fonte="casacivil",
        tipo=tipo,
        numero=numero,
        uuid5=uuid5,
        txt_name=f"{tipo}-{numero:05d}_{uuid5}_djvu.txt",
    )


def _long_text(n: int) -> str:
    """n content lines, each followed by a blank line (2n lines)."""
    return "\n".join(f"linha {i}\n" for i in range(1, n + 1))


# --------------------------------------------------------------------------
# Fake API (real SDK, mock transport)
# --------------------------------------------------------------------------


def _message(
    payload: Any,
    stop_reason: str = "end_turn",
    usage: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-haiku-5-5",
        # A thinking block first: the answer must be found by type, not position.
        "content": [
            {"type": "thinking", "thinking": "", "signature": "sig"},
            {"type": "text", "text": text},
        ],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": usage or {"input_tokens": 100, "output_tokens": 20},
    }


def _ok(custom_id: str, payload: Any, **kw: Any) -> Dict[str, Any]:
    return {
        "custom_id": custom_id,
        "result": {"type": "succeeded", "message": _message(payload, **kw)},
    }


class FakeAPI:
    """Minimal Message Batches + count_tokens server."""

    def __init__(self) -> None:
        self.created: List[Dict[str, Any]] = []
        self.results: Dict[str, List[Dict[str, Any]]] = {}
        self.status: Dict[str, List[str]] = {}
        self.fail_create_at: Optional[int] = None
        self.count_calls: List[Dict[str, Any]] = []
        self.paths: List[str] = []

    def _batch(self, batch_id: str, status: str) -> Dict[str, Any]:
        return {
            "id": batch_id,
            "type": "message_batch",
            "processing_status": status,
            "request_counts": {
                "processing": 0 if status == "ended" else 1,
                "succeeded": 0,
                "errored": 0,
                "canceled": 0,
                "expired": 0,
            },
            "created_at": "2026-11-14T00:00:00Z",
            "expires_at": "2026-11-15T00:00:00Z",
            "ended_at": None,
            "archived_at": None,
            "cancel_initiated_at": None,
            # As on the real API: only an ended batch has a results_url.
            "results_url": (
                f"https://api.anthropic.com/v1/messages/batches/{batch_id}/results"
                if status == "ended"
                else None
            ),
        }

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        self.paths.append(f"{request.method} {path}")
        if path == "/v1/messages/count_tokens":
            self.count_calls.append(json.loads(request.content))
            return httpx2.Response(200, json={"input_tokens": 1000})
        if path == "/v1/messages/batches" and request.method == "POST":
            if self.fail_create_at == len(self.created):
                return httpx2.Response(
                    400,
                    json={
                        "type": "error",
                        "error": {"type": "invalid_request_error", "message": "no"},
                    },
                )
            self.created.append(json.loads(request.content))
            return httpx2.Response(
                200, json=self._batch(f"msgbatch_{len(self.created)}", "in_progress")
            )
        if path.endswith("/results"):
            batch_id = path.split("/")[-2]
            body = "".join(json.dumps(r) + "\n" for r in self.results[batch_id])
            return httpx2.Response(200, text=body)
        batch_id = path.split("/")[-1]
        queue = self.status.get(batch_id, ["ended"])
        status = queue.pop(0) if len(queue) > 1 else queue[0]
        return httpx2.Response(200, json=self._batch(batch_id, status))

    def client(self) -> anthropic.Anthropic:
        return anthropic.Anthropic(
            api_key="test-key",
            max_retries=0,
            http_client=DefaultHttpxClient(
                transport=httpx2.MockTransport(self.handler)
            ),
        )


def _plan(texts: Dict[tb.NormRef, Optional[str]], **kw: Any) -> tb.Plan:
    return tb.build_plan(list(texts), lambda ref: texts[ref], **kw)


def _submit(
    api: FakeAPI, plan: tb.Plan, tmp_path: Path, **kw: Any
) -> tuple[Dict[str, Any], Path]:
    spec = tb.MODELS[tb.DEFAULT_MODEL]
    estimate = tb.estimate_cost(plan, spec, "medium", True)
    manifest = tb.build_manifest(
        plan,
        estimate,
        ente="ro",
        effort="medium",
        cache=True,
        max_usd=1.0,
        guard="ceiling",
    )
    path = tmp_path / "manifest.json"
    tb.submit_batches(
        api.client(), plan, spec, manifest, path, effort="medium", cache=True, **kw
    )
    return manifest, path


# --------------------------------------------------------------------------
# Chunking
# --------------------------------------------------------------------------


class TestChunking:
    def test_single_chunk_keeps_global_line_numbers(self) -> None:
        lines = tb.split_lines(SIMPLE_LAW)
        chunks = tb.chunk_document(lines)
        assert len(chunks) == 1
        assert chunks[0].owned == (1, 3, 5, 6, 7, 8, 10)  # blank lines skipped
        assert chunks[0].context == () and chunks[0].head == ()

    def test_empty_text_has_no_chunks(self) -> None:
        assert tb.chunk_document(tb.split_lines("\n  \n\n")) == []

    def test_every_nonblank_line_owned_exactly_once_in_order(self) -> None:
        lines = tb.split_lines(_long_text(53))
        chunks = tb.chunk_document(lines, max_lines=10, context_lines=3, head_lines=4)
        owned = [n for c in chunks for n in c.owned]
        assert owned == [i + 1 for i, line in enumerate(lines) if line.strip()]
        assert [c.index for c in chunks] == list(range(6))
        assert all(c.total == 6 for c in chunks)
        assert all(len(c.owned) <= 10 for c in chunks)

    def test_context_is_the_lines_just_before_and_never_owned(self) -> None:
        lines = tb.split_lines(_long_text(30))
        chunks = tb.chunk_document(lines, max_lines=10, context_lines=3, head_lines=4)
        second = chunks[1]
        assert second.context == chunks[0].owned[-3:]
        assert second.head == chunks[0].owned[:4]
        assert not set(second.context) & set(second.owned)
        assert max(second.context) < second.first_line

    def test_head_does_not_repeat_context(self) -> None:
        lines = tb.split_lines(_long_text(12))
        chunks = tb.chunk_document(lines, max_lines=5, context_lines=4, head_lines=8)
        second = chunks[1]
        assert not set(second.head) & set(second.context)
        assert second.head == (1,)  # only line 1 precedes the 4 context lines

    def test_char_budget_closes_a_chunk(self) -> None:
        lines = ["x" * 50] * 10
        chunks = tb.chunk_document(lines, max_lines=100, max_chars=120)
        assert [len(c.owned) for c in chunks] == [2, 2, 2, 2, 2]

    def test_oversized_line_still_gets_its_own_chunk(self) -> None:
        chunks = tb.chunk_document(["a", "x" * 500, "b"], max_chars=100)
        assert [c.owned for c in chunks] == [(1,), (2,), (3,)]

    def test_is_deterministic(self) -> None:
        lines = tb.split_lines(_long_text(200))
        assert tb.chunk_document(lines, max_lines=17) == tb.chunk_document(
            lines, max_lines=17
        )

    def test_render_marks_owned_and_context_blocks(self) -> None:
        lines = tb.split_lines(_long_text(30))
        chunks = tb.chunk_document(lines, max_lines=10, context_lines=2, head_lines=2)
        text = tb.render_user_message(_ref(), lines, chunks[1])
        assert text.startswith('<norma tipo="lei" numero="7" parte="2/3">')
        head, rest = text.split("<contexto_anterior>")
        context, owned = rest.split("<linhas_a_rotular>")
        assert "1\tlinha 1" in head and "3\tlinha 2" in head
        assert "19\tlinha 10" in context
        assert "21\tlinha 11" in owned and "19\tlinha 10" not in owned

    def test_first_chunk_has_no_context_blocks(self) -> None:
        lines = tb.split_lines(SIMPLE_LAW)
        text = tb.render_user_message(_ref(), lines, tb.chunk_document(lines)[0])
        assert "contexto" not in text
        assert "7\tArt. Io - Fica criada a coisa." in text


# --------------------------------------------------------------------------
# Requests, schema, cost
# --------------------------------------------------------------------------


def _walk_objects(schema: Any) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            found.append(schema)
        for value in schema.values():
            found.extend(_walk_objects(value))
    elif isinstance(schema, list):
        for value in schema:
            found.extend(_walk_objects(value))
    return found


class TestRequests:
    def test_schema_is_strict(self) -> None:
        objects = _walk_objects(tb.LABEL_SCHEMA)
        assert len(objects) == 3
        for obj in objects:
            assert obj["additionalProperties"] is False
            assert sorted(obj["required"]) == sorted(obj["properties"])
        unsupported = {"minimum", "maximum", "minLength", "maxLength", "minItems"}
        assert not unsupported & set(
            json.dumps(tb.LABEL_SCHEMA).replace('"', " ").split()
        )

    def test_schema_carries_every_owner_category(self) -> None:
        enum = tb.LABEL_SCHEMA["properties"]["labels"]["items"]["properties"][
            "category"
        ]["enum"]
        assert enum == [
            "ementa",
            "preambulo",
            "artigo",
            "paragrafo",
            "inciso",
            "alinea",
            "item",
            "vigencia",
            "revogacao",
            "assinatura",
            "anexo",
        ]

    def test_params_shape(self) -> None:
        plan = _plan({_ref(): SIMPLE_LAW})
        params = tb.build_request_params(
            plan.requests[0], tb.MODELS["claude-haiku-5-5"], "medium", cache=True
        )
        assert params["model"] == "claude-haiku-5-5"
        assert params["system"] == [
            {
                "type": "text",
                "text": tb.SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral", "ttl": "1h"},
            }
        ]
        assert params["output_config"] == {
            "format": {"type": "json_schema", "schema": tb.LABEL_SCHEMA},
            "effort": "medium",
        }
        assert params["messages"] == [
            {"role": "user", "content": plan.requests[0].user_text}
        ]
        # Rejected by current models / by the Batches API.
        for forbidden in ("temperature", "top_p", "thinking", "stream", "fallbacks"):
            assert forbidden not in params

    def test_no_effort_for_models_that_reject_it_and_no_cache_when_off(self) -> None:
        plan = _plan({_ref(): SIMPLE_LAW})
        params = tb.build_request_params(
            plan.requests[0], tb.MODELS["claude-haiku-4-5"], "medium", cache=False
        )
        assert "effort" not in params["output_config"]
        assert "cache_control" not in params["system"][0]

    def test_system_prefix_is_identical_across_requests(self) -> None:
        plan = _plan(
            {_ref(1, "aaaaaaaa"): SIMPLE_LAW, _ref(2, "bbbbbbbb"): "Art. 1º x"}
        )
        spec = tb.MODELS[tb.DEFAULT_MODEL]
        systems = {
            json.dumps(tb.build_request_params(r, spec, "low", True)["system"])
            for r in plan.requests
        }
        assert len(systems) == 1

    def test_prompt_never_asks_for_the_text_back(self) -> None:
        assert "nunca" in tb.SYSTEM_PROMPT and "Art. Io" in tb.SYSTEM_PROMPT
        assert set(tb.LABEL_SCHEMA["properties"]) == {"labels", "amends"}

    def test_custom_ids_are_valid_unique_and_map_back(self) -> None:
        plan = _plan(
            {_ref(1, "aaaaaaaa"): _long_text(25), _ref(2, "bbbbbbbb"): SIMPLE_LAW},
            max_lines=10,
        )
        ids = [r.custom_id for r in plan.requests]
        assert ids == [
            "t000000-aaaaaaaa-c0000",
            "t000000-aaaaaaaa-c0001",
            "t000000-aaaaaaaa-c0002",
            "t000001-bbbbbbbb-c0000",
        ]
        assert all(tb._CUSTOM_ID_RE.match(i) for i in ids)

    def test_max_tokens_scales_with_chunk_and_is_capped(self) -> None:
        plan = _plan({_ref(): _long_text(600)}, max_lines=500)
        big, small = plan.requests
        assert big.max_tokens == tb.MAX_TOKENS_CAP
        assert small.max_tokens == tb.MAX_TOKENS_BASE + tb.TOKENS_PER_LABEL * 100

    def test_plan_records_unfetched_and_empty_texts(self) -> None:
        plan = _plan(
            {
                _ref(1, "aaaaaaaa"): None,
                _ref(2, "bbbbbbbb"): " \n\n",
                _ref(3, "cccccccc"): SIMPLE_LAW,
            }
        )
        assert plan.fetch_failed == [f"{_ITEM}/aaaaaaaa"]
        assert plan.empty == [f"{_ITEM}/bbbbbbbb"]
        assert [n.uuid5 for n in plan.norms] == ["cccccccc"]


class TestCost:
    def test_estimate_arithmetic(self) -> None:
        plan = _plan({_ref(): SIMPLE_LAW})
        req = plan.requests[0]
        spec = tb.MODELS["claude-haiku-5-5"]
        est = tb.estimate_cost(plan, spec, "medium", cache=True)
        system = -(-len(tb.SYSTEM_PROMPT) // 2)
        user = -(-len(req.user_text) // 2) + tb.REQUEST_OVERHEAD_TOKENS
        out = 1500 + 200 + 140  # thinking + fixed + 40 * 0.5 * 7 lines
        assert est.input_tokens == system + user
        assert est.estimated_output_tokens == out
        assert est.ceiling_output_tokens == req.max_tokens
        assert est.estimate_usd == round((system + user) * 0.05e-6 + out * 0.25e-6, 4)
        assert est.ceiling_usd == round(
            user * 0.05e-6 + system * 2 * 0.05e-6 + req.max_tokens * 0.25e-6, 4
        )
        assert est.ceiling_usd >= est.estimate_usd

    def test_batch_prices_are_half_of_the_published_standard_rates(self) -> None:
        assert tb.BATCH_DISCOUNT == 0.5
        haiku = tb.MODELS["claude-haiku-5-5"]
        assert (haiku.input_usd_mtok, haiku.output_usd_mtok) == (0.10, 0.50)
        assert haiku.long_prompt_threshold == 100_000
        opus = tb.MODELS["claude-opus-5-5"]
        assert (opus.input_usd_mtok, opus.output_usd_mtok) == (4.0, 20.0)

    def test_unknown_model_has_no_price_and_is_refused(self) -> None:
        with pytest.raises(tb.TeacherBatchError, match="unknown model"):
            tb.resolve_model("claude-made-up-9")

    def test_guard_refuses_above_max_usd(self) -> None:
        plan = _plan({_ref(): _long_text(400)})
        spec = tb.MODELS["claude-opus-5-5"]
        est = tb.estimate_cost(plan, spec, "medium", True)
        with pytest.raises(tb.TeacherBatchError, match="cost guard"):
            tb.check_cost_guard(est, spec, est.ceiling_usd - 0.01, "ceiling")
        tb.check_cost_guard(est, spec, est.ceiling_usd, "ceiling")

    def test_estimate_guard_is_an_explicit_weaker_choice(self) -> None:
        plan = _plan({_ref(): _long_text(400)})
        spec = tb.MODELS["claude-opus-5-5"]
        est = tb.estimate_cost(plan, spec, "low", True)
        between = (est.estimate_usd + est.ceiling_usd) / 2
        tb.check_cost_guard(est, spec, between, "estimate")
        with pytest.raises(tb.TeacherBatchError):
            tb.check_cost_guard(est, spec, between, "ceiling")

    @pytest.mark.parametrize("bad", [0.0, -1.0, float("nan")])
    def test_guard_rejects_non_positive_budget(self, bad: float) -> None:
        plan = _plan({_ref(): SIMPLE_LAW})
        spec = tb.MODELS[tb.DEFAULT_MODEL]
        est = tb.estimate_cost(plan, spec, "low", True)
        with pytest.raises(tb.TeacherBatchError, match="positive"):
            tb.check_cost_guard(est, spec, bad, "ceiling")

    def test_guard_refuses_a_request_in_the_long_prompt_price_tier(self) -> None:
        plan = _plan({_ref(): "x" * 250_000}, max_chars=10**9)
        spec = tb.MODELS["claude-haiku-5-5"]
        est = tb.estimate_cost(plan, spec, "low", True)
        with pytest.raises(tb.TeacherBatchError, match="threshold"):
            tb.check_cost_guard(est, spec, 1000.0, "ceiling")

    def test_measured_cost_uses_cache_and_batch_rates(self) -> None:
        usage = {
            "input_tokens": 1_000_000,
            "output_tokens": 1_000_000,
            "cache_creation_input_tokens": 1_000_000,
            "cache_read_input_tokens": 1_000_000,
        }
        cost = tb.measured_cost_usd(usage, tb.MODELS["claude-haiku-5-5"], True)
        assert cost == pytest.approx(0.05 + 0.25 + 0.05 * 2 + 0.05 * 0.1)

    def test_count_tokens_sample_calls_the_counting_endpoint(self) -> None:
        api = FakeAPI()
        plan = _plan({_ref(n, f"{n:08x}"): SIMPLE_LAW for n in range(1, 7)})
        spec = tb.MODELS[tb.DEFAULT_MODEL]
        sample = tb.count_tokens_sample(api.client(), plan, spec, "medium", 3)
        assert sample is not None
        assert sample["sampled_requests"] == 3 and sample["input_tokens"] == 3000
        assert len(api.count_calls) == 3
        assert api.count_calls[0]["model"] == "claude-haiku-5-5"
        assert api.count_calls[0]["output_config"]["format"]["type"] == "json_schema"
        assert not api.created  # counting never creates a batch


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------


class TestEnumeration:
    def _patch(
        self, index: Optional[str], files: Optional[set[str]], items: Any = (_ITEM,)
    ) -> Any:
        return (
            patch(
                "leizilla.teacher_batch.publisher.scrape_identifiers",
                return_value=None if items is None else list(items),
            ),
            patch(
                "leizilla.teacher_batch.publisher.fetch_existing_index",
                return_value=index,
            ),
            patch(
                "leizilla.teacher_batch.publisher.fetch_item_filenames",
                return_value=files,
            ),
        )

    def test_latest_capture_with_text_only(self) -> None:
        index = _INDEX_HEADER + "\n".join(
            [
                "lei,1,original,pdf,aaaa0001,h,2026-01-01T00:00:00Z,s",
                "lei,1,original,pdf,aaaa0002,h,2026-02-01T00:00:00Z,s",  # newer
                "lei,2,original,pdf,bbbb0001,h,2026-01-01T00:00:00Z,s",  # no OCR
                "lei,3,original,html,cccc0001,h,2026-01-01T00:00:00Z,s",  # not pdf
                "lc,4,original,pdf,dddd0001,h,2026-01-01T00:00:00Z,s",
                "lei,x,original,pdf,eeee0001,h,2026-01-01T00:00:00Z,s",  # malformed
            ]
        )
        files = {
            "lei-00001_aaaa0001_djvu.txt",
            "lei-00001_aaaa0002_djvu.txt",
            "lei-00002_bbbb0001.pdf",
            "lc-00004_dddd0001_djvu.txt",
        }
        items = [_ITEM, "leizilla_ro_casacivil_unidentified"]
        p1, p2, p3 = self._patch(index, files, items)
        with p1, p2 as fetch_index, p3:
            result = tb.enumerate_norms("ro", ["casacivil"])
        assert result.errors == []
        assert [(n.tipo, n.numero, n.uuid5) for n in result.norms] == [
            ("lc", 4, "dddd0001"),
            ("lei", 1, "aaaa0002"),
        ]
        assert result.norms[1].txt_name == "lei-00001_aaaa0002_djvu.txt"
        fetch_index.assert_called_once_with(_ITEM)  # holding item skipped

    def test_tipo_filter(self) -> None:
        index = _INDEX_HEADER + (
            "lei,1,original,pdf,aaaa0001,h,t,s\nlc,4,original,pdf,dddd0001,h,t,s\n"
        )
        files = {"lei-00001_aaaa0001_djvu.txt", "lc-00004_dddd0001_djvu.txt"}
        p1, p2, p3 = self._patch(index, files)
        with p1, p2, p3:
            result = tb.enumerate_norms("ro", ["casacivil"], ["LC"])
        assert [n.tipo for n in result.norms] == ["lc"]

    def test_failures_are_recorded_not_swallowed(self) -> None:
        p1, p2, p3 = self._patch(None, None, items=None)
        with p1, p2, p3:
            assert tb.enumerate_norms("ro", ["casacivil"]).errors == [
                "leizilla_ro_casacivil_*: item search failed"
            ]
        p1, _, p3 = self._patch("", None)
        with (
            p1,
            patch(
                "leizilla.teacher_batch.publisher.fetch_existing_index",
                side_effect=tb.publisher.IndexFetchError("boom"),
            ),
            p3,
        ):
            errors = tb.enumerate_norms("ro", ["casacivil"]).errors
        assert errors == [f"{_ITEM}: index.csv fetch failed (boom)"]
        p1, p2, p3 = self._patch(_INDEX_HEADER, None)
        with p1, p2, p3:
            errors = tb.enumerate_norms("ro", ["casacivil"]).errors
        assert errors == [f"{_ITEM}: file list fetch failed"]

    def test_select_is_deterministic_and_seeded(self) -> None:
        norms = [_ref(n, f"{n:08x}") for n in range(1, 21)]
        shuffled = norms[:]
        random.Random(3).shuffle(shuffled)
        assert tb.select_norms(shuffled, limit=3) == norms[:3]
        seeded = tb.select_norms(shuffled, limit=5, shuffle_seed="pilot")
        assert seeded == tb.select_norms(norms, limit=5, shuffle_seed="pilot")
        assert seeded != norms[:5]
        only = tb.select_norms(norms, only_keys=[norms[4].key, "missing/key"])
        assert only == [norms[4]]

    def test_fetch_text_uses_cache_and_gives_up_cleanly(self, tmp_path: Path) -> None:
        ref = _ref()

        class _Resp:
            def __enter__(self) -> "_Resp":
                return self

            def __exit__(self, *a: Any) -> None:
                return None

            def read(self) -> bytes:
                return "Art. 1º".encode("utf-8")

        with patch(
            "leizilla.teacher_batch.urllib.request.urlopen", return_value=_Resp()
        ) as urlopen:
            assert tb.fetch_text(ref, tmp_path) == "Art. 1º"
            assert tb.fetch_text(ref, tmp_path) == "Art. 1º"
        assert urlopen.call_count == 1
        url = urlopen.call_args[0][0].full_url
        assert url == f"https://archive.org/download/{_ITEM}/{ref.txt_name}"

        slept: List[float] = []
        with patch(
            "leizilla.teacher_batch.urllib.request.urlopen",
            side_effect=OSError("down"),
        ) as urlopen:
            assert tb.fetch_text(_ref(9, "99999999"), None, sleep=slept.append) is None
        assert urlopen.call_count == 3 and slept == [2.0, 4.0]


# --------------------------------------------------------------------------
# Submit
# --------------------------------------------------------------------------


class TestSubmit:
    def test_split_batches_by_count_and_bytes(self) -> None:
        reqs = [{"custom_id": f"r{i}", "params": {"x": "y" * 100}} for i in range(5)]
        assert [len(b) for b in tb.split_batches(reqs, max_requests=2)] == [2, 2, 1]
        one = len(json.dumps(reqs[0]).encode())
        by_bytes = tb.split_batches(reqs, max_requests=100, max_bytes=one * 2)
        assert [len(b) for b in by_bytes] == [2, 2, 1]
        with pytest.raises(tb.TeacherBatchError):
            tb.split_batches(reqs, max_requests=100_001)
        with pytest.raises(tb.TeacherBatchError, match="alone"):
            tb.split_batches(reqs, max_requests=10, max_bytes=10)

    def test_submit_sends_sdk_shaped_requests_and_writes_manifest(
        self, tmp_path: Path
    ) -> None:
        api = FakeAPI()
        plan = _plan({_ref(1, "aaaaaaaa"): _long_text(25)}, max_lines=10)
        manifest, path = _submit(api, plan, tmp_path)

        assert api.paths == ["POST /v1/messages/batches"]
        sent = api.created[0]["requests"]
        assert [r["custom_id"] for r in sent] == [r.custom_id for r in plan.requests]
        assert sent[0]["params"]["output_config"]["format"]["schema"] == tb.LABEL_SCHEMA
        assert sent[0]["params"]["system"][0]["cache_control"]["ttl"] == "1h"

        on_disk = tb.load_manifest(path)
        assert on_disk == manifest
        assert on_disk["batches"][0]["id"] == "msgbatch_1"
        assert on_disk["batches"][0]["custom_ids"] == [r["custom_id"] for r in sent]
        assert on_disk["model"] == "claude-haiku-5-5"
        assert on_disk["prompt_version"] == tb.PROMPT_VERSION
        assert on_disk["prompt_sha256"] == tb.prompt_sha256()
        entry = on_disk["requests"]["t000000-aaaaaaaa-c0001"]
        assert (entry["item"], entry["uuid5"], entry["chunk"]) == (_ITEM, "aaaaaaaa", 1)
        assert (entry["first_line"], entry["last_line"]) == (21, 39)
        # The norm text itself is not in the manifest.
        assert "linha 11" not in path.read_text(encoding="utf-8")

    def test_created_batches_survive_a_later_failure(self, tmp_path: Path) -> None:
        api = FakeAPI()
        api.fail_create_at = 1
        plan = _plan({_ref(1, "aaaaaaaa"): _long_text(25)}, max_lines=10)
        with pytest.raises(anthropic.BadRequestError):
            _submit(api, plan, tmp_path, max_requests=2)
        on_disk = tb.load_manifest(tmp_path / "manifest.json")
        assert [b["id"] for b in on_disk["batches"]] == ["msgbatch_1"]
        assert len(on_disk["batches"][0]["custom_ids"]) == 2
        assert len(on_disk["requests"]) == 3

    def test_manifest_version_is_checked(self, tmp_path: Path) -> None:
        path = tmp_path / "m.json"
        path.write_text('{"manifest_version": 99}', encoding="utf-8")
        with pytest.raises(tb.TeacherBatchError, match="manifest_version"):
            tb.load_manifest(path)


# --------------------------------------------------------------------------
# Collect
# --------------------------------------------------------------------------

_META = {"first_line": 1, "last_line": 10}
_GOOD = {
    "labels": [
        {"line": 5, "category": "ementa", "number": None, "quoted": False},
        {"line": 7, "category": "artigo", "number": "1", "quoted": False},
        {"line": 8, "category": "artigo", "number": "2", "quoted": False},
    ],
    "amends": [],
}


class TestInterpret:
    def test_good_answer(self) -> None:
        outcome = tb.interpret_result(_ok("a", _GOOD), _META)
        assert outcome.ok and outcome.stop_reason == "end_turn"
        assert [label["line"] for label in outcome.labels] == [5, 7, 8]
        assert outcome.usage["output_tokens"] == 20

    def test_fenced_json_is_accepted(self) -> None:
        text = "```json\n" + json.dumps(_GOOD) + "\n```"
        assert tb.interpret_result(_ok("a", text), _META).ok

    @pytest.mark.parametrize("stop", ["max_tokens", "refusal", "pause_turn"])
    def test_bad_stop_reason_is_a_failure_even_with_valid_json(self, stop: str) -> None:
        outcome = tb.interpret_result(_ok("a", _GOOD, stop_reason=stop), _META)
        assert not outcome.ok
        assert outcome.reason == f"stop_reason_{stop}" and outcome.labels == []
        assert outcome.usage["input_tokens"] == 100  # still billed, still counted

    @pytest.mark.parametrize("kind", ["errored", "expired", "canceled"])
    def test_non_succeeded_results(self, kind: str) -> None:
        result: Dict[str, Any] = {"type": kind}
        if kind == "errored":
            result["error"] = {
                "type": "error",
                "error": {"type": "invalid_request_error", "message": "bad"},
            }
        outcome = tb.interpret_result({"custom_id": "a", "result": result}, _META)
        assert not outcome.ok and outcome.reason == f"result_{kind}"
        if kind == "errored":
            assert outcome.detail == "invalid_request_error: bad"

    def test_invalid_json_and_missing_text(self) -> None:
        assert tb.interpret_result(_ok("a", '{"labels": ['), _META).reason == (
            "invalid_json"
        )
        entry = _ok("a", _GOOD)
        entry["result"]["message"]["content"] = [
            {"type": "thinking", "thinking": "", "signature": "s"}
        ]
        assert tb.interpret_result(entry, _META).reason == "no_text_block"

    @pytest.mark.parametrize(
        "label, fragment",
        [
            (
                {"line": 11, "category": "artigo", "number": "1", "quoted": False},
                "outside",
            ),
            (
                {"line": 5, "category": "titulo", "number": None, "quoted": False},
                "unknown",
            ),
            (
                {"line": "5", "category": "artigo", "number": "1", "quoted": False},
                "integer",
            ),
            (
                {"line": True, "category": "artigo", "number": "1", "quoted": False},
                "integer",
            ),
            ({"line": 5, "category": "artigo", "number": 1, "quoted": False}, "number"),
            (
                {"line": 5, "category": "artigo", "number": "1", "quoted": "no"},
                "boolean",
            ),
            ({"line": 5, "category": "artigo", "number": "1"}, "wrong shape"),
            (
                {
                    "line": 5,
                    "category": "artigo",
                    "number": "1",
                    "quoted": False,
                    "text": "Art",
                },
                "wrong shape",
            ),
        ],
    )
    def test_schema_violations_invalidate_the_chunk(
        self, label: Dict[str, Any], fragment: str
    ) -> None:
        outcome = tb.interpret_result(
            _ok("a", {"labels": [label], "amends": []}), _META
        )
        assert not outcome.ok and outcome.reason == "schema_violation"
        assert fragment in (outcome.detail or "")

    def test_duplicate_line_and_extra_keys(self) -> None:
        label = {"line": 5, "category": "artigo", "number": "1", "quoted": False}
        _, _, problems = tb.validate_payload(
            {"labels": [label, label], "amends": [], "text": "x"}, 1, 10
        )
        assert any("duplicate line 5" in p for p in problems)
        assert any("unexpected keys" in p for p in problems)
        assert tb.validate_payload([], 1, 10)[2] == ["payload is not an object"]

    def test_normalisation(self) -> None:
        payload = {
            "labels": [
                {
                    "line": 8,
                    "category": "paragrafo",
                    "number": " unico ",
                    "quoted": True,
                },
                {"line": 5, "category": "ementa", "number": "9", "quoted": False},
            ],
            "amends": [
                {"action": "altera", "tipo": " Lei ", "numero": "123", "ano": 1990},
                {"action": "revoga", "tipo": "decreto", "numero": None, "ano": None},
            ],
        }
        labels, amends, problems = tb.validate_payload(payload, 1, 10)
        assert problems == []
        assert labels == [
            {"line": 5, "category": "ementa", "number": None, "quoted": False},
            {"line": 8, "category": "paragrafo", "number": "unico", "quoted": True},
        ]
        assert amends[0] == {
            "action": "altera",
            "tipo": "lei",
            "numero": "123",
            "ano": 1990,
        }

    def test_bad_amends(self) -> None:
        bad = [
            {"action": "cita", "tipo": "lei", "numero": "1", "ano": None},
            {"action": "altera", "tipo": "", "numero": "1", "ano": None},
            {"action": "altera", "tipo": "lei", "numero": 1, "ano": None},
            {"action": "altera", "tipo": "lei", "numero": "1", "ano": "1990"},
        ]
        _, amends, problems = tb.validate_payload({"labels": [], "amends": bad}, 1, 10)
        assert amends == [] and len(problems) == 4


class TestCollect:
    def _two_norms(self, tmp_path: Path) -> tuple[FakeAPI, Dict[str, Any]]:
        api = FakeAPI()
        plan = _plan(
            {_ref(1, "aaaaaaaa"): _long_text(25), _ref(7, "bbbbbbbb"): SIMPLE_LAW},
            max_lines=10,
        )
        manifest, _ = _submit(api, plan, tmp_path)
        return api, manifest

    def test_wait_polls_until_ended(self, tmp_path: Path) -> None:
        api, manifest = self._two_norms(tmp_path)
        api.status["msgbatch_1"] = ["in_progress", "in_progress", "ended"]
        slept: List[float] = []
        ended, status = tb.wait_for_batches(
            api.client(), manifest, 10, sleep=slept.append, clock=lambda: 0.0
        )
        assert ended and slept == [60.0, 60.0]
        assert status[0]["processing_status"] == "ended"

    def test_wait_gives_up_at_deadline_without_sleeping(self, tmp_path: Path) -> None:
        api, manifest = self._two_norms(tmp_path)
        api.status["msgbatch_1"] = ["in_progress"]
        slept: List[float] = []
        ended, status = tb.wait_for_batches(
            api.client(), manifest, 0, sleep=slept.append, clock=lambda: 0.0
        )
        assert not ended and slept == []
        assert status[0]["request_counts"]["processing"] == 1

    def test_merge_writes_one_jsonl_per_norm(self, tmp_path: Path) -> None:
        api, manifest = self._two_norms(tmp_path)
        amend = {"action": "altera", "tipo": "lei", "numero": "3", "ano": 1984}
        results = [
            _ok(
                "t000000-aaaaaaaa-c0002",
                {
                    "labels": [
                        {
                            "line": 45,
                            "category": "assinatura",
                            "number": None,
                            "quoted": False,
                        }
                    ],
                    "amends": [amend],
                },
            ),
            _ok("t000001-bbbbbbbb-c0000", _GOOD),
            _ok(
                "t000000-aaaaaaaa-c0000",
                {
                    "labels": [
                        {
                            "line": 3,
                            "category": "artigo",
                            "number": "1",
                            "quoted": False,
                        },
                        {
                            "line": 1,
                            "category": "ementa",
                            "number": None,
                            "quoted": False,
                        },
                    ],
                    "amends": [amend],
                },
            ),
            _ok(
                "t000000-aaaaaaaa-c0001",
                {
                    "labels": [
                        {
                            "line": 21,
                            "category": "artigo",
                            "number": "5",
                            "quoted": True,
                        }
                    ],
                    "amends": [],
                },
            ),
        ]
        api.results["msgbatch_1"] = results  # deliberately out of order
        out = tmp_path / "out"
        summary = tb.collect_results(api.client(), manifest, out)

        assert (summary["norms_ok"], summary["norms_failed"]) == (2, 0)
        assert summary["labels"] == 7 and summary["failure_reasons"] == {}
        assert summary["labels_by_category"]["artigo"] == 4
        assert summary["usage"] == {
            "input_tokens": 400,
            "output_tokens": 80,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }
        assert summary["measured_usd"] == pytest.approx(400 * 0.05e-6 + 80 * 0.25e-6)
        assert (out / "failures.jsonl").read_text(encoding="utf-8") == ""

        path = out / "labels" / _ITEM / "lei-00001_aaaaaaaa.jsonl"
        records = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
        header, labels = records[0], records[1:]
        assert header["record"] == "norm" and header["chunks"] == 3
        assert header["amends"] == [amend]  # union, deduplicated
        assert header["model"] == "claude-haiku-5-5"
        assert header["prompt_version"] == tb.PROMPT_VERSION
        assert header["batch_ids"] == ["msgbatch_1"]
        assert "git_sha" in header and len(header["text_sha256"]) == 64
        assert header["n_lines"] == 50
        assert [(r["line"], r["category"], r["quoted"]) for r in labels] == [
            (1, "ementa", False),
            (3, "artigo", False),
            (21, "artigo", True),
            (45, "assinatura", False),
        ]
        assert all(
            set(r) == {"record", "line", "category", "number", "quoted"} for r in labels
        )
        assert (out / "labels" / _ITEM / "lei-00007_bbbbbbbb.jsonl").is_file()
        raw = (out / "raw" / "msgbatch_1.jsonl").read_text("utf-8").splitlines()
        assert len(raw) == 4
        assert json.loads((out / "manifest.json").read_text("utf-8")) == manifest

    def test_one_bad_chunk_fails_the_whole_norm(self, tmp_path: Path) -> None:
        api, manifest = self._two_norms(tmp_path)
        empty = {"labels": [], "amends": []}
        api.results["msgbatch_1"] = [
            _ok("t000000-aaaaaaaa-c0000", empty),
            _ok("t000000-aaaaaaaa-c0001", empty, stop_reason="max_tokens"),
            # c0002 has no result at all
            _ok("t000001-bbbbbbbb-c0000", _GOOD),
            _ok("t999999-zzzzzzzz-c0000", empty),  # not ours
        ]
        out = tmp_path / "out"
        summary = tb.collect_results(api.client(), manifest, out)
        assert (summary["norms_ok"], summary["norms_failed"]) == (1, 1)
        assert summary["failure_reasons"] == {
            "missing_result": 1,
            "stop_reason_max_tokens": 1,
        }
        assert summary["unknown_custom_ids"] == ["t999999-zzzzzzzz-c0000"]
        assert not (out / "labels" / _ITEM / "lei-00001_aaaaaaaa.jsonl").exists()
        failures = [
            json.loads(line)
            for line in (out / "failures.jsonl").read_text("utf-8").splitlines()
        ]
        assert len(failures) == 1 and failures[0]["key"] == f"{_ITEM}/aaaaaaaa"
        assert [p["reason"] for p in failures[0]["problems"]] == [
            "stop_reason_max_tokens",
            "missing_result",
        ]
        # The failures file is the input of `submit --retry-failures`.
        assert tb._read_failure_keys(out / "failures.jsonl") == [f"{_ITEM}/aaaaaaaa"]

    def test_requests_never_submitted_are_reported(self, tmp_path: Path) -> None:
        api = FakeAPI()
        api.fail_create_at = 1
        plan = _plan({_ref(1, "aaaaaaaa"): _long_text(25)}, max_lines=10)
        with pytest.raises(anthropic.BadRequestError):
            _submit(api, plan, tmp_path, max_requests=2)
        manifest = tb.load_manifest(tmp_path / "manifest.json")
        empty = {"labels": [], "amends": []}
        api.results["msgbatch_1"] = [
            _ok("t000000-aaaaaaaa-c0000", empty),
            _ok("t000000-aaaaaaaa-c0001", empty),
        ]
        summary = tb.collect_results(api.client(), manifest, tmp_path / "out")
        assert summary["failure_reasons"] == {"not_submitted": 1}


# --------------------------------------------------------------------------
# IA upload and CLI
# --------------------------------------------------------------------------


def test_upload_to_ia_follows_publisher_conventions(tmp_path: Path) -> None:
    out = tmp_path / "out"
    (out / "labels" / _ITEM).mkdir(parents=True)
    (out / "labels" / _ITEM / "lei-00001_aaaaaaaa.jsonl").write_text("{}\n")
    for name in ("failures.jsonl", "summary.json", "manifest.json"):
        (out / name).write_text("{}")
    summary = {"ente": "ro", "norms_ok": 1, "labels": 3}
    seen: List[List[str]] = []

    def fake_upload(self: Any, args: List[str], **_: Any) -> None:
        assert Path(args[3]).name == "labels.tar.gz" and Path(args[3]).is_file()
        seen.append(args)

    with patch.object(
        tb.publisher.InternetArchivePublisher, "_run_ia_upload", fake_upload
    ):
        result = tb.upload_to_ia(out, summary, revision="20261114t120000z")
    assert result == {
        "success": True,
        "ia_id": "leizilla-teacher-labels-ro-20261114t120000z",
    }
    args = seen[0]
    assert args[:3] == ["ia", "upload", "leizilla-teacher-labels-ro-20261114t120000z"]
    assert "mediatype:data" in args and "creator:leizilla-teacher-batch" in args

    def failing(self: Any, args: List[str], **_: Any) -> None:
        raise subprocess.CalledProcessError(1, args, stderr="denied")

    with patch.object(tb.publisher.InternetArchivePublisher, "_run_ia_upload", failing):
        result = tb.upload_to_ia(out, summary, revision="r")
    assert result["success"] is False and result["error"] == "denied"


class TestCLI:
    runner = CliRunner()

    def _patches(self, api: FakeAPI, norms: Dict[tb.NormRef, Optional[str]]) -> Any:
        enumeration = tb.Enumeration(norms=list(norms))

        def fetch(ref: tb.NormRef, cache_dir: Optional[Path] = None) -> Optional[str]:
            return norms[ref]

        return (
            patch("leizilla.teacher_batch.enumerate_norms", return_value=enumeration),
            patch("leizilla.teacher_batch.fetch_text", side_effect=fetch),
            patch("leizilla.teacher_batch._client", side_effect=api.client),
        )

    def _run(self, api: FakeAPI, norms: Any, args: List[str]) -> Any:
        p1, p2, p3 = self._patches(api, norms)
        with p1, p2, p3:
            return self.runner.invoke(tb.app, [*args, "--fetch-delay", "0"])

    def test_plan_prints_every_model_and_sends_nothing(self, tmp_path: Path) -> None:
        api = FakeAPI()
        out = tmp_path / "plan.json"
        result = self._run(api, {_ref(): SIMPLE_LAW}, ["plan", "--out", str(out)])
        assert result.exit_code == 0, result.output
        for model in tb.MODELS:
            assert model in result.output
        assert api.paths == []
        saved = json.loads(out.read_text("utf-8"))
        assert [e["model"] for e in saved["estimates"]] == list(tb.MODELS)

    def test_submit_requires_max_usd(self, tmp_path: Path) -> None:
        api = FakeAPI()
        result = self._run(
            api,
            {_ref(): SIMPLE_LAW},
            ["submit", "--manifest", str(tmp_path / "m.json")],
        )
        # Typer colours its usage errors when the environment allows it (CI does),
        # which splits the option name with escape codes.
        plain = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
        assert result.exit_code == 2 and "--max-usd" in plain
        assert api.paths == []

    def test_submit_refuses_above_max_usd(self, tmp_path: Path) -> None:
        api = FakeAPI()
        manifest = tmp_path / "m.json"
        result = self._run(
            api,
            {_ref(): _long_text(400)},
            ["submit", "--max-usd", "0.0001", "--manifest", str(manifest)],
        )
        assert result.exit_code == 2 and "cost guard" in result.output
        assert api.paths == [] and not manifest.exists()

    def test_submit_refuses_unknown_model_and_existing_manifest(
        self, tmp_path: Path
    ) -> None:
        api = FakeAPI()
        manifest = tmp_path / "m.json"
        base = ["submit", "--max-usd", "5", "--manifest", str(manifest)]
        result = self._run(api, {_ref(): SIMPLE_LAW}, [*base, "--model", "claude-x"])
        assert result.exit_code == 2 and "unknown model" in result.output
        manifest.write_text("{}")
        result = self._run(api, {_ref(): SIMPLE_LAW}, base)
        assert result.exit_code == 2 and "already exists" in result.output
        assert api.paths == []

    def test_submit_refuses_incomplete_inputs_unless_allowed(
        self, tmp_path: Path
    ) -> None:
        api = FakeAPI()
        norms = {_ref(1, "aaaaaaaa"): None, _ref(2, "bbbbbbbb"): SIMPLE_LAW}
        manifest = tmp_path / "m.json"
        base = ["submit", "--max-usd", "5", "--manifest", str(manifest)]
        result = self._run(api, norms, base)
        assert result.exit_code == 2 and "incomplete" in result.output
        assert api.paths == []
        result = self._run(api, norms, [*base, "--allow-partial"])
        assert result.exit_code == 0, result.output
        saved = tb.load_manifest(manifest)
        assert saved["fetch_failed"] == [f"{_ITEM}/aaaaaaaa"]

    def test_submit_then_collect_round_trip(self, tmp_path: Path) -> None:
        api = FakeAPI()
        manifest = tmp_path / "m.json"
        norms = {_ref(): SIMPLE_LAW}
        result = self._run(
            api, norms, ["submit", "--max-usd", "1", "--manifest", str(manifest)]
        )
        assert result.exit_code == 0, result.output
        assert "msgbatch_1" in result.output
        assert tb.load_manifest(manifest)["max_usd"] == 1.0

        out = tmp_path / "out"
        collect = ["collect", "--manifest", str(manifest), "--out-dir", str(out)]
        api.status["msgbatch_1"] = ["in_progress"]
        with patch("leizilla.teacher_batch._client", side_effect=api.client):
            pending = self.runner.invoke(tb.app, collect)
        assert pending.exit_code == 3 and not out.exists()

        api.status["msgbatch_1"] = ["ended"]
        api.results["msgbatch_1"] = [_ok("t000000-aaaaaaaa-c0000", _GOOD)]
        with patch("leizilla.teacher_batch._client", side_effect=api.client):
            done = self.runner.invoke(tb.app, collect)
        assert done.exit_code == 0, done.output
        assert "1/1 norms labelled" in done.output
        assert (out / "labels" / _ITEM / "lei-00007_aaaaaaaa.jsonl").is_file()

    def test_collect_exits_4_on_failures(self, tmp_path: Path) -> None:
        api = FakeAPI()
        manifest = tmp_path / "m.json"
        self._run(
            api,
            {_ref(): SIMPLE_LAW},
            ["submit", "--max-usd", "1", "--manifest", str(manifest)],
        )
        api.results["msgbatch_1"] = [
            _ok("t000000-aaaaaaaa-c0000", _GOOD, stop_reason="refusal")
        ]
        args = [
            "collect",
            "--manifest",
            str(manifest),
            "--out-dir",
            str(tmp_path / "o"),
        ]
        with patch("leizilla.teacher_batch._client", side_effect=api.client):
            assert self.runner.invoke(tb.app, args).exit_code == 4
            ok = self.runner.invoke(tb.app, [*args, "--allow-failures"])
        assert ok.exit_code == 0 and "stop_reason_refusal" in ok.output
