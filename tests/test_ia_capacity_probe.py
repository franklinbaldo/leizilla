"""IA ``check_limit`` probe, flush bounds, spool and exit codes (ADR-0016, 2026-11-18)."""

import io
import json
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional
from unittest.mock import MagicMock, patch
from urllib.error import URLError

import pytest
from typer.testing import CliRunner

from leizilla import ia_utils
from leizilla.cli import app
from leizilla.ia_utils import IaCapacity, parse_ia_capacity, probe_ia_capacity
from leizilla.scraper import harvest_pending_resources
from leizilla.spool import DownloadSpool
from leizilla.storage import DuckDBStorage

from harvest_fakes import batch_ok, uploaded_captures

# Shape measured against the live endpoint on 2026-11-18 (no credential, real item).
LIVE_OK = {
    "accesskey": "k",
    "bucket": "leizilla_ro_casacivil_lc_0001-1000",
    "detail": {
        "accesskey_ration": 499,
        "accesskey_tasks_queued": 0,
        "bucket_limit": 999,
        "bucket_ration": 149,
        "bucket_tasks_queued": 150,
        "limit_reason": "",
        "rationing_engaged": 0,
        "rationing_level": 9999,
        "total_global_limit": 11999,
        "total_tasks_queued": 9770,
    },
    "over_limit": 0,
}


def _over(**detail: Any) -> Dict[str, Any]:
    d = dict(LIVE_OK["detail"])
    d.update(detail)
    return {**LIVE_OK, "detail": d, "over_limit": 1}


class _Resp(io.BytesIO):
    def __enter__(self) -> "_Resp":
        return self

    def __exit__(self, *a: Any) -> None:
        return None


# ------------------------------------------------------------------ parse / probe


def test_over_limit_zero_is_ok_even_if_bucket_counter_passed_the_ration() -> None:
    cap = parse_ia_capacity(LIVE_OK)
    assert cap is not None and not cap.over_limit and cap.scope is None


@pytest.mark.parametrize(
    ("payload", "scope"),
    [
        (
            _over(limit_reason="accesskey_tasks_queued exceeds rationed amount"),
            "account",
        ),
        (_over(limit_reason="bucket_tasks_queued exceeds rationed amount"), "item"),
        (_over(limit_reason="total_tasks_queued exceeds global_limit"), "account"),
        (_over(accesskey_tasks_queued=500), "account"),
        (_over(total_tasks_queued=12000), "account"),
        (_over(bucket_tasks_queued=150), "item"),
        (_over(bucket_tasks_queued=0), "account"),  # unknown cause: conservative
        (_over(accesskey_tasks_queued=500, bucket_tasks_queued=150), "account"),
    ],
)
def test_scope_of_an_over_limit_answer(payload: Dict[str, Any], scope: str) -> None:
    cap = parse_ia_capacity(payload)
    assert cap is not None and cap.over_limit and cap.scope == scope


@pytest.mark.parametrize("payload", [None, [], {}, {"over_limit": "x"}, "text"])
def test_unknown_shape_is_not_an_answer(payload: Any) -> None:
    assert parse_ia_capacity(payload) is None


def test_probe_calls_check_limit_with_key_and_bucket_and_writes_nothing() -> None:
    seen: List[str] = []

    def fake_urlopen(url: str, timeout: float) -> _Resp:
        seen.append(url)
        return _Resp(json.dumps(LIVE_OK).encode())

    with patch("leizilla.ia_utils.urllib.request.urlopen", fake_urlopen):
        cap = probe_ia_capacity("AK", "item_x")
    assert cap is not None and not cap.over_limit
    assert seen == [
        "https://s3.us.archive.org/?check_limit=1&accesskey=AK&bucket=item_x"
    ]
    assert "secret" not in seen[0].lower()


def test_probe_without_bucket_omits_it() -> None:
    seen: List[str] = []

    def fake_urlopen(url: str, timeout: float) -> _Resp:
        seen.append(url)
        return _Resp(json.dumps(LIVE_OK).encode())

    with patch("leizilla.ia_utils.urllib.request.urlopen", fake_urlopen):
        probe_ia_capacity("AK")
    assert "bucket" not in seen[0]


@pytest.mark.parametrize(
    "boom", [URLError("down"), TimeoutError(), OSError("x"), ValueError("bad json")]
)
def test_probe_is_fail_open(boom: Exception) -> None:
    def fake_urlopen(url: str, timeout: float) -> _Resp:
        raise boom

    with patch("leizilla.ia_utils.urllib.request.urlopen", fake_urlopen):
        assert probe_ia_capacity("AK", "i") is None


