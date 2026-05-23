"""Testes unitários para leizilla.publisher — funções puras sem IA."""

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock


from leizilla.publisher import (
    _raw_identifier,
    _bundle_identifier,
    build_raw_meta,
    InternetArchivePublisher,
)


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
            self._law(),
            b"pdf",
            "wayback",
            wayback_url="https://web.archive.org/web/20260522/https://example",
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


_PARSED_META = {
    "leizilla_meta_version": "0.1",
    "ente": "ro",
    "tipo": "lei",
    "ia_id_raw": "leizilla-raw-ro-casacivil-coddoc-00042",
    "ia_id_parsed": "leizilla-ro-lei-00042-1990",
    "parse_method": "claude-haiku-4-5",
    "confianca_parse_global": 0.95,
    "parse_timestamp": "2026-05-22T04:00:00+00:00",
    "fontes_consultadas": ["leizilla-raw-ro-casacivil-coddoc-00042"],
    "tem_divergencia": False,
    "num_divergencias": 0,
}

_XML_CONTENT = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<lei xmlns="https://leizilla.org/lei/0.1" schema-version="0.1"'
    ' urn-lex="urn:lex:br;rondonia:estadual:lei:1990-01-01;42"'
    ' vigente-em="2026-05-22">'
    '<dispositivo path="ementa">'
    "<versao><texto>Ementa.</texto></versao>"
    "</dispositivo>"
    "</lei>"
)


class TestUploadParsed:
    def _publisher(self) -> InternetArchivePublisher:
        pub = InternetArchivePublisher()
        pub.access_key = "test-key"
        pub.secret_key = "test-secret"
        return pub

    def test_returns_success_on_valid_upload(self):
        pub = self._publisher()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = pub.upload_parsed(
                "leizilla-ro-lei-00042-1990", _XML_CONTENT, _PARSED_META
            )
        assert result["success"] is True
        assert result["ia_id"] == "leizilla-ro-lei-00042-1990"
        assert (
            result["ia_url"] == "https://archive.org/details/leizilla-ro-lei-00042-1990"
        )

    def test_uploads_law_xml_and_parsed_meta(self):
        pub = self._publisher()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            pub.upload_parsed("leizilla-ro-lei-00042-1990", _XML_CONTENT, _PARSED_META)

        call_args = mock_run.call_args[0][0]
        assert "ia" in call_args
        assert "upload" in call_args
        assert "leizilla-ro-lei-00042-1990" in call_args
        xml_arg = next((a for a in call_args if a.endswith("law.xml")), None)
        assert xml_arg is not None
        meta_arg = next((a for a in call_args if a.endswith("parsed_meta.json")), None)
        assert meta_arg is not None

    def test_xml_content_written_to_file(self):
        pub = self._publisher()
        captured_files: list[str] = []

        def capture_run(cmd, **kwargs):
            for arg in cmd:
                if arg.endswith("law.xml"):
                    real_path = os.path.realpath(arg)
                    assert real_path.startswith(os.path.realpath(tempfile.gettempdir()))
                    captured_files.append(Path(real_path).read_text())
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=capture_run):
            pub.upload_parsed("leizilla-ro-lei-00042-1990", _XML_CONTENT, _PARSED_META)

        assert len(captured_files) == 1
        assert captured_files[0] == _XML_CONTENT

    def test_parsed_meta_json_written_correctly(self):
        pub = self._publisher()
        captured_metas: list[dict] = []

        def capture_run(cmd, **kwargs):
            for arg in cmd:
                if arg.endswith("parsed_meta.json"):
                    real_path = os.path.realpath(arg)
                    assert real_path.startswith(os.path.realpath(tempfile.gettempdir()))
                    captured_metas.append(json.loads(Path(real_path).read_text()))
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=capture_run):
            pub.upload_parsed("leizilla-ro-lei-00042-1990", _XML_CONTENT, _PARSED_META)

        assert len(captured_metas) == 1
        assert captured_metas[0]["ia_id_parsed"] == "leizilla-ro-lei-00042-1990"

    def test_returns_failure_without_credentials(self):
        pub = InternetArchivePublisher()
        pub.access_key = None
        pub.secret_key = None
        result = pub.upload_parsed(
            "leizilla-ro-lei-00042-1990", _XML_CONTENT, _PARSED_META
        )
        assert result["success"] is False
        assert "credentials" in result["error"]

    def test_returns_failure_on_subprocess_error(self):
        import subprocess

        pub = self._publisher()
        err = subprocess.CalledProcessError(1, "ia", stderr="upload failed")
        with patch("subprocess.run", side_effect=err):
            result = pub.upload_parsed(
                "leizilla-ro-lei-00042-1990", _XML_CONTENT, _PARSED_META
            )
        assert result["success"] is False
        assert "upload failed" in result["error"]

    def test_metadata_fields_are_passed(self):
        pub = self._publisher()
        pub.collection = "test-collection"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            pub.upload_parsed("leizilla-ro-lei-00042-1990", _XML_CONTENT, _PARSED_META)

        call_args = mock_run.call_args[0][0]
        metadata_pairs = {}
        for i in range(len(call_args) - 1):
            if call_args[i] == "--metadata":
                k, v = call_args[i + 1].split(":", 1)
                metadata_pairs[k] = v

        assert metadata_pairs["language"] == "por"
        assert "Rondônia, Brazil" in metadata_pairs["coverage"]
        assert metadata_pairs["date"] == "1990"
        assert metadata_pairs["collection"] == "test-collection"
        assert "URN" in metadata_pairs["description"]


