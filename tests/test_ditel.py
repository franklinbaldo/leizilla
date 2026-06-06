"""Tests for the DITEL (Casa Civil RO) ingestion adapter — Phase 1.

Covers: decreto enumeration, https base URLs, the manifest (https + D template), and the
Wayback provenance helpers (closest_snapshot / ensure_archived). All offline — the Wayback
API is mocked. See docs/ditel-ingestion.md.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from leizilla import wayback
from leizilla.crawler import discover_casacivil_laws
from leizilla.discovery import parse_filename

MANIFEST = (
    Path(__file__).resolve().parents[1] / "src" / "leizilla" / "manifests" / "ro.json"
)
_BASE = "https://ditel.casacivil.ro.gov.br/COTEL/Livros/Files"


class TestDiscoverCasacivil:
    def test_decreto_enumeration(self):
        laws = discover_casacivil_laws(tipo="decreto", start_num=1, end_num=2)
        assert [law["chave"] for law in laws] == ["decreto-00001", "decreto-00002"]
        assert laws[0]["url_pdf_original"] == f"{_BASE}/D1.pdf"
        assert laws[0]["fonte"] == "casacivil" and laws[0]["ente"] == "ro"

    def test_lei_and_lc_use_https(self):
        lei = discover_casacivil_laws(tipo="lei", start_num=5, end_num=5)[0]
        lc = discover_casacivil_laws(tipo="lc", start_num=5, end_num=5)[0]
        assert lei["url_pdf_original"] == f"{_BASE}/L5.pdf"
        assert lc["url_pdf_original"] == f"{_BASE}/LC5.pdf"
        assert lei["url_original"].startswith("https://")

    def test_unknown_tipo_raises(self):
        with pytest.raises(ValueError, match="tipo deve ser"):
            discover_casacivil_laws(tipo="portaria")

    def test_empty_range_is_empty(self):
        assert discover_casacivil_laws(tipo="decreto", start_num=10, end_num=5) == []


class TestParseFilenameDecreto:
    def test_decreto_filename(self):
        assert parse_filename("D26000.pdf") == ("decreto", "decreto-26000")

    def test_lei_and_lc_filenames(self):
        assert parse_filename("L5120.pdf") == ("lei", "lei-05120")
        assert parse_filename("LC42.pdf") == ("lc", "lc-00042")


class TestManifest:
    def test_casacivil_has_https_and_decreto_template(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cc = manifest["fontes"]["casacivil"]["discovery"]
        templates = [t for cfg in cc for t in cfg.get("templates", [])]
        prefixes = [cfg.get("prefix") for cfg in cc if "prefix" in cfg]
        # every DITEL URL is https (the WAF 403s on http)
        for url in templates + prefixes:
            assert url.startswith("https://ditel.casacivil.ro.gov.br/"), url
        # decreto (D{num}) is enumerated alongside L and LC
        assert any("/D{num}.pdf" in t for t in templates)
        assert any("/L{num}.pdf" in t for t in templates)
        assert any("/LC{num}.pdf" in t for t in templates)


def _avail_response(snapshot: dict | None) -> bytes:
    closest = {"archived_snapshots": {"closest": snapshot} if snapshot else {}}
    return json.dumps(closest).encode()


class TestWaybackProvenance:
    def _mock_urlopen(self, body: bytes):
        resp = MagicMock()
        resp.read.return_value = body
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    def test_closest_snapshot_returns_url_and_timestamp_any_age(self):
        snap = {
            "status": "200",
            "url": "http://web.archive.org/web/20220903083131/http://ditel/D1.pdf",
            "timestamp": "20220903083131",
        }
        with patch(
            "urllib.request.urlopen",
            return_value=self._mock_urlopen(_avail_response(snap)),
        ):
            result = wayback.closest_snapshot("http://ditel/D1.pdf")
        assert result == (snap["url"], "20220903083131")

    def test_closest_snapshot_none_when_unarchived(self):
        with patch(
            "urllib.request.urlopen",
            return_value=self._mock_urlopen(_avail_response(None)),
        ):
            assert wayback.closest_snapshot("http://ditel/LC1000.pdf") is None

    def test_closest_snapshot_none_on_non_200(self):
        snap = {"status": "404", "url": "x", "timestamp": "1"}
        with patch(
            "urllib.request.urlopen",
            return_value=self._mock_urlopen(_avail_response(snap)),
        ):
            assert wayback.closest_snapshot("http://ditel/x.pdf") is None

    def test_ensure_archived_reuses_existing_without_saving(self):
        existing = ("http://web.archive.org/web/2022/x", "20220101000000")
        with (
            patch("leizilla.wayback.closest_snapshot", return_value=existing),
            patch("leizilla.wayback.save_page") as save,
        ):
            assert wayback.ensure_archived("http://ditel/x.pdf") == existing
            save.assert_not_called()  # SPN-first means "don't re-archive what exists"

    def test_ensure_archived_saves_then_resolves_when_missing(self):
        saved = ("http://web.archive.org/web/2026/x", "20260101000000")
        with (
            patch("leizilla.wayback.closest_snapshot", side_effect=[None, saved]),
            patch("leizilla.wayback.save_page", return_value=True) as save,
        ):
            assert wayback.ensure_archived("http://ditel/x.pdf") == saved
            save.assert_called_once()

    def test_ensure_archived_none_when_save_and_lookup_fail(self):
        with (
            patch("leizilla.wayback.closest_snapshot", side_effect=[None, None]),
            patch("leizilla.wayback.save_page", return_value=False),
        ):
            assert wayback.ensure_archived("http://ditel/x.pdf") is None
