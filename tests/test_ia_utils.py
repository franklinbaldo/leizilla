"""Tests for the content-addressed raw layer utilities (ADR-0010)."""

from unittest.mock import patch

from leizilla.ia_utils import (
    INDEX_COLUMNS,
    compute_hash,
    download_url,
    lookup_current_hash,
    merge_index_row,
    parse_raw_id,
    raw_filename,
    raw_index_identifier,
    raw_range_identifier,
    resolve_raw_url,
)


class TestComputeHash:
    def test_deterministic_sha256(self):
        import hashlib

        data = b"PDF bytes"
        assert compute_hash(data) == hashlib.sha256(data).hexdigest()

    def test_distinct_bytes_distinct_hash(self):
        assert compute_hash(b"a") != compute_hash(b"b")


class TestParseRawId:
    def test_simple_ente(self):
        assert parse_raw_id("leizilla-raw-ro-casacivil-coddoc-05120") == (
            "ro",
            "casacivil",
            "coddoc-05120",
        )

    def test_hyphenated_ente_longest_match(self):
        # When a hyphenated municipal slug is in the catalog, longest-match must
        # pick it over the bare state slug (ro-porto-velho before ro).
        with patch(
            "leizilla.ia_utils.list_slugs",
            return_value=["ro", "ro-porto-velho", "federal"],
        ):
            assert parse_raw_id("leizilla-raw-ro-porto-velho-camara-doc-7") == (
                "ro-porto-velho",
                "camara",
                "doc-7",
            )

    def test_source_key_may_contain_hyphens(self):
        assert parse_raw_id("leizilla-raw-federal-planalto-lei-complementar-42") == (
            "federal",
            "planalto",
            "lei-complementar-42",
        )

    def test_non_raw_id_returns_none(self):
        assert parse_raw_id("external-archive-item") is None

    def test_unknown_ente_returns_none(self):
        assert parse_raw_id("leizilla-raw-xx-fonte-key") is None

    def test_missing_source_key_returns_none(self):
        assert parse_raw_id("leizilla-raw-ro-casacivil") is None


class TestIdentifiers:
    def test_index_identifier(self):
        assert (
            raw_index_identifier("ro", "casacivil") == "leizilla-raw-ro-casacivil-index"
        )

    def test_range_identifier_buckets_by_hash_prefix(self):
        h = "3f8a" + "0" * 60
        assert (
            raw_range_identifier("ro", "casacivil", h) == "leizilla-raw-ro-casacivil-3f"
        )

    def test_range_identifier_lowercases(self):
        h = "AB" + "0" * 62
        assert (
            raw_range_identifier("RO", "CasaCivil", h) == "leizilla-raw-ro-casacivil-ab"
        )

    def test_raw_filename_is_content_addressed(self):
        h = "3f8a" + "0" * 60
        assert raw_filename(h, ".pdf") == f"{h}.pdf"
        assert raw_filename(h, "_djvu.txt") == f"{h}_djvu.txt"

    def test_download_url(self):
        assert (
            download_url("item-x", "file.pdf")
            == "https://archive.org/download/item-x/file.pdf"
        )


class TestMergeIndexRow:
    def test_creates_header_and_row(self):
        csv_out = merge_index_row(
            None,
            source_key="coddoc-05120",
            content_hash="abc",
            content_type="application/pdf",
            source_url="http://src/1",
            captured_at="2026-05-30T00:00:00+00:00",
        )
        lines = csv_out.strip().splitlines()
        assert lines[0] == ",".join(INDEX_COLUMNS)
        assert lines[1].startswith("coddoc-05120,abc,application/pdf,http://src/1,")

    def test_append_only_keeps_history(self):
        first = merge_index_row(
            None,
            source_key="coddoc-1",
            content_hash="h1",
            content_type="application/pdf",
            source_url="http://src/1",
            captured_at="2026-05-30T00:00:00+00:00",
        )
        second = merge_index_row(
            first,
            source_key="coddoc-1",
            content_hash="h2",
            content_type="application/pdf",
            source_url="http://src/1",
            captured_at="2026-05-31T00:00:00+00:00",
        )
        rows = [ln for ln in second.strip().splitlines()[1:]]
        assert len(rows) == 2  # both captures retained

    def test_idempotent_same_key_and_hash(self):
        first = merge_index_row(
            None,
            source_key="coddoc-1",
            content_hash="h1",
            content_type="application/pdf",
            source_url="http://src/1",
            captured_at="2026-05-30T00:00:00+00:00",
        )
        second = merge_index_row(
            first,
            source_key="coddoc-1",
            content_hash="h1",
            content_type="application/pdf",
            source_url="http://src/1",
            captured_at="2026-05-31T00:00:00+00:00",
        )
        rows = [ln for ln in second.strip().splitlines()[1:]]
        assert len(rows) == 1  # re-crawl, identical bytes → no duplicate


