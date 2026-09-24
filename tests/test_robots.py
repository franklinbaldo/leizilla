"""Testes unitários para leizilla.robots — sem rede (mocked)."""

import urllib.error
import urllib.robotparser
from unittest.mock import MagicMock, patch


from leizilla import robots


def _make_parser(
    disallow: list[str] | None = None,
    allow: list[str] | None = None,
    agent: str = "*",
) -> urllib.robotparser.RobotFileParser:
    lines = [f"User-agent: {agent}"]
    for path in allow or []:
        lines.append(f"Allow: {path}")
    for path in disallow or []:
        lines.append(f"Disallow: {path}")
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(lines)
    return rp


class TestIsAllowed:
    def test_allowed_when_no_disallow_rules(self):
        parser = _make_parser()
        with patch.object(robots, "_load_robots", return_value=parser):
            assert robots.is_allowed("https://example.gov.br/leis/1") is True

    def test_blocked_by_wildcard_disallow(self):
        parser = _make_parser(disallow=["/leis/"])
        with patch.object(robots, "_load_robots", return_value=parser):
            assert robots.is_allowed("https://example.gov.br/leis/1") is False

    def test_allowed_outside_disallowed_path(self):
        parser = _make_parser(disallow=["/admin/"])
        with patch.object(robots, "_load_robots", return_value=parser):
            assert robots.is_allowed("https://example.gov.br/leis/1") is True

    def test_allowed_when_robots_txt_missing(self):
        with patch.object(robots, "_load_robots", return_value=None):
            assert robots.is_allowed("https://example.gov.br/leis/1") is True

    def test_malformed_url_returns_false(self):
        assert robots.is_allowed("not-a-url") is False

    def test_empty_url_returns_false(self):
        assert robots.is_allowed("") is False

    def test_constructs_robots_url_from_host(self):
        captured: list[str] = []

        def capture(url: str) -> urllib.robotparser.RobotFileParser:
            captured.append(url)
            return _make_parser()

        with patch.object(robots, "_load_robots", side_effect=capture):
            robots.is_allowed("https://casacivil.ro.gov.br/cotel/leis/42")

        assert captured == ["https://casacivil.ro.gov.br/robots.txt"]

    def test_disallow_all_blocks_any_path(self):
        parser = _make_parser(disallow=["/"])
        with patch.object(robots, "_load_robots", return_value=parser):
            assert robots.is_allowed("https://example.gov.br/leis/1") is False

    def test_specific_agent_disallow(self):
        parser = _make_parser(disallow=["/leis/"], agent="leizilla")
        with patch.object(robots, "_load_robots", return_value=parser):
            assert robots.is_allowed("https://example.gov.br/leis/1") is False


class TestFetchRobots:
    """Covers issue #121: a 403 must not permanently poison the cache."""

    def setup_method(self) -> None:
        robots._confirmed_cache.clear()

    def teardown_method(self) -> None:
        robots._confirmed_cache.clear()

    def test_403_fails_open_without_caching(self):
        forbidden = urllib.error.HTTPError(
            "https://waf.gov.br/robots.txt", 403, "Forbidden", None, None
        )
        with patch("urllib.request.urlopen", side_effect=forbidden):
            assert robots.is_allowed("https://waf.gov.br/leis/1") is True

        # A transient fetch failure (403 WAF block) must NOT be cached as a
        # confirmed outcome — before this fix, RobotFileParser silently set
        # disallow_all=True on a 403 and lru_cache pinned that forever.
        assert "https://waf.gov.br/robots.txt" not in robots._confirmed_cache

    def test_403_then_later_successful_fetch_is_not_poisoned(self):
        # First call: transient WAF 403 — fails open, not cached.
        forbidden = urllib.error.HTTPError(
            "https://waf.gov.br/robots.txt", 403, "Forbidden", None, None
        )
        with patch("urllib.request.urlopen", side_effect=forbidden):
            assert robots.is_allowed("https://waf.gov.br/leis/1") is True

        # Second call: robots.txt is actually fetchable now and disallows /leis/.
        body = b"User-agent: *\nDisallow: /leis/\n"
        resp = MagicMock()
        resp.status = 200
        resp.read.return_value = body
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=resp):
            assert robots.is_allowed("https://waf.gov.br/leis/1") is False

        # And this real, confirmed outcome IS now cached — the durable cache
        # only holds confirmed fetches, never the earlier transient failure.
        assert "https://waf.gov.br/robots.txt" in robots._confirmed_cache

    def test_429_on_robots_fetch_fails_open_without_caching(self):
        rate_limited = urllib.error.HTTPError(
            "https://x.gov.br/robots.txt", 429, "Too Many Requests", None, None
        )
        with patch("urllib.request.urlopen", side_effect=rate_limited):
            assert robots.is_allowed("https://x.gov.br/leis/1") is True
        assert "https://x.gov.br/robots.txt" not in robots._confirmed_cache

    def test_confirmed_404_is_cached_as_allow_all(self):
        not_found = urllib.error.HTTPError(
            "https://x.gov.br/robots.txt", 404, "Not Found", None, None
        )
        with patch("urllib.request.urlopen", side_effect=not_found):
            assert robots.is_allowed("https://x.gov.br/leis/1") is True
        assert robots._confirmed_cache["https://x.gov.br/robots.txt"] is None

    def test_confirmed_disallow_is_cached_and_stays_blocked(self):
        body = b"User-agent: *\nDisallow: /\n"
        resp = MagicMock()
        resp.status = 200
        resp.read.return_value = body
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=resp):
            assert robots.is_allowed("https://x.gov.br/leis/1") is False
        assert "https://x.gov.br/robots.txt" in robots._confirmed_cache

        # Cached — a subsequent network error doesn't matter, the confirmed
        # disallow still applies (this direction of "permanent" is correct).
        with patch("urllib.request.urlopen", side_effect=OSError("boom")):
            assert robots.is_allowed("https://x.gov.br/leis/1") is False
