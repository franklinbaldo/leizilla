"""Tests for the identity-keyed raw layer utilities (ADR-0011)."""

from unittest.mock import patch

from leizilla.ia_utils import (
    INDEX_COLUMNS,
    compute_hash,
    download_url,
    list_identities,
    lookup_current,
    merge_index_row,
    parse_identity,
    parse_raw_id,
    range_bounds,
    range_item_identifier,
    raw_filename,
    resolve_raw_url,
    uuid5_collision,
    uuid5_name,
)


class TestComputeHash:
    def test_deterministic_sha256(self):
        import hashlib

        data = b"PDF bytes"
        assert compute_hash(data) == hashlib.sha256(data).hexdigest()

    def test_distinct_bytes_distinct_hash(self):
        assert compute_hash(b"a") != compute_hash(b"b")


class TestUuid5Name:
    def test_deterministic_and_truncated(self):
        name = uuid5_name(b"PDF bytes")
        assert name == uuid5_name(b"PDF bytes")
        assert len(name) == 8

    def test_distinct_bytes_distinct_name(self):
        assert uuid5_name(b"a") != uuid5_name(b"b")

    def test_custom_length(self):
        assert len(uuid5_name(b"x", length=32)) == 32


class TestParseIdentity:
    def test_extracts_tipo_and_numero(self):
        assert parse_identity("lei-05120") == ("lei", 5120)

    def test_hyphenated_tipo(self):
        assert parse_identity("lei-complementar-00042") == ("lei-complementar", 42)

    def test_coddoc_is_not_identifying(self):
        assert parse_identity("coddoc-00099") is None

    def test_seq_and_fallback_not_identifying(self):
        assert parse_identity("seq-00042") is None
        assert parse_identity("fallback-foo") is None

    def test_non_numeric_returns_none(self):
        assert parse_identity("documento") is None
        assert parse_identity("lei-abc") is None


class TestParseRawId:
    def test_simple_ente(self):
        assert parse_raw_id("leizilla-raw-ro-casacivil-lei-05120") == (
            "ro",
            "casacivil",
            "lei-05120",
        )

    def test_hyphenated_ente_longest_match(self):
        with patch(
            "leizilla.ia_utils.list_slugs",
            return_value=["ro", "ro-porto-velho", "federal"],
        ):
            assert parse_raw_id("leizilla-raw-ro-porto-velho-camara-lei-7") == (
                "ro-porto-velho",
                "camara",
                "lei-7",
            )

    def test_non_raw_id_returns_none(self):
        assert parse_raw_id("external-archive-item") is None

    def test_unknown_ente_returns_none(self):
        assert parse_raw_id("leizilla-raw-xx-fonte-key") is None

    def test_missing_chave_returns_none(self):
        assert parse_raw_id("leizilla-raw-ro-casacivil") is None


class TestRanges:
    def test_range_bounds(self):
        assert range_bounds(5120) == (5001, 6000)
        assert range_bounds(1) == (1, 1000)
        assert range_bounds(1000) == (1, 1000)
        assert range_bounds(1001) == (1001, 2000)

    def test_range_item_identifier(self):
        assert (
            range_item_identifier("ro", "casacivil", "lei", 5120)
            == "leizilla_ro_casacivil_lei_5001-6000"
        )

    def test_range_item_identifier_lowercases_and_keeps_hyphen_in_tipo(self):
        assert (
            range_item_identifier("RO", "CasaCivil", "lei-complementar", 42)
            == "leizilla_ro_casacivil_lei-complementar_0001-1000"
        )

    def test_raw_filename(self):
        assert raw_filename("a1b2c3d4", ".pdf") == "a1b2c3d4.pdf"
        assert raw_filename("a1b2c3d4", "_djvu.txt") == "a1b2c3d4_djvu.txt"

    def test_download_url(self):
        assert (
            download_url("item-x", "file.pdf")
            == "https://archive.org/download/item-x/file.pdf"
        )


