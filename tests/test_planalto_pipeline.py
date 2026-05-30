"""Testes para M2.7 + M6.3: Planalto federal HTML pipeline.

Cobre: discover_planalto_laws (legacy + year-scoped), planalto_year_scoped_url,
build_raw_meta_html, upload_raw_html, scrape_one_html.
HTTP e IA CLI 100% mockados — sem rede.
"""

import subprocess
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
import typer

from leizilla.fontes.federal import (
    _CamaraApiState,
    _camara_year_lookup,
    discover_planalto_laws,
    planalto_year_scoped_url,
)
from leizilla.publisher import InternetArchivePublisher, build_raw_meta_html

# ---------------------------------------------------------------------------
# discover_planalto_laws
# ---------------------------------------------------------------------------


def _no_year(t: str, n: int) -> None:
    """Stub de year_lookup_fn para testes offline (sem chamada à Câmara API)."""
    return None


class TestDiscoverPlanaltoLaws:
    def test_generates_correct_lei_urls(self) -> None:
        laws = discover_planalto_laws("lei", 9503, 9505, year_lookup_fn=_no_year)
        assert len(laws) == 3
        assert (
            laws[0]["url_original"]
            == "https://www.planalto.gov.br/ccivil_03/leis/L9503.htm"
        )
        assert (
            laws[1]["url_original"]
            == "https://www.planalto.gov.br/ccivil_03/leis/L9504.htm"
        )
        assert (
            laws[2]["url_original"]
            == "https://www.planalto.gov.br/ccivil_03/leis/L9505.htm"
        )

    def test_generates_correct_lcp_urls(self) -> None:
        laws = discover_planalto_laws("lcp", 87, 88, year_lookup_fn=_no_year)
        assert (
            laws[0]["url_original"]
            == "https://www.planalto.gov.br/ccivil_03/leis/lcp/Lcp87.htm"
        )
        assert (
            laws[1]["url_original"]
            == "https://www.planalto.gov.br/ccivil_03/leis/lcp/Lcp88.htm"
        )

    def test_generates_correct_decreto_urls(self) -> None:
        laws = discover_planalto_laws("decreto", 99, 101, year_lookup_fn=_no_year)
        assert (
            laws[0]["url_original"]
            == "https://www.planalto.gov.br/ccivil_03/decreto/D99.htm"
        )

    def test_sets_correct_metadata(self) -> None:
        laws = discover_planalto_laws("lei", 9503, 9503, year_lookup_fn=_no_year)
        law = laws[0]
        assert law["ente"] == "federal"
        assert law["fonte"] == "planalto"
        assert law["chave"] == "lei-09503"
        assert law["tipo"] == "lei"
        assert law["numero"] == 9503

    def test_empty_range(self) -> None:
        laws = discover_planalto_laws("lei", 5, 4, year_lookup_fn=_no_year)
        assert laws == []

    def test_invalid_tipo_raises(self) -> None:
        with pytest.raises(ValueError, match="tipo deve ser"):
            discover_planalto_laws("portaria", 1, 5)

    def test_single_item_range(self) -> None:
        laws = discover_planalto_laws("lei", 1, 1, year_lookup_fn=_no_year)
        assert len(laws) == 1
        assert laws[0]["chave"] == "lei-00001"


# ---------------------------------------------------------------------------
# M6.3: year-scoped URLs
# ---------------------------------------------------------------------------


