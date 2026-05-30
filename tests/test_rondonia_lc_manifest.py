"""Pipeline validation for the content-addressed raw layer (ADR-0010).

Rondônia Lei Complementar example: upload names the file by content hash, the
range item buckets by hash prefix, and the (ente, fonte) index records the
source_key → content_hash mapping. The source's harvest key (coddoc/lc number)
is metadata, never a path.
"""

from unittest.mock import patch, MagicMock

from leizilla.publisher import InternetArchivePublisher
from leizilla.ia_utils import (
    compute_hash,
    lookup_current_hash,
    raw_filename,
    raw_range_identifier,
    resolve_raw_url,
)


class TestRondoniaLCContentAddressed:
    def test_filename_and_range_are_content_addressed(self):
        pdf_bytes = b"PDF content for LC 42"
        h = compute_hash(pdf_bytes)

        # Range item buckets by hash prefix — no coddoc, no lc number in the path.
        assert raw_range_identifier("ro", "casacivil", h) == (
            f"leizilla-raw-ro-casacivil-{h[:2]}"
        )
        # File is named purely by the content hash.
        assert raw_filename(h, ".pdf") == f"{h}.pdf"

    def test_resolve_via_index_roundtrip(self):
        pdf_bytes = b"PDF content for LC 42"
        h = compute_hash(pdf_bytes)
        # Index maps the legacy source_key (lc-00042) to the content hash.
        index_csv = (
            "source_key,content_hash,content_type,source_url,captured_at\n"
            f"lc-00042,{h},application/pdf,http://ditel/LC42.pdf,2026-05-30T00:00:00+00:00\n"
        )
        assert lookup_current_hash(index_csv, "lc-00042") == (h, "application/pdf")

        with patch("leizilla.ia_utils._fetch_text", return_value=index_csv):
            url = resolve_raw_url("leizilla-raw-ro-casacivil-lc-00042", "_djvu.txt")
        assert url == (
            f"https://archive.org/download/leizilla-raw-ro-casacivil-{h[:2]}/"
            f"{h}_djvu.txt"
        )

    @patch("leizilla.publisher.update_raw_index")
    @patch("subprocess.run")
    def test_complete_upload_raw_lc_rondonia(self, mock_run, mock_index, tmp_path):
        mock_run.return_value = MagicMock(returncode=0)
        mock_index.return_value = {"success": True}

        pub = InternetArchivePublisher()
        pub.access_key = "fake-key"
        pub.secret_key = "fake-secret"

        pdf_path = tmp_path / "LC42.pdf"
        pdf_bytes = b"PDF content for LC 42"
        pdf_path.write_bytes(pdf_bytes)
        h = compute_hash(pdf_bytes)

        lei_data = {
            "ente": "ro",
            "fonte": "casacivil",
            "chave": "lc-00042",
            "url_original": "http://ditel.casacivil.ro.gov.br/COTEL/Livros/Files/LC42.pdf",
        }

        res = pub.upload_raw(pdf_path, lei_data, pdf_bytes, fetched_from="wayback")

        assert res["success"] is True
        assert (
            res["ia_url"]
            == f"https://archive.org/details/leizilla-raw-ro-casacivil-{h[:2]}"
        )

        # Upload targeted the hash-prefix range item with the hash-named file.
        args = mock_run.call_args[0][0]
        assert "ia" in args and "upload" in args
        assert f"leizilla-raw-ro-casacivil-{h[:2]}" in args
        assert any(a.endswith(f"{h}.pdf") for a in args)

        # The index was updated with source_key → content_hash (coddoc/lc as metadata).
        _, kwargs = mock_index.call_args
        assert kwargs["source_key"] == "lc-00042"
        assert kwargs["content_hash"] == h
        assert kwargs["content_type"] == "application/pdf"

    @patch("leizilla.publisher.update_raw_index")
    @patch("subprocess.run")
    def test_index_failure_propagates_as_upload_failure(
        self, mock_run, mock_index, tmp_path
    ):
        # Reads resolve exclusively through the index; if the index write fails,
        # the capture would be unreachable. upload_raw must NOT report success.
        mock_run.return_value = MagicMock(returncode=0)
        mock_index.return_value = {"success": False, "error": "IA 503"}

        pub = InternetArchivePublisher()
        pub.access_key = "fake-key"
        pub.secret_key = "fake-secret"

        pdf_path = tmp_path / "LC42.pdf"
        pdf_bytes = b"PDF content for LC 42"
        pdf_path.write_bytes(pdf_bytes)

        lei_data = {
            "ente": "ro",
            "fonte": "casacivil",
            "chave": "lc-00042",
            "url_original": "http://ditel/LC42.pdf",
        }

        res = pub.upload_raw(pdf_path, lei_data, pdf_bytes, fetched_from="wayback")

        assert res["success"] is False
        assert "index update failed" in res["error"]
