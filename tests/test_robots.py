"""Testes unitários para leizilla.robots — sem rede (mocked)."""

import urllib.robotparser
from unittest.mock import patch

import pytest

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