class TestPlanaltoYearScopedUrl:
    def test_lei_2014(self) -> None:
        url = planalto_year_scoped_url("lei", 12965, 2014)
        assert (
            url
            == "https://www.planalto.gov.br/ccivil_03/_ato2011-2014/2014/lei/l12965.htm"
        )

    def test_lcp_2006(self) -> None:
        url = planalto_year_scoped_url("lcp", 123, 2006)
        assert (
            url
            == "https://www.planalto.gov.br/ccivil_03/_ato2003-2006/2006/lei/lcp123.htm"
        )

    def test_decreto_2012(self) -> None:
        url = planalto_year_scoped_url("decreto", 7724, 2012)
        assert (
            url
            == "https://www.planalto.gov.br/ccivil_03/_ato2011-2014/2012/decreto/d7724.htm"
        )

    def test_year_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="fora dos ranges"):
            planalto_year_scoped_url("lei", 1, 1900)

    def test_ato_range_boundaries(self) -> None:
        assert "_ato2003-2006" in planalto_year_scoped_url("lei", 1, 2003)
        assert "_ato2003-2006" in planalto_year_scoped_url("lei", 1, 2006)
        assert "_ato2023-2026" in planalto_year_scoped_url("lei", 1, 2026)
        # Anos futuros: quadriênio dinâmico além da tabela estática (P2 fix)
        assert "_ato2027-2030" in planalto_year_scoped_url("lei", 1, 2027)
        assert "_ato2027-2030" in planalto_year_scoped_url("lei", 1, 2030)
        assert "_ato2031-2034" in planalto_year_scoped_url("lei", 1, 2031)


class TestDiscoverPlanaltoLawsYearScoped:
    def _lookup_2014(self, tipo: str, numero: int) -> int:
        return 2014

    def _lookup_none(self, tipo: str, numero: int) -> None:
        return None

    def test_post_2002_uses_year_scoped_url(self) -> None:
        laws = discover_planalto_laws(
            "lei", 12965, 12965, year_lookup_fn=self._lookup_2014
        )
        assert laws[0]["url_original"] == (
            "https://www.planalto.gov.br/ccivil_03/_ato2011-2014/2014/lei/l12965.htm"
        )

    def test_year_lookup_fail_falls_back_to_legacy(self) -> None:
        laws = discover_planalto_laws(
            "lei", 12965, 12965, year_lookup_fn=self._lookup_none
        )
        assert laws[0]["url_original"] == (
            "https://www.planalto.gov.br/ccivil_03/leis/L12965.htm"
        )

    def test_year_2002_uses_legacy(self) -> None:
        laws = discover_planalto_laws(
            "lei", 10406, 10406, year_lookup_fn=lambda t, n: 2002
        )
        assert "/leis/L10406.htm" in laws[0]["url_original"]

    def test_lcp_post_2002(self) -> None:
        laws = discover_planalto_laws("lcp", 123, 123, year_lookup_fn=lambda t, n: 2006)
        assert "_ato2003-2006" in laws[0]["url_original"]
        assert "lcp123.htm" in laws[0]["url_original"]

    def test_chave_unchanged_by_year(self) -> None:
        laws = discover_planalto_laws(
            "lei", 12965, 12965, year_lookup_fn=self._lookup_2014
        )
        assert laws[0]["chave"] == "lei-12965"

    def test_mixed_range_with_year_lookup(self) -> None:
        def lookup(tipo: str, num: int) -> int | None:
            return 2014 if num > 12000 else None

        laws = discover_planalto_laws("lei", 9503, 12965, year_lookup_fn=lookup)
        assert "/leis/L9503.htm" in laws[0]["url_original"]
        assert "_ato2011-2014" in laws[-1]["url_original"]


# ---------------------------------------------------------------------------
# _camara_year_lookup — circuit breaker
# ---------------------------------------------------------------------------


