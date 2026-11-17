"""Batched harvest (ADR-0016): one upload per flush, one derive per item, no lost rows.

Everything here is offline: ``subprocess.run`` (the ``ia`` CLI), the index fetch, the
source fetch and Save Page Now are all replaced.
"""

import csv
import io
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from leizilla import publisher, wayback
from leizilla.cli import app
from leizilla.publisher import (
    IndexFetchError,
    InternetArchivePublisher,
    RawCapture,
    make_raw_capture,
)
from leizilla.ratelimit import make_rate_limiter
from leizilla.scraper import harvest_pending_resources, ia_throttle_scope
from leizilla.storage import DuckDBStorage

from harvest_fakes import batch_ok, uploaded_captures

REPO = Path(__file__).resolve().parents[1]
ITEM = "leizilla_ro_casacivil_decreto_31001-32000"
REJECTED = "Uploaded content is unacceptable. - error checking pdf file"
THROTTLED = "Please reduce your request rate. - total_tasks_queued exceeds global_limit"
PLAIN_RATE = "Please reduce your request rate."
ACCESSKEY_FULL = (
    "Please reduce your request rate. - accesskey_tasks_queued exceeds rationed amount"
)


# --------------------------------------------------------------------------- helpers


def _capture(numero: int, body: Optional[bytes] = None) -> RawCapture:
    chave = f"decreto-{numero:05d}"
    lei_data = {
        "id": f"ro-casacivil-{chave}",
        "ente": "ro",
        "fonte": "casacivil",
        "chave": chave,
        "titulo": chave,
        "url_original": f"https://fonte.example/Files/D{numero}.pdf",
    }
    content = body if body is not None else f"%PDF-1.4 decreto {numero}".encode()
    return make_raw_capture(lei_data, content, "source-direct")


def _index_rows(index_csv: str) -> List[Dict[str, str]]:
    return list(csv.DictReader(io.StringIO(index_csv)))


class FakeIA:
    """Stands in for the ``ia`` CLI: records each invocation and what it would PUT."""

    def __init__(self) -> None:
        self.calls: List[List[str]] = []
        self.indexes: List[str] = []
        self.failures: List[Callable[[List[str]], Optional[str]]] = []

    def fail_when(self, rule: Callable[[List[str]], Optional[str]]) -> None:
        self.failures.append(rule)

    def __call__(self, args: List[str], **_: Any) -> "subprocess.CompletedProcess[str]":
        self.calls.append(list(args))
        if args[:2] == ["ia", "upload"]:
            for rule in self.failures:
                stderr = rule(args)
                if stderr is not None:
                    raise subprocess.CalledProcessError(1, args, stderr=stderr)
            index_path = next(a for a in args if a.endswith("/index.csv"))
            self.indexes.append(Path(index_path).read_text(encoding="utf-8"))
        return subprocess.CompletedProcess(args, 0, "", "")

    @property
    def uploads(self) -> List[List[str]]:
        return [c for c in self.calls if c[:2] == ["ia", "upload"]]

    @staticmethod
    def files(args: List[str]) -> List[str]:
        """Remote file names of an ``ia upload`` call, in PUT order."""
        return [Path(a).name for a in args[3:] if a.startswith("/")]


@pytest.fixture
def pub(monkeypatch: pytest.MonkeyPatch) -> InternetArchivePublisher:
    p = InternetArchivePublisher()
    p.access_key, p.secret_key = "key", "secret"
    monkeypatch.setattr(p, "_upload_rate_limiter", lambda _url: None)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    return p


@pytest.fixture
def ia(monkeypatch: pytest.MonkeyPatch) -> FakeIA:
    fake = FakeIA()
    monkeypatch.setattr(subprocess, "run", fake)
    return fake


@pytest.fixture
def temp_db(tmp_path: Path) -> Iterator[DuckDBStorage]:
    db = DuckDBStorage(tmp_path / "t.duckdb")
    yield db
    db.close()


@pytest.fixture
def fast_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """No per-host pause between direct fetches (pacing has its own tests)."""
    monkeypatch.setattr(
        "leizilla.scraper.make_rate_limiter", lambda *a, **k: lambda _url: None
    )


def _resource(numero: int, **extra: Any) -> Dict[str, Any]:
    return {
        "url": f"https://fonte.example/Files/D{numero}.pdf",
        "ente": "ro",
        "fonte": "casacivil",
        "tipo_documento": "decreto",
        "chave": f"decreto-{numero:05d}",
        "status": "pending",
        **extra,
    }


def _statuses(db: DuckDBStorage) -> Dict[str, str]:
    rows = db.connect().execute("SELECT chave, status FROM discovered_resources")
    return dict(rows.fetchall())


def _harvest(
    db: DuckDBStorage, pub: Any, fetch: Any = None, **kwargs: Any
) -> Dict[str, Any]:
    def default_fetch(url: str) -> tuple[bytes, bool]:
        return f"%PDF-1.4 {url}".encode(), False

    with (
        patch("leizilla.scraper.robots.is_allowed", return_value=True),
        patch(
            "leizilla.scraper.wayback.fetch_bytes_detailed",
            side_effect=fetch or default_fetch,
        ),
    ):
        return harvest_pending_resources(db, pub, **kwargs)


# ------------------------------------------------------- publisher: one upload per flush


def test_batch_is_one_ia_upload_without_derive_and_index_last(
    pub: InternetArchivePublisher, ia: FakeIA
) -> None:
    captures = [_capture(n) for n in (31250, 31249, 31248)]
    with patch.object(publisher, "_fetch_existing_index", return_value=None):
        results = pub.upload_raw_batch(ITEM, captures, index_cache={})

    assert [r["success"] for r in results] == [True, True, True]
    assert len(ia.uploads) == 1
    args = ia.uploads[0]
    assert args[2] == ITEM
    assert "--no-derive" in args and "--checksum" in args
    files = ia.files(args)
    # 3 PDFs + the index, written once: one PUT per capture (no _meta.json sidecar;
    # ADR-0016 addendum 2026-11-17 puts the provenance in index.csv columns)
    assert len(files) == 4
    assert not any(f.endswith("_meta.json") for f in files)
    assert files[-1] == "index.csv"
    assert [f for f in files if f.endswith(".pdf")] == [
        f"decreto-{n:05d}_{r['uuid5']}.pdf"
        for n, r in zip((31250, 31249, 31248), results)
    ]
    assert [row["numero"] for row in _index_rows(ia.indexes[0])] == [
        "31250",
        "31249",
        "31248",
    ]


def test_flags_used_exist_in_the_installed_ia_cli() -> None:
    # The flags are read off the installed library, not guessed (internetarchive 5.8).
    from internetarchive.cli import ia_tasks, ia_upload

    upload_src = Path(ia_upload.__file__).read_text()
    for flag in ('"--no-derive"', '"--checksum"', '"--retries"', '"--sleep"'):
        assert flag in upload_src
    tasks_src = Path(ia_tasks.__file__).read_text()
    for flag in ('"--cmd"', '"--reduced-priority"'):
        assert flag in tasks_src
    assert "already queued/running" in tasks_src


def test_successive_flushes_keep_every_row_without_rereading_ia(
    pub: InternetArchivePublisher, ia: FakeIA
) -> None:
    existing = publisher.merge_index_row(
        None,
        tipo="decreto",
        numero=31999,
        rendicao="",
        formato="pdf",
        uuid5="aaaaaaaa",
        sha256="old",
        source="https://fonte.example/Files/D31999.pdf",
    )
    cache: Dict[str, str] = {}
    with patch.object(
        publisher, "_fetch_existing_index", return_value=existing
    ) as fetch:
        pub.upload_raw_batch(ITEM, [_capture(31250), _capture(31249)], cache)
        pub.upload_raw_batch(ITEM, [_capture(31248)], cache)

    # IA gives no read-after-write: the second flush must build on the first one's
    # index, not on a fresh (possibly stale) read.
    assert fetch.call_count == 1
    assert [row["numero"] for row in _index_rows(ia.indexes[-1])] == [
        "31999",
        "31250",
        "31249",
        "31248",
    ]
    assert _index_rows(cache[ITEM]) == _index_rows(ia.indexes[-1])


def test_unreadable_index_uploads_nothing(
    pub: InternetArchivePublisher, ia: FakeIA
) -> None:
    cache: Dict[str, str] = {}
    with patch.object(
        publisher, "_fetch_existing_index", side_effect=IndexFetchError("timeout")
    ):
        results = pub.upload_raw_batch(ITEM, [_capture(1), _capture(2)], cache)

    assert [r["reason"] for r in results] == ["index-unreadable"] * 2
    assert ia.calls == []  # never overwrite an index we could not read
    assert cache == {}


def test_failed_flush_does_not_poison_the_index_cache(
    pub: InternetArchivePublisher, ia: FakeIA
) -> None:
    cache: Dict[str, str] = {}
    with patch.object(publisher, "_fetch_existing_index", return_value=None):
        pub.upload_raw_batch(ITEM, [_capture(31250)], cache)
        good_index = cache[ITEM]
        ia.fail_when(lambda args: "HTTP 400 Bad Request")
        failed = pub.upload_raw_batch(ITEM, [_capture(31249)], cache)
        ia.failures.clear()
        assert [r["reason"] for r in failed] == ["upload-failed"]
        assert cache[ITEM] == good_index
        pub.upload_raw_batch(ITEM, [_capture(31248)], cache)

    # the row of the confirmed flush survives; the failed one was never recorded
    assert [row["numero"] for row in _index_rows(ia.indexes[-1])] == ["31250", "31248"]


def test_rejected_pdf_is_dropped_and_the_rest_of_the_batch_lands(
    pub: InternetArchivePublisher, ia: FakeIA
) -> None:
    captures = [_capture(31250), _capture(31249, b"%PDF-broken"), _capture(31248)]
    bad_uuid5 = publisher.uuid5_name(b"%PDF-broken")
    bad_name = f"decreto-31249_{bad_uuid5}.pdf"

    def reject_bad(args: List[str]) -> Optional[str]:
        if bad_name in FakeIA.files(args):
            return (
                f"{ITEM}:\n uploading x\n error uploading {bad_name}: {REJECTED}\n"
                "HTTP 503 somewhere in the progress output\n"
            )
        return None

    ia.fail_when(reject_bad)
    with (
        patch.object(publisher, "_fetch_existing_index", return_value=None),
        patch("time.sleep") as sleep,
    ):
        results = pub.upload_raw_batch(ITEM, captures, {})

    assert [r.get("reason") for r in results] == [None, "ia-rejected", None]
    assert [r["success"] for r in results] == [True, False, True]
    sleep.assert_not_called()  # a rejected PDF is permanent: no backoff, no retry
    assert len(ia.uploads) == 2
    assert bad_name not in ia.files(ia.uploads[1])
    assert [row["numero"] for row in _index_rows(ia.indexes[-1])] == ["31250", "31248"]


