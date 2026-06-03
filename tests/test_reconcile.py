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
    @patch("leizilla.publisher._fetch_item_file_bytes", return_value=b"PDF-bytes")
    @patch("leizilla.publisher._fetch_existing_index")
    def test_range_upload_failure_is_surfaced(self, mock_idx, _mock_bytes, _env):
        # Identity is known but the range upload fails (IA/network/CLI). The row
        # stays in _unidentified; reconcile must report success=False with an error
        # so automation doesn't read exit 0 and miss the failed promotion (the row
        # alone is indistinguishable from a still-unidentified one).
        mock_idx.side_effect = [_holding_index_one_unidentified(), None]
        identity = {"http://alro.ro.gov.br/legislacao/leis/99": ("lei", 99)}
        pub = _pub()
        with patch.object(pub, "_upload_to_range", return_value=False):
            res = pub.reconcile_unidentified("ro", "assembleia", identity)
        assert res["success"] is False
        assert res["promoted"] == 0
        assert res["remaining"] == 1
        assert "range" in res["error"].lower()

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
        # ... carrying the provenance _meta.json sidecar (parity with upload_raw).
        range_call = next(
            c
            for c in mock_run.call_args_list
            if c.args[0][2] == "leizilla_ro_assembleia_lei_0001-1000"
        )
        assert any(str(a).endswith("_meta.json") for a in range_call.args[0])

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

    @patch("leizilla.publisher._ia_subprocess_env", return_value={})
    @patch("subprocess.run")
    @patch("leizilla.publisher._fetch_item_file_bytes", return_value=b"PDF-bytes")
    @patch("leizilla.publisher._fetch_existing_index")
    def test_holding_index_rewrite_failure_is_surfaced(
        self, mock_idx, _mock_bytes, _run, _env
    ):
        # Range upload succeeds, but rewriting the holding index fails → report the
        # failure (success False) and keep the promoted row counted as remaining,
        # so the operator sees cleanup didn't finish.
        mock_idx.side_effect = [_holding_index_one_unidentified(), None]
        identity = {"http://alro.ro.gov.br/legislacao/leis/99": ("lei", 99)}
        pub = _pub()
        with patch.object(pub, "_upload_index_only", return_value=False):
            res = pub.reconcile_unidentified("ro", "assembleia", identity)
        assert res["success"] is False
        assert "error" in res
        assert res["promoted"] == 1
        assert res["remaining"] == 1  # still listed in holding → not cleaned

    @patch("leizilla.publisher._ia_subprocess_env", return_value={})
    @patch("subprocess.run")
    @patch("leizilla.publisher._fetch_item_file_bytes", return_value=b"PDF-bytes")
    @patch("leizilla.publisher._fetch_existing_index")
    def test_aliased_sources_only_promotes_identified(
        self, mock_idx, _mock_bytes, _run, _env
    ):
        # Two holding rows: same bytes/uuid5, different source URLs. Only srcA is
        # identifiable → promote it, but srcB (still unidentified) must remain.
        holding = merge_index_row(
            None,
            tipo="",
            numero=None,
            rendicao="",
            formato="pdf",
            uuid5="u1",
            sha256="hsame",
            source="http://alro/leis/7",
        )
        holding = merge_index_row(
            holding,
            tipo="",
            numero=None,
            rendicao="",
            formato="pdf",
            uuid5="u1",
            sha256="hsame",
            source="http://alro/leis/8",
        )
        # holding fetched once; range index fetched once (for the single promotion).
        mock_idx.side_effect = [holding, None]
        identity = {"http://alro/leis/7": ("lei", 7)}  # only src 7 is mappable
        res = _pub().reconcile_unidentified("ro", "assembleia", identity)
        assert res["promoted"] == 1
        assert res["remaining"] == 1  # src 8 alias still preserved

    def test_same_range_promotions_accumulate_index_no_lost_update(self):
        # Two held files (different bytes → different uuid5, different sources) both
        # resolve into the SAME range bucket (lei 7 & 8 → lei_0001-1000). The range
        # index must be fetched once and accumulate BOTH rows; without the per-call
        # cache, each upload would re-read a stale index and clobber the prior row.
        import csv as _csv
        import io as _io

        holding = merge_index_row(
            None,
            tipo="",
            numero=None,
            rendicao="",
            formato="pdf",
            uuid5="ua",
            sha256="ha",
            source="http://x/7",
        )
        holding = merge_index_row(
            holding,
            tipo="",
            numero=None,
            rendicao="",
            formato="pdf",
            uuid5="ub",
            sha256="hb",
            source="http://x/8",
        )
        identity = {"http://x/7": ("lei", 7), "http://x/8": ("lei", 8)}

        captured: list[tuple[str, str]] = []

        def fake_upload(range_id, content, filename, index_csv, *a):
            captured.append((range_id, index_csv))
            return True

        def fake_bytes(item_id, filename):
            return b"A" if filename.startswith("ua") else b"B"

        pub = _pub()
        with (
            patch("leizilla.publisher._fetch_item_file_bytes", side_effect=fake_bytes),
            patch("leizilla.publisher._fetch_existing_index") as mock_idx,
            patch.object(pub, "_upload_to_range", side_effect=fake_upload),
            patch.object(pub, "_upload_index_only", return_value=True),
        ):
            mock_idx.side_effect = [holding, None]  # holding, then range ONCE
            res = pub.reconcile_unidentified("ro", "casacivil", identity)

        assert res["promoted"] == 2
        # holding (1) + range index (1) — the range is NOT re-fetched per file.
        assert mock_idx.call_count == 2
        # Final index uploaded for the range carries BOTH números (no lost update).
        last_index = captured[-1][1]
        numeros = {r["numero"] for r in _csv.DictReader(_io.StringIO(last_index))}
        assert numeros == {"7", "8"}

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
