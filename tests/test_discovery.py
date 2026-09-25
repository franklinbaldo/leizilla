"""Testes unitários para leizilla.discovery."""

import json
from unittest.mock import MagicMock, patch

import pytest

from leizilla import storage
from leizilla.discovery import (
    DEFAULT_CDX_AUTO_FALLBACK_END,
    STRATEGIES,
    PlanaltoDiscovery,
    SequentialDiscovery,
    WaybackCdxDiscovery,
    load_manifest,
    parse_filename,
    resolve_cdx_max_by_tipo,
    run_discovery,
)
from leizilla.ia_utils import parse_identity


def _cdx_mock_response(rows: list) -> MagicMock:
    """Build a `urllib.request.urlopen` mock returning a CDX-shaped JSON body."""
    header = [
        "urlkey",
        "timestamp",
        "original",
        "mimetype",
        "statuscode",
        "digest",
        "length",
    ]
    mock_resp = MagicMock()
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.read.return_value = json.dumps([header, *rows]).encode("utf-8")
    return mock_resp


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


def test_load_manifest_federal():
    """Issue #246: manifests/federal.json existe e usa a estratégia 'planalto'."""
    manifest = load_manifest("federal")
    assert manifest["ente"] == "federal"
    assert "planalto" in manifest["fontes"]
    discovery_cfgs = manifest["fontes"]["planalto"]["discovery"]
    assert discovery_cfgs, "esperado ao menos uma estratégia de descoberta"
    tipos = {cfg["tipo"] for cfg in discovery_cfgs}
    # Cobre todos os tipos que fontes.federal.discover_planalto_laws suporta.
    assert tipos == {"lei", "lcp", "decreto", "decreto-lei", "emc", "mpv"}
    for cfg in discovery_cfgs:
        assert cfg["strategy"] == "planalto"
        assert cfg["start"] >= 1
        assert cfg["end"] > cfg["start"]


def test_strategies_registry_includes_planalto():
    assert STRATEGIES["planalto"] is PlanaltoDiscovery

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


def test_sequential_discovery_skips_known_urls_without_head_request(temp_db):
    """Achado de produção 2026-09-25: `storage` existia em `SequentialDiscovery.run`
    mas `discover_resources`/`run_discovery` nunca o repassavam, então o dedup-por-DB
    abaixo nunca disparava — toda semana o `head_check` refazia HEAD request para
    TODOS os números desde `start=1`, não só os novos (ver run_discovery). Esta
    verifica que uma URL já em `discovered_resources` é pulada SEM HEAD request."""
    temp_db.insert_resource(
        {
            "url": "http://example.com/Files/D2.pdf",
            "ente": "ro",
            "fonte": "casacivil",
            "tipo_documento": "decreto",
            "chave": "decreto-00002",
            "status": "pending",
            "wayback_snapshot": None,
        }
    )

    config = {
        "strategy": "sequential",
        "templates": ["http://example.com/Files/D{num}.pdf"],
        "start": 1,
        "end": 3,
        "head_check": True,
    }

    head_checked_urls: list[str] = []

    def fake_head(url: str, timeout: float = 10.0) -> bool:
        head_checked_urls.append(url)
        return True

    with patch("leizilla.discovery._head_exists", side_effect=fake_head):
        resources = SequentialDiscovery(config, "ro", "casacivil").run(temp_db)

    # D2 já conhecido: nem HEAD-checked nem re-incluído no resultado.
    assert "http://example.com/Files/D2.pdf" not in head_checked_urls
    urls = [r["url"] for r in resources]
    assert "http://example.com/Files/D2.pdf" not in urls
    assert "http://example.com/Files/D1.pdf" in urls
    assert "http://example.com/Files/D3.pdf" in urls
    assert sorted(head_checked_urls) == [
        "http://example.com/Files/D1.pdf",
        "http://example.com/Files/D3.pdf",
    ]


