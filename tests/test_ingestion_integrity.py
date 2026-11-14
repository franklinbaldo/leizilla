"""Ingestion integrity: IA index as durable memory, IA-based frontier, loud failure.

Regression tests for the 2026-11-14 findings: the weekly harvest re-uploaded the
same PDFs because its local state was never persisted, the lei frontier collapsed
to 10 whenever the Wayback CDX was down, and both ended in a green job.
"""

from pathlib import Path
from typing import Any, Dict, Iterator
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from leizilla import publisher
from leizilla.cli import app
from leizilla.discovery import (
    DEFAULT_CDX_AUTO_FALLBACK_END,
    SequentialDiscovery,
    resolve_ia_range_max,
)
from leizilla.scraper import harvest_pending_resources
from leizilla.storage import DuckDBStorage

runner = CliRunner()
REPO = Path(__file__).resolve().parents[1]
INDEX_HEADER = "tipo,numero,rendicao,formato,uuid5,sha256,captured_at,source\n"


@pytest.fixture
def temp_db(tmp_path: Path) -> Iterator[DuckDBStorage]:
    db = DuckDBStorage(tmp_path / "t.duckdb")
    yield db
    db.close()


def _resource(numero: int) -> Dict[str, Any]:
    return {
        "url": f"https://example.com/Files/L{numero}.pdf",
        "ente": "ro",
        "fonte": "casacivil",
        "tipo_documento": "lei",
        "chave": f"lei-{numero:05d}",
        "status": "pending",
    }


# --- IA index.csv as the memory of what is preserved ---------------------------------


def test_preserved_sources_reads_index_and_ignores_scheme() -> None:
    index = INDEX_HEADER + (
        "lei,1,,pdf,aaaa,sha1,2026-01-01T00:00:00,http://example.com/Files/L1.pdf\n"
        "lei,2,,pdf,bbbb,sha2,2026-01-01T00:00:00,\n"
    )
    pub = publisher.InternetArchivePublisher()
    with patch.object(publisher, "_fetch_existing_index", return_value=index):
        assert pub.preserved_sources("item") == {"example.com/Files/L1.pdf"}


def test_preserved_sources_missing_index_is_empty_not_unknown() -> None:
    pub = publisher.InternetArchivePublisher()
    with patch.object(publisher, "_fetch_existing_index", return_value=None):
        assert pub.preserved_sources("item") == set()


def test_preserved_sources_unreadable_index_is_unknown() -> None:
    pub = publisher.InternetArchivePublisher()
    with patch.object(
        publisher,
        "_fetch_existing_index",
        side_effect=publisher.IndexFetchError("timeout"),
    ):
        assert pub.preserved_sources("item") is None


def test_harvest_skips_preserved_without_spending_the_limit(
    temp_db: DuckDBStorage,
) -> None:
    for numero in (1, 2, 3):
        temp_db.insert_resource(_resource(numero))
    pub = MagicMock()
    pub.preserved_sources.return_value = {
        "example.com/Files/L1.pdf",
        "example.com/Files/L2.pdf",
    }
    pub.upload_raw.return_value = {"success": True, "ia_id": "x", "ia_url": "u"}

    with (
        patch("leizilla.scraper.robots.is_allowed", return_value=True),
        patch("leizilla.scraper.wayback.ensure_archived", return_value=None),
        patch(
            "leizilla.scraper.wayback.fetch_bytes_detailed",
            return_value=(b"%PDF-1.4 x", False),
        ),
    ):
        stats = harvest_pending_resources(temp_db, pub, limit=1)

    assert stats["already-preserved"] == 2
    assert stats["success"] == 1
    assert pub.upload_raw.call_count == 1
    assert temp_db.get_pending_resources() == []
    # one index read for the whole range item, not one per resource
    assert pub.preserved_sources.call_count == 1


def test_harvest_treats_unreadable_index_as_not_preserved(
    temp_db: DuckDBStorage,
) -> None:
    temp_db.insert_resource(_resource(1))
    pub = MagicMock()
    pub.preserved_sources.return_value = None
    pub.upload_raw.return_value = {"success": True, "ia_id": "x", "ia_url": "u"}

    with (
        patch("leizilla.scraper.robots.is_allowed", return_value=True),
        patch("leizilla.scraper.wayback.ensure_archived", return_value=None),
        patch(
            "leizilla.scraper.wayback.fetch_bytes_detailed",
            return_value=(b"%PDF-1.4 x", False),
        ),
    ):
        stats = harvest_pending_resources(temp_db, pub, limit=5)

    assert stats["already-preserved"] == 0
    assert stats["success"] == 1


def test_harvest_does_not_retry_a_transient_failure_in_the_same_run(
    temp_db: DuckDBStorage,
) -> None:
    temp_db.insert_resource(_resource(1))
    pub = MagicMock()
    pub.preserved_sources.return_value = set()

    with (
        patch("leizilla.scraper.robots.is_allowed", return_value=True),
        patch("leizilla.scraper.wayback.ensure_archived", return_value=None),
        patch(
            "leizilla.scraper.wayback.fetch_bytes_detailed", return_value=(None, False)
        ) as fetch,
    ):
        stats = harvest_pending_resources(temp_db, pub, limit=5)

    assert fetch.call_count == 1
    assert stats["failed"] == 1


