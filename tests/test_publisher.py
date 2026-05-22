"""Testes unitários para leizilla.publisher — funções puras sem IA."""

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from leizilla.publisher import _raw_identifier, _bundle_identifier, build_raw_meta


class TestRawIdentifier:
    def test_format(self):
        assert _raw_identifier("ro", "casacivil", "coddoc-00042") == (
            "leizilla-raw-ro-casacivil-coddoc-00042"
        )

    def test_federal(self):
        assert _raw_identifier("federal", "planalto", "lei-14133-2021") == (
            "leizilla-raw-federal-planalto-lei-14133-2021"
        )


class TestBundleIdentifier:
    def test_format_uses_iso_week(self):
        dt = datetime(2026, 5, 22, tzinfo=timezone.utc)
        iso = dt.isocalendar()
        expected = f"leizilla-bundle-ro-casacivil-{iso[0]}-W{iso[1]:02d}"
        assert _bundle_identifier("ro", "casacivil", dt) == expected

    def test_defaults_to_current_date(self):
        result = _bundle_identifier("ro", "casacivil")
        assert result.startswith("leizilla-bundle-ro-casacivil-")
        assert "-W" in result


class TestBuildRawMeta:
    def _law(self) -> dict:
        return {
            "ente": "ro",
            "fonte": "casacivil",
            "chave": "coddoc-00042",
            "url_original": "https://ditel.casacivil.ro.gov.br/cotel/livros?coddoc=42",
            "titulo": "Lei 42/1990",
        }

    def test_meta_version(self):
        meta = build_raw_meta(self._law(), b"pdf", "wayback")
        assert meta["leizilla_meta_version"] == "0.1"

    def test_ente_fonte_chave(self):
        meta = build_raw_meta(self._law(), b"pdf", "wayback")
        assert meta["ente"] == "ro"
        assert meta["fonte"] == "casacivil"
        assert meta["chave"] == "coddoc-00042"

    def test_hash_pdf_sha256(self):
        pdf = b"binary pdf content"
        meta = build_raw_meta(self._law(), pdf, "wayback")
        expected = f"sha256:{hashlib.sha256(pdf).hexdigest()}"
        assert meta["hash_pdf"] == expected

    def test_fetched_from_wayback(self):
        meta = build_raw_meta(
            self._law(), b"pdf", "wayback",
            wayback_url="https://web.archive.org/web/20260522/https://example"
        )
        assert meta["provenance_wayback"]["fetched_from"] == "wayback"
        assert meta["provenance_wayback"]["wayback_url"] == (
            "https://web.archive.org/web/20260522/https://example"
        )

    def test_fetched_from_source_fallback(self):
        meta = build_raw_meta(self._law(), b"pdf", "source-fallback")
        assert meta["provenance_wayback"]["fetched_from"] == "source-fallback"
        assert meta["provenance_wayback"]["wayback_url"] is None

    def test_ia_id_bundle_present(self):
        meta = build_raw_meta(self._law(), b"pdf", "wayback")
        assert meta["ia_id_bundle"].startswith("leizilla-bundle-ro-casacivil-")

    def test_data_captura_is_iso8601(self):
        meta = build_raw_meta(self._law(), b"pdf", "wayback")
        dt = datetime.fromisoformat(meta["data_captura"])
        assert dt.tzinfo is not None

    def test_falls_back_to_id_when_no_chave(self):
        law = {"ente": "ro", "fonte": "casacivil", "id": "ro-casacivil-coddoc-00042"}
        meta = build_raw_meta(law, b"pdf", "wayback")
        assert meta["chave"] == "ro-casacivil-coddoc-00042"