def test_probe_with_garbage_body_or_no_key_is_none() -> None:
    with patch(
        "leizilla.ia_utils.urllib.request.urlopen",
        lambda url, timeout: _Resp(b"<html>503</html>"),
    ):
        assert probe_ia_capacity("AK") is None
    assert probe_ia_capacity("") is None
    assert probe_ia_capacity(None) is None


# --------------------------------------------------------------------- harvest


@pytest.fixture
def temp_db(tmp_path: Path) -> Iterator[DuckDBStorage]:
    db = DuckDBStorage(tmp_path / "t.duckdb")
    yield db
    db.close()


@pytest.fixture(autouse=True)
def fast_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "leizilla.scraper.make_rate_limiter", lambda *a, **k: lambda _url: None
    )


def _res(numero: int) -> Dict[str, Any]:
    return {
        "url": f"https://fonte.example/Files/D{numero}.pdf",
        "ente": "ro",
        "fonte": "casacivil",
        "tipo_documento": "decreto",
        "chave": f"decreto-{numero:05d}",
        "status": "pending",
    }


def _statuses(db: DuckDBStorage) -> Dict[str, str]:
    rows = db.connect().execute("SELECT chave, status FROM discovered_resources")
    return dict(rows.fetchall())


def _pub(capacity: Any = None) -> MagicMock:
    pub = MagicMock()
    pub.preserved_sources.return_value = set()
    pub.check_ia_capacity.side_effect = (
        capacity if callable(capacity) else (lambda item_id=None: capacity)
    )
    return batch_ok(pub)


def _run(db: DuckDBStorage, pub: Any, fetched: Optional[List[str]] = None, **kw: Any):
    def fetch(url: str) -> tuple[bytes, bool]:
        if fetched is not None:
            fetched.append(url)
        return f"%PDF-1.4 {url}".encode(), False

    with (
        patch("leizilla.scraper.robots.is_allowed", return_value=True),
        patch("leizilla.scraper.wayback.fetch_bytes_detailed", side_effect=fetch),
    ):
        return harvest_pending_resources(db, pub, **kw)


def test_account_over_ration_fetches_nothing_and_changes_nothing(
    temp_db: DuckDBStorage,
) -> None:
    for n in range(1, 6):
        temp_db.insert_resource(_res(n))
    pub = _pub(IaCapacity(True, "account", "accesskey_tasks_queued", {}))
    fetched: List[str] = []

    stats = _run(temp_db, pub, fetched, limit=10)

    assert fetched == []  # the government host was never touched
    assert stats["aborted"] == "ia-account-ration-skip"
    assert stats["success"] == 0 and stats["failed"] == 0
    assert set(_statuses(temp_db).values()) == {"pending"}
    pub.upload_raw_batch.assert_not_called()
    pub.request_derive.assert_not_called()


def test_failing_probe_proceeds_as_before(temp_db: DuckDBStorage) -> None:
    temp_db.insert_resource(_res(1))
    pub = _pub(lambda item_id=None: (_ for _ in ()).throw(RuntimeError("boom")))
    stats = _run(temp_db, pub, limit=5)
    assert stats["success"] == 1 and stats["aborted"] is None


def test_unknown_probe_answer_proceeds(temp_db: DuckDBStorage) -> None:
    temp_db.insert_resource(_res(1))
    stats = _run(temp_db, _pub(None), limit=5)
    assert stats["success"] == 1


def test_item_over_ration_is_skipped_others_are_fetched(
    temp_db: DuckDBStorage,
) -> None:
    # decreto 5 -> item 0001-1000 (over); decreto 2005 -> another item (fine)
    for n in (5, 6, 2005):
        temp_db.insert_resource(_res(n))

    def cap(item_id: Optional[str] = None) -> IaCapacity:
        if item_id and "0001-1000" in item_id:
            return IaCapacity(True, "item", "bucket_tasks_queued", {})
        return IaCapacity(False)

    fetched: List[str] = []
    stats = _run(temp_db, _pub(cap), fetched, limit=10)

    assert fetched == ["https://fonte.example/Files/D2005.pdf"]
    assert stats["success"] == 1 and stats["deferred"] == 2
    st = _statuses(temp_db)
    assert st["decreto-02005"] == "downloaded"
    assert st["decreto-00005"] == st["decreto-00006"] == "pending"


def test_account_ration_appearing_mid_run_stops_fetching(
    temp_db: DuckDBStorage,
) -> None:
    for n in (5, 2005, 3005):
        temp_db.insert_resource(_res(n))
    state = {"calls": 0}

    def cap(item_id: Optional[str] = None) -> IaCapacity:
        state["calls"] += 1
        # start probe ok, first item ok, second item: account now over
        return IaCapacity(state["calls"] >= 3, "account", "x", {})

    fetched: List[str] = []
    stats = _run(temp_db, _pub(cap), fetched, limit=10, first_flush_at=50)

    assert len(fetched) == 1  # only the first item's capture was downloaded
    assert stats["aborted"] == "ia-account-throttled"
    assert stats["requeued"] == 1
    assert set(_statuses(temp_db).values()) == {"pending"}