class TestMergeIndexRow:
    def _row(self, existing, **kw):
        defaults = dict(
            tipo="lei",
            numero=5120,
            rendicao="",
            formato="pdf",
            uuid5="aaaa1111",
            sha256="h1",
            captured_at="2026-05-30T00:00:00+00:00",
        )
        defaults.update(kw)
        return merge_index_row(existing, **defaults)

    def test_creates_header_and_row(self):
        csv_out = self._row(None)
        lines = csv_out.strip().splitlines()
        assert lines[0] == ",".join(INDEX_COLUMNS)
        assert lines[1].startswith("lei,5120,,pdf,aaaa1111,h1,")

    def test_append_only_keeps_history(self):
        first = self._row(None)
        second = self._row(
            first,
            uuid5="bbbb2222",
            sha256="h2",
            captured_at="2026-05-31T00:00:00+00:00",
        )
        rows = second.strip().splitlines()[1:]
        assert len(rows) == 2

    def test_idempotent_same_identity_and_bytes(self):
        first = self._row(None)
        second = self._row(first, captured_at="2026-05-31T00:00:00+00:00")
        assert second == first  # truly no-op: unchanged bytes → unchanged CSV
        assert "2026-05-31" not in second

    def test_records_source_provenance(self):
        # ADR-0010: the manifest maps each file back to its harvest source — this
        # is what lets identity drop coddoc without losing traceability.
        csv_out = self._row(None, source="http://alro.ro.gov.br/legislacao/leis/7")
        assert "source" in INDEX_COLUMNS
        assert (
            csv_out.strip()
            .splitlines()[1]
            .endswith(",http://alro.ro.gov.br/legislacao/leis/7")
        )


class TestRemoveIndexRows:
    def test_drops_named_uuid5_keeps_others(self):
        from leizilla.ia_utils import remove_index_rows

        idx = merge_index_row(
            None,
            tipo="lei",
            numero=5120,
            rendicao="",
            formato="pdf",
            uuid5="keep1",
            sha256="h1",
        )
        idx = merge_index_row(
            idx,
            tipo="lei",
            numero=5121,
            rendicao="",
            formato="pdf",
            uuid5="drop1",
            sha256="h2",
        )
        out = remove_index_rows(idx, {"drop1"})
        assert "drop1" not in out
        assert "keep1" in out
        assert out.splitlines()[0] == ",".join(INDEX_COLUMNS)  # header intact
        assert len(out.strip().splitlines()) == 2  # header + 1 kept row


class TestUuid5Collision:
    def test_detects_same_name_different_bytes(self):
        idx = merge_index_row(
            None,
            tipo="lei",
            numero=5120,
            rendicao="",
            formato="pdf",
            uuid5="dup",
            sha256="h1",
        )
        assert uuid5_collision(idx, uuid5="dup", sha256="h2") is True
        assert uuid5_collision(idx, uuid5="dup", sha256="h1") is False
        assert uuid5_collision(idx, uuid5="other", sha256="h2") is False


class TestLookupCurrent:
    def _mixed_index(self) -> str:
        idx = merge_index_row(
            None,
            tipo="lc",
            numero=42,
            rendicao="original",
            formato="pdf",
            uuid5="pdf1",
            sha256="hpdf",
            captured_at="2026-05-30T00:00:00+00:00",
        )
        return merge_index_row(
            idx,
            tipo="lc",
            numero=42,
            rendicao="atual",
            formato="html",
            uuid5="html1",
            sha256="hhtml",
            captured_at="2026-05-30T01:00:00+00:00",
        )

    def test_returns_latest_for_identity(self):
        idx = self._mixed_index()
        # No filter → last-appended matching row (html).
        assert lookup_current(idx, "lc", 42)["uuid5"] == "html1"

    def test_formato_filter(self):
        idx = self._mixed_index()
        assert lookup_current(idx, "lc", 42, formato="pdf")["uuid5"] == "pdf1"
        assert lookup_current(idx, "lc", 42, formato="html")["uuid5"] == "html1"

    def test_rendicao_filter(self):
        idx = self._mixed_index()
        assert lookup_current(idx, "lc", 42, rendicao="original")["uuid5"] == "pdf1"

    def test_missing_returns_none(self):
        idx = self._mixed_index()
        assert lookup_current(idx, "lc", 999) is None
        assert lookup_current(idx, "lc", 42, formato="docx") is None