# --- frontier from what is already in IA ---------------------------------------------


def test_resolve_ia_range_max_reads_item_identifiers() -> None:
    ids = [
        "leizilla_ro_casacivil_lei_0001-1000",
        "leizilla_ro_casacivil_lei_1001-2000",
        "leizilla_ro_casacivil_lei_unidentified",
    ]
    with patch.object(publisher, "scrape_identifiers", return_value=ids):
        assert resolve_ia_range_max("ro", "casacivil", "lei") == 2000


def test_resolve_ia_range_max_fails_open_to_zero() -> None:
    with patch.object(publisher, "scrape_identifiers", return_value=None):
        assert resolve_ia_range_max("ro", "casacivil", "lei") == 0


def _sequential(**overrides: Any) -> SequentialDiscovery:
    config: Dict[str, Any] = {
        "strategy": "sequential",
        "templates": ["http://example.com/Files/L{num}.pdf"],
        "start": 1,
        "end": "cdx-auto",
    }
    config.update(overrides)
    return SequentialDiscovery(config, "ro", "casacivil")


def test_cdx_down_uses_ia_frontier_instead_of_ten() -> None:
    with (
        patch("leizilla.discovery.resolve_cdx_max_for_template", return_value=0),
        patch("leizilla.discovery.resolve_ia_range_max", return_value=2000),
    ):
        assert _sequential(ia_frontier=True)._resolve_end() == 3000


def test_ia_frontier_extends_beyond_what_wayback_knows() -> None:
    with (
        patch("leizilla.discovery.resolve_cdx_max_for_template", return_value=1736),
        patch("leizilla.discovery.resolve_ia_range_max", return_value=2000),
    ):
        assert _sequential(ia_frontier=True)._resolve_end() == 3000


def test_cdx_ahead_of_ia_keeps_cdx() -> None:
    with (
        patch("leizilla.discovery.resolve_cdx_max_for_template", return_value=5900),
        patch("leizilla.discovery.resolve_ia_range_max", return_value=2000),
    ):
        assert _sequential(ia_frontier=True)._resolve_end() == 5900


def test_without_ia_frontier_behaviour_is_unchanged() -> None:
    with (
        patch("leizilla.discovery.resolve_cdx_max_for_template", return_value=0),
        patch("leizilla.discovery.resolve_ia_range_max") as ia,
    ):
        assert _sequential()._resolve_end() == DEFAULT_CDX_AUTO_FALLBACK_END
    ia.assert_not_called()


def test_ia_frontier_with_nothing_in_ia_falls_back() -> None:
    with (
        patch("leizilla.discovery.resolve_cdx_max_for_template", return_value=0),
        patch("leizilla.discovery.resolve_ia_range_max", return_value=0),
    ):
        end = _sequential(ia_frontier=True)._resolve_end()
    assert end == DEFAULT_CDX_AUTO_FALLBACK_END


# --- a harvest that captured nothing must not end green -------------------------------


def _invoke_harvest(items: list[Dict[str, Any]]) -> Any:
    stats = {
        "success": sum(1 for i in items if i["status"] == "ok"),
        "failed": sum(1 for i in items if i["status"] == "failed"),
        "robots-blocked": 0,
        "already-preserved": 0,
        "items": items,
    }
    with (
        patch("leizilla.scraper.harvest_pending_resources", return_value=stats),
        patch("leizilla.storage.DuckDBStorage"),
        patch("leizilla.publisher.InternetArchivePublisher"),
    ):
        return runner.invoke(app, ["harvest"])


def test_harvest_exits_nonzero_when_nothing_captured_and_failures_unexpected() -> None:
    result = _invoke_harvest(
        [{"status": "failed", "chave": "lei-1", "reason": "fetch-failed-transient"}]
    )
    assert result.exit_code == 1


def test_harvest_confirmed_absences_alone_are_not_an_error() -> None:
    result = _invoke_harvest(
        [{"status": "failed", "chave": "lei-1", "reason": "fetch-failed"}]
    )
    assert result.exit_code == 0


def test_harvest_with_some_success_stays_green() -> None:
    result = _invoke_harvest(
        [
            {"status": "ok", "chave": "lei-1", "ia_id": "x"},
            {"status": "failed", "chave": "lei-2", "reason": "upload-failed"},
        ]
    )
    assert result.exit_code == 0


# --- workflow: state is saved after the harvest ---------------------------------------


def test_workflow_saves_db_cache_after_harvest() -> None:
    text = (REPO / ".github/workflows/discover-harvest.yml").read_text()
    jobs = text.split("\n  harvest-")[1:]
    assert len(jobs) == 2
    for job in jobs:
        assert job.index("name: Harvest") < job.index(
            "name: Save discovered-resources DB cache"
        )
