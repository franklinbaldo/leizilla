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
from leizilla.ia_utils import parse_identity


def test_parse_filename():
    assert parse_filename("L5120.pdf") == ("lei", "lei-05120")
    assert parse_filename("LC0012.PDF") == ("lc", "lc-00012")
    assert parse_filename("D9.pdf") == ("decreto", "decreto-00009")
    assert parse_filename("L100012.pdf") == ("lei", "lei-100012")
    assert parse_filename("invalid_name.pdf") == (None, None)
    # New tipos
    assert parse_filename("EC10.pdf") == ("ec", "ec-00010")
    assert parse_filename("Res50.pdf") == ("resolucao", "resolucao-00050")
    assert parse_filename("Port100.pdf") == ("portaria", "portaria-00100")
    assert parse_filename("DEC1026.pdf") == ("decreto", "decreto-01026")
    assert parse_filename("DL11.pdf") == ("decreto-lei", "decreto-lei-00011")
    # Port must not match P alone or conflict with LC/L prefix ordering
    assert parse_filename("LC5.pdf") == ("lc", "lc-00005")  # not "l"
    assert parse_filename("EC1.PDF") == ("ec", "ec-00001")  # case insensitive


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


def test_sequential_discovery_head_check():
    """SequentialDiscovery with head_check=True only includes URLs that pass HEAD."""
    config = {
        "strategy": "sequential",
        "templates": ["http://example.com/Files/D{num}.pdf"],
        "start": 1,
        "end": 5,
        "head_check": True,
    }

    # Simulate: only D2 and D4 exist
    def fake_head(url: str, timeout: float = 10.0) -> bool:
        return any(f"/D{n}.pdf" in url for n in [2, 4])

    with patch("leizilla.discovery._head_exists", side_effect=fake_head):
        discoverer = SequentialDiscovery(config, "ro", "casacivil")
        resources = discoverer.run()

    assert len(resources) == 2
    urls = [r["url"] for r in resources]
    assert "http://example.com/Files/D2.pdf" in urls
    assert "http://example.com/Files/D4.pdf" in urls
    assert all(r["tipo_documento"] == "decreto" for r in resources)


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


def test_sequential_discovery_captures_unidentifiable():
    # ADR-0011 §1: filenames that don't yield (tipo, número) are still CAPTURED
    # (preserved, not discarded) — tipo unknown (""), chave = harvest key — so the
    # upload routes them to the _unidentified holding area.
    config = {
        "strategy": "sequential",
        "templates": ["http://example.com/page{num}.pdf"],
        "start": 1,
        "end": 3,
    }
    resources = SequentialDiscovery(config, "ro", "casacivil").run()
    assert len(resources) == 3
    assert resources[0]["tipo_documento"] == ""
    # harvest key preserved under a non-identifying prefix so it can never be
    # mis-promoted to a navigable range (parse_identity must return None).
    assert resources[0]["chave"] == "documento-page1"
    assert parse_identity(resources[0]["chave"]) is None


def test_wayback_cdx_captures_unidentifiable_filenames():
    config = {"strategy": "wayback-cdx", "prefix": "http://example.com/Files/"}
    cdx_response = [
        ["urlkey", "timestamp", "original", "mimetype", "statuscode", "digest", "len"],
        [
            "com,example)/files/relatorio.pdf",
            "20220824115429",
            "http://example.com/Files/relatorio_anual.pdf",
            "application/pdf",
            "200",
            "DIGEST",
            "1234",
        ],
    ]
    mock_resp = MagicMock()
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.read.return_value = json.dumps(cdx_response).encode("utf-8")
    with patch("urllib.request.urlopen", return_value=mock_resp):
        resources = WaybackCdxDiscovery(config, "ro", "casacivil").run()
    assert len(resources) == 1
    assert resources[0]["tipo_documento"] == ""
    assert resources[0]["chave"] == "documento-relatorio_anual"
    assert parse_identity(resources[0]["chave"]) is None


def test_wayback_cdx_word_digit_stem_stays_unidentified():
    # Regression: a fallback stem shaped "{letters}-{digits}" (e.g. oficio-123)
    # must NOT satisfy parse_identity — otherwise it would be promoted to a bogus
    # navigable range (oficio_0001-1000) instead of the _unidentified holding.
    config = {"strategy": "wayback-cdx", "prefix": "http://example.com/Files/"}
    cdx_response = [
        ["urlkey", "timestamp", "original", "mimetype", "statuscode", "digest", "len"],
        [
            "com,example)/files/oficio-123.pdf",
            "20220824115429",
            "http://example.com/Files/oficio-123.pdf",
            "application/pdf",
            "200",
            "DIGEST",
            "1234",
        ],
    ]
    mock_resp = MagicMock()
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.read.return_value = json.dumps(cdx_response).encode("utf-8")
    with patch("urllib.request.urlopen", return_value=mock_resp):
        resources = WaybackCdxDiscovery(config, "ro", "casacivil").run()
    assert resources[0]["chave"] == "documento-oficio-123"
    assert parse_identity(resources[0]["chave"]) is None


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

    from leizilla.discovery import PlaywrightCrawlerDiscovery

    with (
        patch.object(WaybackCdxDiscovery, "run", return_value=mock_res_cdx),
        patch.object(SequentialDiscovery, "run", return_value=mock_res_seq),
        patch.object(PlaywrightCrawlerDiscovery, "run", return_value=[]),
    ):
        total = run_discovery("ro", temp_db)

    # casacivil: 1 cdx + 8 sequential strategies (lei, lc, D, EC, Res, Port, DEC, DL) = 9
    assert total == 9

    pending = temp_db.get_pending_resources()
    assert len(pending) == 2  # lei-00001 (cdx) + lei-00002 (sequential, deduplicated)
    urls = [p["url"] for p in pending]
    assert "http://example.com/L1.pdf" in urls
    assert "http://example.com/L2.pdf" in urls