def test_run_discovery_second_run_skips_head_checks_for_known_urls(temp_db):
    """Fim a fim via `run_discovery` (o que `leizilla discover` realmente chama):
    uma segunda rodada não deve refazer HEAD request para URLs que a primeira
    rodada já gravou em `discovered_resources`."""
    manifest_fontes = {
        "casacivil": {
            "discovery": [
                {
                    "strategy": "sequential",
                    "templates": ["http://example.com/Files/D{num}.pdf"],
                    "start": 1,
                    "end": 3,
                    "head_check": True,
                }
            ]
        }
    }

    head_checked_urls: list[str] = []

    def fake_head(url: str, timeout: float = 10.0) -> bool:
        head_checked_urls.append(url)
        return True

    with (
        patch(
            "leizilla.discovery.load_manifest",
            return_value={"ente": "ro", "fontes": manifest_fontes},
        ),
        patch("leizilla.discovery._head_exists", side_effect=fake_head),
    ):
        first_total = run_discovery("ro", temp_db)
        assert first_total == 3
        assert len(head_checked_urls) == 3

        head_checked_urls.clear()
        second_total = run_discovery("ro", temp_db)

    # Nada novo pra descobrir e nenhum HEAD refeito pras 3 URLs já conhecidas.
    assert second_total == 0
    assert head_checked_urls == []


def _fake_planalto_laws(tipo: str, start: int, end: int, **kwargs) -> list:
    """Substitui fontes.federal.discover_planalto_laws sem chamar a API Câmara."""
    return [
        {
            "ente": "federal",
            "fonte": "planalto",
            "chave": f"{tipo}-{num:05d}",
            "tipo": tipo,
            "numero": num,
            "url_original": f"https://www.planalto.gov.br/ccivil_03/leis/L{num}.htm",
        }
        for num in range(start, end + 1)
    ]


def test_planalto_discovery_basic():
    config = {"strategy": "planalto", "tipo": "lei", "start": 1, "end": 3}
    with patch(
        "leizilla.fontes.federal.discover_planalto_laws",
        side_effect=_fake_planalto_laws,
    ):
        with patch("leizilla.discovery._head_exists", return_value=True):
            resources = PlanaltoDiscovery(config, "federal", "planalto").run()

    assert len(resources) == 3
    assert resources[0]["ente"] == "federal"
    assert resources[0]["fonte"] == "planalto"
    assert resources[0]["tipo_documento"] == "lei"
    assert resources[0]["chave"] == "lei-00001"
    assert resources[0]["url"] == "https://www.planalto.gov.br/ccivil_03/leis/L1.htm"


def test_planalto_discovery_head_check_filters_missing():
    config = {
        "strategy": "planalto",
        "tipo": "lei",
        "start": 1,
        "end": 5,
        "head_check": True,
    }

    def fake_head(url: str, timeout: float = 10.0) -> bool:
        return any(f"/L{n}.htm" in url for n in [2, 4])

    with patch(
        "leizilla.fontes.federal.discover_planalto_laws",
        side_effect=_fake_planalto_laws,
    ):
        with patch("leizilla.discovery._head_exists", side_effect=fake_head):
            resources = PlanaltoDiscovery(config, "federal", "planalto").run()

    assert [r["chave"] for r in resources] == ["lei-00002", "lei-00004"]