class TestListIdentities:
    def test_distinct_tipo_numero_keys(self):
        idx = merge_index_row(
            None,
            tipo="lei",
            numero=5120,
            rendicao="",
            formato="pdf",
            uuid5="a",
            sha256="h1",
        )
        idx = merge_index_row(
            idx,
            tipo="lei",
            numero=5120,
            rendicao="atual",
            formato="html",
            uuid5="b",
            sha256="h2",
        )
        idx = merge_index_row(
            idx,
            tipo="lc",
            numero=42,
            rendicao="",
            formato="pdf",
            uuid5="c",
            sha256="h3",
        )
        assert list_identities(idx) == {"lei-05120", "lc-00042"}


class TestResolveRawUrl:
    def test_non_raw_id_passthrough(self):
        assert (
            resolve_raw_url("external-archive-item", "_djvu.txt")
            == "https://archive.org/download/external-archive-item/external-archive-item_djvu.txt"
        )

    def test_unidentified_chave_returns_none(self):
        # coddoc is not an identity → not in the collection, regardless of index.
        assert (
            resolve_raw_url("leizilla-raw-ro-assembleia-coddoc-00099", ".pdf") is None
        )

    def test_resolves_via_index_to_uuid5_url(self):
        idx = merge_index_row(
            None,
            tipo="lei",
            numero=5120,
            rendicao="",
            formato="pdf",
            uuid5="a1b2c3d4",
            sha256="h1",
        )
        with patch("leizilla.ia_utils._fetch_text", return_value=idx):
            url = resolve_raw_url("leizilla-raw-ro-casacivil-lei-05120", "_djvu.txt")
        assert url == (
            "https://archive.org/download/"
            "leizilla_ro_casacivil_lei_5001-6000/a1b2c3d4_djvu.txt"
        )

    def test_no_index_yet_returns_none(self):
        with patch("leizilla.ia_utils._fetch_text", return_value=None):
            assert resolve_raw_url("leizilla-raw-ro-casacivil-lei-1", ".pdf") is None

    def test_identity_not_in_index_returns_none(self):
        idx = merge_index_row(
            None,
            tipo="lei",
            numero=999,
            rendicao="",
            formato="pdf",
            uuid5="x",
            sha256="h1",
        )
        with patch("leizilla.ia_utils._fetch_text", return_value=idx):
            assert resolve_raw_url("leizilla-raw-ro-casacivil-lei-1", ".pdf") is None

    def test_suffix_formato_filters_mixed_components(self):
        idx = merge_index_row(
            None,
            tipo="lc",
            numero=42,
            rendicao="original",
            formato="pdf",
            uuid5="pdf1",
            sha256="hpdf",
        )
        idx = merge_index_row(
            idx,
            tipo="lc",
            numero=42,
            rendicao="atual",
            formato="html",
            uuid5="html1",
            sha256="hhtml",
        )
        ia_id = "leizilla-raw-ro-casacivil-lc-00042"
        with patch("leizilla.ia_utils._fetch_text", return_value=idx):
            ocr_url = resolve_raw_url(ia_id, "_djvu.txt")
            assert ocr_url and "pdf1_djvu.txt" in ocr_url
        with patch("leizilla.ia_utils._fetch_text", return_value=idx):
            html_url = resolve_raw_url(ia_id, ".html")
            assert html_url and "html1.html" in html_url