def test_unattributable_rejection_isolates_one_capture_per_upload(
    pub: InternetArchivePublisher, ia: FakeIA
) -> None:
    captures = [_capture(31250), _capture(31249, b"%PDF-broken"), _capture(31248)]
    bad_uuid5 = publisher.uuid5_name(b"%PDF-broken")

    def reject_without_naming(args: List[str]) -> Optional[str]:
        if any(bad_uuid5 in name for name in FakeIA.files(args)):
            return REJECTED  # no "error uploading <key>:" line to read
        return None

    ia.fail_when(reject_without_naming)
    cache: Dict[str, str] = {}
    with patch.object(publisher, "_fetch_existing_index", return_value=None):
        results = pub.upload_raw_batch(ITEM, captures, cache)

    assert [r.get("reason") for r in results] == [None, "ia-rejected", None]
    assert [len(ia.files(a)) for a in ia.uploads] == [4, 2, 2, 2]
    assert [row["numero"] for row in _index_rows(cache[ITEM])] == ["31250", "31248"]


def test_throttled_flush_backs_off_then_reports_throttled(
    pub: InternetArchivePublisher, ia: FakeIA
) -> None:
    # A plain "reduce your request rate" (no *_tasks_queued marker) is an ordinary rate
    # limit: short backoffs, then reported (as account scope). The queue-full messages
    # fail fast instead (see test_queue_full_..._fails_fast below).
    ia.fail_when(lambda args: f" error uploading x.pdf: {PLAIN_RATE}")
    cache: Dict[str, str] = {}
    with (
        patch.object(publisher, "_fetch_existing_index", return_value=None),
        patch("time.sleep") as sleep,
    ):
        results = pub.upload_raw_batch(ITEM, [_capture(1), _capture(2)], cache)

    assert [r["reason"] for r in results] == ["ia-throttled"] * 2
    assert [r["scope"] for r in results] == ["account"] * 2
    assert len(ia.uploads) == publisher._IA_BATCH_MAX_ATTEMPTS
    waits = [call.args[0] for call in sleep.call_args_list]
    assert len(waits) == 2 and waits[0] >= 60 and waits[1] >= 120
    assert cache == {}


def test_batch_without_credentials_never_calls_the_cli(ia: FakeIA) -> None:
    p = InternetArchivePublisher()
    p.access_key = p.secret_key = None
    results = p.upload_raw_batch(ITEM, [_capture(1)], {})
    assert results[0]["reason"] == "ia-unavailable"
    assert p.request_derive(ITEM) is False
    assert ia.calls == []


# ----------------------------------------------------------------- publisher: derive


def test_request_derive_submits_one_derive_task(
    pub: InternetArchivePublisher, ia: FakeIA
) -> None:
    assert pub.request_derive(ITEM) is True
    assert ia.calls == [["ia", "tasks", ITEM, "--cmd", "derive.php"]]


def test_request_derive_treats_already_queued_as_done(
    pub: InternetArchivePublisher,
) -> None:
    err = subprocess.CalledProcessError(
        1, ["ia"], stderr="success: derive.php task already queued/running"
    )
    with patch.object(subprocess, "run", side_effect=err) as run:
        assert pub.request_derive(ITEM) is True
    assert run.call_count == 1


def test_request_derive_falls_back_to_reduced_priority_when_throttled(
    pub: InternetArchivePublisher,
) -> None:
    calls: List[List[str]] = []

    def run(args: List[str], **_: Any) -> "subprocess.CompletedProcess[str]":
        calls.append(list(args))
        if "--reduced-priority" not in args:
            raise subprocess.CalledProcessError(1, args, stderr=f"error: {THROTTLED}")
        return subprocess.CompletedProcess(args, 0, "", "")

    with patch.object(subprocess, "run", side_effect=run):
        assert pub.request_derive(ITEM) is True
    assert calls[-1] == [
        "ia",
        "tasks",
        ITEM,
        "--cmd",
        "derive.php",
        "--reduced-priority",
    ]


def test_request_derive_reports_a_refusal(pub: InternetArchivePublisher) -> None:
    err = subprocess.CalledProcessError(1, ["ia"], stderr="error: no such item")
    with patch.object(subprocess, "run", side_effect=err):
        assert pub.request_derive(ITEM) is False


# ------------------------------------------------------- harvest: buffering and state


def test_harvest_flushes_in_batches_and_derives_once_at_the_end(
    temp_db: DuckDBStorage, fast_source: None
) -> None:
    for n in range(31246, 31251):
        temp_db.insert_resource(_resource(n))
    pub = MagicMock()
    pub.preserved_sources.return_value = set()
    batch_ok(pub)

    stats = _harvest(temp_db, pub, limit=10, batch_size=2)

    flushes = [c for c in pub.mock_calls if c[0] == "upload_raw_batch"]
    assert [len(c.args[1]) for c in flushes] == [2, 2, 1]
    assert {c.args[0] for c in flushes} == {ITEM}
    # exactly one derive for the item, and only after its last flush
    names = [
        c[0] for c in pub.mock_calls if c[0] in ("upload_raw_batch", "request_derive")
    ]
    assert names == ["upload_raw_batch"] * 3 + ["request_derive"]
    pub.request_derive.assert_called_once_with(ITEM)
    assert stats["success"] == 5
    assert stats["flushes"] == 3
    assert stats["derive-requested"] == 1
    assert set(_statuses(temp_db).values()) == {"downloaded"}


def test_harvest_takes_the_newest_norms_first(
    temp_db: DuckDBStorage, fast_source: None
) -> None:
    for n in (7, 31250, 900, 31249):
        temp_db.insert_resource(_resource(n))
    pub = MagicMock()
    pub.preserved_sources.return_value = set()
    batch_ok(pub)

    _harvest(temp_db, pub, limit=2, batch_size=25)

    # newest of each bucket in turn: 31250 (bucket 31xxx), then 900 (bucket 0xxx)
    assert [c.target.numero for c in uploaded_captures(pub)] == [31250, 900]


def test_status_changes_only_after_the_flush_that_holds_the_file(
    temp_db: DuckDBStorage, fast_source: None
) -> None:
    for n in (31250, 31249, 31248):
        temp_db.insert_resource(_resource(n))
    seen_at_flush: List[Dict[str, str]] = []

    def upload(
        item_id: str,
        captures: List[RawCapture],
        index_cache: Any = None,
        **_: Any,
    ) -> Any:
        seen_at_flush.append(_statuses(temp_db))
        return [{"success": True, "ia_url": "u"} for _ in captures]

    pub = MagicMock()
    pub.preserved_sources.return_value = set()
    pub.upload_raw_batch.side_effect = upload

    _harvest(temp_db, pub, limit=10, batch_size=2)

    # first flush: nothing is 'downloaded' yet, not even the files being sent
    assert set(seen_at_flush[0].values()) == {"pending"}
    # second flush: only the first batch has been confirmed
    assert seen_at_flush[1] == {
        "decreto-31250": "downloaded",
        "decreto-31249": "downloaded",
        "decreto-31248": "pending",
    }


def test_failed_flush_leaves_resources_pending_and_requests_no_derive(
    temp_db: DuckDBStorage, fast_source: None
) -> None:
    for n in (31250, 31249):
        temp_db.insert_resource(_resource(n))
    pub = MagicMock()
    pub.preserved_sources.return_value = set()
    pub.upload_raw_batch.side_effect = lambda item_id, captures, index_cache=None: [
        {"success": False, "reason": "index-unreadable", "error": "timeout"}
        for _ in captures
    ]

    stats = _harvest(temp_db, pub, limit=10, batch_size=25)

    assert _statuses(temp_db) == {
        "decreto-31250": "pending",
        "decreto-31249": "pending",
    }
    assert stats["success"] == 0 and stats["failed"] == 2
    assert {i["reason"] for i in stats["items"]} == {"index-unreadable"}
    pub.request_derive.assert_not_called()
    assert temp_db.connect().execute("SELECT count(*) FROM leis").fetchone() == (0,)


def test_harvest_survives_a_publisher_exception_during_flush(
    temp_db: DuckDBStorage, fast_source: None
) -> None:
    temp_db.insert_resource(_resource(31250))
    pub = MagicMock()
    pub.preserved_sources.return_value = set()
    pub.upload_raw_batch.side_effect = RuntimeError("boom")

    stats = _harvest(temp_db, pub, limit=10)

    assert stats["failed"] == 1
    assert _statuses(temp_db) == {"decreto-31250": "pending"}


def test_ia_rejected_pdf_is_terminal_and_counted(
    temp_db: DuckDBStorage, fast_source: None
) -> None:
    for n in (31250, 31249):
        temp_db.insert_resource(_resource(n))

    def upload(
        item_id: str,
        captures: List[RawCapture],
        index_cache: Any = None,
        **_: Any,
    ) -> Any:
        return [
            {"success": False, "reason": "ia-rejected", "error": REJECTED}
            if c.target.numero == 31249
            else {"success": True, "ia_url": "u"}
            for c in captures
        ]

    pub = MagicMock()
    pub.preserved_sources.return_value = set()
    pub.upload_raw_batch.side_effect = upload

    first = _harvest(temp_db, pub, limit=10)
    second = _harvest(temp_db, pub, limit=10)

    assert _statuses(temp_db) == {
        "decreto-31250": "downloaded",
        "decreto-31249": "ia-rejected",
    }
    assert first["ia-rejected"] == 1 and first["success"] == 1 and first["failed"] == 0
    # the rest of the batch landed, so the item still gets its derive
    assert first["derive-requested"] == 1
    # not retried on the next run
    assert pub.upload_raw_batch.call_count == 1
    assert second["ia-rejected"] == 0 and second["flushes"] == 0


def test_throttled_flush_stops_the_harvest_and_stops_hitting_the_source(
    temp_db: DuckDBStorage, fast_source: None
) -> None:
    # two items: 31xxx (flushes at batch_size) and 30xxx (still buffered)
    for n in (31250, 31249, 30010, 31248, 31247, 31246):
        temp_db.insert_resource(_resource(n))
    fetched: List[str] = []

    def fetch(url: str) -> tuple[bytes, bool]:
        fetched.append(url)
        return f"%PDF {url}".encode(), False

    pub = MagicMock()
    pub.preserved_sources.return_value = set()
    pub.upload_raw_batch.side_effect = lambda item_id, captures, index_cache=None: [
        {"success": False, "reason": "ia-throttled", "error": THROTTLED}
        for _ in captures
    ]

    stats = _harvest(temp_db, pub, fetch=fetch, limit=10, batch_size=2)

    # total_tasks_queued is account scope: ia-account-throttled (was ia-throttled)
    assert stats["aborted"] == "ia-account-throttled"
    # the trip happens at the flush of the 2nd capture of 31xxx (3rd fetch, since
    # buckets alternate); nothing more is taken from the source after it
    assert len(fetched) == 3
    assert pub.upload_raw_batch.call_count == 1  # and IA is not asked again
    assert set(_statuses(temp_db).values()) == {"pending"}
    pub.request_derive.assert_not_called()


def test_each_ia_item_gets_its_own_flush_and_its_own_derive(
    temp_db: DuckDBStorage, fast_source: None
) -> None:
    for n in (31250, 30010, 31249):
        temp_db.insert_resource(_resource(n))
    pub = MagicMock()
    pub.preserved_sources.return_value = set()
    batch_ok(pub)

    stats = _harvest(temp_db, pub, limit=10)

    flushed = {c.args[0]: len(c.args[1]) for c in pub.upload_raw_batch.call_args_list}
    assert flushed == {ITEM: 2, "leizilla_ro_casacivil_decreto_30001-31000": 1}
    assert sorted(c.args[0] for c in pub.request_derive.call_args_list) == sorted(
        flushed
    )
    assert stats["derive-requested"] == 2