def test_first_flush_after_five_captures_then_global_bound(
    temp_db: DuckDBStorage,
) -> None:
    # 12 items x 3 captures each: batch_size 25 would never flush on its own.
    numbers = [i * 1000 + 1 + k for i in range(12) for k in range(3)]
    for n in numbers:
        temp_db.insert_resource(_res(n))
    pub = _pub(IaCapacity(False))
    fetched: List[str] = []
    at_flush: List[int] = []
    inner = pub.upload_raw_batch.side_effect

    def spy(item_id: str, captures: Any, **kw: Any) -> Any:
        at_flush.append(len(fetched))
        return inner(item_id, captures, **kw)

    pub.upload_raw_batch.side_effect = spy

    stats = _run(temp_db, pub, fetched, limit=100, batch_size=25, max_unflushed=10)

    sizes = [len(c.args[1]) for c in pub.upload_raw_batch.call_args_list]
    assert stats["success"] == 36 and len(uploaded_captures(pub)) == 36
    assert at_flush[0] == 5  # first flush: after 5 downloads, not 25 per item
    assert all(s <= 10 for s in sizes)
    # unflushed never exceeded the bound (fetched - uploaded so far)
    uploaded = 0
    for n_fetched, size in zip(at_flush, sizes):
        assert n_fetched - uploaded <= 10
        uploaded += size


def test_first_flush_throttle_costs_only_a_handful_of_downloads(
    temp_db: DuckDBStorage,
) -> None:
    for i in range(14):
        for k in range(24):
            temp_db.insert_resource(_res(i * 1000 + 1 + k))
    pub = _pub(IaCapacity(False))
    pub.upload_raw_batch.side_effect = lambda item_id, captures, **_: [
        {
            "success": False,
            "reason": "ia-throttled",
            "scope": "account",
            "error": "accesskey_tasks_queued exceeds rationed amount",
        }
        for _ in captures
    ]
    fetched: List[str] = []

    stats = _run(temp_db, pub, fetched, limit=400)

    assert len(fetched) == 5  # was 330
    assert stats["aborted"] == "ia-account-throttled"
    assert stats["requeued"] == 5 and stats["success"] == 0


# ----------------------------------------------------------------------- spool


def test_spool_roundtrip_and_revalidation(tmp_path: Path) -> None:
    sp = DownloadSpool(tmp_path / "s", max_files=5, max_bytes=10_000, max_age_days=7)
    assert sp.put(
        "u1",
        b"%PDF-1.4 a",
        fetched_from="source-direct",
        wayback_url=None,
        captured_at="2026-11-18T12:00:00+00:00",
    )
    sp.save()
    again = DownloadSpool(tmp_path / "s", max_files=5, max_bytes=10_000)
    got = again.get("u1")
    assert got is not None and got[0] == b"%PDF-1.4 a"
    # tamper: same size, different bytes -> sha mismatch -> dropped
    path = next((tmp_path / "s").glob("*.pdf"))
    path.write_bytes(b"%PDF-1.4 b")
    assert again.get("u1") is None
    assert again.entries == {}


def test_spool_bounds_and_age(tmp_path: Path) -> None:
    sp = DownloadSpool(tmp_path / "s", max_files=2, max_bytes=25, max_age_days=7)
    kw = dict(fetched_from="source-direct", wayback_url=None, captured_at="t")
    assert sp.put("a", b"%PDF-1.4 aaaa", **kw)  # 13 bytes
    assert not sp.put("b", b"%PDF-1.4 bbbbbbbbbbbbbbb", **kw)  # over byte cap
    assert sp.put("c", b"%PDF-1.4 c", **kw)
    assert not sp.put("d", b"%PDF-1.4 d", **kw)  # file cap
    sp.save()
    idx = json.loads((tmp_path / "s" / "index.json").read_text())
    for e in idx.values():
        e["stored_at"] -= 8 * 86400
    (tmp_path / "s" / "index.json").write_text(json.dumps(idx))
    old = DownloadSpool(tmp_path / "s", max_files=2, max_bytes=25, max_age_days=7)
    assert old.entries == {}
    assert list((tmp_path / "s").glob("*.pdf")) == []  # orphans collected