class TestLookupCurrentHash:
    def _two_version_index(self) -> str:
        idx = merge_index_row(
            None,
            source_key="coddoc-1",
            content_hash="h1",
            content_type="application/pdf",
            source_url="http://src/1",
            captured_at="2026-05-30T00:00:00+00:00",
        )
        return merge_index_row(
            idx,
            source_key="coddoc-1",
            content_hash="h2",
            content_type="application/pdf",
            source_url="http://src/1",
            captured_at="2026-05-31T00:00:00+00:00",
        )

    def test_returns_latest_capture(self):
        idx = self._two_version_index()
        assert lookup_current_hash(idx, "coddoc-1") == ("h2", "application/pdf")

    def test_missing_key_returns_none(self):
        idx = self._two_version_index()
        assert lookup_current_hash(idx, "coddoc-999") is None

    def test_content_type_filter_picks_correct_component(self):
        # Same source_key has a PDF row and an HTML row.
        pdf_hash = "pdf_hash"
        html_hash = "html_hash"
        idx = merge_index_row(
            None,
            source_key="lc-00042",
            content_hash=pdf_hash,
            content_type="application/pdf",
            source_url="http://src/pdf",
            captured_at="2026-05-30T00:00:00+00:00",
        )
        idx = merge_index_row(
            idx,
            source_key="lc-00042",
            content_hash=html_hash,
            content_type="text/html",
            source_url="http://src/html",
            captured_at="2026-05-30T01:00:00+00:00",
        )
        # Without filter, returns last-appended row (HTML).
        assert lookup_current_hash(idx, "lc-00042") == (html_hash, "text/html")
        # With filter, each component resolves independently.
        assert lookup_current_hash(idx, "lc-00042", "application/pdf") == (
            pdf_hash,
            "application/pdf",
        )
        assert lookup_current_hash(idx, "lc-00042", "text/html") == (
            html_hash,
            "text/html",
        )

    def test_content_type_filter_returns_none_when_type_absent(self):
        idx = merge_index_row(
            None,
            source_key="lc-00042",
            content_hash="h1",
            content_type="application/pdf",
            source_url="http://src/1",
        )
        # Requesting HTML for a source that only has a PDF entry → None.
        assert lookup_current_hash(idx, "lc-00042", "text/html") is None


class TestResolveRawUrl:
    def test_non_raw_id_passthrough(self):
        assert (
            resolve_raw_url("external-archive-item", "_djvu.txt")
            == "https://archive.org/download/external-archive-item/external-archive-item_djvu.txt"
        )

    def test_resolves_via_index_to_content_addressed_url(self):
        content_hash = "3f8a" + "0" * 60
        index_csv = merge_index_row(
            None,
            source_key="coddoc-05120",
            content_hash=content_hash,
            content_type="application/pdf",
            source_url="http://src/1",
        )
        with patch("leizilla.ia_utils._fetch_text", return_value=index_csv):
            url = resolve_raw_url("leizilla-raw-ro-casacivil-coddoc-05120", "_djvu.txt")
        assert url == (
            "https://archive.org/download/"
            "leizilla-raw-ro-casacivil-3f/"
            f"{content_hash}_djvu.txt"
        )

    def test_no_index_yet_returns_none(self):
        with patch("leizilla.ia_utils._fetch_text", return_value=None):
            assert resolve_raw_url("leizilla-raw-ro-casacivil-coddoc-1", ".pdf") is None

    def test_source_key_not_in_index_returns_none(self):
        index_csv = merge_index_row(
            None,
            source_key="coddoc-OTHER",
            content_hash="h1",
            content_type="application/pdf",
            source_url="http://src/1",
        )
        with patch("leizilla.ia_utils._fetch_text", return_value=index_csv):
            assert resolve_raw_url("leizilla-raw-ro-casacivil-coddoc-1", ".pdf") is None

    def test_suffix_content_type_filters_mixed_components(self):
        # source_key has both PDF and HTML components; suffix drives which hash is used.
        pdf_hash = "aa" + "0" * 62
        html_hash = "bb" + "0" * 62
        idx = merge_index_row(
            None,
            source_key="lc-00042",
            content_hash=pdf_hash,
            content_type="application/pdf",
            source_url="http://src/pdf",
        )
        idx = merge_index_row(
            idx,
            source_key="lc-00042",
            content_hash=html_hash,
            content_type="text/html",
            source_url="http://src/html",
        )
        ia_id = "leizilla-raw-ro-casacivil-lc-00042"
        with patch("leizilla.ia_utils._fetch_text", return_value=idx):
            # OCR suffix → PDF hash (IA derives djvu.txt from the PDF)
            ocr_url = resolve_raw_url(ia_id, "_djvu.txt")
            assert ocr_url and f"{pdf_hash}_djvu.txt" in ocr_url
        with patch("leizilla.ia_utils._fetch_text", return_value=idx):
            # .html suffix → HTML hash
            html_url = resolve_raw_url(ia_id, ".html")
            assert html_url and f"{html_hash}.html" in html_url
