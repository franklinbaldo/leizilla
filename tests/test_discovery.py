"""Testes unitários para leizilla.discovery."""

import json
from unittest.mock import MagicMock, patch

import pytest

from leizilla import storage
from leizilla.discovery import (
    SequentialDiscovery,
    WaybackCdxDiscovery,
    load_manifest,
    parse_filename,
    run_discovery,
)


def test_parse_filename():
    assert parse_filename("L5120.pdf") == ("lei", "lei-05120")
    assert parse_filename("LC0012.PDF") == ("lc", "lc-00012")
    assert parse_filename("D9.pdf") == ("decreto", "decreto-00009")
    assert parse_filename("L100012.pdf") == ("lei", "lei-100012")
    assert parse_filename("invalid_name.pdf") == (None, None)


def test_load_manifest():
    manifest = load_manifest("ro")
    assert manifest["ente"] == "ro"
    assert "casacivil" in manifest["fontes"]
    assert "assembleia" in manifest["fontes"]

    with pytest.raises(FileNotFoundError):
        load_manifest("non_existent_ente")


def test_sequential_discovery():
    config = {
        "strategy": "sequential",
        "templates": [
            "http://example.com/Files/L{num}.pdf",
            "http://example.com/Files/LC{num}.pdf",
        ],
        "start": 1,
        "end": 3,
    }
    discoverer = SequentialDiscovery(config, "ro", "casacivil")
    resources = discoverer.run()

    assert len(resources) == 6
    urls = [r["url"] for r in resources]
    assert "http://example.com/Files/L1.pdf" in urls
    assert "http://example.com/Files/LC3.pdf" in urls
    assert resources[0]["ente"] == "ro"
    assert resources[0]["fonte"] == "casacivil"
    assert resources[0]["tipo_documento"] == "lei"
    assert resources[0]["chave"] == "lei-00001"


def test_wayback_cdx_discovery():
    config = {
        "strategy": "wayback-cdx",
        "prefix": "http://example.com/Files/",
    }
    cdx_response = [
        [
            "urlkey",
            "timestamp",
            "original",
            "mimetype",
            "statuscode",
            "digest",
            "length",
        ],
        [
            "com,example)/files/l5120.pdf",
            "20220824115429",
            "http://example.com/Files/L5120.pdf",
            "application/pdf",
            "200",
            "DIGEST123",
            "1234",
        ],
        [
            "com,example)/files/d10.pdf",
            "20220824115430",
            "http://example.com/Files/D10.pdf",
            "application/pdf",
            "302",  # Should be skipped (not 200)
            "DIGEST456",
            "1234",
        ],
    ]

    mock_resp = MagicMock()
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.read.return_value = json.dumps(cdx_response).encode("utf-8")

    with patch("urllib.request.urlopen", return_value=mock_resp):
        discoverer = WaybackCdxDiscovery(config, "ro", "casacivil")
        resources = discoverer.run()

    assert len(resources) == 1
    res = resources[0]
    assert res["url"] == "http://example.com/Files/L5120.pdf"
    assert res["tipo_documento"] == "lei"
    assert res["chave"] == "lei-05120"
    assert (
        res["wayback_snapshot"]
        == "https://web.archive.org/web/20220824115429/http://example.com/Files/L5120.pdf"
    )


@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "test.duckdb"
    db = storage.DuckDBStorage(db_path)
    yield db
    db.close()


def test_run_discovery(temp_db):
    # Mock all runner strategies
    mock_res_cdx = [
        {
            "url": "http://example.com/L1.pdf",
            "ente": "ro",
            "fonte": "casacivil",
            "tipo_documento": "lei",
            "chave": "lei-00001",
            "status": "pending",
            "wayback_snapshot": "http://web.archive.org/web/2022/L1.pdf",
        }
    ]
    mock_res_seq = [
        {
            "url": "http://example.com/L2.pdf",
            "ente": "ro",
            "fonte": "casacivil",
            "tipo_documento": "lei",
            "chave": "lei-00002",
            "status": "pending",
            "wayback_snapshot": None,
        }
    ]

    with (
        patch.object(WaybackCdxDiscovery, "run", return_value=mock_res_cdx),
        patch.object(SequentialDiscovery, "run", return_value=mock_res_seq),
        patch("leizilla.discovery.PlaywrightCrawlerDiscovery") as mock_playwright_cls,
    ):
        mock_playwright_instance = MagicMock()
        mock_playwright_instance.run.return_value = []
        mock_playwright_cls.return_value = mock_playwright_instance

        total = run_discovery("ro", temp_db)

    assert total == 2
    pending = temp_db.get_pending_resources()
    assert len(pending) == 2
    urls = [p["url"] for p in pending]
    assert "http://example.com/L1.pdf" in urls
    assert "http://example.com/L2.pdf" in urls
