"""Regression tests for the release row-count floor gate (issue #118)."""

from __future__ import annotations

import json
import urllib.error
from pathlib import Path
from unittest.mock import patch

import duckdb
import pytest
from typer.testing import CliRunner

from leizilla.cli import app
from leizilla.publisher import (
    DatasetFloorCheckError,
    fetch_published_dataset_row_count,
)


_runner = CliRunner()


class _UrlopenResponse:
    def __init__(self, payload: object) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "_UrlopenResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _meta_response(exists: bool) -> _UrlopenResponse:
    """archive.org/metadata: {} (falsy) for a nonexistent item, always HTTP 200."""
    return _UrlopenResponse(
        {"files": [{"name": "dataset_meta.json"}]} if exists else {}
    )


def _row_count_response(row_count: int) -> _UrlopenResponse:
    return _UrlopenResponse({"row_count": row_count})


def _parquet(tmp_path: Path) -> Path:
    out = tmp_path / "versoes.parquet"
    conn = duckdb.connect()
    try:
        conn.execute(
            "CREATE TABLE t AS SELECT "
            "'leizilla-ro-lei-00001-2000' AS lei_id, "
            "'art-1' AS dispositivo_path, "
            "NULL::VARCHAR AS texto_normalizado, "
            "NULL::DATE AS ate"
        )
        conn.table("t").write_parquet(str(out))
    finally:
        conn.close()
    return out


def test_floor_reads_latest_first() -> None:
    with patch(
        "urllib.request.urlopen",
        side_effect=[_meta_response(exists=True), _row_count_response(42)],
    ) as mocked:
        assert fetch_published_dataset_row_count("ro", 0) == 42
    assert mocked.call_count == 2
    assert "/metadata/" in mocked.call_args_list[0][0][0].full_url
    assert "-latest" in mocked.call_args_list[0][0][0].full_url
    assert "-latest/dataset_meta.json" in mocked.call_args_list[1][0][0].full_url


def test_floor_uses_legacy_only_after_confirmed_latest_missing() -> None:
    """archive.org/download returns 503 (not 404) for a nonexistent item's files —
    confirmed in production, 2026-09-24 — so existence is checked via the
    metadata API (always HTTP 200, {} body when absent) instead."""
    with patch(
        "urllib.request.urlopen",
        side_effect=[
            _meta_response(exists=False),
            _meta_response(exists=True),
            _row_count_response(37),
        ],
    ) as mocked:
        assert fetch_published_dataset_row_count("ro", 0) == 37
    assert mocked.call_count == 3
    assert "-latest" in mocked.call_args_list[0][0][0].full_url
    assert "-latest" not in mocked.call_args_list[1][0][0].full_url


def test_floor_allows_first_ever_release_when_neither_item_exists() -> None:
    with patch(
        "urllib.request.urlopen",
        side_effect=[_meta_response(exists=False), _meta_response(exists=False)],
    ):
        assert fetch_published_dataset_row_count("ro", 0) is None


def test_floor_fails_closed_on_transient_existence_check_error() -> None:
    unavailable = urllib.error.HTTPError(
        "https://example/metadata", 503, "Unavailable", None, None
    )
    with (
        patch("urllib.request.urlopen", side_effect=unavailable),
        pytest.raises(DatasetFloorCheckError, match="HTTP 503"),
    ):
        fetch_published_dataset_row_count("ro", 0)


def test_floor_fails_closed_when_existing_items_dataset_meta_unreadable() -> None:
    """Metadata confirms the item exists, but dataset_meta.json itself errors —
    an unexpected state for an item that exists, so it fails closed rather than
    being read as "no prior release"."""
    broken = urllib.error.HTTPError(
        "https://example/dataset_meta.json", 404, "Not Found", None, None
    )
    with (
        patch(
            "urllib.request.urlopen",
            side_effect=[_meta_response(exists=True), broken],
        ),
        pytest.raises(DatasetFloorCheckError, match="HTTP 404"),
    ):
        fetch_published_dataset_row_count("ro", 0)


def test_cli_rejects_candidate_below_published_floor(tmp_path: Path) -> None:
    p = _parquet(tmp_path)
    with (
        patch("leizilla.publisher.fetch_published_dataset_row_count", return_value=2),
        patch("leizilla.publisher.InternetArchivePublisher.upload_dataset") as upload,
    ):
        result = _runner.invoke(app, ["release-dataset", str(p), "--version", "0"])
    assert result.exit_code == 1
    assert "abaixo do piso publicado de 2" in result.output
    upload.assert_not_called()


def test_cli_floor_lookup_failure_aborts_before_upload(tmp_path: Path) -> None:
    p = _parquet(tmp_path)
    with (
        patch(
            "leizilla.publisher.fetch_published_dataset_row_count",
            side_effect=DatasetFloorCheckError("network indeterminate"),
        ),
        patch("leizilla.publisher.InternetArchivePublisher.upload_dataset") as upload,
    ):
        result = _runner.invoke(app, ["release-dataset", str(p), "--version", "0"])
    assert result.exit_code == 1
    assert "não foi possível verificar o piso atual" in result.output
    upload.assert_not_called()