class TestUploadRaw:
    def _publisher(self) -> InternetArchivePublisher:
        pub = InternetArchivePublisher()
        pub.access_key = "test-key"
        pub.secret_key = "test-secret"
        pub.collection = "test-collection"
        return pub

    def test_upload_raw_metadata(self, tmp_path):
        pub = self._publisher()
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"pdf data")

        lei_data = {
            "ente": "ro",
            "fonte": "casacivil",
            "chave": "coddoc-00042",
            "titulo": "Lei 42/1990",
            "ano": "1990",
        }

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            pub.upload_raw(pdf_path, lei_data, b"pdf data")

        call_args = mock_run.call_args[0][0]
        metadata_pairs = {}
        for i in range(len(call_args) - 1):
            if call_args[i] == "--metadata":
                k, v = call_args[i + 1].split(":", 1)
                metadata_pairs[k] = v

        assert metadata_pairs["language"] == "por"
        assert "Rondônia, Brazil" in metadata_pairs["coverage"]
        assert metadata_pairs["date"] == "1990"
        assert metadata_pairs["collection"] == "test-collection"
        assert "Documento original (PDF)" in metadata_pairs["description"]


class TestUploadRawHtml:
    def _publisher(self) -> InternetArchivePublisher:
        pub = InternetArchivePublisher()
        pub.access_key = "test-key"
        pub.secret_key = "test-secret"
        pub.collection = "test-collection"
        return pub

    def test_upload_raw_html_metadata(self):
        pub = self._publisher()
        lei_data = {
            "ente": "federal",
            "fonte": "planalto",
            "chave": "lei-14133-2021",
            "titulo": "Lei 14133/2021",
            "ano": 2021,
        }

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            pub.upload_raw_html("<html></html>", lei_data)

        call_args = mock_run.call_args[0][0]
        metadata_pairs = {}
        for i in range(len(call_args) - 1):
            if call_args[i] == "--metadata":
                k, v = call_args[i + 1].split(":", 1)
                metadata_pairs[k] = v

        assert metadata_pairs["language"] == "por"
        assert metadata_pairs["coverage"] == "Brazil"
        assert metadata_pairs["date"] == "2021"
        assert metadata_pairs["collection"] == "test-collection"
        assert "Documento original (HTML)" in metadata_pairs["description"]


class TestUploadDataset:
    def _publisher(self) -> InternetArchivePublisher:
        pub = InternetArchivePublisher()
        pub.access_key = "test-key"
        pub.secret_key = "test-secret"
        pub.collection = "test-collection"
        return pub

    def test_upload_dataset_metadata(self, tmp_path):
        pub = self._publisher()
        parquet_path = tmp_path / "versoes.parquet"
        parquet_path.write_bytes(b"parquet data")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            pub.upload_dataset(
                parquet_path, "ro", version=1, row_count=10, git_sha="fake-git-sha"
            )

        call_args = mock_run.call_args[0][0]
        metadata_pairs = {}
        for i in range(len(call_args) - 1):
            if call_args[i] == "--metadata":
                k, v = call_args[i + 1].split(":", 1)
                metadata_pairs[k] = v

        assert metadata_pairs["language"] == "por"
        assert "Rondônia, Brazil" in metadata_pairs["coverage"]
        assert metadata_pairs["collection"] == "test-collection"
        assert "Dataset consolidado" in metadata_pairs["description"]
