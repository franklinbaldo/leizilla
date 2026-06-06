"""Testes para o pipeline de discovery/harvest (M10.A).

Cobre: storage.get_pending_resources, storage.insert_resource,
       storage.update_resource_status, scraper.harvest_pending_resources,
       discovery.SequentialDiscovery, discovery.run_discovery.
"""

import json
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from leizilla.storage import DuckDBStorage


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_db(tmp_path: Path) -> DuckDBStorage:
    db = DuckDBStorage(tmp_path / "test.duckdb")
    yield db  # type: ignore[misc]
    db.close()


def _make_resource(
    url: str = "http://example.com/lei.pdf",
    ente: str = "ro",
    fonte: str = "casacivil",
    chave: str = "lei-00001",
    status: str = "pending",
) -> Dict[str, Any]:
    return {
        "url": url,
        "ente": ente,
        "fonte": fonte,
        "tipo_documento": "lei",
        "chave": chave,
        "status": status,
    }


# ---------------------------------------------------------------------------
# storage.insert_resource / get_pending_resources / update_resource_status
# ---------------------------------------------------------------------------


class TestStorageResources:
    def test_empty_queue_returns_empty_list(self, temp_db: DuckDBStorage) -> None:
        assert temp_db.get_pending_resources() == []

    def test_insert_and_get_pending(self, temp_db: DuckDBStorage) -> None:
        res = _make_resource()
        temp_db.insert_resource(res)
        pending = temp_db.get_pending_resources()
        assert len(pending) == 1
        assert pending[0]["url"] == res["url"]
        assert pending[0]["ente"] == "ro"

    def test_only_pending_status_returned(self, temp_db: DuckDBStorage) -> None:
        temp_db.insert_resource(
            _make_resource(url="http://a.com/a.pdf", status="pending")
        )
        temp_db.insert_resource(
            _make_resource(url="http://b.com/b.pdf", status="downloaded")
        )
        pending = temp_db.get_pending_resources()
        assert len(pending) == 1
        assert pending[0]["url"] == "http://a.com/a.pdf"

    def test_limit_respected(self, temp_db: DuckDBStorage) -> None:
        for i in range(5):
            temp_db.insert_resource(
                _make_resource(url=f"http://x.com/{i}.pdf", chave=f"lei-{i:05d}")
            )
        pending = temp_db.get_pending_resources(limit=3)
        assert len(pending) == 3

    def test_insert_ignore_duplicate(self, temp_db: DuckDBStorage) -> None:
        res = _make_resource()
        temp_db.insert_resource(res)
        temp_db.insert_resource(res)  # duplicate — should be ignored
        assert len(temp_db.get_pending_resources()) == 1

    def test_update_status_downloaded(self, temp_db: DuckDBStorage) -> None:
        res = _make_resource()
        temp_db.insert_resource(res)
        temp_db.update_resource_status(res["url"], "downloaded")
        assert temp_db.get_pending_resources() == []

    def test_update_status_with_wayback(self, temp_db: DuckDBStorage) -> None:
        res = _make_resource()
        temp_db.insert_resource(res)
        snap = "https://web.archive.org/web/20240101000000/http://example.com/lei.pdf"
        temp_db.update_resource_status(res["url"], "downloaded", wayback_snapshot=snap)
        conn = temp_db.connect()
        row = conn.execute(
            "SELECT wayback_snapshot FROM discovered_resources WHERE url = ?",
            [res["url"]],
        ).fetchone()
        assert row is not None
        assert row[0] == snap


# ---------------------------------------------------------------------------
# discovery.SequentialDiscovery
# ---------------------------------------------------------------------------


class TestSequentialDiscovery:
    def test_generates_urls_for_range(self) -> None:
        from leizilla.discovery import SequentialDiscovery

        cfg = {
            "templates": ["http://example.com/L{num}.pdf"],
            "start": 1,
            "end": 3,
        }
        strategy = SequentialDiscovery(cfg, "ro", "casacivil")
        resources = strategy.run()
        assert len(resources) == 3
        urls = [r["url"] for r in resources]
        assert "http://example.com/L1.pdf" in urls
        assert "http://example.com/L3.pdf" in urls

    def test_resource_fields_populated(self) -> None:
        from leizilla.discovery import SequentialDiscovery

        cfg = {
            "templates": ["http://example.com/L{num}.pdf"],
            "start": 5,
            "end": 5,
        }
        res = SequentialDiscovery(cfg, "ro", "casacivil").run()[0]
        assert res["ente"] == "ro"
        assert res["fonte"] == "casacivil"
        assert res["status"] == "pending"
        assert res["chave"] is not None

    def test_multiple_templates(self) -> None:
        from leizilla.discovery import SequentialDiscovery

        cfg = {
            "templates": [
                "http://a.com/L{num}.pdf",
                "http://b.com/LC{num}.pdf",
            ],
            "start": 1,
            "end": 2,
        }
        resources = SequentialDiscovery(cfg, "ro", "casacivil").run()
        assert len(resources) == 4  # 2 templates × 2 numbers


