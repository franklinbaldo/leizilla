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
from leizilla.discovery import WaybackCdxDiscovery, parse_filename
from leizilla.publisher import build_raw_meta
from leizilla.scraper import scrape_one

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
        casacivil = manifest["fontes"]["casacivil"]
        discovery = casacivil["discovery"]
        probe = casacivil.get("probe", [])
        prefixes = [cfg.get("prefix") for cfg in discovery if "prefix" in cfg]
        probe_templates = [t for cfg in probe for t in cfg.get("templates", [])]
        # every DITEL URL is https (the WAF 403s on http)
        for url in prefixes + probe_templates:
            assert url.startswith("https://ditel.casacivil.ro.gov.br/"), url
        # decreto (D{num}) is enumerated in probe alongside L and LC
        assert any("/D{num}.pdf" in t for t in probe_templates)
        assert any("/L{num}.pdf" in t for t in probe_templates)
        assert any("/LC{num}.pdf" in t for t in probe_templates)


class TestCdxSchemeNormalization:
    def test_http_capture_normalized_to_manifest_https_for_dedup(self):
        # CDX returns DITEL's historical http capture; the dedup `url` must be normalized
        # to the manifest https scheme (so it matches the sequential strategy and isn't
        # harvested twice), while the http snapshot is kept in wayback_snapshot.
        config = {"strategy": "wayback-cdx", "prefix": f"{_BASE}/"}
        cdx = [
            ["urlkey", "timestamp", "original", "mime", "statuscode", "digest", "len"],
            [
                "k",
                "20241208215859",
                f"http://{_BASE[len('https://') :]}/L5120.pdf",
                "application/pdf",
                "200",
                "d",
                "1",
            ],
        ]
        resp = MagicMock()
        resp.read.return_value = json.dumps(cdx).encode()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=resp):
            resources = WaybackCdxDiscovery(config, "ro", "casacivil").run()
        assert len(resources) == 1
        assert resources[0]["url"] == f"{_BASE}/L5120.pdf"  # https dedup key
        assert resources[0]["wayback_snapshot"].endswith(
            f"/http://{_BASE[len('https://') :]}/L5120.pdf"  # http snapshot preserved
        )


class TestRawMetaProvenance:
    """The Wayback timestamp must land in the serialized _meta.json sidecar, not be dropped."""

    def test_timestamp_from_explicit_field(self):
        meta = build_raw_meta(
            {
                "ente": "ro",
                "fonte": "casacivil",
                "chave": "lei-05120",
                "wayback_timestamp": "20241208215859",
            },
            b"PDF",
            "wayback",
            wayback_url="http://web.archive.org/web/20241208215859/http://x/L5120.pdf",
        )
        assert meta["provenance_wayback"]["wayback_timestamp"] == "20241208215859"

    def test_timestamp_derived_from_snapshot_url(self):
        # No explicit field (e.g. the CLI scrape path) → derived from the snapshot URL.
        meta = build_raw_meta(
            {"ente": "ro", "fonte": "casacivil", "chave": "decreto-01000"},
            b"PDF",
            "wayback",
            wayback_url="https://web.archive.org/web/20220903083131/http://x/D1000.pdf",
        )
        assert meta["provenance_wayback"]["wayback_timestamp"] == "20220903083131"

    def test_timestamp_none_on_direct_fetch(self):
        meta = build_raw_meta(
            {"ente": "ro"}, b"PDF", "source-fallback", wayback_url=None
        )
        assert meta["provenance_wayback"]["wayback_timestamp"] is None


