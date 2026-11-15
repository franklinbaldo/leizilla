"""refile_raw: move a capture filed under a wrong number (offline, all IA calls mocked)."""

from __future__ import annotations

import csv
import io
import subprocess
from typing import Any, Optional

import pytest
from typer.testing import CliRunner

from leizilla import cli
from leizilla import publisher as pub_mod
from leizilla.ia_utils import INDEX_COLUMNS, compute_hash
from leizilla.publisher import IndexFetchError, InternetArchivePublisher

WRONG_ITEM = "leizilla_ro_casacivil_decreto_304001-305000"
TARGET_ITEM = "leizilla_ro_casacivil_decreto_30001-31000"
WRONG_FILE = "decreto-304012_a1b2c3d4.pdf"
WRONG_META = "decreto-304012_a1b2c3d4_meta.json"
NOTE = "Nota de teste: o índice, com dois-pontos: e acentos (Decreto n. 304012)."
PDF = b"%PDF-1.4 fake capture bytes"
SHA = compute_hash(PDF)
UUID5 = "a1b2c3d4"
SOURCE = "https://www.casacivil.ro.gov.br/D30412.pdf"
REFILE_KWARGS: dict[str, Any] = {
    "ente": "ro",
    "fonte": "casacivil",
    "tipo": "decreto",
    "note": NOTE,
}


def _index(rows: list[dict[str, str]]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=INDEX_COLUMNS)
    writer.writeheader()
    for row in rows:
        writer.writerow({c: row.get(c, "") for c in INDEX_COLUMNS})
    return buf.getvalue()


def _row(
    numero: int,
    *,
    sha: str = SHA,
    uuid5: str = UUID5,
    formato: str = "pdf",
    tipo: str = "decreto",
) -> dict[str, str]:
    return {
        "tipo": tipo,
        "numero": str(numero),
        "rendicao": "",
        "formato": formato,
        "uuid5": uuid5,
        "sha256": sha,
        "captured_at": "2026-11-15T00:00:00+00:00",
        "source": SOURCE,
    }


