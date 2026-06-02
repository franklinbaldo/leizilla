"""Pipeline validation for the identity-keyed raw layer (ADR-0011).

Rondônia Lei Complementar example: ingestion is gated on a known identity
(tipo, número); the IA item is an identity range bucket
(``leizilla_ro_casacivil_lc_0001-1000``); the file inside is content-addressed
(truncated UUIDv5); and the item's ``index.csv`` maps the identity to the file.
"""

from unittest.mock import MagicMock, patch

from leizilla.publisher import InternetArchivePublisher, IndexFetchError
from leizilla.ia_utils import (
    lookup_current,
    merge_index_row,
    range_item_identifier,
    raw_filename,
    resolve_raw_url,
    uuid5_name,
)


class TestRondoniaLCIdentityKeyed:
    def test_item_and_filename_are_identity_keyed(self):
        pdf_bytes = b"PDF content for LC 42"
        u = uuid5_name(pdf_bytes)
        # Item is the identity range bucket — tipo + número range, no hash, no coddoc.
        assert (
            range_item_identifier("ro", "casacivil", "lc", 42)
            == "leizilla_ro_casacivil_lc_0001-1000"
        )
        # File inside the item is content-addressed (truncated UUIDv5).
        assert raw_filename(u, ".pdf") == f"{u}.pdf"

    def test_resolve_via_index_roundtrip(self):
        pdf_bytes = b"PDF content for LC 42"
        u = uuid5_name(pdf_bytes)
        index_csv = merge_index_row(
            None,
            tipo="lc",
            numero=42,
            rendicao="",
            formato="pdf",
            uuid5=u,
            sha256="hpdf",
            captured_at="2026-05-30T00:00:00+00:00",
        )
        assert lookup_current(index_csv, "lc", 42, formato="pdf")["uuid5"] == u

        with patch("leizilla.ia_utils._fetch_text", return_value=index_csv):
            url = resolve_raw_url("leizilla-raw-ro-casacivil-lc-00042", "_djvu.txt")
        assert url == (
            "https://archive.org/download/leizilla_ro_casacivil_lc_0001-1000/"
            f"{u}_djvu.txt"
        )

    @patch("leizilla.publisher._fetch_existing_index", return_value=None)
    @patch("subprocess.run")
    def test_complete_upload_raw_lc_rondonia(self, mock_run, _mock_idx, tmp_path):
        mock_run.return_value = MagicMock(returncode=0)

        pub = InternetArchivePublisher()
        pub.access_key = "fake-key"
        pub.secret_key = "fake-secret"

        pdf_path = tmp_path / "LC42.pdf"
        pdf_bytes = b"PDF content for LC 42"
        pdf_path.write_bytes(pdf_bytes)
        u = uuid5_name(pdf_bytes)

        lei_data = {
            "ente": "ro",
            "fonte": "casacivil",
            "chave": "lc-00042",
            "url_original": "http://ditel.casacivil.ro.gov.br/COTEL/Livros/Files/LC42.pdf",
        }

        res = pub.upload_raw(pdf_path, lei_data, pdf_bytes, fetched_from="wayback")

        assert res["success"] is True
        assert res["uuid5"] == u
        assert (
            res["ia_url"]
            == "https://archive.org/details/leizilla_ro_casacivil_lc_0001-1000"
        )

        # Upload targeted the identity range item with the uuid5-named file + index.
        args = mock_run.call_args[0][0]
        assert "ia" in args and "upload" in args
        assert "leizilla_ro_casacivil_lc_0001-1000" in args
        assert any(a.endswith(f"{u}.pdf") for a in args)
        assert any(a.endswith("index.csv") for a in args)

    @patch("subprocess.run")
    def test_unidentified_chave_is_rejected(self, mock_run, tmp_path):
        # coddoc is a harvest key, not an identity → reject-until-identified.
        pub = InternetArchivePublisher()
        pub.access_key = "fake-key"
        pub.secret_key = "fake-secret"

        pdf_path = tmp_path / "doc.pdf"
        pdf_path.write_bytes(b"x")
        lei_data = {"ente": "ro", "fonte": "assembleia", "chave": "coddoc-00099"}

        res = pub.upload_raw(pdf_path, lei_data, b"x")
        assert res["success"] is False
        assert "unidentified" in res["error"]
        mock_run.assert_not_called()

    @patch(
        "leizilla.publisher._fetch_existing_index",
        side_effect=IndexFetchError("IA 503"),
    )
    @patch("subprocess.run")
    def test_index_fetch_error_aborts(self, mock_run, _mock_idx, tmp_path):
        # A transient failure reading the item's index must abort, not overwrite.
        pub = InternetArchivePublisher()
        pub.access_key = "fake-key"
        pub.secret_key = "fake-secret"

        pdf_path = tmp_path / "LC42.pdf"
        pdf_path.write_bytes(b"PDF content for LC 42")
        lei_data = {"ente": "ro", "fonte": "casacivil", "chave": "lc-00042"}

        res = pub.upload_raw(pdf_path, lei_data, b"PDF content for LC 42")
        assert res["success"] is False
        assert "could not read existing index" in res["error"]
        mock_run.assert_not_called()
