"""Tests for the reconcile step: promote held _unidentified files into range items.

ADR-0011 §1 (revised): identity is evidence, not an ingestion gate. Un-numbered
captures are preserved in `leizilla_{ente}_{fonte}_unidentified`; reconcile re-derives
identity from discovery context and promotes them — pulling bytes from IA, never the
fragile source.
"""

from unittest.mock import patch

from leizilla.ia_utils import merge_index_row
from leizilla.publisher import InternetArchivePublisher


def _holding_index_one_unidentified() -> str:
    # One preserved row with no número and a source URL (the reconcile target).
    return merge_index_row(
        None,
        tipo="",
        numero=None,
        rendicao="",
        formato="pdf",
        uuid5="abcd1234",
        sha256="h1",
        source="http://alro.ro.gov.br/legislacao/leis/99",
    )


def _pub() -> InternetArchivePublisher:
    pub = InternetArchivePublisher()
    pub.access_key = "fake-key"
    pub.secret_key = "fake-secret"
    return pub


class TestReconcileUnidentified:
    @patch("leizilla.publisher._ia_subprocess_env", return_value={})
    @patch("subprocess.run")
    @patch("leizilla.publisher._fetch_item_file_bytes", return_value=b"PDF-bytes")
    @patch("leizilla.publisher._fetch_existing_index")
    def test_promotes_now_identified_resource(
        self, mock_idx, _mock_bytes, mock_run, _env
    ):
        # _fetch_existing_index: first the holding index, then the (new) range index.
        mock_idx.side_effect = [_holding_index_one_unidentified(), None]
        identity = {"http://alro.ro.gov.br/legislacao/leis/99": ("lei", 99)}

        res = _pub().reconcile_unidentified("ro", "assembleia", identity)

        assert res["success"] is True
        assert res["promoted"] == 1
        assert res["remaining"] == 0

        uploaded_items = [call.args[0][2] for call in mock_run.call_args_list]
        # Promoted into the navigable range item ...
        assert "leizilla_ro_assembleia_lei_0001-1000" in uploaded_items
        # ... and the holding index was rewritten (promoted row removed).
        assert "leizilla_ro_assembleia_unidentified" in uploaded_items

    @patch("leizilla.publisher._ia_subprocess_env", return_value={})
    @patch("subprocess.run")
    @patch("leizilla.publisher._fetch_item_file_bytes", return_value=b"PDF-bytes")
    @patch("leizilla.publisher._fetch_existing_index")
    def test_leaves_still_unidentified_in_holding(
        self, mock_idx, _mock_bytes, mock_run, _env
    ):
        mock_idx.return_value = _holding_index_one_unidentified()
        # The held resource's source is NOT in the identity map → not promotable.
        res = _pub().reconcile_unidentified("ro", "assembleia", {})

        assert res["promoted"] == 0
        assert res["remaining"] == 1
        mock_run.assert_not_called()  # nothing uploaded, holding untouched

    @patch("leizilla.publisher._fetch_existing_index", return_value=None)
    def test_empty_holding_is_noop(self, _mock_idx):
        res = _pub().reconcile_unidentified("ro", "assembleia", {"x": ("lei", 1)})
        assert res["promoted"] == 0
        assert res["remaining"] == 0

    def test_no_credentials_returns_error(self):
        pub = InternetArchivePublisher()
        pub.access_key = None
        pub.secret_key = None
        res = pub.reconcile_unidentified("ro", "assembleia", {})
        assert res["success"] is False


class TestSourceMatchesDiscoveryURL:
    """Regression: the index `source` must equal discovery's res['url'] (the PDF
    URL) so reconcile can match — not the ALRO listing-page url_original."""

    @patch("leizilla.publisher._ia_subprocess_env", return_value={})
    @patch("subprocess.run")
    def test_upload_raw_records_pdf_url_as_source(self, _run, _env, tmp_path):
        from pathlib import Path

        captured = {}

        def _capture(item_id, content, **kw):
            captured.update(kw)
            return "uuid5x", "tipo,numero\n"

        pdf = Path(tmp_path) / "doc.pdf"
        pdf.write_bytes(b"x")
        lei_data = {
            "ente": "ro",
            "fonte": "assembleia",
            "chave": "lei-00099",
            "url_original": "http://alro/legislacao/leis/77",  # listing page
            "url_pdf_original": "http://alro/files/L99.pdf",  # the PDF (res['url'])
        }
        with patch("leizilla.publisher._resolve_uuid5_and_index", side_effect=_capture):
            _pub().upload_raw(pdf, lei_data, b"x")
        assert captured["source"] == "http://alro/files/L99.pdf"
