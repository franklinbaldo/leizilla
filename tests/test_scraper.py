"""Testes para scraper.py — robots → wayback → fetch → upload_raw."""

from typing import Any
from unittest.mock import MagicMock, patch

from leizilla.scraper import make_rate_limiter, scrape_one

_LEI = {
    "id": "ro-assembleia-coddoc-00001",
    "ente": "ro",
    "fonte": "assembleia",
    "chave": "coddoc-00001",
    "titulo": "Lei de Teste",
}
_FONTE_URL = "https://www.al.ro.leg.br/legislacao/leis/1"
_PDF_URL = "https://www.al.ro.leg.br/legislacao/leis/1.pdf"
_WB_URL = "https://web.archive.org/web/20260101000000/" + _PDF_URL
_PDF_BYTES = b"%PDF-fake"


def _make_publisher(success: bool = True) -> MagicMock:
    pub = MagicMock()
    if success:
        pub.upload_raw.return_value = {
            "success": True,
            "ia_id": "leizilla-raw-ro-assembleia-coddoc-00001",
            "ia_url": "https://archive.org/details/leizilla-raw-ro-assembleia-coddoc-00001",
        }
    else:
        pub.upload_raw.return_value = {"success": False, "error": "IA error"}
    return pub


class TestScrapeOne:
    @patch("leizilla.scraper.robots.is_allowed", return_value=False)
    def test_fonte_url_robots_blocked(self, _mock: Any) -> None:
        result = scrape_one(_FONTE_URL, _PDF_URL, _LEI, _make_publisher())
        assert result == {
            "success": False,
            "reason": "robots-blocked",
            "url": _FONTE_URL,
        }

    @patch("leizilla.scraper.robots.is_allowed", side_effect=[True, False])
    def test_pdf_url_robots_blocked(self, _mock: Any) -> None:
        result = scrape_one(_FONTE_URL, _PDF_URL, _LEI, _make_publisher())
        assert result == {"success": False, "reason": "robots-blocked", "url": _PDF_URL}

    @patch("leizilla.scraper.wayback.check_available", return_value=_WB_URL)
    @patch("leizilla.scraper.wayback.fetch_bytes", return_value=_PDF_BYTES)
    @patch("leizilla.scraper.wayback.save_page", return_value=True)
    @patch("leizilla.scraper.robots.is_allowed", return_value=True)
    def test_wayback_fetch_success(self, _r: Any, _s: Any, _f: Any, _c: Any) -> None:
        pub = _make_publisher()
        result = scrape_one(_FONTE_URL, _PDF_URL, _LEI, pub)
        assert result["success"] is True
        call_kwargs = pub.upload_raw.call_args
        assert call_kwargs.kwargs["fetched_from"] == "wayback"
        assert call_kwargs.kwargs["wayback_url"] == _WB_URL

    @patch("leizilla.scraper.wayback.check_available", return_value=None)
    @patch("leizilla.scraper.wayback.fetch_bytes", return_value=_PDF_BYTES)
    @patch("leizilla.scraper.wayback.save_page", return_value=False)
    @patch("leizilla.scraper.robots.is_allowed", return_value=True)
    def test_fallback_direct_fetch(self, _r: Any, _s: Any, _f: Any, _c: Any) -> None:
        pub = _make_publisher()
        result = scrape_one(_FONTE_URL, _PDF_URL, _LEI, pub)
        assert result["success"] is True
        call_kwargs = pub.upload_raw.call_args
        assert call_kwargs.kwargs["fetched_from"] == "source-fallback"
        assert call_kwargs.kwargs["wayback_url"] is None

    @patch("leizilla.scraper.wayback.check_available", return_value=None)
    @patch("leizilla.scraper.wayback.fetch_bytes", return_value=None)
    @patch("leizilla.scraper.wayback.save_page", return_value=False)
    @patch("leizilla.scraper.robots.is_allowed", return_value=True)
    def test_fetch_failed(self, _r: Any, _s: Any, _f: Any, _c: Any) -> None:
        pub = _make_publisher()
        result = scrape_one(_FONTE_URL, _PDF_URL, _LEI, pub)
        assert result == {"success": False, "reason": "fetch-failed", "url": _PDF_URL}
        pub.upload_raw.assert_not_called()

    @patch("leizilla.scraper.wayback.check_available", return_value=_WB_URL)
    @patch("leizilla.scraper.wayback.fetch_bytes", return_value=_PDF_BYTES)
    @patch("leizilla.scraper.wayback.save_page", return_value=True)
    @patch("leizilla.scraper.robots.is_allowed", return_value=True)
    def test_upload_failure_propagated(
        self, _r: Any, _s: Any, _f: Any, _c: Any
    ) -> None:
        pub = _make_publisher(success=False)
        result = scrape_one(_FONTE_URL, _PDF_URL, _LEI, pub)
        assert result["success"] is False
        assert "error" in result

    @patch("leizilla.scraper.wayback.check_available", return_value=_WB_URL)
    @patch("leizilla.scraper.wayback.fetch_bytes", side_effect=[None, _PDF_BYTES])
    @patch("leizilla.scraper.wayback.save_page", return_value=True)
    @patch("leizilla.scraper.robots.is_allowed", return_value=True)
    def test_wayback_bytes_none_then_fallback(
        self, _r: Any, _s: Any, _f: Any, _c: Any
    ) -> None:
        """Wayback URL existe mas fetch retorna None → fallback direto."""
        pub = _make_publisher()
        result = scrape_one(_FONTE_URL, _PDF_URL, _LEI, pub)
        assert result["success"] is True
        call_kwargs = pub.upload_raw.call_args
        assert call_kwargs.kwargs["fetched_from"] == "source-fallback"

    @patch("leizilla.scraper.wayback.check_available", return_value=None)
    @patch("leizilla.scraper.wayback.fetch_bytes", return_value=_PDF_BYTES)
    @patch("leizilla.scraper.wayback.save_page", return_value=False)
    @patch("leizilla.scraper.robots.is_allowed", return_value=True)
    def test_rate_limiter_called_with_pdf_url_on_fallback(
        self, _r: Any, _s: Any, _f: Any, _c: Any
    ) -> None:
        pub = _make_publisher()
        rate_mock = MagicMock()
        scrape_one(_FONTE_URL, _PDF_URL, _LEI, pub, rate_limiter=rate_mock)
        rate_mock.assert_called_once_with(_PDF_URL)