def test_aborted_run_spools_and_the_next_run_does_not_fetch_again(
    temp_db: DuckDBStorage, tmp_path: Path
) -> None:
    for n in (5, 6, 7):
        temp_db.insert_resource(_res(n))
    sp = DownloadSpool(tmp_path / "s", max_files=10, max_bytes=10_000)
    pub = _pub(IaCapacity(False))
    pub.upload_raw_batch.side_effect = lambda item_id, captures, **_: [
        {
            "success": False,
            "reason": "ia-throttled",
            "scope": "account",
            "error": "accesskey_tasks_queued exceeds rationed amount",
        }
        for _ in captures
    ]
    fetched: List[str] = []
    first = _run(temp_db, pub, fetched, limit=10, first_flush_at=3, spool=sp)
    assert first["aborted"] == "ia-account-throttled" and first["spooled"] == 3
    assert len(fetched) == 3
    assert set(_statuses(temp_db).values()) == {"pending"}

    # next run: IA healthy; same files, spool reloaded from disk
    sp2 = DownloadSpool(tmp_path / "s", max_files=10, max_bytes=10_000)
    pub2 = _pub(IaCapacity(False))
    fetched2: List[str] = []
    second = _run(temp_db, pub2, fetched2, limit=10, spool=sp2)

    assert fetched2 == []  # the government host is not touched again
    assert second["success"] == 3 and second["from-spool"] == 3
    assert set(_statuses(temp_db).values()) == {"downloaded"}
    assert sp2.entries == {}  # uploaded -> removed from the spool
    assert {c.content for c in uploaded_captures(pub2)} == {
        f"%PDF-1.4 https://fonte.example/Files/D{n}.pdf".encode() for n in (5, 6, 7)
    }


def test_corrupt_spool_entry_falls_back_to_the_source(
    temp_db: DuckDBStorage, tmp_path: Path
) -> None:
    temp_db.insert_resource(_res(5))
    sp = DownloadSpool(tmp_path / "s", max_files=10, max_bytes=10_000)
    url = "https://fonte.example/Files/D5.pdf"
    sp.put(
        url,
        b"%PDF-1.4 old",
        fetched_from="source-direct",
        wayback_url=None,
        captured_at="t",
    )
    next((tmp_path / "s").glob("*.pdf")).write_bytes(b"<html>oops")
    fetched: List[str] = []
    stats = _run(temp_db, _pub(IaCapacity(False)), fetched, limit=5, spool=sp)
    assert fetched == [url] and stats["success"] == 1 and stats["from-spool"] == 0


# ------------------------------------------------------------------------- CLI


def _cli(stats: Dict[str, Any], summary: Optional[Path] = None) -> Any:
    env = {"GITHUB_STEP_SUMMARY": str(summary)} if summary else {}
    with (
        patch("leizilla.scraper.harvest_pending_resources", return_value=stats),
        patch("leizilla.storage.DuckDBStorage"),
        patch("leizilla.publisher.InternetArchivePublisher"),
        patch("leizilla.spool.DownloadSpool"),
    ):
        return CliRunner().invoke(app, ["harvest"], env=env)


def test_cli_ration_skip_is_green_with_a_job_summary(tmp_path: Path) -> None:
    out = tmp_path / "summary.md"
    res = _cli(
        {"success": 0, "failed": 0, "aborted": "ia-account-ration-skip", "items": []},
        out,
    )
    assert res.exit_code == 0
    assert "adiado: cota da conta no Internet Archive" in res.output
    assert "Colheita adiada" in out.read_text()


def test_cli_account_throttle_mid_run_is_green_and_reports_the_count(
    tmp_path: Path,
) -> None:
    out = tmp_path / "summary.md"
    res = _cli(
        {
            "success": 0,
            "failed": 0,
            "requeued": 330,
            "spooled": 100,
            "aborted": "ia-account-throttled",
            "items": [],
        },
        out,
    )
    assert res.exit_code == 0
    assert "330 capturas devolvidas à fila" in out.read_text()


@pytest.mark.parametrize(
    "stats",
    [
        # flush-timeout with nothing preserved is still a break
        {"success": 0, "failed": 0, "requeued": 3, "aborted": "flush-timeout"},
        # throttled AND real failures: not just a ration
        {
            "success": 0,
            "failed": 2,
            "requeued": 3,
            "aborted": "ia-account-throttled",
            "items": [{"status": "failed", "reason": "not-pdf"}] * 2,
        },
        # unexpected fetch failures, nothing preserved
        {
            "success": 0,
            "failed": 1,
            "aborted": None,
            "items": [{"status": "failed", "reason": "not-pdf"}],
        },
    ],
)
def test_cli_real_failures_stay_red(stats: Dict[str, Any]) -> None:
    stats = {"items": [], **stats}
    assert _cli(stats).exit_code == 1


def test_ia_utils_exports() -> None:
    assert ia_utils.IA_S3_CHECK_LIMIT_URL.startswith("https://s3.us.archive.org")