def test_refused_derive_is_reported_not_swallowed(
    temp_db: DuckDBStorage, fast_source: None
) -> None:
    temp_db.insert_resource(_resource(31250))
    pub = MagicMock()
    pub.preserved_sources.return_value = set()
    batch_ok(pub)
    pub.request_derive.return_value = False

    stats = _harvest(temp_db, pub, limit=10)

    assert stats["success"] == 1
    assert stats["derive-requested"] == 0
    assert stats["derive-failed"] == [ITEM]


def test_buffered_captures_are_flushed_even_if_the_loop_raises(
    temp_db: DuckDBStorage, fast_source: None
) -> None:
    for n in (31250, 31249):
        temp_db.insert_resource(_resource(n))
    pub = MagicMock()
    pub.preserved_sources.return_value = set()
    batch_ok(pub)

    def fetch(url: str) -> tuple[bytes, bool]:
        if url.endswith("D31249.pdf"):
            raise KeyboardInterrupt
        return b"%PDF-1.4", False

    with pytest.raises(KeyboardInterrupt):
        _harvest(temp_db, pub, fetch=fetch, limit=10)

    assert _statuses(temp_db) == {
        "decreto-31250": "downloaded",
        "decreto-31249": "pending",
    }
    # 31249 is still pending, so the item is not finished: derive postponed
    pub.request_derive.assert_not_called()


def test_harvest_stops_after_consecutive_transient_source_failures(
    temp_db: DuckDBStorage, fast_source: None
) -> None:
    for n in range(1, 16):
        temp_db.insert_resource(_resource(n))
    calls: List[str] = []

    def fetch(url: str) -> tuple[None, bool]:
        calls.append(url)
        return None, False

    pub = MagicMock()
    pub.preserved_sources.return_value = set()

    stats = _harvest(temp_db, pub, fetch=fetch, limit=15)

    assert len(calls) == 10  # the source is down: stop hammering it
    assert stats["aborted"] == "source-unavailable"
    assert set(_statuses(temp_db).values()) == {"pending"}


def test_confirmed_404s_do_not_trip_the_source_breaker(
    temp_db: DuckDBStorage, fast_source: None
) -> None:
    for n in range(1, 16):
        temp_db.insert_resource(_resource(n))
    pub = MagicMock()
    pub.preserved_sources.return_value = set()

    stats = _harvest(temp_db, pub, fetch=lambda url: (None, True), limit=15)

    assert stats["aborted"] is None
    assert stats["failed"] == 15


