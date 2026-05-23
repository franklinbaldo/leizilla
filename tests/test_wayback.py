"""Testes unitários para leizilla.wayback — HTTP mockado, sem rede."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch


from leizilla import wayback


def _mock_urlopen(data: dict, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status = status
    resp.read.return_value = json.dumps(data).encode()
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _ts(delta_hours: float = 0.0) -> str:
    dt = datetime.now(tz=timezone.utc) - timedelta(hours=delta_hours)
    return dt.strftime("%Y%m%d%H%M%S")


class TestCheckAvailable:
    def test_returns_url_for_fresh_snapshot(self):
        data = {
            "archived_snapshots": {
                "closest": {
                    "status": "200",
                    "timestamp": _ts(1),
                    "url": "https://web.archive.org/web/20260522/https://example.gov.br",
                }
            }
        }
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(data)):
            result = wayback.check_available("https://example.gov.br")
        assert result == "https://web.archive.org/web/20260522/https://example.gov.br"

    def test_returns_none_for_expired_snapshot(self):
        data = {
            "archived_snapshots": {
                "closest": {
                    "status": "200",
                    "timestamp": _ts(25),  # 25h atrás > 24h limite
                    "url": "https://web.archive.org/web/old/https://example.gov.br",
                }
            }
        }
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(data)):
            result = wayback.check_available(
                "https://example.gov.br", max_age_seconds=24 * 3600
            )
        assert result is None

    def test_returns_old_snapshot_when_no_max_age_limit(self):
        data = {
            "archived_snapshots": {
                "closest": {
                    "status": "200",
                    "timestamp": _ts(25),  # 25h atrás
                    "url": "https://web.archive.org/web/old/https://example.gov.br",
                }
            }
        }
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(data)):
            result = wayback.check_available("https://example.gov.br")
        assert result == "https://web.archive.org/web/old/https://example.gov.br"

    def test_returns_none_when_no_snapshot(self):
        data = {"archived_snapshots": {}}
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(data)):
            result = wayback.check_available("https://example.gov.br")
        assert result is None

    def test_returns_none_when_snapshot_status_not_200(self):
        data = {
            "archived_snapshots": {
                "closest": {"status": "404", "timestamp": _ts(1), "url": "..."}
            }
        }
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(data)):
            result = wayback.check_available("https://example.gov.br")
        assert result is None

    def test_returns_none_on_network_error(self):
        with patch("urllib.request.urlopen", side_effect=OSError("timeout")):
            result = wayback.check_available("https://example.gov.br")
        assert result is None

    def test_custom_max_age(self):
        data = {
            "archived_snapshots": {
                "closest": {
                    "status": "200",
                    "timestamp": _ts(2),  # 2h atrás
                    "url": "https://web.archive.org/web/x/https://example.gov.br",
                }
            }
        }
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(data)):
            # max_age de 1h → snapshot de 2h é expirado
            assert (
                wayback.check_available("https://example.gov.br", max_age_seconds=3600)
                is None
            )
            # max_age de 3h → snapshot de 2h é fresco
            assert (
                wayback.check_available("https://example.gov.br", max_age_seconds=10800)
                is not None
            )


class TestSavePage:
    def test_returns_true_on_200(self):
        resp = MagicMock()
        resp.status = 200
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=resp):
            assert wayback.save_page("https://example.gov.br") is True

    def test_returns_true_on_302(self):
        resp = MagicMock()
        resp.status = 302
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=resp):
            assert wayback.save_page("https://example.gov.br") is True

    def test_returns_false_on_network_error(self):
        with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
            assert wayback.save_page("https://example.gov.br") is False

    def test_returns_false_on_exception(self):
        with patch("urllib.request.urlopen", side_effect=Exception("unexpected")):
            assert wayback.save_page("https://example.gov.br") is False


class TestFetchBytes:
    def test_returns_bytes_on_success(self):
        resp = MagicMock()
        resp.read.return_value = b"%PDF-1.4 binary content"
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=resp):
            result = wayback.fetch_bytes(
                "https://web.archive.org/web/x/https://lei.pdf"
            )
        assert result == b"%PDF-1.4 binary content"

    def test_returns_none_on_error(self):
        with patch("urllib.request.urlopen", side_effect=OSError("404")):
            assert (
                wayback.fetch_bytes("https://web.archive.org/web/x/https://lei.pdf")
                is None
            )

    def test_returns_none_on_timeout(self):
        with patch("urllib.request.urlopen", side_effect=TimeoutError()):
            assert (
                wayback.fetch_bytes("https://web.archive.org/web/x/https://lei.pdf")
                is None
            )