class TestMakeRateLimiter:
    def test_returns_callable(self) -> None:
        limiter = make_rate_limiter(0.0)
        assert callable(limiter)

    def test_callable_runs_without_error(self) -> None:
        limiter = make_rate_limiter(0.0)
        limiter("https://host-a.gov.br/doc.pdf")
        limiter("https://host-a.gov.br/doc2.pdf")

    def test_different_hosts_independent(self) -> None:
        """Hosts distintos não bloqueiam uns aos outros."""
        import time

        limiter = make_rate_limiter(min_interval=60.0)  # intervalo longo
        t0 = time.monotonic()
        limiter("https://host-a.gov.br/doc.pdf")
        limiter("https://host-b.gov.br/doc.pdf")  # host diferente — não deve sleep
        elapsed = time.monotonic() - t0
        assert elapsed < 5.0, (
            f"Hosts distintos serializaram indevidamente ({elapsed:.2f}s)"
        )

    def test_same_host_respects_interval(self) -> None:
        """Mesmo host é rate-limitado corretamente."""
        import time

        limiter = make_rate_limiter(min_interval=0.05)
        t0 = time.monotonic()
        limiter("https://host-a.gov.br/doc1.pdf")
        limiter("https://host-a.gov.br/doc2.pdf")  # mesmo host → deve aguardar
        elapsed = time.monotonic() - t0
        assert elapsed >= 0.04, f"Rate limit não respeitado ({elapsed:.3f}s)"