class _Resp:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data

    def __enter__(self) -> "_Resp":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class FakeArchive:
    """Stands in for every IA-touching collaborator and records the call order."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.wrong_index: Optional[str] = _index([_row(304012)])
        self.target_index: Optional[str] = None
        self.index_error = False
        self.download_ok = True
        self.downloads: list[str] = []
        self.sleeps: list[float] = []
        self.upload_ok = True
        self.uploads: list[tuple[dict[str, Any], bytes, str, bool]] = []
        self.copy_appears = True
        self.cleanup_fail_on: Optional[str] = None
        self.ia_calls: list[list[str]] = []
        self.item_files: Optional[set[str]] = set()
        self.fail_nth_delete: Optional[int] = None
        self.delete_count = 0

    def fetch_files(self, item_id: str) -> Optional[set[str]]:
        return self.item_files

    def fetch_index(self, item_id: str) -> Optional[str]:
        self.events.append(f"read-index:{item_id}")
        if self.index_error:
            raise IndexFetchError("timeout")
        if item_id == WRONG_ITEM:
            return self.wrong_index
        return self.target_index

    def download(self, url: str, sha256: str) -> Optional[bytes]:
        self.downloads.append(url)
        return PDF if self.download_ok else None

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)

    def upload_raw(
        self,
        pdf_path: Any,
        lei_data: dict[str, Any],
        pdf_bytes: bytes,
        fetched_from: str = "source-fallback",
        wayback_url: Optional[str] = None,
        index_cache: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        self.events.append("upload_raw")
        self.uploads.append(
            (lei_data, pdf_bytes, fetched_from, index_cache is not None)
        )
        if not self.upload_ok:
            return {"success": False, "error": "upload rejected"}
        if self.copy_appears:
            self.target_index = _index([_row(30412)])
        return {"success": True}

    def run_ia(
        self, args: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        self.events.append(f"ia:{args[1]}")
        self.ia_calls.append(args)
        if args[1] == "delete":
            self.delete_count += 1
            if self.delete_count == self.fail_nth_delete:
                raise subprocess.CalledProcessError(1, args, stderr="ia failed")
        if self.cleanup_fail_on == args[1]:
            raise subprocess.CalledProcessError(1, args, stderr="ia failed")
        return subprocess.CompletedProcess(args, 0)


@pytest.fixture
def archive(monkeypatch: pytest.MonkeyPatch) -> FakeArchive:
    fa = FakeArchive()
    publisher = InternetArchivePublisher()
    monkeypatch.setattr(pub_mod, "fetch_item_filenames", fa.fetch_files)
    monkeypatch.setattr(pub_mod, "_fetch_existing_index", fa.fetch_index)
    monkeypatch.setattr(pub_mod, "_download_refile_bytes", fa.download)
    monkeypatch.setattr(pub_mod.time, "sleep", fa.sleep)
    monkeypatch.setattr(publisher, "upload_raw", fa.upload_raw)
    monkeypatch.setattr(publisher, "_run_ia_upload", fa.run_ia)
    fa.publisher = publisher  # type: ignore[attr-defined]
    return fa


def _refile(
    fa: FakeArchive,
    *,
    wrong_numero: int = 304012,
    correct_numero: int = 30412,
    dry_run: bool = False,
) -> dict[str, Any]:
    publisher: InternetArchivePublisher = fa.publisher  # type: ignore[attr-defined]
    return publisher.refile_raw(
        WRONG_ITEM,
        wrong_numero,
        correct_numero,
        dry_run=dry_run,
        **REFILE_KWARGS,
    )


def test_dry_run_returns_plan_and_writes_nothing(archive: FakeArchive) -> None:
    publisher: InternetArchivePublisher = archive.publisher  # type: ignore[attr-defined]
    result = publisher.refile_raw(WRONG_ITEM, 304012, 30412, **REFILE_KWARGS)

    assert result["success"] is True
    assert result["dry_run"] is True
    assert result["plan"] == [
        {
            "wrong_file": WRONG_FILE,
            "sha256": SHA,
            "source_url": SOURCE,
            "target_item": TARGET_ITEM,
        }
    ]
    assert archive.uploads == []
    assert archive.ia_calls == []
    assert archive.sleeps == []
    assert "read-index:" + WRONG_ITEM in archive.events


def test_sha_mismatch_stops_before_any_write(archive: FakeArchive) -> None:
    archive.download_ok = False

    result = _refile(archive)

    assert result == {
        "success": False,
        "reason": "bytes-mismatch",
        "wrong_item": WRONG_ITEM,
        "wrong_file": WRONG_FILE,
    }
    assert archive.uploads == []
    assert archive.ia_calls == []


def test_index_unreadable_stops_first(archive: FakeArchive) -> None:
    archive.index_error = True

    result = _refile(archive)

    assert result["reason"] == "index-unreadable"
    assert archive.downloads == []
    assert archive.ia_calls == []


def test_not_found_when_no_pdf_row_for_wrong_number(archive: FakeArchive) -> None:
    archive.wrong_index = _index([_row(999999)])

    result = _refile(archive)

    assert result["reason"] == "not-found"
    assert archive.uploads == []


def test_extra_rows_in_wrong_item_block_the_refile(archive: FakeArchive) -> None:
    archive.wrong_index = _index([_row(304012), _row(1, uuid5="ffffffff")])

    result = _refile(archive)

    assert result["reason"] == "index-has-other-rows"
    assert archive.uploads == []
    assert archive.ia_calls == []


def test_same_target_and_wrong_item_is_refused(archive: FakeArchive) -> None:
    result = _refile(archive, correct_numero=304500)

    assert result["reason"] == "same-item"
    assert archive.uploads == []
    assert archive.ia_calls == []


def test_upload_failure_leaves_wrong_item_untouched(archive: FakeArchive) -> None:
    archive.upload_ok = False

    result = _refile(archive)

    assert result["success"] is False
    assert result["reason"] == "upload-failed"
    assert len(archive.uploads) == 1
    assert archive.ia_calls == []
    assert "ia:delete" not in archive.events


def test_unverified_copy_leaves_wrong_item_untouched(archive: FakeArchive) -> None:
    archive.copy_appears = False

    result = _refile(archive)

    assert result["success"] is False
    assert result["reason"] == "copy-unverified"
    # 1 leitura inicial + 6 novas tentativas, 20 s entre elas.
    assert archive.events.count("read-index:" + TARGET_ITEM) == 7
    assert archive.sleeps == [pub_mod._REFILE_VERIFY_SLEEP_S] * 6
    assert archive.ia_calls == []


def test_happy_path_runs_copy_verify_annotate_delete_in_order(
    archive: FakeArchive,
) -> None:
    result = _refile(archive)

    assert result["success"] is True
    assert result["dry_run"] is False
    assert result["target_item"] == TARGET_ITEM
    assert archive.events == [
        f"read-index:{WRONG_ITEM}",
        "upload_raw",
        f"read-index:{TARGET_ITEM}",
        "ia:metadata",
        "ia:delete",
    ]

    lei_data, pdf_bytes, fetched_from, has_cache = archive.uploads[0]
    assert lei_data == {
        "id": "ro-casacivil-decreto-30412",
        "ente": "ro",
        "fonte": "casacivil",
        "chave": "decreto-30412",
        "titulo": "DECRETO decreto-30412 (RO)",
        "url_original": SOURCE,
        "rendicao": "",
    }
    assert pdf_bytes == PDF
    assert fetched_from == "refile"
    assert has_cache is True


def test_happy_path_passes_note_unchanged_and_names_exact_files(
    archive: FakeArchive,
) -> None:
    _refile(archive)

    metadata, delete = archive.ia_calls
    assert metadata == [
        "ia",
        "metadata",
        WRONG_ITEM,
        "--modify",
        f"title:[CADASTRO CORRIGIDO] {WRONG_ITEM}",
        "--modify",
        f"description:{NOTE}",
    ]
    assert delete == [
        "ia",
        "delete",
        WRONG_ITEM,
        WRONG_FILE,
        WRONG_META,
        "index.csv",
    ]


def test_annotate_failure_returns_refiled_true(archive: FakeArchive) -> None:
    archive.cleanup_fail_on = "metadata"

    result = _refile(archive)

    assert result["success"] is False
    assert result["reason"] == "cleanup-failed"
    assert result["refiled"] is True
    assert result["stage"] == "annotate"
    assert archive.events[-1] == "ia:metadata"


def test_delete_failure_returns_refiled_true(archive: FakeArchive) -> None:
    archive.cleanup_fail_on = "delete"

    result = _refile(archive)

    assert result["success"] is False
    assert result["reason"] == "cleanup-failed"
    assert result["refiled"] is True
    assert result["stage"] == "delete"


STEM = "decreto-304012_a1b2c3d4"
OCR_FILES = {
    f"{STEM}_djvu.txt",
    f"{STEM}_hocr.html",
    f"{STEM}_imgonly_pdfmeta.json",
}


def test_purge_dry_run_lists_leftovers_and_deletes_nothing(
    archive: FakeArchive,
) -> None:
    publisher: InternetArchivePublisher = archive.publisher  # type: ignore[attr-defined]
    archive.item_files = {*OCR_FILES, "other-file.txt"}

    result = publisher.purge_capture_leftovers(WRONG_ITEM, STEM)

    assert result == {
        "success": True,
        "dry_run": True,
        "would_delete": sorted(OCR_FILES),
    }
    assert archive.ia_calls == []


def test_purge_refuses_item_that_still_has_index(archive: FakeArchive) -> None:
    publisher: InternetArchivePublisher = archive.publisher  # type: ignore[attr-defined]
    archive.item_files = {*OCR_FILES, "index.csv"}

    result = publisher.purge_capture_leftovers(WRONG_ITEM, STEM, dry_run=False)

    assert result == {"success": False, "reason": "index-present"}
    assert archive.ia_calls == []


def test_purge_refuses_when_original_pdf_still_present(archive: FakeArchive) -> None:
    publisher: InternetArchivePublisher = archive.publisher  # type: ignore[attr-defined]
    archive.item_files = {*OCR_FILES, f"{STEM}.pdf"}

    result = publisher.purge_capture_leftovers(WRONG_ITEM, STEM, dry_run=False)

    assert result == {"success": False, "reason": "original-present"}
    assert archive.ia_calls == []


def test_purge_reports_unreadable_metadata(archive: FakeArchive) -> None:
    publisher: InternetArchivePublisher = archive.publisher  # type: ignore[attr-defined]
    archive.item_files = None

    result = publisher.purge_capture_leftovers(WRONG_ITEM, STEM, dry_run=False)

    assert result == {"success": False, "reason": "metadata-unreadable"}
    assert archive.ia_calls == []


def test_purge_never_selects_history_or_other_stems(archive: FakeArchive) -> None:
    publisher: InternetArchivePublisher = archive.publisher  # type: ignore[attr-defined]
    archive.item_files = {
        f"{STEM}_djvu.txt",
        f"history/files/{STEM}_djvu.txt",
        f"{STEM}X_djvu.txt",
        "decreto-30412_b9999999_djvu.txt",
    }

    result = publisher.purge_capture_leftovers(WRONG_ITEM, STEM, dry_run=False)

    assert result["deleted"] == [f"{STEM}_djvu.txt"]
    assert archive.ia_calls == [["ia", "delete", WRONG_ITEM, f"{STEM}_djvu.txt"]]


def test_purge_nothing_to_delete_is_success_without_ia_call(
    archive: FakeArchive,
) -> None:
    publisher: InternetArchivePublisher = archive.publisher  # type: ignore[attr-defined]
    archive.item_files = {"unrelated.txt"}

    result = publisher.purge_capture_leftovers(WRONG_ITEM, STEM, dry_run=False)

    assert result == {"success": True, "deleted": [], "dry_run": False}
    assert archive.ia_calls == []


def test_purge_real_delete_is_one_call_with_sorted_names(archive: FakeArchive) -> None:
    publisher: InternetArchivePublisher = archive.publisher  # type: ignore[attr-defined]
    archive.item_files = set(OCR_FILES)

    result = publisher.purge_capture_leftovers(WRONG_ITEM, STEM, dry_run=False)

    assert result == {
        "success": True,
        "dry_run": False,
        "deleted": sorted(OCR_FILES),
    }
    assert archive.ia_calls == [["ia", "delete", WRONG_ITEM, *sorted(OCR_FILES)]]


def test_purge_delete_failure_is_reported_not_raised(archive: FakeArchive) -> None:
    publisher: InternetArchivePublisher = archive.publisher  # type: ignore[attr-defined]
    archive.item_files = set(OCR_FILES)
    archive.cleanup_fail_on = "delete"

    result = publisher.purge_capture_leftovers(WRONG_ITEM, STEM, dry_run=False)

    assert result["success"] is False
    assert result["reason"] == "delete-failed"
    assert result["error"] == "ia failed"


def test_refile_happy_path_purges_leftovers_after_delete(archive: FakeArchive) -> None:
    archive.item_files = set(OCR_FILES)

    result = _refile(archive)

    assert result["success"] is True
    assert result["leftovers"] == [
        {
            "stem": STEM,
            "success": True,
            "dry_run": False,
            "deleted": sorted(OCR_FILES),
        }
    ]
    assert archive.ia_calls[-1] == ["ia", "delete", WRONG_ITEM, *sorted(OCR_FILES)]


def test_refile_still_succeeds_when_purge_fails(archive: FakeArchive) -> None:
    archive.item_files = set(OCR_FILES)
    archive.fail_nth_delete = 2  # 1ª: cleanup do refile; 2ª: purge

    result = _refile(archive)

    assert result["success"] is True
    assert result["leftovers"][0]["success"] is False
    assert result["leftovers"][0]["reason"] == "delete-failed"


def test_download_helper_gives_up_after_three_hash_mismatches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_urlopen(req: Any, timeout: float) -> _Resp:
        calls.append(req.full_url)
        return _Resp(b"other bytes")

    monkeypatch.setattr(pub_mod.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(pub_mod.time, "sleep", lambda _s: None)

    assert pub_mod._download_refile_bytes("https://example.test/f.pdf", SHA) is None
    assert len(calls) == pub_mod._REFILE_DOWNLOAD_ATTEMPTS


def test_download_helper_recovers_after_network_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses: list[Any] = [OSError("reset"), _Resp(PDF)]

    def fake_urlopen(req: Any, timeout: float) -> _Resp:
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(pub_mod.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(pub_mod.time, "sleep", lambda _s: None)

    assert pub_mod._download_refile_bytes("https://example.test/f.pdf", SHA) == PDF


def test_cli_exits_1_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_cls = _fake_publisher_class({"success": False, "reason": "not-found"})
    monkeypatch.setattr(pub_mod, "InternetArchivePublisher", fake_cls)

    result = CliRunner().invoke(cli.app, _CLI_ARGS)

    assert result.exit_code == 1


def test_cli_dry_run_exits_0_and_defaults_to_no_execute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = {"success": True, "dry_run": True, "plan": []}
    fake_cls = _fake_publisher_class(plan)
    monkeypatch.setattr(pub_mod, "InternetArchivePublisher", fake_cls)

    result = CliRunner().invoke(cli.app, _CLI_ARGS)

    assert result.exit_code == 0
    refile = fake_cls.return_value.refile_raw
    assert refile.call_args.kwargs["dry_run"] is True


def test_cli_execute_flag_disables_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_cls = _fake_publisher_class({"success": True, "dry_run": False})
    monkeypatch.setattr(pub_mod, "InternetArchivePublisher", fake_cls)

    result = CliRunner().invoke(cli.app, [*_CLI_ARGS, "--execute"])

    assert result.exit_code == 0
    refile = fake_cls.return_value.refile_raw
    assert refile.call_args.kwargs["dry_run"] is False


_CLI_ARGS = [
    "refile-raw",
    "--fonte",
    "casacivil",
    "--tipo",
    "decreto",
    "--wrong-item",
    WRONG_ITEM,
    "--wrong-numero",
    "304012",
    "--correct-numero",
    "30412",
    "--note",
    NOTE,
]


def _fake_publisher_class(result: dict[str, Any]) -> Any:
    from unittest.mock import MagicMock

    cls = MagicMock()
    cls.return_value.refile_raw.return_value = result
    return cls


def _fake_purge_class(result: dict[str, Any]) -> Any:
    from unittest.mock import MagicMock

    cls = MagicMock()
    cls.return_value.purge_capture_leftovers.return_value = result
    return cls


_PURGE_ARGS = [
    "purge-leftovers",
    "--item",
    WRONG_ITEM,
    "--stem",
    STEM,
]


def test_cli_purge_dry_run_exits_0_and_defaults_to_no_execute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_cls = _fake_purge_class({"success": True, "dry_run": True, "would_delete": []})
    monkeypatch.setattr(pub_mod, "InternetArchivePublisher", fake_cls)

    result = CliRunner().invoke(cli.app, _PURGE_ARGS)

    assert result.exit_code == 0
    purge = fake_cls.return_value.purge_capture_leftovers
    assert purge.call_args.kwargs["dry_run"] is True


def test_cli_purge_failure_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_cls = _fake_purge_class({"success": False, "reason": "index-present"})
    monkeypatch.setattr(pub_mod, "InternetArchivePublisher", fake_cls)

    result = CliRunner().invoke(cli.app, [*_PURGE_ARGS, "--execute"])

    assert result.exit_code == 1
    purge = fake_cls.return_value.purge_capture_leftovers
    assert purge.call_args.kwargs["dry_run"] is False