class TestScrapeOneSnapshot:
    def test_uses_pre_discovered_snapshot(self):
        # A CDX-discovered http snapshot is used directly — scheme-sensitive
        # check_available is bypassed, preserving the historical capture + its timestamp.
        snap = "http://web.archive.org/web/20241208215859/http://ditel/L5120.pdf"
        pub = MagicMock()
        pub.upload_raw.return_value = {"success": True, "ia_id": "x", "ia_url": "u"}
        with (
            patch("leizilla.scraper.robots.is_allowed", return_value=True),
            patch("leizilla.scraper.wayback.save_page"),
            patch("leizilla.scraper.wayback.check_available") as check,
            patch("leizilla.scraper.wayback.fetch_bytes", return_value=b"%PDF-fake") as fetch,
        ):
            result = scrape_one(
                "https://ditel/",
                "https://ditel/L5120.pdf",
                {"ente": "ro", "fonte": "casacivil", "chave": "lei-05120"},
                pub,
                wayback_snapshot=snap,
            )
        assert result["success"]
        check.assert_not_called()  # provided snapshot bypasses the availability lookup
        fetch.assert_called_with(snap)  # fetched from the http-keyed capture
        assert pub.upload_raw.call_args.kwargs["wayback_url"] == snap


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

    def test_closest_snapshot_tries_both_schemes(self):
        # https query misses (DITEL captures are http-keyed); http query finds it.
        hit = (
            "http://web.archive.org/web/20241208215859/http://ditel/L5120.pdf",
            "20241208215859",
        )
        with patch("leizilla.wayback._query_available", side_effect=[None, hit]) as q:
            result = wayback.closest_snapshot("https://ditel/L5120.pdf")
        assert result == hit
        assert q.call_count == 2  # tried https, then flipped to http

    def test_save_and_locate_reads_content_location(self):
        resp = MagicMock()
        resp.headers.get.return_value = "/web/20260606010101/https://ditel/x.pdf"
        resp.geturl.return_value = "https://web.archive.org/save/https://ditel/x.pdf"
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=resp):
            result = wayback.save_and_locate("https://ditel/x.pdf")
        assert result == (
            "https://web.archive.org/web/20260606010101/https://ditel/x.pdf",
            "20260606010101",
        )

    def test_ensure_archived_reuses_existing_without_saving(self):
        existing = ("http://web.archive.org/web/2022/x", "20220101000000")
        with (
            patch("leizilla.wayback.closest_snapshot", return_value=existing),
            patch("leizilla.wayback.save_and_locate") as save,
        ):
            assert wayback.ensure_archived("http://ditel/x.pdf") == existing
            save.assert_not_called()  # SPN-first means "don't re-archive what exists"

    def test_ensure_archived_saves_and_locates_from_response(self):
        # SPN exposes the snapshot asynchronously → we read it from the save response.
        saved = ("https://web.archive.org/web/2026/x", "20260101000000")
        with (
            patch("leizilla.wayback.closest_snapshot", return_value=None),
            patch("leizilla.wayback.save_and_locate", return_value=saved) as save,
        ):
            assert wayback.ensure_archived("http://ditel/x.pdf") == saved
            save.assert_called_once()

    def test_ensure_archived_none_when_save_and_lookup_fail(self):
        with (
            patch("leizilla.wayback.closest_snapshot", return_value=None),
            patch("leizilla.wayback.save_and_locate", return_value=None),
        ):
            assert wayback.ensure_archived("http://ditel/x.pdf") is None

    def test_snapshot_timestamp_extracted_from_url(self):
        url = "http://web.archive.org/web/20220903083131/http://ditel/D1.pdf"
        assert wayback.snapshot_timestamp(url) == "20220903083131"

    def test_snapshot_timestamp_handles_modifier_suffix(self):
        # Wayback URLs may carry a modifier like /web/<ts>id_/<orig>.
        url = "https://web.archive.org/web/20241208221945id_/https://ditel/L5121.pdf"
        assert wayback.snapshot_timestamp(url) == "20241208221945"

    def test_snapshot_timestamp_none_for_non_wayback(self):
        assert wayback.snapshot_timestamp("https://ditel/L5121.pdf") is None
        assert wayback.snapshot_timestamp("") is None