def test_planalto_discovery_skips_known_urls(temp_db):
    temp_db.insert_resource(
        {
            "url": "https://www.planalto.gov.br/ccivil_03/leis/L2.htm",
            "ente": "federal",
            "fonte": "planalto",
            "tipo_documento": "lei",
            "chave": "lei-00002",
            "status": "pending",
            "wayback_snapshot": None,
        }
    )
    config = {"strategy": "planalto", "tipo": "lei", "start": 1, "end": 3}

    with patch(
        "leizilla.fontes.federal.discover_planalto_laws",
        side_effect=_fake_planalto_laws,
    ):
        with patch("leizilla.discovery._head_exists", return_value=True):
            resources = PlanaltoDiscovery(config, "federal", "planalto").run(temp_db)

    chaves = [r["chave"] for r in resources]
    assert "lei-00002" not in chaves
    assert sorted(chaves) == ["lei-00001", "lei-00003"]


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

    from leizilla.discovery import CasacivilIndexDiscovery, PlaywrightCrawlerDiscovery

    with (
        patch.object(WaybackCdxDiscovery, "run", return_value=mock_res_cdx),
        patch.object(SequentialDiscovery, "run", return_value=mock_res_seq),
        patch.object(CasacivilIndexDiscovery, "run", return_value=[]),
        patch.object(PlaywrightCrawlerDiscovery, "run", return_value=[]),
    ):
        total = run_discovery("ro", temp_db)

    # casacivil: 1 cdx + 8 sequential (um "sequential" cdx-auto por tipo do
    # manifesto de casacivil, RFC-0003 Fase 1) — cada um mockado retornando o
    # mesmo mock_res_seq (L2.pdf), então só 2 URLs distintas chegam ao DuckDB.
    assert total == 9

    pending = temp_db.get_pending_resources()
    assert len(pending) == 2  # lei-00001 (cdx) + lei-00002 (sequential, deduplicado)
    urls = [p["url"] for p in pending]
    assert "http://example.com/L1.pdf" in urls
    assert "http://example.com/L2.pdf" in urls


def test_run_discovery_scoped_to_fonte(temp_db):
    """fonte='casacivil' nunca deve instanciar/rodar a estratégia da assembleia.

    A PlaywrightCrawlerDiscovery da assembleia crawla milhares de páginas
    sequencialmente e pode travar por horas (visto em produção); um filtro de
    fonte precisa pular a estratégia inteiramente, não só descartar o resultado.
    """
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

    from leizilla.discovery import CasacivilIndexDiscovery, PlaywrightCrawlerDiscovery

    with (
        patch.object(WaybackCdxDiscovery, "run", return_value=mock_res_cdx),
        patch.object(CasacivilIndexDiscovery, "run", return_value=[]),
        patch.object(SequentialDiscovery, "run", return_value=[]),
        patch.object(PlaywrightCrawlerDiscovery, "run") as mock_playwright_run,
    ):
        total = run_discovery("ro", temp_db, fonte="casacivil")

    assert total == 1
    mock_playwright_run.assert_not_called()


class TestResolveCdxMaxByTipo:
    """resolve_cdx_max_by_tipo — porta o cdx_max do legado cmd_scrape/casacivil
    (RFC-0003 Fase 1) para uma função reutilizável pelas estratégias de discovery."""

    def test_normal_response(self):
        rows = [
            [
                "com,example)/files/l10.pdf",
                "20220101000000",
                "http://example.com/Files/L10.pdf",
                "application/pdf",
                "200",
                "D1",
                "1",
            ],
            [
                "com,example)/files/l5120.pdf",
                "20220102000000",
                "http://example.com/Files/L5120.pdf",
                "application/pdf",
                "200",
                "D2",
                "1",
            ],
            [
                "com,example)/files/d3.pdf",
                "20220103000000",
                "http://example.com/Files/D3.pdf",
                "application/pdf",
                "200",
                "D3",
                "1",
            ],
        ]
        with patch("urllib.request.urlopen", return_value=_cdx_mock_response(rows)):
            result = resolve_cdx_max_by_tipo("http://example.com/Files/")
        assert result == {"lei": 5120, "decreto": 3}

    def test_ignores_non_200_and_non_pdf(self):
        rows = [
            [
                "com,example)/files/l10.pdf",
                "20220101000000",
                "http://example.com/Files/L10.pdf",
                "application/pdf",
                "302",
                "D1",
                "1",
            ],
            [
                "com,example)/files/readme.txt",
                "20220101000000",
                "http://example.com/Files/readme.txt",
                "text/plain",
                "200",
                "D2",
                "1",
            ],
        ]
        with patch("urllib.request.urlopen", return_value=_cdx_mock_response(rows)):
            result = resolve_cdx_max_by_tipo("http://example.com/Files/")
        assert result == {}

    def test_empty_response(self):
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.read.return_value = json.dumps([]).encode("utf-8")
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = resolve_cdx_max_by_tipo("http://example.com/Files/")
        assert result == {}

    def test_header_only_response(self):
        with patch("urllib.request.urlopen", return_value=_cdx_mock_response([])):
            result = resolve_cdx_max_by_tipo("http://example.com/Files/")
        assert result == {}

    def test_timeout_fails_open(self):
        import socket

        with patch("urllib.request.urlopen", side_effect=socket.timeout("timed out")):
            result = resolve_cdx_max_by_tipo("http://example.com/Files/")
        assert result == {}

    def test_network_error_fails_open(self):
        with patch("urllib.request.urlopen", side_effect=OSError("network down")):
            result = resolve_cdx_max_by_tipo("http://example.com/Files/")
        assert result == {}

    def test_malformed_json_fails_open(self):
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.read.return_value = b"not json"
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = resolve_cdx_max_by_tipo("http://example.com/Files/")
        assert result == {}