class TestCamaraYearLookupCircuitBreaker:
    def setup_method(self) -> None:
        """Reseta estado do circuit breaker e cache entre testes."""
        _CamaraApiState.available = True
        _camara_year_lookup.cache_clear()

    def test_returns_year_on_success(self) -> None:
        payload = b'{"dados":[{"ano":2014}]}'
        with patch("urllib.request.urlopen") as mock_open:
            mock_resp = MagicMock()
            mock_resp.__enter__ = lambda s: mock_resp
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_resp.read.return_value = payload
            mock_open.return_value = mock_resp
            result = _camara_year_lookup("lei", 12965)
        assert result == 2014

    def test_circuit_opens_on_network_failure(self) -> None:
        import urllib.error

        with patch(
            "urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")
        ):
            result = _camara_year_lookup("lei", 1)
        assert result is None
        assert _CamaraApiState.available is False

    def test_skips_api_after_circuit_opens(self) -> None:
        _CamaraApiState.available = False
        with patch("urllib.request.urlopen") as mock_open:
            result = _camara_year_lookup("lei", 99999)
        mock_open.assert_not_called()
        assert result is None

    def test_timeout_is_3s(self) -> None:
        """Verifica que o timeout configurado é 3s (não 10s)."""
        payload = b'{"dados":[{"ano":2020}]}'
        captured_timeout: list = []
        with patch("urllib.request.urlopen") as mock_open:
            mock_resp = MagicMock()
            mock_resp.__enter__ = lambda s: mock_resp
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_resp.read.return_value = payload
            mock_open.side_effect = lambda url, timeout=None: (
                captured_timeout.append(timeout) or mock_resp
            )
            _camara_year_lookup("lei", 54321)
        assert captured_timeout == [3]

    def test_429_does_not_open_circuit(self) -> None:
        """HTTP 429 (rate-limit) é transiente — não deve abrir o circuit breaker."""
        import urllib.error

        http_error = urllib.error.HTTPError(
            url="", code=429, msg="Too Many Requests", hdrs=None, fp=None
        )  # type: ignore[arg-type]
        with patch("urllib.request.urlopen", side_effect=http_error):
            result = _camara_year_lookup("lei", 2)
        assert result is None
        assert _CamaraApiState.available is True, "429 não deve abrir o circuit breaker"

    def test_non_429_http_error_opens_circuit(self) -> None:
        """HTTP 503 (server error) abre o circuit breaker."""
        import urllib.error

        http_error = urllib.error.HTTPError(
            url="", code=503, msg="Service Unavailable", hdrs=None, fp=None
        )  # type: ignore[arg-type]
        with patch("urllib.request.urlopen", side_effect=http_error):
            result = _camara_year_lookup("lei", 3)
        assert result is None
        assert _CamaraApiState.available is False, "503 deve abrir o circuit breaker"


# ---------------------------------------------------------------------------
# build_raw_meta_html
# ---------------------------------------------------------------------------


class TestBuildRawMetaHtml:
    def _lei_data(self) -> Dict[str, Any]:
        return {
            "ente": "federal",
            "fonte": "planalto",
            "chave": "lei-09503",
            "url_original": "https://www.planalto.gov.br/ccivil_03/leis/L9503.htm",
        }

    def test_content_type_is_html(self) -> None:
        meta = build_raw_meta_html("<html/>", self._lei_data(), "wayback")
        assert meta["content_type"] == "html"

    def test_hash_html_present(self) -> None:
        meta = build_raw_meta_html("<html>test</html>", self._lei_data(), "wayback")
        assert meta["hash_html"].startswith("sha256:")
        assert len(meta["hash_html"]) == 71  # "sha256:" + 64 hex chars

    def test_hash_depends_on_content(self) -> None:
        meta1 = build_raw_meta_html("<html>a</html>", self._lei_data(), "wayback")
        meta2 = build_raw_meta_html("<html>b</html>", self._lei_data(), "wayback")
        assert meta1["hash_html"] != meta2["hash_html"]

    def test_provenance_wayback_field(self) -> None:
        meta = build_raw_meta_html(
            "<html/>",
            self._lei_data(),
            "wayback",
            wayback_url="https://web.archive.org/web/snap/url",
        )
        assert meta["provenance_wayback"]["fetched_from"] == "wayback"
        assert (
            meta["provenance_wayback"]["wayback_url"]
            == "https://web.archive.org/web/snap/url"
        )

    def test_meta_version(self) -> None:
        meta = build_raw_meta_html("<html/>", self._lei_data(), "source-fallback")
        assert meta["leizilla_meta_version"] == "0.1"


# ---------------------------------------------------------------------------
# upload_raw_html
# ---------------------------------------------------------------------------


def _publisher() -> InternetArchivePublisher:
    pub = InternetArchivePublisher()
    pub.access_key = "test-key"
    pub.secret_key = "test-secret"
    return pub


def _lei_data_html() -> Dict[str, Any]:
    return {
        "ente": "federal",
        "fonte": "planalto",
        "chave": "lei-09503",
        "url_original": "https://www.planalto.gov.br/ccivil_03/leis/L9503.htm",
        "titulo": "Lei 9503",
    }