def test_time_budget_ends_the_harvest_cleanly(
    temp_db: DuckDBStorage, fast_source: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    for n in (31250, 31249, 31248):
        temp_db.insert_resource(_resource(n))
    pub = MagicMock()
    pub.preserved_sources.return_value = set()
    batch_ok(pub)
    monkeypatch.setattr("leizilla.config.HARVEST_MAX_SECONDS", 100.0)
    clock = iter([0.0, 10.0, 150.0, 151.0])
    monkeypatch.setattr("leizilla.scraper.time.monotonic", lambda: next(clock))

    stats = _harvest(temp_db, pub, limit=10)

    assert stats["aborted"] == "time-budget"
    assert stats["success"] == 1  # what was fetched before the budget still lands
    # two norms of the item are still pending: the derive waits for a later run
    pub.request_derive.assert_not_called()
    assert stats["derive-postponed"] == [ITEM]


# ------------------------------------------------------------- storage: queue ordering


def test_pending_queue_is_newest_first_but_never_tried_still_wins(
    temp_db: DuckDBStorage,
) -> None:
    for n in (5, 31250, 120, 31249, 9000):
        temp_db.insert_resource(_resource(n))
    # 31250 and 9000 were tried before (9000 longer ago) and are still pending
    conn = temp_db.connect()
    conn.execute(
        "UPDATE discovered_resources SET ultima_tentativa = ? WHERE chave = ?",
        ["2026-11-10 00:00:00", "decreto-09000"],
    )
    conn.execute(
        "UPDATE discovered_resources SET ultima_tentativa = ? WHERE chave = ?",
        ["2026-11-14 00:00:00", "decreto-31250"],
    )

    order = [r["chave"] for r in temp_db.get_pending_resources(limit=10)]

    assert order == [
        "decreto-31249",  # never tried, highest number
        "decreto-00120",
        "decreto-00005",
        "decreto-09000",  # retried: least recently tried first
        "decreto-31250",
    ]


def test_pending_queue_interleaves_range_buckets_newest_first(
    temp_db: DuckDBStorage,
) -> None:
    for n in (31250, 31249, 31248, 30010, 30009, 5, 31001, 1000, 1001):
        temp_db.insert_resource(_resource(n))
    conn = temp_db.connect()
    # a retried resource keeps its place after every never-tried one
    conn.execute(
        "UPDATE discovered_resources SET ultima_tentativa = ? WHERE chave = ?",
        ["2026-11-14 00:00:00", "decreto-31248"],
    )

    order = [r["chave"] for r in temp_db.get_pending_resources(limit=20)]

    assert order == [
        "decreto-31250",  # bucket 31001-32000, newest
        "decreto-30010",  # bucket 30001-31000, newest
        "decreto-01001",  # bucket 1001-2000
        "decreto-01000",  # bucket 1-1000
        "decreto-31249",  # second of each bucket, highest bucket first
        "decreto-30009",
        "decreto-00005",  # second of the 1-1000 bucket
        "decreto-31001",  # third of the 31xxx bucket (31248 was retried)
        "decreto-31248",  # retried: after everything never tried
    ]


def test_iteration_never_repeats_a_url_while_buckets_rotate(
    temp_db: DuckDBStorage, fast_source: None
) -> None:
    for n in (31250, 31249, 31248, 30010, 30009, 29001):
        temp_db.insert_resource(_resource(n))
    pub = MagicMock()
    pub.preserved_sources.return_value = set()
    batch_ok(pub)

    stats = _harvest(temp_db, pub, limit=10, batch_size=25)

    numbers = [c.target.numero for c in uploaded_captures(pub)]
    assert sorted(numbers) == sorted({31250, 31249, 31248, 30010, 30009, 29001})
    assert len(numbers) == 6 and stats["success"] == 6


def test_pending_queue_orders_by_number_not_by_text(temp_db: DuckDBStorage) -> None:
    for chave in ("lei-999", "lei-1000", "lei-00998", "coddoc-abc"):
        temp_db.insert_resource(
            {
                "url": f"https://fonte.example/{chave}.pdf",
                "ente": "ro",
                "fonte": "casacivil",
                "tipo_documento": "lei",
                "chave": chave,
            }
        )
    order = [r["chave"] for r in temp_db.get_pending_resources(limit=10)]
    assert order == ["lei-1000", "lei-999", "lei-00998", "coddoc-abc"]


# ------------------------------------------------- Wayback off the critical path (SPN)


def test_save_page_now_is_requested_but_never_awaited(
    temp_db: DuckDBStorage, fast_source: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    temp_db.insert_resource(_resource(31250))
    release = threading.Event()
    started = threading.Event()

    def stuck_save(url: str, access_key: Any, secret_key: Any, timeout: int) -> None:
        started.set()
        release.wait(5)

    monkeypatch.setattr("leizilla.wayback._background_save", stuck_save)
    monkeypatch.setattr("leizilla.scraper._WAYBACK_SAVE_GRACE_S", 0.05)
    pub = MagicMock()
    pub.preserved_sources.return_value = set()
    batch_ok(pub)
    saver = wayback.BackgroundSaver(min_interval=0.0)

    t0 = time.monotonic()
    try:
        stats = _harvest(temp_db, pub, limit=10, wayback_saver=saver)
        elapsed = time.monotonic() - t0
    finally:
        release.set()

    assert started.is_set()
    assert elapsed < 2.0  # the capture did not wait for the Wayback
    assert stats["success"] == 1
    assert stats["wayback-save"]["requested"] == 1
    assert (
        uploaded_captures(pub)[0].raw_meta["provenance_wayback"]["wayback_url"] is None
    )


def test_snapshot_returned_later_goes_to_the_ledger_not_to_the_sidecar(
    temp_db: DuckDBStorage, fast_source: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    temp_db.insert_resource(_resource(31250))
    url = "https://fonte.example/Files/D31250.pdf"
    snapshot = f"https://web.archive.org/web/20261115120000/{url}"
    monkeypatch.setattr(
        "leizilla.wayback._background_save", lambda u, a, s, timeout: snapshot
    )
    pub = MagicMock()
    pub.preserved_sources.return_value = set()
    batch_ok(pub)

    stats = _harvest(
        temp_db, pub, limit=10, wayback_saver=wayback.BackgroundSaver(min_interval=0.0)
    )

    assert stats["wayback-save"] == {
        "requested": 1,
        "accepted": 1,
        "failed": 0,
        "dropped": 0,
    }
    row = (
        temp_db.connect()
        .execute("SELECT status, wayback_snapshot FROM discovered_resources")
        .fetchone()
    )
    assert row == ("downloaded", snapshot)
    provenance = uploaded_captures(pub)[0].raw_meta["provenance_wayback"]
    assert provenance["fetched_from"] == "source-direct"
    assert provenance["wayback_url"] is None
    assert provenance["wayback_timestamp"] is None


def test_known_snapshot_is_used_and_not_saved_again(
    temp_db: DuckDBStorage, fast_source: None
) -> None:
    snapshot = "http://web.archive.org/web/20241208221945/http://fonte.example/D1.pdf"
    temp_db.insert_resource(_resource(31250, wayback_snapshot=snapshot))
    pub = MagicMock()
    pub.preserved_sources.return_value = set()
    batch_ok(pub)
    saver = MagicMock()
    saver.snapshots = {}
    saver.close.return_value = {}

    with (
        patch("leizilla.scraper.robots.is_allowed", return_value=True),
        patch("leizilla.scraper.wayback.fetch_bytes", return_value=b"%PDF-1.4") as fb,
        patch("leizilla.scraper.wayback.fetch_bytes_detailed") as direct,
    ):
        harvest_pending_resources(temp_db, pub, limit=10, wayback_saver=saver)

    fb.assert_called_once_with(snapshot)
    direct.assert_not_called()
    saver.submit.assert_not_called()
    provenance = uploaded_captures(pub)[0].raw_meta["provenance_wayback"]
    assert provenance["fetched_from"] == "wayback"
    assert provenance["wayback_url"] == snapshot
    assert provenance["wayback_timestamp"] == "20241208221945"


def test_save_is_not_requested_for_a_failed_or_non_pdf_fetch(
    temp_db: DuckDBStorage, fast_source: None
) -> None:
    temp_db.insert_resource(_resource(1))
    temp_db.insert_resource(_resource(2))
    saver = MagicMock()
    saver.snapshots = {}
    saver.close.return_value = {}
    pub = MagicMock()
    pub.preserved_sources.return_value = set()

    def fetch(url: str) -> tuple[Optional[bytes], bool]:
        return (None, True) if url.endswith("D1.pdf") else (b"<html>", False)

    _harvest(temp_db, pub, fetch=fetch, limit=10, wayback_saver=saver)

    saver.submit.assert_not_called()


def test_background_saver_shares_the_source_budget_and_survives_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paced: List[str] = []
    results = iter(
        [
            "https://web.archive.org/web/20261115120000/https://a.example/1.pdf",
            "https://web.archive.org/web/*/https://a.example/2.pdf",  # history page
            None,
        ]
    )

    def save(url: str, access_key: Any, secret_key: Any, timeout: int) -> Optional[str]:
        result = next(results)
        if url.endswith("4.pdf"):
            raise RuntimeError("network down")
        return result

    monkeypatch.setattr("leizilla.wayback._background_save", save)
    saver = wayback.BackgroundSaver(min_interval=0.0, source_limiter=paced.append)
    urls = [f"https://a.example/{i}.pdf" for i in (1, 2, 3)]
    for url in urls:
        assert saver.submit(url) is True
    stats = saver.close(grace=5)

    assert paced == urls  # every request spends the per-host budget of the source
    assert stats == {"requested": 3, "accepted": 2, "failed": 1, "dropped": 0}
    # only a real capture (with a timestamp) counts as a known snapshot
    assert saver.snapshots == {urls[0]: next(iter(saver.snapshots.values()))}
    assert "/web/2026" in saver.snapshots[urls[0]]
    assert saver.submit("https://a.example/late.pdf") is False  # closed


def test_background_saver_is_bounded_and_drops_instead_of_blocking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = threading.Event()
    monkeypatch.setattr(
        "leizilla.wayback._background_save",
        lambda u, a, s, timeout: release.wait(5) and None,
    )
    saver = wayback.BackgroundSaver(min_interval=0.0, max_pending=2)
    try:
        accepted = [saver.submit(f"https://a.example/{i}.pdf") for i in range(10)]
        stats = saver.close(grace=0.05)
    finally:
        release.set()

    assert accepted.count(True) <= 3  # one in flight + two queued
    assert stats["dropped"] >= 7
    assert stats["requested"] + accepted.count(False) == 10


def test_rate_limiter_budget_is_shared_between_threads() -> None:
    limiter = make_rate_limiter(min_interval=0.05)
    t0 = time.monotonic()
    threads = [
        threading.Thread(target=limiter, args=("https://a.example/x",))
        for _ in range(4)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # 4 hits on one host from 4 threads still take 3 intervals
    assert time.monotonic() - t0 >= 0.14


# ---------------------------------------------------------------- CLI and the workflow


def test_cli_summary_surfaces_rejected_batches_derive_and_early_stop() -> None:
    stats = {
        "success": 48,
        "failed": 0,
        "robots-blocked": 0,
        "already-preserved": 3,
        "ia-rejected": 2,
        "flushes": 2,
        "derive-requested": 1,
        "derive-failed": ["leizilla_ro_casacivil_decreto_30001-31000"],
        "aborted": "ia-throttled",
        "wayback-save": {"requested": 50, "accepted": 40, "failed": 4, "dropped": 6},
        "items": [],
    }
    with (
        patch("leizilla.scraper.harvest_pending_resources", return_value=stats),
        patch("leizilla.storage.DuckDBStorage"),
        patch("leizilla.publisher.InternetArchivePublisher"),
    ):
        result = CliRunner().invoke(app, ["harvest"])

    assert result.exit_code == 0
    out = result.output
    assert "Recusados pelo IA (PDF inválido, não serão retentados): 2" in out
    assert "Lotes enviados ao IA: 2" in out
    assert "sem derive: leizilla_ro_casacivil_decreto_30001-31000" in out
    assert "50 pedidos, 40 aceitos, 4 falhas, 6 descartados" in out
    assert "Colheita interrompida cedo: ia-throttled" in out  # echo of any reason


def test_cli_summary_tolerates_stats_from_before_batching() -> None:
    stats = {"success": 1, "failed": 0, "robots-blocked": 0, "items": []}
    with (
        patch("leizilla.scraper.harvest_pending_resources", return_value=stats),
        patch("leizilla.storage.DuckDBStorage"),
        patch("leizilla.publisher.InternetArchivePublisher"),
    ):
        result = CliRunner().invoke(app, ["harvest"])
    assert result.exit_code == 0
    assert "Recusados pelo IA (PDF inválido, não serão retentados): 0" in result.output


def test_workflow_runs_two_tipos_in_parallel_and_bounds_the_harvest_in_time() -> None:
    text = (REPO / ".github/workflows/discover-harvest.yml").read_text()
    # ADR-0016 (adendo 2026-11-17 (2)): back to 2 tipos at a time (was 3): the
    # account-wide IA ration (accesskey_tasks_queued) is shared by every job
    settings = re.findall(r"^\s*max-parallel: (\d+)\s*$", text, flags=re.MULTILINE)
    assert settings == ["2"]
    jobs = text.split("\n  harvest-")[1:]
    assert len(jobs) == 2
    single, parallel = jobs
    # the dispatch-one-tipo job runs alone: keeps the long budget and job limit
    assert "timeout-minutes: 360" in single
    assert 'HARVEST_MAX_SECONDS: "16200"' in single
    # the parallel job: budget + setup/discovery/flush margin fits its own timeout
    harvest_step = parallel[parallel.index("name: Harvest") :].split("\n      - name:")[
        0
    ]
    budget = int(harvest_step.split('HARVEST_MAX_SECONDS: "')[1].split('"')[0])
    job_minutes = int(re.search(r"timeout-minutes: (\d+)", parallel).group(1))  # type: ignore[union-attr]
    assert 0 < budget <= 2700
    assert budget + 40 * 60 <= job_minutes * 60
    # ADR-0016 adendo 2026-11-17: the harvest also stops in time for the job's own
    # end. The deadline is recorded by the first step (before checkout/discovery) and
    # the harvest is handed it, so a slow discovery shortens the harvest, not the job.
    assert job_minutes == 85
    assert parallel.index("JOB_DEADLINE_EPOCH=$(( $(date +%s) + 85 * 60 ))") < (
        parallel.index("uses: actions/checkout@v4")
    )
    assert '--job-deadline "${JOB_DEADLINE_EPOCH}"' in harvest_step
    # the dispatch-one-tipo job keeps its own unbounded-by-deadline shape
    assert "--job-deadline" not in single
    # the biggest tipos are the first wave
    assert "tipo: [lei, lc, decreto," in parallel
    # politeness (ADR-0008): per-job pacing x parallel jobs keeps ~1 req/s combined
    interval = float(harvest_step.split('HARVEST_HOST_INTERVAL_S: "')[1].split('"')[0])
    assert interval >= int(settings[0]) * 1.0
    # the discovery step hits the same host: same pacing factor
    discover_step = parallel[parallel.index("name: Discover") :].split(
        "\n      - name:"
    )[0]
    assert 'HARVEST_HOST_INTERVAL_S: "2.0"' in discover_step
    assert interval == 2.0
    # worst case: 7 tipos on 2 slots = ceil(7/2) = 4 full-length jobs back to back on
    # the busiest slot, inside the 6 h between crons
    assert 4 * job_minutes <= 360


# ------------------------------------- per-item throttle, derive timing, absent streak

ITEM_LOW = "leizilla_ro_casacivil_decreto_30001-31000"
ITEM_QUEUE_FULL = (
    "Please reduce your request rate. - bucket_tasks_queued exceeds rationed amount"
)
ACCOUNT_FULL = (
    "Please reduce your request rate. - total_tasks_queued exceeds rationed amount"
)


def _throttle_item_only(blocked: str, fetched: Optional[List[str]] = None) -> Any:
    """upload_raw_batch fake: ``blocked`` has a full queue, every other item works."""

    def _upload(
        item_id: str,
        captures: List[RawCapture],
        index_cache: Any = None,
        **_: Any,
    ) -> List[Dict[str, Any]]:
        if item_id == blocked:
            return [
                {"success": False, "reason": "ia-throttled", "error": ITEM_QUEUE_FULL}
                for _ in captures
            ]
        return [{"success": True, "item_id": item_id} for _ in captures]

    return _upload


def test_throttle_scope_parses_the_two_real_ia_messages() -> None:
    assert ia_throttle_scope(ITEM_QUEUE_FULL) == "item"
    assert ia_throttle_scope(ACCOUNT_FULL) == "account"
    assert ia_throttle_scope(THROTTLED) == "account"
    # no marker at all: conservative, stop the run
    assert ia_throttle_scope("Please reduce your request rate.") == "account"
    assert ia_throttle_scope("") == "account"
    assert ia_throttle_scope(None) == "account"
    assert ia_throttle_scope(f"{ITEM_QUEUE_FULL} total_tasks_queued") == "account"


def test_per_item_throttle_defers_that_item_and_the_run_continues(
    temp_db: DuckDBStorage, fast_source: None
) -> None:
    high = [31250, 31249, 31248, 31247]  # ITEM, newest first
    low = [30010, 30009]
    for n in [*high, *low]:
        temp_db.insert_resource(_resource(n))
    fetched: List[str] = []

    def fetch(url: str) -> tuple[bytes, bool]:
        fetched.append(url)
        return f"%PDF {url}".encode(), False

    pub = MagicMock()
    pub.preserved_sources.return_value = set()
    pub.upload_raw_batch.side_effect = _throttle_item_only(ITEM)
    pub.request_derive.return_value = True

    stats = _harvest(temp_db, pub, fetch=fetch, limit=10, batch_size=2)

    assert stats["aborted"] is None
    # only the first flush of ITEM was fetched/attempted; 31248/31247 are deferred
    # buckets alternate: 31250, 30010, then 31249 completes ITEM's first flush
    assert [u.rsplit("/", 1)[1] for u in fetched[:3]] == [
        "D31250.pdf",
        "D30010.pdf",
        "D31249.pdf",
    ]
    assert not any(u.endswith(("D31248.pdf", "D31247.pdf")) for u in fetched)
    assert stats["deferred"] == 2 and stats["deferred-items"] == [ITEM]
    assert stats["success"] == 2  # the other item was harvested
    assert stats["failed"] == 2  # the two captures of the rejected flush
    statuses = _statuses(temp_db)
    assert {statuses[f"decreto-{n}"] for n in (31250, 31249, 31248, 31247)} == {
        "pending"
    }
    assert {statuses["decreto-30010"], statuses["decreto-30009"]} == {"downloaded"}
    # the throttled item gets no derive; the finished one does
    pub.request_derive.assert_called_once_with(ITEM_LOW)
    assert ITEM in stats["derive-postponed"]


def test_deferred_resources_do_not_count_against_the_limit(
    temp_db: DuckDBStorage, fast_source: None
) -> None:
    for n in (31250, 31249, 31248, 31247, 30010):
        temp_db.insert_resource(_resource(n))
    pub = MagicMock()
    pub.preserved_sources.return_value = set()
    pub.upload_raw_batch.side_effect = _throttle_item_only(ITEM)

    # limit 3 = the two throttled attempts + the one resource of the other item
    stats = _harvest(temp_db, pub, limit=3, batch_size=2)

    assert stats["deferred"] == 2
    assert _statuses(temp_db)["decreto-30010"] == "downloaded"


def test_account_wide_throttle_still_stops_the_run(
    temp_db: DuckDBStorage, fast_source: None
) -> None:
    for n in (31250, 31249, 30010, 30009):
        temp_db.insert_resource(_resource(n))
    pub = MagicMock()
    pub.preserved_sources.return_value = set()
    pub.upload_raw_batch.side_effect = lambda item_id, captures, index_cache=None: [
        {"success": False, "reason": "ia-throttled", "error": ACCOUNT_FULL}
        for _ in captures
    ]

    stats = _harvest(temp_db, pub, limit=10, batch_size=2)

    assert stats["aborted"] == "ia-account-throttled"
    assert stats["deferred"] == 0
    assert pub.upload_raw_batch.call_count == 1
    assert set(_statuses(temp_db).values()) == {"pending"}


def test_derive_is_requested_only_for_items_with_no_pending_work(
    temp_db: DuckDBStorage, fast_source: None
) -> None:
    # ITEM is finished by this run; ITEM_LOW still has resources beyond the limit
    for n in (31250, 30010, 30009, 30008):
        temp_db.insert_resource(_resource(n))
    pub = MagicMock()
    pub.preserved_sources.return_value = set()
    batch_ok(pub)

    stats = _harvest(temp_db, pub, limit=2)

    assert stats["success"] == 2
    pub.request_derive.assert_called_once_with(ITEM)
    assert stats["derive-requested"] == 1
    assert stats["derive-postponed"] == [ITEM_LOW]


def test_pending_in_other_tipo_or_range_does_not_postpone_the_derive(
    temp_db: DuckDBStorage, fast_source: None
) -> None:
    temp_db.insert_resource(_resource(31250))
    temp_db.insert_resource(_resource(30010))  # lower range: another item
    temp_db.insert_resource(
        {
            **_resource(31249),
            "url": "https://fonte.example/Files/DL31249.pdf",
            "tipo_documento": "decreto-lei",
            "chave": "decreto-lei-31249",
        }
    )
    assert (
        temp_db.count_pending_in_range("ro", "casacivil", "decreto", 31001, 32000) == 1
    )
    pub = MagicMock()
    pub.preserved_sources.return_value = set()
    batch_ok(pub)

    stats = _harvest(temp_db, pub, limit=1)

    assert stats["success"] == 1
    pub.request_derive.assert_called_once_with(ITEM)


def test_item_finished_without_uploads_gets_its_derive(
    temp_db: DuckDBStorage, fast_source: None
) -> None:
    # 31250 was uploaded in an earlier run (its derive was postponed then); the
    # only pending resource left in the item is a confirmed 404 → nothing uploaded
    temp_db.insert_resource(_resource(31249))
    pub = MagicMock()
    pub.preserved_sources.return_value = set()
    pub.request_derive.return_value = True

    stats = _harvest(temp_db, pub, fetch=lambda url: (None, True), limit=10)

    assert stats["success"] == 0 and stats["flushes"] == 0
    assert _statuses(temp_db) == {"decreto-31249": "failed"}
    pub.upload_raw_batch.assert_not_called()
    pub.request_derive.assert_called_once_with(ITEM)
    assert stats["derive-requested"] == 1


def test_item_skipped_as_already_preserved_gets_its_derive_once_finished(
    temp_db: DuckDBStorage, fast_source: None
) -> None:
    temp_db.insert_resource(_resource(31250))
    pub = MagicMock()
    pub.preserved_sources.return_value = {"fonte.example/files/d31250.pdf"}
    pub.request_derive.return_value = True

    stats = _harvest(temp_db, pub, limit=10)

    assert stats["already-preserved"] == 1
    pub.request_derive.assert_called_once_with(ITEM)


def test_untouched_item_without_uploads_and_with_pending_gets_no_derive(
    temp_db: DuckDBStorage, fast_source: None
) -> None:
    temp_db.insert_resource(_resource(31249))
    temp_db.insert_resource(_resource(31248))
    pub = MagicMock()
    pub.preserved_sources.return_value = set()

    stats = _harvest(temp_db, pub, fetch=lambda url: (None, True), limit=1)

    assert stats["failed"] == 1
    pub.request_derive.assert_not_called()
    assert stats["derive-postponed"] == []  # received no files: nothing to report


def test_harvest_derive_zero_still_disables_every_derive(
    temp_db: DuckDBStorage, fast_source: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("leizilla.config.HARVEST_DERIVE", False)
    temp_db.insert_resource(_resource(31250))  # uploaded, item finished
    temp_db.insert_resource(_resource(30010))  # failed permanently, item finished

    def fetch(url: str) -> tuple[Optional[bytes], bool]:
        if url.endswith("D30010.pdf"):
            return None, True
        return b"%PDF-1.4", False

    pub = MagicMock()
    pub.preserved_sources.return_value = set()
    batch_ok(pub)

    stats = _harvest(temp_db, pub, fetch=fetch, limit=10)

    pub.request_derive.assert_not_called()
    assert stats["derive-requested"] == 0
    assert stats["derive-failed"] == [ITEM]


def test_consecutive_absent_documents_without_a_success_end_the_run_early(
    temp_db: DuckDBStorage, fast_source: None
) -> None:
    for n in range(1, 81):
        temp_db.insert_resource(_resource(n))
    calls: List[str] = []

    def fetch(url: str) -> tuple[None, bool]:
        calls.append(url)
        return None, True

    pub = MagicMock()
    pub.preserved_sources.return_value = set()

    stats = _harvest(temp_db, pub, fetch=fetch, limit=80)

    assert len(calls) == 50
    assert stats["aborted"] == "sequência de documentos inexistentes"
    statuses = list(_statuses(temp_db).values())
    assert statuses.count("failed") == 50 and statuses.count("pending") == 30


def test_a_success_resets_the_absent_streak(
    temp_db: DuckDBStorage, fast_source: None
) -> None:
    for n in range(1, 111):
        temp_db.insert_resource(_resource(n))

    def fetch(url: str) -> tuple[Optional[bytes], bool]:
        # newest first: 110 .. 61 absent (50 would trip), but 60 is a hit
        n = int(url.rsplit("D", 1)[1].split(".")[0])
        if n == 80:
            return b"%PDF-1.4", False
        return None, True

    pub = MagicMock()
    pub.preserved_sources.return_value = set()
    batch_ok(pub)

    stats = _harvest(temp_db, pub, fetch=fetch, limit=200)

    # 110..81 = 30 absent, a hit at 80, then 79..1 = 79 absent: never 50 in a row
    # before the first success, and afterwards the streak no longer ends the run
    assert stats["aborted"] is None
    assert stats["success"] == 1 and stats["failed"] == 109


def test_a_streak_just_under_the_threshold_does_not_stop(
    temp_db: DuckDBStorage, fast_source: None
) -> None:
    for n in range(1, 50):
        temp_db.insert_resource(_resource(n))
    pub = MagicMock()
    pub.preserved_sources.return_value = set()

    stats = _harvest(temp_db, pub, fetch=lambda url: (None, True), limit=100)

    assert stats["aborted"] is None and stats["failed"] == 49


def test_cli_summary_reports_deferred_items_and_postponed_derives() -> None:
    stats = {
        "success": 3,
        "failed": 2,
        "robots-blocked": 0,
        "derive-postponed": [ITEM],
        "deferred": 7,
        "deferred-items": [ITEM],
        "items": [{"status": "failed", "chave": "x", "reason": "ia-throttled"}],
    }
    with (
        patch("leizilla.scraper.harvest_pending_resources", return_value=stats),
        patch("leizilla.storage.DuckDBStorage"),
        patch("leizilla.publisher.InternetArchivePublisher"),
    ):
        result = CliRunner().invoke(app, ["harvest"])

    assert result.exit_code == 0  # captures plus deferrals is a success
    assert "adiados (item com fila cheia no IA): 7 em 1 item(ns)" in result.output
    assert f"adiado: {ITEM}" in result.output
    assert "derive adiado: 1 item(ns) ainda com pendências" in result.output


def test_cli_fails_when_everything_was_deferred_by_item_throttling() -> None:
    stats = {
        "success": 0,
        "failed": 0,
        "robots-blocked": 0,
        "deferred": 5,
        "deferred-items": [ITEM],
        "items": [],
    }
    with (
        patch("leizilla.scraper.harvest_pending_resources", return_value=stats),
        patch("leizilla.storage.DuckDBStorage"),
        patch("leizilla.publisher.InternetArchivePublisher"),
    ):
        result = CliRunner().invoke(app, ["harvest"])

    assert result.exit_code == 1


def test_workflow_runs_four_times_a_day_and_the_whole_run_fits_the_interval() -> None:
    text = (REPO / ".github/workflows/discover-harvest.yml").read_text()
    for hour in (2, 8, 14, 20):
        assert f'cron: "0 {hour} * * *"' in text
    assert text.count('HARVEST_MAX_SECONDS: "2700"') == 1
    assert "inputs.limit || '3000'" in text and 'default: "3000"' in text
    # 7 tipos / 2 slots = 4 jobs in sequence on the busiest slot; each job is at most
    # 45 min of harvest + 40 min margin = 85 min (the job timeout)
    assert 4 * (2700 + 40 * 60) <= 6 * 3600
    # overlapping runs queue behind the singleton group instead of cancelling it
    assert "cancel-in-progress: false" in text


# ------------------------------------------- end to end: real publisher, fake `ia` CLI


def test_end_to_end_one_index_write_per_flush_and_a_single_final_derive(
    temp_db: DuckDBStorage,
    fast_source: None,
    pub: InternetArchivePublisher,
    ia: FakeIA,
) -> None:
    numbers = list(range(31240, 31251))  # 11 norms, one IA item
    for n in numbers:
        temp_db.insert_resource(_resource(n))
    with (
        patch.object(publisher, "_fetch_existing_index", return_value=None) as fetch,
        patch("leizilla.scraper.robots.is_allowed", return_value=True),
        patch(
            "leizilla.scraper.wayback.fetch_bytes_detailed",
            side_effect=lambda url: (f"%PDF-1.4 {url}".encode(), False),
        ),
    ):
        stats = harvest_pending_resources(temp_db, pub, limit=50, batch_size=5)

    assert stats["success"] == 11 and stats["failed"] == 0
    # 11 captures in batches of 5: three `ia upload` calls, then exactly one derive
    assert [c[1] for c in ia.calls] == ["upload", "upload", "upload", "tasks"]
    assert ia.calls[-1] == ["ia", "tasks", ITEM, "--cmd", "derive.php"]
    assert all("--no-derive" in c for c in ia.uploads)
    # 5 + 5 + 1 PDFs, each flush plus its index (was 11/11/3 with sidecars)
    assert [len(ia.files(c)) for c in ia.uploads] == [6, 6, 2]
    # one read for "what is already preserved", one for the first flush; the later
    # flushes build on the cached index instead of re-reading IA
    assert fetch.call_count == 2
    # no row is ever lost: each index is a superset of the previous one
    written = [[row["numero"] for row in _index_rows(i)] for i in ia.indexes]
    assert [len(w) for w in written] == [5, 10, 11]
    assert written[1][:5] == written[0] and written[2][:10] == written[1]
    assert sorted(written[-1]) == sorted(str(n) for n in numbers)
    assert written[-1][0] == "31250"  # newest first
    assert set(_statuses(temp_db).values()) == {"downloaded"}
    sources = {row["source"] for row in _index_rows(ia.indexes[-1])}
    assert sources == {f"https://fonte.example/Files/D{n}.pdf" for n in numbers}


# ------------------------------- per-file "spam" rejection and fail-fast item ration

SPAM = "Uploaded content is unacceptable. - pdf file looks like spam"


def test_spam_rejection_mid_batch_uploads_the_rest_and_writes_the_index(
    pub: InternetArchivePublisher, ia: FakeIA
) -> None:
    captures = [_capture(31250), _capture(31249, b"%PDF-spam"), _capture(31248)]
    bad_name = f"decreto-31249_{publisher.uuid5_name(b'%PDF-spam')}.pdf"

    def spam(args: List[str]) -> Optional[str]:
        if bad_name in FakeIA.files(args):
            return f"{ITEM}:\n error uploading {bad_name}: {SPAM}\n"
        return None

    ia.fail_when(spam)
    cache: Dict[str, str] = {}
    with (
        patch.object(publisher, "_fetch_existing_index", return_value=None),
        patch("time.sleep") as sleep,
    ):
        results = pub.upload_raw_batch(ITEM, captures, cache)

    assert [r.get("reason") for r in results] == [None, "ia-rejected", None]
    assert results[1]["rejection"] == "spam"
    sleep.assert_not_called()
    # first call carried the culprit (files before it went up); the retry drops it,
    # re-sends the others (--checksum skips what is there) and writes the index
    assert len(ia.uploads) == 2
    assert "--checksum" in ia.uploads[1]
    assert bad_name not in ia.files(ia.uploads[1])
    assert ia.files(ia.uploads[1])[-1] == "index.csv"
    assert [row["numero"] for row in _index_rows(cache[ITEM])] == ["31250", "31248"]


def test_generic_failure_is_still_upload_failed_with_backoff(
    pub: InternetArchivePublisher, ia: FakeIA
) -> None:
    ia.fail_when(lambda args: "error uploading x.pdf: connection reset by peer")
    with (
        patch.object(publisher, "_fetch_existing_index", return_value=None),
        patch("time.sleep") as sleep,
    ):
        results = pub.upload_raw_batch(ITEM, [_capture(1)], {})
    assert results[0]["reason"] == "upload-failed"
    assert len(ia.uploads) == publisher._IA_BATCH_MAX_ATTEMPTS
    assert sleep.call_count == publisher._IA_BATCH_MAX_ATTEMPTS - 1


def test_item_ration_fails_fast_without_long_backoff(
    pub: InternetArchivePublisher, ia: FakeIA
) -> None:
    ia.fail_when(lambda args: f" error uploading x.pdf: {ITEM_QUEUE_FULL}")
    with (
        patch.object(publisher, "_fetch_existing_index", return_value=None),
        patch("time.sleep") as sleep,
    ):
        results = pub.upload_raw_batch(ITEM, [_capture(1), _capture(2)], {})

    assert [r["reason"] for r in results] == ["ia-throttled"] * 2
    assert ia_throttle_scope(results[0]["error"]) == "item"
    assert len(ia.uploads) == 1
    sleep.assert_not_called()


@pytest.mark.parametrize(
    "message",
    [ACCOUNT_FULL, ACCESSKEY_FULL, THROTTLED, "x: foo_tasks_queued exceeds y"],
)
def test_account_queue_full_fails_fast_in_harvest(
    pub: InternetArchivePublisher, ia: FakeIA, message: str
) -> None:
    # Was: the account limit kept the 60 s + 120 s backoffs (3 attempts). Now every
    # queue-full scope fails fast: one attempt, no sleep, scope reported as account.
    ia.fail_when(lambda args: f" error uploading x.pdf: {message}")
    with (
        patch.object(publisher, "_fetch_existing_index", return_value=None),
        patch("time.sleep") as sleep,
    ):
        results = pub.upload_raw_batch(ITEM, [_capture(1)], {})
    assert results[0]["reason"] == "ia-throttled" and results[0]["scope"] == "account"
    assert len(ia.uploads) == 1
    sleep.assert_not_called()


def test_item_ration_still_waits_for_dataset_uploads_with_queue_wait(
    pub: InternetArchivePublisher, ia: FakeIA
) -> None:
    # the fail-fast is opt-in: other callers (reocr/dataset) keep their behaviour
    calls = {"n": 0}

    def run(args: List[str], **_: Any) -> "subprocess.CompletedProcess[str]":
        calls["n"] += 1
        if calls["n"] == 1:
            raise subprocess.CalledProcessError(1, args, stderr=ITEM_QUEUE_FULL)
        return subprocess.CompletedProcess(args, 0, "", "")

    with patch.object(subprocess, "run", side_effect=run), patch("time.sleep"):
        pub._run_ia_upload(["ia", "upload"], queue_wait=publisher.IaQueueWait(600.0))
    assert calls["n"] == 2


def test_spam_rejections_in_consecutive_flushes_do_not_abort_the_harvest(
    temp_db: DuckDBStorage, fast_source: None
) -> None:
    for n in (31250, 31249, 31248, 31247, 31246, 31245):
        temp_db.insert_resource(_resource(n))
    spam_numbers = {31249, 31247}

    def upload(
        item_id: str,
        captures: List[RawCapture],
        index_cache: Any = None,
        **_: Any,
    ) -> Any:
        return [
            {
                "success": False,
                "reason": "ia-rejected",
                "rejection": "spam",
                "error": SPAM,
            }
            if c.target.numero in spam_numbers
            else {"success": True, "ia_url": "u"}
            for c in captures
        ]

    pub = MagicMock()
    pub.preserved_sources.return_value = set()
    pub.upload_raw_batch.side_effect = upload
    pub.request_derive.return_value = True

    stats = _harvest(temp_db, pub, limit=10, batch_size=2)

    assert stats["aborted"] is None
    assert pub.upload_raw_batch.call_count == 3  # all three flushes happened
    assert stats["ia-rejected"] == 2 and stats["ia-rejected-spam"] == 2
    assert stats["success"] == 4 and stats["failed"] == 0
    rows = (
        temp_db.connect()
        .execute(
            "SELECT chave, status, motivo, url FROM discovered_resources "
            "WHERE status = 'ia-rejected' ORDER BY chave"
        )
        .fetchall()
    )
    assert [(r[0], r[1], r[2]) for r in rows] == [
        ("decreto-31247", "ia-rejected", "spam"),
        ("decreto-31249", "ia-rejected", "spam"),
    ]
    assert all(r[3].startswith("https://fonte.example/") for r in rows)
    reasons = {i["reason"] for i in stats["items"] if i["status"] == "ia-rejected"}
    assert reasons == {"ia-rejected: spam"}


def test_old_database_gets_the_motivo_column(tmp_path: Path) -> None:
    import duckdb

    path = tmp_path / "old.duckdb"
    conn = duckdb.connect(str(path))
    conn.execute(
        "CREATE TABLE discovered_resources (url VARCHAR PRIMARY KEY, ente VARCHAR "
        "NOT NULL, fonte VARCHAR NOT NULL, tipo_documento VARCHAR, chave VARCHAR, "
        "status VARCHAR DEFAULT 'pending', data_descoberta TIMESTAMP DEFAULT "
        "CURRENT_TIMESTAMP, ultima_tentativa TIMESTAMP, wayback_snapshot VARCHAR)"
    )
    conn.close()
    db = DuckDBStorage(path)
    db.insert_resource(_resource(1))
    db.update_resource_status(_resource(1)["url"], "ia-rejected", motivo="spam")
    assert db.connect().execute(
        "SELECT motivo FROM discovered_resources"
    ).fetchall() == [("spam",)]
    db.close()


def test_cli_summary_counts_spam_separately() -> None:
    stats = {
        "success": 1,
        "failed": 0,
        "robots-blocked": 0,
        "ia-rejected": 4,
        "ia-rejected-spam": 3,
        "items": [],
    }
    with (
        patch("leizilla.scraper.harvest_pending_resources", return_value=stats),
        patch("leizilla.storage.DuckDBStorage"),
        patch("leizilla.publisher.InternetArchivePublisher"),
    ):
        result = CliRunner().invoke(app, ["harvest"])
    assert "Recusados pelo IA" in result.output
    assert ": 4 (spam: 3)" in result.output


def test_harvest_host_interval_comes_from_config(
    temp_db: DuckDBStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: List[float] = []
    monkeypatch.setattr(
        "leizilla.scraper.make_rate_limiter",
        lambda interval=1.0: seen.append(interval) or (lambda _url: None),
    )
    monkeypatch.setattr("leizilla.config.HARVEST_HOST_INTERVAL_S", 3.0)
    pub = MagicMock()
    _harvest(temp_db, pub, limit=1)
    assert seen == [3.0]


# ----------------------------------- ADR-0016 (adendo 2026-11-17): recusa, prazo, resumo

SYNTAX = (
    "Uploaded content is unacceptable. - Syntax error detected in pdf data. You may "
    "be able to repair the pdf file with a repair tool, pdftk is one such tool."
)


def test_syntax_error_rejection_is_terminal_and_the_rest_lands(
    pub: InternetArchivePublisher, ia: FakeIA
) -> None:
    captures = [_capture(31250), _capture(31249, b"%PDF-syntax"), _capture(31248)]
    bad_name = f"decreto-31249_{publisher.uuid5_name(b'%PDF-syntax')}.pdf"

    def syntax(args: List[str]) -> Optional[str]:
        if bad_name in FakeIA.files(args):
            return f"{ITEM}:\n error uploading {bad_name}: {SYNTAX}\n"
        return None

    ia.fail_when(syntax)
    cache: Dict[str, str] = {}
    with (
        patch.object(publisher, "_fetch_existing_index", return_value=None),
        patch("time.sleep") as sleep,
    ):
        results = pub.upload_raw_batch(ITEM, captures, cache)

    assert [r.get("reason") for r in results] == [None, "ia-rejected", None]
    assert results[1]["rejection"] == "pdf-syntax"
    sleep.assert_not_called()  # permanent: no backoff, no retry of the same file
    assert len(ia.uploads) == 2
    assert bad_name not in ia.files(ia.uploads[1])
    assert [row["numero"] for row in _index_rows(cache[ITEM])] == ["31250", "31248"]


def test_unknown_content_rejection_is_kept_as_other(
    pub: InternetArchivePublisher, ia: FakeIA
) -> None:
    captures = [_capture(31250), _capture(31249, b"%PDF-new")]
    bad_name = f"decreto-31249_{publisher.uuid5_name(b'%PDF-new')}.pdf"

    def new_reason(args: List[str]) -> Optional[str]:
        if bad_name in FakeIA.files(args):
            return (
                f"{ITEM}:\n error uploading {bad_name}: "
                "Uploaded content is unacceptable - something new\n"
            )
        return None

    ia.fail_when(new_reason)
    with (
        patch.object(publisher, "_fetch_existing_index", return_value=None),
        patch("time.sleep") as sleep,
    ):
        results = pub.upload_raw_batch(ITEM, captures, {})

    assert [r.get("reason") for r in results] == [None, "ia-rejected"]
    assert results[1]["rejection"] == "other: something new"
    sleep.assert_not_called()
    assert results[0]["success"] is True


@pytest.mark.parametrize(
    ("stderr", "kind"),
    [
        (
            "error uploading f.pdf: Uploaded content is unacceptable. - pdf file looks like spam",
            "spam",
        ),
        (f"error uploading f.pdf: {SYNTAX}", "pdf-syntax"),
        (
            "error uploading f.pdf: Uploaded content is unacceptable. - error checking pdf file",
            "pdf-check",
        ),
        (
            "error uploading f.pdf: Uploaded content is unacceptable - something new",
            "other: something new",
        ),
        ("error uploading f.pdf: Uploaded content is unacceptable.", "other"),
    ],
)
def test_rejection_kind_classifies_known_and_unknown_reasons(
    stderr: str, kind: str
) -> None:
    assert publisher._rejection_kind(stderr) == kind


def test_rejection_kind_truncates_an_unknown_reason() -> None:
    long = "x" * 500
    kind = publisher._rejection_kind(f"Uploaded content is unacceptable - {long}")
    assert kind == "other: " + "x" * 120


def test_syntax_rejection_is_stored_with_its_reason_and_counted(
    temp_db: DuckDBStorage, fast_source: None
) -> None:
    for n in (31250, 31249):
        temp_db.insert_resource(_resource(n))

    def upload(
        item_id: str,
        captures: List[RawCapture],
        index_cache: Any = None,
        **_: Any,
    ) -> Any:
        return [
            {"success": False, "reason": "ia-rejected", "rejection": "pdf-syntax"}
            if c.target.numero == 31249
            else {"success": True, "ia_url": "u"}
            for c in captures
        ]

    pub = MagicMock()
    pub.preserved_sources.return_value = set()
    pub.upload_raw_batch.side_effect = upload

    stats = _harvest(temp_db, pub, limit=10)

    rows = temp_db.connect().execute(
        "SELECT chave, status, motivo FROM discovered_resources ORDER BY chave"
    )
    assert rows.fetchall() == [
        ("decreto-31249", "ia-rejected", "pdf-syntax"),
        ("decreto-31250", "downloaded", None),
    ]
    assert stats["ia-rejected"] == 1
    assert stats["ia-rejected-reasons"] == {"pdf-syntax": 1}
    assert stats["success"] == 1 and stats["failed"] == 0


def test_cli_summary_lists_the_other_rejection_reasons() -> None:
    stats = {
        "success": 1,
        "failed": 0,
        "robots-blocked": 0,
        "ia-rejected": 6,
        "ia-rejected-spam": 3,
        "ia-rejected-reasons": {"spam": 3, "pdf-syntax": 1, "other": 2},
        "items": [],
    }
    with (
        patch("leizilla.scraper.harvest_pending_resources", return_value=stats),
        patch("leizilla.storage.DuckDBStorage"),
        patch("leizilla.publisher.InternetArchivePublisher"),
    ):
        result = CliRunner().invoke(app, ["harvest"])
    assert ": 6 (spam: 3)" in result.output
    assert "- pdf-syntax: 1" in result.output
    assert "- other: 2" in result.output
    assert "- spam:" not in result.output  # spam is already in the line above


def test_budget_is_the_smaller_of_cap_and_time_left_before_the_job_dies() -> None:
    from leizilla.scraper import HARVEST_TAIL_RESERVE_S, harvest_budget_s

    now = 1_000_000.0
    job_end = now + 7200  # the job dies two hours from now
    assert harvest_budget_s(cap_s=4500, job_deadline_epoch=None, now_epoch=now) == 4500
    assert harvest_budget_s(cap_s=0, job_deadline_epoch=None, now_epoch=now) is None
    # discovery ate 42 min: 120 - 42 - 20 (reserve) = 58 min, below the 75 min cap
    left = harvest_budget_s(
        cap_s=4500, job_deadline_epoch=job_end, now_epoch=now + 42 * 60
    )
    assert left == pytest.approx(7200 - 42 * 60 - HARVEST_TAIL_RESERVE_S)
    assert left < 4500
    # with nothing spent yet the cap wins
    assert (
        harvest_budget_s(cap_s=4500, job_deadline_epoch=job_end, now_epoch=now) == 4500
    )


def test_harvest_with_no_useful_time_left_fetches_nothing(
    temp_db: DuckDBStorage, fast_source: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time as _time

    monkeypatch.setattr("leizilla.config.HARVEST_MAX_SECONDS", 0.0)
    temp_db.insert_resource(_resource(31250))
    pub = MagicMock()
    pub.preserved_sources.return_value = set()
    fetch = MagicMock(return_value=(b"%PDF-1.4 x", False))
    # the job dies in 10 min: less than the 20 min reserve, so nothing to spend
    stats = _harvest(
        temp_db, pub, fetch=fetch, limit=10, job_deadline_epoch=_time.time() + 600
    )

    assert stats["aborted"] == "no-time-left"
    fetch.assert_not_called()
    pub.upload_raw_batch.assert_not_called()
    assert _statuses(temp_db) == {"decreto-31250": "pending"}


def test_harvest_stops_fetching_in_time_for_the_tail_flush(
    temp_db: DuckDBStorage, fast_source: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time as _time

    from leizilla.scraper import HARVEST_TAIL_RESERVE_S

    monkeypatch.setattr("leizilla.config.HARVEST_MAX_SECONDS", 0.0)
    for n in (31250, 31249):
        temp_db.insert_resource(_resource(n))
    pub = MagicMock()
    pub.preserved_sources.return_value = set()
    batch_ok(pub)
    # 30 min of job left: 10 min of fetching budget after the 20 min reserve
    stats = _harvest(
        temp_db,
        pub,
        limit=10,
        job_deadline_epoch=_time.time() + HARVEST_TAIL_RESERVE_S + 600,
    )
    assert stats["aborted"] is None
    assert stats["success"] == 2  # both fit in the 10 min budget and are flushed


def test_stats_dict_passed_in_is_filled_even_when_the_harvest_raises(
    temp_db: DuckDBStorage, fast_source: None
) -> None:
    temp_db.insert_resource(_resource(31250))
    pub = MagicMock()
    pub.preserved_sources.return_value = set()
    stats: Dict[str, Any] = {}
    boom = MagicMock(side_effect=RuntimeError("source exploded"))
    with pytest.raises(RuntimeError):
        _harvest(temp_db, pub, fetch=boom, limit=10, stats=stats)
    # the caller's dict is the one filled in, so a partial summary is still printable
    assert stats["success"] == 0 and stats["flushes"] == 0
    assert stats["aborted"] is None


def test_cli_prints_the_summary_when_the_harvest_raises() -> None:
    def boom(db: Any, pub: Any, **kwargs: Any) -> Dict[str, Any]:
        kwargs["stats"].update({"success": 2, "failed": 0, "items": []})
        raise RuntimeError("boom")

    with (
        patch("leizilla.scraper.harvest_pending_resources", side_effect=boom),
        patch("leizilla.storage.DuckDBStorage"),
        patch("leizilla.publisher.InternetArchivePublisher"),
    ):
        result = CliRunner().invoke(app, ["harvest"])
    assert result.exit_code == 1
    assert "Colheita parcial" in result.output
    assert "Sucesso: 2" in result.output
    assert "Erro: boom" in result.output


def test_cli_passes_the_job_deadline_to_the_harvest() -> None:
    stats = {"success": 0, "failed": 0, "items": []}
    with (
        patch(
            "leizilla.scraper.harvest_pending_resources", return_value=stats
        ) as harvest,
        patch("leizilla.storage.DuckDBStorage"),
        patch("leizilla.publisher.InternetArchivePublisher"),
    ):
        CliRunner().invoke(app, ["harvest", "--job-deadline", "1700000000"])
    assert harvest.call_args.kwargs["job_deadline_epoch"] == 1700000000.0


def test_cache_restore_prefix_never_matches_another_tipo() -> None:
    # achado 2026-11-17: "discover-db-decreto-" restored the decreto-lei cache. The
    # restore prefix must end in a terminator that no other tipo's key can contain.
    text = (REPO / ".github/workflows/discover-harvest.yml").read_text()
    prefixes = re.findall(
        r"^\s+(discover-db-\$\{\{ matrix\.tipo \}\}--)\s*$", text, re.M
    )
    assert prefixes == ["discover-db-${{ matrix.tipo }}--"]
    tipos = ["lei", "lc", "decreto", "ec", "resolucao", "portaria", "decreto-lei"]
    for tipo in tipos:
        prefix = f"discover-db-{tipo}--"
        keys = [f"discover-db-{other}--123" for other in tipos]
        assert [k.startswith(prefix) for k in keys].count(True) == 1


# ------------------------------- account throttle, flush deadline, one PUT per capture
# (ADR-0016 addendum 2026-11-17 (2))


class _SubprocessSpy:
    """``subprocess.run`` stand-in that records the ``timeout`` it was handed."""

    def __init__(
        self, fail: Optional[Callable[[List[str]], Optional[Exception]]] = None
    ):
        self.fail = fail
        self.calls: List[List[str]] = []
        self.timeouts: List[Optional[float]] = []

    def __call__(
        self, args: List[str], **kwargs: Any
    ) -> "subprocess.CompletedProcess[str]":
        self.calls.append(list(args))
        self.timeouts.append(kwargs.get("timeout"))
        if self.fail is not None:
            exc = self.fail(args)
            if exc is not None:
                raise exc
        return subprocess.CompletedProcess(args, 0, "", "")


def _real_harvest(
    db: DuckDBStorage, pub: InternetArchivePublisher, **kwargs: Any
) -> Dict[str, Any]:
    with (
        patch.object(publisher, "_fetch_existing_index", return_value=None),
        patch("leizilla.scraper.robots.is_allowed", return_value=True),
        patch(
            "leizilla.scraper.wayback.fetch_bytes_detailed",
            side_effect=lambda url: (f"%PDF-1.4 {url}".encode(), False),
        ),
    ):
        return harvest_pending_resources(db, pub, **kwargs)


def test_account_throttle_ends_the_run_with_captures_back_to_pending(
    temp_db: DuckDBStorage,
    fast_source: None,
    pub: InternetArchivePublisher,
    ia: FakeIA,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The 2026-11-17 message: a ration per ACCESS KEY, not per item.
    ia.fail_when(lambda args: f" error uploading x.pdf: {ACCESSKEY_FULL}")
    sleeps: List[float] = []
    monkeypatch.setattr("time.sleep", sleeps.append)
    for n in range(31250, 31244, -1):
        temp_db.insert_resource(_resource(n))

    stats = _real_harvest(temp_db, pub, limit=20, batch_size=3)

    assert stats["aborted"] == "ia-account-throttled"
    assert stats["success"] == 0
    # not a failure of the documents: counted as requeued, never as "failed"
    assert stats["failed"] == 0 and stats["requeued"] == 3
    assert set(_statuses(temp_db).values()) == {"pending"}
    assert len(ia.uploads) == 1  # one attempt, no retry...
    assert sleeps == []  # ...and no sleep at all (zero long waits)
    assert [
        c for c in ia.calls if c[1] == "tasks"
    ] == []  # no derive on a throttled run
    assert {item["status"] for item in stats["items"]} == {"requeued"}
    # nothing more is fetched/uploaded after the trip: only the first flush happened
    assert stats["flushes"] == 1


def test_account_throttle_requeues_the_other_buffers_too(
    temp_db: DuckDBStorage, fast_source: None
) -> None:
    for n in (31250, 31249, 30010, 31248):
        temp_db.insert_resource(_resource(n))
    pub = MagicMock()
    pub.preserved_sources.return_value = set()
    pub.upload_raw_batch.side_effect = (
        lambda item_id, captures, index_cache=None, **_: [
            {
                "success": False,
                "reason": "ia-throttled",
                "scope": "account",
                "error": ACCESSKEY_FULL,
            }
            for _ in captures
        ]
    )

    stats = _harvest(temp_db, pub, limit=10, batch_size=2)

    assert stats["aborted"] == "ia-account-throttled"
    # the 30xxx capture was still buffered when the run stopped: back to pending too,
    # as requeued (not failed)
    assert stats["failed"] == 0
    assert stats["requeued"] == 3
    assert set(_statuses(temp_db).values()) == {"pending"}
    pub.request_derive.assert_not_called()


def test_cli_exit_code_on_an_account_throttle() -> None:
    base = {
        "failed": 0,
        "requeued": 4,
        "robots-blocked": 0,
        "aborted": "ia-account-throttled",
        "items": [{"status": "requeued", "reason": "ia-account-throttled"}] * 4,
    }

    def run(success: int) -> Any:
        with (
            patch(
                "leizilla.scraper.harvest_pending_resources",
                return_value={**base, "success": success},
            ),
            patch("leizilla.storage.DuckDBStorage"),
            patch("leizilla.publisher.InternetArchivePublisher"),
        ):
            return CliRunner().invoke(app, ["harvest"])

    partial = run(success=7)
    assert partial.exit_code == 0  # something was preserved: a throttle is not a break
    assert "Colheita interrompida cedo: ia-account-throttled" in partial.output
    assert "Falhas: 0" in partial.output
    assert "Devolvidas à fila (pending, não são falhas dos documentos): 4" in (
        partial.output
    )
    nothing = run(success=0)
    assert nothing.exit_code == 1  # nothing preserved: the job must not look green
    assert "nenhuma captura preservada" in nothing.output


def test_run_ia_upload_deadline_bounds_the_subprocess_and_the_backoff(
    pub: InternetArchivePublisher, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = _SubprocessSpy()
    monkeypatch.setattr(subprocess, "run", spy)
    pub._run_ia_upload(["ia", "upload", "x"], timeout_s=100.0)
    assert spy.timeouts[0] is not None and 0 < spy.timeouts[0] <= 100.0

    # a retryable failure whose backoff does not fit in what is left: no sleep, no
    # second attempt, TimeoutExpired
    spy2 = _SubprocessSpy(
        lambda a: subprocess.CalledProcessError(1, a, stderr="connection reset")
    )
    monkeypatch.setattr(subprocess, "run", spy2)
    slept: List[float] = []
    monkeypatch.setattr("time.sleep", slept.append)
    with pytest.raises(subprocess.TimeoutExpired):
        pub._run_ia_upload(
            ["ia", "upload", "x"], timeout_s=30.0, max_attempts=3, base_delay=60.0
        )
    assert len(spy2.calls) == 1 and slept == []

    # without a budget the call is exactly what it was: no `timeout` kwarg at all
    spy3 = _SubprocessSpy()
    monkeypatch.setattr(subprocess, "run", spy3)
    pub._run_ia_upload(["ia", "upload", "x"])
    assert spy3.timeouts == [None]


def test_flush_timeout_returns_the_captures_to_pending_and_prints_the_summary(
    temp_db: DuckDBStorage,
    fast_source: None,
    pub: InternetArchivePublisher,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spy = _SubprocessSpy(
        lambda a: subprocess.TimeoutExpired(a, 1.0) if a[1] == "upload" else None
    )
    monkeypatch.setattr(subprocess, "run", spy)
    for n in (31250, 31249):
        temp_db.insert_resource(_resource(n))
    deadline = time.time() + 2000  # 20 min tail reserve leaves ~13 min of harvest

    stats = _real_harvest(
        temp_db, pub, limit=10, batch_size=2, job_deadline_epoch=deadline
    )

    # the upload got what is left of the job minus the 3 min for the summary
    upload_timeout = next(
        t for c, t in zip(spy.calls, spy.timeouts) if c[1] == "upload"
    )
    assert upload_timeout is not None
    assert 2000 - 180 - 60 < upload_timeout <= 2000 - 180
    assert stats["aborted"] == "flush-timeout"
    assert stats["failed"] == 0 and stats["requeued"] == 2 and stats["success"] == 0
    assert set(_statuses(temp_db).values()) == {"pending"}
    assert [c for c in spy.calls if c[1] == "tasks"] == []  # no derive after it

    # the same stats print as a normal summary (the run is not killed silently)
    with (
        patch("leizilla.scraper.harvest_pending_resources", return_value=stats),
        patch("leizilla.storage.DuckDBStorage"),
        patch("leizilla.publisher.InternetArchivePublisher"),
    ):
        result = CliRunner().invoke(app, ["harvest"])
    assert "Colheita interrompida cedo: flush-timeout" in result.output
    assert result.exit_code == 1  # nothing preserved


def test_batcher_with_no_time_left_never_calls_ia(temp_db: DuckDBStorage) -> None:
    from leizilla.scraper import _RawBatcher, _Staged

    pub = MagicMock()
    stats: Dict[str, Any] = {
        "success": 0,
        "failed": 0,
        "requeued": 0,
        "flushes": 0,
        "items": [],
        "derive-failed": [],
        "derive-postponed": [],
        "derive-requested": 0,
        "ia-rejected-reasons": {},
    }
    batcher = _RawBatcher(
        temp_db, pub, stats, batch_size=10, flush_deadline_epoch=time.time() - 1
    )
    cap = _capture(31250)
    url = "https://fonte.example/Files/D31250.pdf"
    temp_db.insert_resource(_resource(31250))
    batcher.add(
        _Staged(
            capture=cap,
            url=url,
            chave="decreto-31250",
            ente="ro",
            tipo="decreto",
            wayback_snapshot=None,
        )
    )
    batcher.finish()

    pub.upload_raw_batch.assert_not_called()
    pub.request_derive.assert_not_called()
    assert batcher.abort_reason == "flush-timeout"
    assert stats["requeued"] == 1 and stats["failed"] == 0
    assert _statuses(temp_db) == {"decreto-31250": "pending"}


def test_derive_gets_the_remaining_time_when_there_is_a_deadline(
    temp_db: DuckDBStorage, fast_source: None
) -> None:
    temp_db.insert_resource(_resource(31250))
    pub = MagicMock()
    pub.preserved_sources.return_value = set()
    batch_ok(pub)
    _harvest(
        temp_db, pub, limit=10, batch_size=5, job_deadline_epoch=time.time() + 3000
    )
    assert pub.request_derive.call_count == 1
    assert 0 < pub.request_derive.call_args.kwargs["timeout_s"] <= 3000 - 180
    assert pub.upload_raw_batch.call_args.kwargs["timeout_s"] <= 3000 - 180


def test_batched_flush_is_one_put_per_capture_plus_the_index(
    pub: InternetArchivePublisher, ia: FakeIA
) -> None:
    captures = [_capture(n) for n in (31250, 31249, 31248, 31247)]
    with patch.object(publisher, "_fetch_existing_index", return_value=None):
        pub.upload_raw_batch(ITEM, captures, {})
    files = ia.files(ia.uploads[0])
    # before: 2 per capture + the index (9 PUTs for 4 captures); now 1 per capture
    assert len(files) == len(captures) + 1 == 5
    assert files[-1] == "index.csv"
    assert not any("_meta" in f for f in files)


def test_index_rows_carry_the_provenance_the_sidecar_used_to_hold(
    pub: InternetArchivePublisher, ia: FakeIA
) -> None:
    snapshot = (
        "https://web.archive.org/web/20261115120000/"
        "https://fonte.example/Files/D31249.pdf"
    )
    direct = _capture(31250)
    lei_data = {**_capture(31249).lei_data, "wayback_timestamp": "20261115120000"}
    from_wayback = make_raw_capture(
        lei_data, b"%PDF-1.4 snapshot bytes", "wayback", wayback_url=snapshot
    )
    with patch.object(publisher, "_fetch_existing_index", return_value=None):
        pub.upload_raw_batch(ITEM, [direct, from_wayback], {})

    rows = {r["numero"]: r for r in _index_rows(ia.indexes[0])}
    assert rows["31250"]["fetched_from"] == "source-direct"
    assert rows["31250"]["wayback_url"] == ""
    assert rows["31250"]["wayback_timestamp"] == ""
    assert rows["31250"]["wayback_blocked_robots"] == "false"
    assert rows["31250"]["user_agent"] == publisher._USER_AGENT
    assert rows["31249"]["fetched_from"] == "wayback"
    assert rows["31249"]["wayback_url"] == snapshot
    assert rows["31249"]["wayback_timestamp"] == "20261115120000"
    # the identity columns are untouched
    assert rows["31249"]["sha256"] == publisher.compute_hash(b"%PDF-1.4 snapshot bytes")


def test_old_index_without_provenance_columns_is_extended_not_broken(
    pub: InternetArchivePublisher, ia: FakeIA
) -> None:
    old_index = (
        "tipo,numero,rendicao,formato,uuid5,sha256,captured_at,source\n"
        "decreto,31200,,pdf,aaaa1111,hash1,2026-11-10T00:00:00+00:00,https://x/D31200.pdf\n"
    )
    with patch.object(publisher, "_fetch_existing_index", return_value=old_index):
        results = pub.upload_raw_batch(ITEM, [_capture(31250)], {})
    assert results[0]["success"]
    rows = _index_rows(ia.indexes[0])
    assert [r["numero"] for r in rows] == ["31200", "31250"]
    assert rows[0]["source"] == "https://x/D31200.pdf"
    assert rows[0]["fetched_from"] == "" and rows[0]["user_agent"] == ""  # unknown
    assert rows[1]["fetched_from"] == "source-direct"


def test_unit_upload_keeps_its_sidecar_and_also_fills_the_index(
    pub: InternetArchivePublisher, ia: FakeIA, tmp_path: Path
) -> None:
    pdf = b"%PDF-1.4 unit"
    pdf_path = tmp_path / "d.pdf"
    pdf_path.write_bytes(pdf)
    lei_data = _capture(31250).lei_data
    with patch.object(publisher, "_fetch_existing_index", return_value=None):
        result = pub.upload_raw(pdf_path, lei_data, pdf, fetched_from="source-direct")
    assert result["success"]
    files = ia.files(ia.uploads[0])
    assert [f.endswith("_meta.json") for f in files] == [False, True, False]
    assert _index_rows(ia.indexes[0])[0]["fetched_from"] == "source-direct"