class TestSequentialDiscoveryCdxAuto:
    """SequentialDiscovery com `"end": "cdx-auto"` (RFC-0003 Fase 1)."""

    def _config(self, **overrides):
        config = {
            "strategy": "sequential",
            "templates": ["http://example.com/Files/L{num}.pdf"],
            "start": 1,
            "end": "cdx-auto",
        }
        config.update(overrides)
        return config

    def test_resolves_end_from_cdx(self):
        rows = [
            [
                "com,example)/files/l7.pdf",
                "20220101000000",
                "http://example.com/Files/L7.pdf",
                "application/pdf",
                "200",
                "D1",
                "1",
            ]
        ]
        with patch("urllib.request.urlopen", return_value=_cdx_mock_response(rows)):
            resources = SequentialDiscovery(self._config(), "ro", "casacivil").run()
        assert len(resources) == 7
        assert resources[-1]["url"] == "http://example.com/Files/L7.pdf"

    def test_empty_cdx_falls_back_to_default(self):
        with patch("urllib.request.urlopen", return_value=_cdx_mock_response([])):
            resources = SequentialDiscovery(self._config(), "ro", "casacivil").run()
        assert len(resources) == DEFAULT_CDX_AUTO_FALLBACK_END

    def test_cdx_error_fails_open_to_default(self):
        with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            resources = SequentialDiscovery(self._config(), "ro", "casacivil").run()
        assert len(resources) == DEFAULT_CDX_AUTO_FALLBACK_END

    def test_custom_end_fallback(self):
        config = self._config(end_fallback=3)
        with patch("urllib.request.urlopen", return_value=_cdx_mock_response([])):
            resources = SequentialDiscovery(config, "ro", "casacivil").run()
        assert len(resources) == 3

    def test_invalid_end_string_raises(self):
        with pytest.raises(ValueError, match="cdx-auto"):
            SequentialDiscovery(self._config(end="latest"), "ro", "casacivil")

    def test_start_past_resolved_end_yields_nothing(self):
        config = self._config(start=100)
        rows = [
            [
                "com,example)/files/l7.pdf",
                "20220101000000",
                "http://example.com/Files/L7.pdf",
                "application/pdf",
                "200",
                "D1",
                "1",
            ]
        ]
        with patch("urllib.request.urlopen", return_value=_cdx_mock_response(rows)):
            resources = SequentialDiscovery(config, "ro", "casacivil").run()
        assert resources == []

    def test_fixed_end_never_queries_cdx(self):
        with patch("urllib.request.urlopen") as mock_urlopen:
            resources = SequentialDiscovery(
                self._config(end=2), "ro", "casacivil"
            ).run()
        mock_urlopen.assert_not_called()
        assert len(resources) == 2