class TestUploadRawHtml:
    def test_success_returns_ia_id(self, tmp_path: Any) -> None:
        pub = _publisher()
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        with (
            patch("subprocess.run", return_value=mock_result),
            patch(
                "leizilla.publisher.update_raw_index",
                return_value={"success": True},
            ),
        ):
            result = pub.upload_raw_html("<html>lei</html>", _lei_data_html())
        assert result["success"] is True
        assert result["ia_id"] == "leizilla-raw-federal-planalto-lei-09503"
        assert "archive.org/details" in result["ia_url"]

    def test_no_credentials_returns_error(self) -> None:
        pub = InternetArchivePublisher()
        pub.access_key = ""
        pub.secret_key = ""
        result = pub.upload_raw_html("<html/>", _lei_data_html())
        assert result["success"] is False
        assert "credentials" in result["error"]

    def test_subprocess_failure_returns_error(self) -> None:
        pub = _publisher()
        err = subprocess.CalledProcessError(1, "ia", stderr="quota exceeded")
        with patch("subprocess.run", side_effect=err):
            result = pub.upload_raw_html("<html/>", _lei_data_html())
        assert result["success"] is False
        assert "quota exceeded" in result["error"]

    def test_missing_ia_cli_returns_error(self) -> None:
        pub = _publisher()
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = pub.upload_raw_html("<html/>", _lei_data_html())
        assert result["success"] is False
        assert "ia CLI" in result["error"]

    def test_ia_called_with_html_extension(self) -> None:
        pub = _publisher()
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            pub.upload_raw_html("<html>lei</html>", _lei_data_html())
        call_args = mock_run.call_args_list[0][0][0]
        html_files = [
            a for a in call_args if isinstance(a, str) and a.endswith(".html")
        ]
        assert len(html_files) == 1

    def test_mediatype_is_texts(self) -> None:
        pub = _publisher()
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            pub.upload_raw_html("<html/>", _lei_data_html())
        call_args = mock_run.call_args_list[0][0][0]
        assert "mediatype:texts" in call_args


# ---------------------------------------------------------------------------
# scrape_one_html
# ---------------------------------------------------------------------------