# ---------------------------------------------------------------------------
# discovery.run_discovery (via mock manifest)
# ---------------------------------------------------------------------------


class TestRunDiscovery:
    def test_run_discovery_sequential(
        self, temp_db: DuckDBStorage, tmp_path: Path
    ) -> None:
        from leizilla.discovery import run_discovery

        manifest = {
            "fontes": {
                "casacivil": {
                    "discovery": [
                        {
                            "strategy": "sequential",
                            "templates": ["http://example.com/L{num}.pdf"],
                            "start": 1,
                            "end": 2,
                        }
                    ]
                }
            }
        }
        manifest_dir = tmp_path / "manifests"
        manifest_dir.mkdir()
        (manifest_dir / "test-ente.json").write_text(json.dumps(manifest))

        import leizilla.discovery as discovery_mod

        original = discovery_mod.load_manifest

        def mock_load(ente: str) -> Any:
            if ente == "test-ente":
                return manifest
            return original(ente)

        with patch.object(discovery_mod, "load_manifest", side_effect=mock_load):
            total = run_discovery("test-ente", temp_db)

        assert total == 2
        assert len(temp_db.get_pending_resources()) == 2

    def test_unknown_strategy_skipped(self, temp_db: DuckDBStorage) -> None:
        from leizilla.discovery import run_discovery

        manifest = {
            "fontes": {"desconhecida": {"discovery": [{"strategy": "nao-existe"}]}}
        }

        import leizilla.discovery as discovery_mod

        with patch.object(discovery_mod, "load_manifest", return_value=manifest):
            total = run_discovery("ro", temp_db)

        assert total == 0


# ---------------------------------------------------------------------------
# scraper.harvest_pending_resources
# ---------------------------------------------------------------------------


class TestHarvestPendingResources:
    def test_empty_queue_returns_zeros(self, temp_db: DuckDBStorage) -> None:
        from leizilla.scraper import harvest_pending_resources

        pub = MagicMock()
        stats = harvest_pending_resources(temp_db, pub, limit=10)
        assert stats["success"] == 0
        assert stats["failed"] == 0
        assert stats["robots-blocked"] == 0

    def test_robots_blocked_increments_counter(self, temp_db: DuckDBStorage) -> None:
        from leizilla.scraper import harvest_pending_resources

        temp_db.insert_resource(_make_resource(url="http://blocked.com/lei.pdf"))
        pub = MagicMock()

        with patch("leizilla.scraper.robots.is_allowed", return_value=False):
            stats = harvest_pending_resources(temp_db, pub, limit=10)

        assert stats["robots-blocked"] == 1
        assert stats["success"] == 0

    def test_failed_fetch_increments_failed(self, temp_db: DuckDBStorage) -> None:
        from leizilla.scraper import harvest_pending_resources

        temp_db.insert_resource(_make_resource())
        pub = MagicMock()

        with (
            patch("leizilla.scraper.robots.is_allowed", return_value=True),
            patch("leizilla.scraper.wayback.check_available", return_value=None),
            patch("leizilla.scraper.wayback.fetch_bytes", return_value=None),
        ):
            stats = harvest_pending_resources(temp_db, pub, limit=10)

        assert stats["failed"] == 1

    def test_successful_harvest_calls_upload(self, temp_db: DuckDBStorage) -> None:
        from leizilla.scraper import harvest_pending_resources

        temp_db.insert_resource(_make_resource())
        pub = MagicMock()
        pub.upload_raw.return_value = {
            "success": True,
            "ia_url": "https://archive.org/details/test",
        }

        with (
            patch("leizilla.scraper.robots.is_allowed", return_value=True),
            patch("leizilla.scraper.wayback.check_available", return_value=None),
            patch("leizilla.scraper.wayback.fetch_bytes", return_value=b"%PDF-1.4\nPDF_CONTENT"),
        ):
            stats = harvest_pending_resources(temp_db, pub, limit=10)

        assert stats["success"] == 1
        pub.upload_raw.assert_called_once()

    def test_limit_respected(self, temp_db: DuckDBStorage) -> None:
        from leizilla.scraper import harvest_pending_resources

        for i in range(5):
            temp_db.insert_resource(
                _make_resource(url=f"http://x.com/{i}.pdf", chave=f"lei-{i:05d}")
            )

        pub = MagicMock()
        with (
            patch("leizilla.scraper.robots.is_allowed", return_value=True),
            patch("leizilla.scraper.wayback.check_available", return_value=None),
            patch("leizilla.scraper.wayback.fetch_bytes", return_value=None),
        ):
            stats = harvest_pending_resources(temp_db, pub, limit=2)

        assert stats["failed"] == 2  # processed 2, both failed fetch
