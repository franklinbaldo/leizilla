"""Testes unitários para leizilla.publisher — funções puras sem IA."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock


from leizilla.publisher import (
    _raw_identifier,
    _bundle_identifier,
    build_raw_meta,
    count_ia_items,
    list_parsed_raw_ids,
    list_raw_ids,
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
                    captured_files.append(Path(arg).read_text())
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
                    captured_metas.append(json.loads(Path(arg).read_text()))
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


class TestListParsedRawIds:
    """Testes para list_parsed_raw_ids — consulta IA sem credenciais."""

    def _make_urlopen(self, responses: list):
        """Retorna mock para urllib.request.urlopen que serve respostas sequenciais."""
        calls = iter(responses)

        class _FakeResponse:
            def __init__(self, data: bytes):
                self._data = data

            def read(self):
                return self._data

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        def fake_urlopen(req, timeout=None):
            return _FakeResponse(next(calls))

        return fake_urlopen

    def test_returns_empty_set_on_search_network_error(self):
        with patch("urllib.request.urlopen", side_effect=OSError("network")):
            result = list_parsed_raw_ids("ro", "assembleia")
        assert result == set()

    def test_returns_empty_set_when_no_parsed_items(self):
        scrape_resp = json.dumps({"items": []}).encode()
        urlopen = self._make_urlopen([scrape_resp])
        with patch("urllib.request.urlopen", side_effect=urlopen):
            result = list_parsed_raw_ids("ro", "assembleia")
        assert result == set()

    def test_returns_raw_ids_matching_fonte(self):
        scrape_resp = json.dumps(
            {"items": [{"identifier": "leizilla-ro-lei-00001-2000"}]}
        ).encode()
        meta_resp = json.dumps(
            {"ia_id_raw": "leizilla-raw-ro-assembleia-coddoc-00001"}
        ).encode()
        urlopen = self._make_urlopen([scrape_resp, meta_resp])
        with patch("urllib.request.urlopen", side_effect=urlopen):
            result = list_parsed_raw_ids("ro", "assembleia")
        assert result == {"leizilla-raw-ro-assembleia-coddoc-00001"}

    def test_filters_out_different_fonte(self):
        scrape_resp = json.dumps(
            {"items": [{"identifier": "leizilla-ro-lei-00001-2000"}]}
        ).encode()
        # raw_id belongs to casacivil, not assembleia
        meta_resp = json.dumps(
            {"ia_id_raw": "leizilla-raw-ro-casacivil-coddoc-00001"}
        ).encode()
        urlopen = self._make_urlopen([scrape_resp, meta_resp])
        with patch("urllib.request.urlopen", side_effect=urlopen):
            result = list_parsed_raw_ids("ro", "assembleia")
        assert result == set()

    def test_skips_items_whose_meta_fetch_fails(self):
        scrape_resp = json.dumps(
            {
                "items": [
                    {"identifier": "leizilla-ro-lei-00001-2000"},
                    {"identifier": "leizilla-ro-lei-00002-2001"},
                ]
            }
        ).encode()
        meta_ok = json.dumps(
            {"ia_id_raw": "leizilla-raw-ro-assembleia-coddoc-00002"}
        ).encode()

        call_count = {"n": 0}

        def urlopen_with_first_meta_fail(req, timeout=None):
            class _R:
                def __init__(self, data):
                    self._data = data

                def read(self):
                    return self._data

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    pass

            call_count["n"] += 1
            if call_count["n"] == 1:
                return _R(scrape_resp)
            if call_count["n"] == 2:
                raise OSError("meta fetch failed")
            return _R(meta_ok)

        with patch("urllib.request.urlopen", side_effect=urlopen_with_first_meta_fail):
            result = list_parsed_raw_ids("ro", "assembleia")
        assert result == {"leizilla-raw-ro-assembleia-coddoc-00002"}

    def test_follows_cursor_for_pagination(self):
        """IA scrape API retorna cursor → segunda requisição busca próxima página."""
        page1 = json.dumps(
            {
                "items": [{"identifier": "leizilla-ro-lei-00001-2000"}],
                "cursor": "abc123",
            }
        ).encode()
        page2 = json.dumps(
            {"items": [{"identifier": "leizilla-ro-lei-00002-2001"}]}
        ).encode()
        meta1 = json.dumps(
            {"ia_id_raw": "leizilla-raw-ro-assembleia-coddoc-00001"}
        ).encode()
        meta2 = json.dumps(
            {"ia_id_raw": "leizilla-raw-ro-assembleia-coddoc-00002"}
        ).encode()
        urlopen = self._make_urlopen([page1, page2, meta1, meta2])
        with patch("urllib.request.urlopen", side_effect=urlopen) as mock_open:
            result = list_parsed_raw_ids("ro", "assembleia")
        assert result == {
            "leizilla-raw-ro-assembleia-coddoc-00001",
            "leizilla-raw-ro-assembleia-coddoc-00002",
        }
        # Verifica que o cursor foi passado na segunda chamada de scrape
        second_call_url = mock_open.call_args_list[1][0][0].full_url
        assert "cursor=abc123" in second_call_url

    def test_returns_empty_set_on_second_page_error(self):
        """Erro na 2ª página do cursor → fail-open retorna set() (não resultado parcial)."""
        page1 = json.dumps(
            {
                "items": [{"identifier": "leizilla-ro-lei-00001-2000"}],
                "cursor": "abc123",
            }
        ).encode()
        call_count = {"n": 0}

        def urlopen_fail_on_second(req, timeout=None):
            class _R:
                def __init__(self, data):
                    self._data = data

                def read(self):
                    return self._data

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    pass

            call_count["n"] += 1
            if call_count["n"] == 1:
                return _R(page1)
            raise OSError("second page network error")

        with patch("urllib.request.urlopen", side_effect=urlopen_fail_on_second):
            result = list_parsed_raw_ids("ro", "assembleia")
        assert result == set()


class TestCountIaItems:
    """Testes para count_ia_items — conta itens no IA sem credenciais."""

    def _make_urlopen(self, responses: list):
        calls = iter(responses)

        class _R:
            def __init__(self, data: bytes):
                self._data = data

            def read(self):
                return self._data

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

        def fake(req, timeout=None):
            return _R(next(calls))

        return fake

    def test_returns_none_on_network_error(self):
        with patch("urllib.request.urlopen", side_effect=OSError("net")):
            assert count_ia_items("leizilla-raw-ro-") is None

    def test_returns_zero_when_no_items(self):
        resp = json.dumps({"items": []}).encode()
        with patch("urllib.request.urlopen", side_effect=self._make_urlopen([resp])):
            assert count_ia_items("leizilla-raw-ro-") == 0

    def test_counts_single_page(self):
        resp = json.dumps(
            {"items": [{"identifier": "a"}, {"identifier": "b"}]}
        ).encode()
        with patch("urllib.request.urlopen", side_effect=self._make_urlopen([resp])):
            assert count_ia_items("leizilla-raw-ro-") == 2

    def test_follows_cursor_across_pages(self):
        page1 = json.dumps({"items": [{"identifier": "a"}], "cursor": "cur1"}).encode()
        page2 = json.dumps(
            {"items": [{"identifier": "b"}, {"identifier": "c"}]}
        ).encode()
        with patch(
            "urllib.request.urlopen",
            side_effect=self._make_urlopen([page1, page2]),
        ) as mock_open:
            result = count_ia_items("leizilla-raw-ro-")
        assert result == 3
        second_url = mock_open.call_args_list[1][0][0].full_url
        assert "cursor=cur1" in second_url

    def test_returns_none_on_second_page_error(self):
        page1 = json.dumps({"items": [{"identifier": "a"}], "cursor": "cur1"}).encode()
        call_n = {"n": 0}

        def urlopen_fail(req, timeout=None):
            class _R:
                def __init__(self, d):
                    self._d = d

                def read(self):
                    return self._d

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    pass

            call_n["n"] += 1
            if call_n["n"] == 1:
                return _R(page1)
            raise OSError("fail")

        with patch("urllib.request.urlopen", side_effect=urlopen_fail):
            assert count_ia_items("leizilla-raw-ro-") is None


class TestListRawIds:
    """Testes para list_raw_ids — lista raw items sem buscar metadados."""

    def _resp(self, data: dict) -> object:
        payload = json.dumps(data).encode()

        class _R:
            def read(self):
                return payload

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

        return _R()

    def test_returns_empty_set_on_network_error(self):
        with patch("urllib.request.urlopen", side_effect=OSError("network")):
            assert list_raw_ids("ro", "assembleia") == set()

    def test_returns_empty_set_when_no_items(self):
        with patch("urllib.request.urlopen", return_value=self._resp({"items": []})):
            assert list_raw_ids("ro", "assembleia") == set()

    def test_returns_identifiers(self):
        items = [
            {"identifier": "leizilla-raw-ro-assembleia-coddoc-00001"},
            {"identifier": "leizilla-raw-ro-assembleia-coddoc-00002"},
        ]
        with patch("urllib.request.urlopen", return_value=self._resp({"items": items})):
            result = list_raw_ids("ro", "assembleia")
        assert result == {
            "leizilla-raw-ro-assembleia-coddoc-00001",
            "leizilla-raw-ro-assembleia-coddoc-00002",
        }

    def test_follows_cursor_pagination(self):
        page1 = {
            "items": [{"identifier": "leizilla-raw-ro-casacivil-lei-00001"}],
            "cursor": "tok",
        }
        page2 = {"items": [{"identifier": "leizilla-raw-ro-casacivil-lei-00002"}]}
        calls = iter([self._resp(page1), self._resp(page2)])
        with patch(
            "urllib.request.urlopen", side_effect=lambda *a, **kw: next(calls)
        ) as m:
            result = list_raw_ids("ro", "casacivil")
        assert result == {
            "leizilla-raw-ro-casacivil-lei-00001",
            "leizilla-raw-ro-casacivil-lei-00002",
        }
        second_url = m.call_args_list[1][0][0].full_url
        assert "cursor=tok" in second_url

    def test_returns_partial_on_second_page_error(self):
        """Page 2 network error → returns confirmed items from page 1.

        Asymmetry with list_parsed_raw_ids (which returns set()): for scraping,
        re-uploading an unconfirmed item is safe (idempotent IA upload); for
        parsing, skipping an unconfirmed item could silently lose work.
        """
        page1 = {
            "items": [{"identifier": "leizilla-raw-ro-assembleia-coddoc-00001"}],
            "cursor": "tok",
        }
        call_n = {"n": 0}

        def urlopen(req, timeout=None):
            call_n["n"] += 1
            if call_n["n"] == 1:
                return self._resp(page1)
            raise OSError("second page error")

        with patch("urllib.request.urlopen", side_effect=urlopen):
            assert list_raw_ids("ro", "assembleia") == {
                "leizilla-raw-ro-assembleia-coddoc-00001"
            }


class TestUploadToArchive:
    @patch("subprocess.run")
    def test_upload_success(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        pub = InternetArchivePublisher()
        pub.access_key = "fake_key"
        pub.secret_key = "fake_secret"

        dummy_file = tmp_path / "test.pdf"
        dummy_file.write_bytes(b"content")

        res = pub.upload_to_archive(
            archive_ia_id="leizilla-archive-ro-casacivil-raw",
            file_path=dummy_file,
            filename_in_archive="lei-05120.pdf",
            ente="ro",
            fonte="casacivil",
        )
        assert res["success"] is True
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "ia" in args
        assert "upload" in args
        assert "leizilla-archive-ro-casacivil-raw" in args
        assert args[3].endswith("lei-05120.pdf")

    def test_missing_credentials(self, tmp_path):
        pub = InternetArchivePublisher()
        pub.access_key = None
        pub.secret_key = None

        dummy_file = tmp_path / "test.pdf"
        res = pub.upload_to_archive(
            archive_ia_id="leizilla-archive-ro-casacivil-raw",
            file_path=dummy_file,
            filename_in_archive="lei-05120.pdf",
            ente="ro",
            fonte="casacivil",
        )
        assert res["success"] is False
        assert "credentials" in res["error"]