class TestScrapeOneHtml:
    def _url(self) -> str:
        return "https://www.planalto.gov.br/ccivil_03/leis/L9503.htm"

    def test_robots_blocked_returns_failure(self) -> None:
        from leizilla.scraper import scrape_one_html

        pub = _publisher()
        with patch("leizilla.robots.is_allowed", return_value=False):
            result = scrape_one_html(self._url(), _lei_data_html(), pub)
        assert result["success"] is False
        assert result["reason"] == "robots-blocked"

    def test_fetch_failed_returns_failure(self) -> None:
        from leizilla.scraper import scrape_one_html

        pub = _publisher()
        with (
            patch("leizilla.robots.is_allowed", return_value=True),
            patch("leizilla.wayback.save_page"),
            patch("leizilla.wayback.check_available", return_value=None),
            patch("leizilla.scraper.fetch_html", return_value=None),
        ):
            result = scrape_one_html(self._url(), _lei_data_html(), pub)
        assert result["success"] is False
        assert result["reason"] == "fetch-failed"

    def test_wayback_primary_success(self) -> None:
        from leizilla.scraper import scrape_one_html

        pub = _publisher()
        wb_url = "https://web.archive.org/web/snap/url"
        mock_run = MagicMock(returncode=0, stdout="", stderr="")
        with (
            patch("leizilla.robots.is_allowed", return_value=True),
            patch("leizilla.wayback.save_page"),
            patch("leizilla.wayback.check_available", return_value=wb_url),
            patch("leizilla.scraper.fetch_html", return_value="<html>lei</html>"),
            patch("subprocess.run", return_value=mock_run),
            patch(
                "leizilla.publisher.update_raw_index",
                return_value={"success": True},
            ),
        ):
            result = scrape_one_html(self._url(), _lei_data_html(), pub)
        assert result["success"] is True

    def test_fallback_when_wayback_unavailable(self) -> None:
        from leizilla.scraper import scrape_one_html

        pub = _publisher()
        mock_run = MagicMock(returncode=0, stdout="", stderr="")
        calls: list = []

        def fake_fetch(url: str, **_: Any) -> str:
            calls.append(url)
            return "<html>lei</html>"

        with (
            patch("leizilla.robots.is_allowed", return_value=True),
            patch("leizilla.wayback.save_page"),
            patch("leizilla.wayback.check_available", return_value=None),
            patch("leizilla.scraper.fetch_html", side_effect=fake_fetch),
            patch("subprocess.run", return_value=mock_run) as _mock,
            patch(
                "leizilla.publisher.update_raw_index",
                return_value={"success": True},
            ),
        ):
            result = scrape_one_html(self._url(), _lei_data_html(), pub)
        assert result["success"] is True, result
        assert self._url() in calls

    def test_rate_limiter_called_on_fallback(self) -> None:
        from leizilla.scraper import scrape_one_html

        pub = _publisher()
        mock_run = MagicMock(returncode=0, stdout="", stderr="")
        rate_mock = MagicMock()
        with (
            patch("leizilla.robots.is_allowed", return_value=True),
            patch("leizilla.wayback.save_page"),
            patch("leizilla.wayback.check_available", return_value=None),
            patch("leizilla.scraper.fetch_html", return_value="<html/>"),
            patch("subprocess.run", return_value=mock_run),
        ):
            scrape_one_html(self._url(), _lei_data_html(), pub, rate_limiter=rate_mock)
        rate_mock.assert_called_once_with(self._url())

    def test_rate_limiter_not_called_when_wayback_succeeds(self) -> None:
        from leizilla.scraper import scrape_one_html

        pub = _publisher()
        mock_run = MagicMock(returncode=0, stdout="", stderr="")
        rate_mock = MagicMock()
        wb_url = "https://web.archive.org/web/snap/url"
        with (
            patch("leizilla.robots.is_allowed", return_value=True),
            patch("leizilla.wayback.save_page"),
            patch("leizilla.wayback.check_available", return_value=wb_url),
            patch("leizilla.scraper.fetch_html", return_value="<html/>"),
            patch("subprocess.run", return_value=mock_run),
        ):
            scrape_one_html(self._url(), _lei_data_html(), pub, rate_limiter=rate_mock)
        rate_mock.assert_not_called()


# ---------------------------------------------------------------------------
# CLI --tipo validation
# ---------------------------------------------------------------------------


class TestCmdScrapeTipoValidation:
    def _invoke(self, *args: str) -> "typer.testing.Result":  # type: ignore[name-defined]
        from typer.testing import CliRunner
        from leizilla.cli import app

        runner = CliRunner()
        return runner.invoke(app, ["scrape"] + list(args))

    def test_invalid_tipo_rejected_immediately(self) -> None:
        result = self._invoke("--tipo", "leii", "--fonte", "casacivil")
        assert result.exit_code != 0
        assert "leii" in result.output

    def test_invalid_tipo_rejected_with_planalto(self) -> None:
        result = self._invoke("--tipo", "poney", "--fonte", "planalto")
        assert result.exit_code != 0
        assert "poney" in result.output

    def test_lc_blocked_for_planalto(self) -> None:
        result = self._invoke("--tipo", "lc", "--fonte", "planalto")
        assert result.exit_code != 0
        assert "casacivil" in result.output

    def test_lcp_blocked_for_casacivil(self) -> None:
        result = self._invoke("--tipo", "lcp", "--fonte", "casacivil")
        assert result.exit_code != 0
        assert "planalto" in result.output

    def test_decreto_blocked_for_casacivil(self) -> None:
        result = self._invoke("--tipo", "decreto", "--fonte", "casacivil")
        assert result.exit_code != 0
        assert "planalto" in result.output

    def test_lcp_accepted_for_planalto(self) -> None:
        with (
            patch("leizilla.robots.is_allowed", return_value=False),
            patch("leizilla.wayback.save_page"),
        ):
            result = self._invoke(
                "--ente",
                "federal",
                "--fonte",
                "planalto",
                "--tipo",
                "lcp",
                "--start-coddoc",
                "1",
                "--end-coddoc",
                "1",
            )
        assert "lcp" not in result.output or "inválido" not in result.output
        assert result.exit_code == 0
