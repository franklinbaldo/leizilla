"""Testes unitários para leizilla.publisher — funções puras sem IA."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock


from leizilla.publisher import (
    _raw_identifier,
    _bundle_identifier,
    _ia_subprocess_env,
    build_raw_meta,
    count_ia_items,
    list_parsed_raw_ids,
    list_raw_ids,
    InternetArchivePublisher,
)


class TestIASubprocessEnv:
    """O CLI `ia` só lê credenciais de um config file; injetamos via IA_CONFIG_FILE."""

    def test_returns_none_without_credentials(self):
        assert _ia_subprocess_env(None, None) is None
        assert _ia_subprocess_env("", "secret") is None
        assert _ia_subprocess_env("access", "") is None

    def test_points_ia_config_file_at_temp_ini_with_keys(self):
        env = _ia_subprocess_env("AKIA-test", "shh-secret")
        assert env is not None
        cfg_path = env["IA_CONFIG_FILE"]
        content = Path(cfg_path).read_text(encoding="utf-8")
        assert "[s3]" in content
        assert "AKIA-test" in content
        assert "shh-secret" in content

    def test_caches_config_per_credential_pair(self):
        first = _ia_subprocess_env("dup-key", "dup-secret")
        second = _ia_subprocess_env("dup-key", "dup-secret")
        assert first is not None and second is not None
        assert first["IA_CONFIG_FILE"] == second["IA_CONFIG_FILE"]


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
                    captured_files.append(Path(arg).read_text(encoding="utf-8"))
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
                    captured_metas.append(
                        json.loads(Path(arg).read_text(encoding="utf-8"))
                    )
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


class TestRunIaUploadRetry:
    """_run_ia_upload: retry exponencial pautado por padrão de erro no stderr do
    `ia` (achado real de produção, 2026-07-14: rajada de uploads levou o IA a
    recusar com 'Please reduce your request rate ... appears to be spam')."""

    def _publisher(self) -> InternetArchivePublisher:
        pub = InternetArchivePublisher()
        pub.access_key = "test-key"
        pub.secret_key = "test-secret"
        return pub

    @patch("time.sleep")
    def test_succeeds_without_retry_on_first_attempt(self, mock_sleep):
        pub = self._publisher()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = pub._run_ia_upload(["ia", "upload", "some-id"])
        assert result.returncode == 0
        assert mock_run.call_count == 1
        mock_sleep.assert_not_called()

    @patch("time.sleep")
    def test_retries_on_rate_limit_error_then_succeeds(self, mock_sleep):
        import subprocess

        pub = self._publisher()
        rate_limit_error = subprocess.CalledProcessError(
            1,
            "ia",
            stderr=(
                "Please reduce your request rate. - Your upload of "
                "leizilla-ro-lei-00290-1984 appears to be spam."
            ),
        )
        success = MagicMock(returncode=0)
        with patch(
            "subprocess.run", side_effect=[rate_limit_error, rate_limit_error, success]
        ) as mock_run:
            result = pub._run_ia_upload(["ia", "upload", "some-id"])
        assert result is success
        assert mock_run.call_count == 3
        assert mock_sleep.call_count == 2  # backoff before attempt 2 and attempt 3

    @patch("time.sleep")
    def test_retries_on_5xx_and_timeout_errors(self, mock_sleep):
        import subprocess

        pub = self._publisher()
        success = MagicMock(returncode=0)
        for stderr in (
            "503 Service Unavailable",
            "connection reset by peer",
            "read timed out",
        ):
            err = subprocess.CalledProcessError(1, "ia", stderr=stderr)
            with patch("subprocess.run", side_effect=[err, success]) as mock_run:
                result = pub._run_ia_upload(["ia", "upload", "some-id"])
            assert result is success
            assert mock_run.call_count == 2

    @patch("time.sleep")
    def test_does_not_retry_non_retryable_error(self, mock_sleep):
        import subprocess

        pub = self._publisher()
        auth_error = subprocess.CalledProcessError(
            1, "ia", stderr="Unauthorized: invalid access key"
        )
        with patch("subprocess.run", side_effect=auth_error) as mock_run:
            try:
                pub._run_ia_upload(["ia", "upload", "some-id"])
                raise AssertionError("expected CalledProcessError to propagate")
            except subprocess.CalledProcessError:
                pass
        assert mock_run.call_count == 1
        mock_sleep.assert_not_called()

    @patch("time.sleep")
    def test_gives_up_after_max_attempts_on_persistent_rate_limit(self, mock_sleep):
        import subprocess

        pub = self._publisher()
        rate_limit_error = subprocess.CalledProcessError(
            1, "ia", stderr="Please reduce your request rate."
        )
        with patch("subprocess.run", side_effect=rate_limit_error) as mock_run:
            try:
                pub._run_ia_upload(["ia", "upload", "some-id"])
                raise AssertionError("expected CalledProcessError to propagate")
            except subprocess.CalledProcessError:
                pass
        assert mock_run.call_count == 5  # _IA_UPLOAD_MAX_ATTEMPTS

    @patch("time.sleep")
    def test_backoff_delay_grows_exponentially(self, mock_sleep):
        import subprocess

        pub = self._publisher()
        rate_limit_error = subprocess.CalledProcessError(
            1, "ia", stderr="503 Service Unavailable"
        )
        success = MagicMock(returncode=0)
        with patch(
            "subprocess.run", side_effect=[rate_limit_error, rate_limit_error, success]
        ):
            pub._run_ia_upload(["ia", "upload", "some-id"])
        delays = [call.args[0] for call in mock_sleep.call_args_list]
        assert len(delays) == 2
        assert delays[0] < delays[1]

    def test_paces_successive_uploads_via_shared_rate_limiter(self):
        pub = self._publisher()
        with (
            patch.object(pub, "_upload_rate_limiter") as mock_limiter,
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            pub._run_ia_upload(["ia", "upload", "id-1"])
            pub._run_ia_upload(["ia", "upload", "id-2"])
        assert mock_limiter.call_count == 2

    def test_file_not_found_is_not_retried(self):
        pub = self._publisher()
        with patch("subprocess.run", side_effect=FileNotFoundError("no ia binary")):
            try:
                pub._run_ia_upload(["ia", "upload", "some-id"])
                raise AssertionError("expected FileNotFoundError to propagate")
            except FileNotFoundError:
                pass


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
    """Testes para list_raw_ids (ADR-0011): enumera os itens de range via scrape
    API e reconstrói os raw_ids legados a partir do index.csv de cada item."""

    def _csv_resp(self, csv_text: str) -> object:
        payload = csv_text.encode()

        class _R:
            def read(self):
                return payload

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

        return _R()

    def test_returns_empty_set_on_scrape_error(self):
        with patch("leizilla.publisher._scrape_identifiers", return_value=None):
            assert list_raw_ids("ro", "assembleia") == set()

    def test_returns_empty_set_when_no_items(self):
        with patch("leizilla.publisher._scrape_identifiers", return_value=[]):
            assert list_raw_ids("ro", "assembleia") == set()

    def test_reconstructs_legacy_raw_ids_from_item_indexes(self):
        index_csv = (
            "tipo,numero,rendicao,formato,uuid5,sha256,captured_at\n"
            "lei,1,,pdf,u1,h1,2026-05-30T00:00:00+00:00\n"
            "lei,2,,pdf,u2,h2,2026-05-30T00:00:00+00:00\n"
        )
        with patch(
            "leizilla.publisher._scrape_identifiers",
            return_value=["leizilla_ro_assembleia_lei_0001-1000"],
        ):
            with patch(
                "urllib.request.urlopen", return_value=self._csv_resp(index_csv)
            ):
                result = list_raw_ids("ro", "assembleia")
        assert result == {
            "leizilla-raw-ro-assembleia-lei-00001",
            "leizilla-raw-ro-assembleia-lei-00002",
        }

    def test_deduplicates_identities_across_versions(self):
        index_csv = (
            "tipo,numero,rendicao,formato,uuid5,sha256,captured_at\n"
            "lei,1,,pdf,u1,h1,2026-05-30T00:00:00+00:00\n"
            "lei,1,atual,html,u2,h2,2026-05-31T00:00:00+00:00\n"
        )
        with patch(
            "leizilla.publisher._scrape_identifiers",
            return_value=["leizilla_ro_casacivil_lei_0001-1000"],
        ):
            with patch(
                "urllib.request.urlopen", return_value=self._csv_resp(index_csv)
            ):
                result = list_raw_ids("ro", "casacivil")
        assert result == {"leizilla-raw-ro-casacivil-lei-00001"}

    def test_enumerates_range_items_by_prefix(self):
        with patch("leizilla.publisher._scrape_identifiers", return_value=[]) as m:
            list_raw_ids("ro", "casacivil")
        m.assert_called_once_with("leizilla_ro_casacivil_")

    def test_transient_index_failure_returns_empty_all_or_nothing(self):
        # A transient failure reading ANY range index must return empty (not a
        # partial set), so cmd_parse_all falls back to the sequential range instead
        # of treating a partial result as authoritative and dropping ranges.
        from leizilla.publisher import IndexFetchError

        good = (
            "tipo,numero,rendicao,formato,uuid5,sha256,captured_at\n"
            "lei,1,,pdf,u1,h1,2026-05-30T00:00:00+00:00\n"
        )
        with (
            patch(
                "leizilla.publisher._scrape_identifiers",
                return_value=[
                    "leizilla_ro_casacivil_lei_0001-1000",
                    "leizilla_ro_casacivil_lei_1001-2000",
                ],
            ),
            patch(
                "leizilla.publisher._fetch_existing_index",
                side_effect=[good, IndexFetchError("HTTP 503")],
            ),
        ):
            assert list_raw_ids("ro", "casacivil") == set()

    def test_confirmed_404_index_skips_only_that_item(self):
        # A confirmed 404 (item without an index) is not transient: that item
        # contributes nothing, but the others are still returned.
        good = (
            "tipo,numero,rendicao,formato,uuid5,sha256,captured_at\n"
            "lei,5,,pdf,u5,h5,2026-05-30T00:00:00+00:00\n"
        )
        with (
            patch(
                "leizilla.publisher._scrape_identifiers",
                return_value=[
                    "leizilla_ro_casacivil_lei_0001-1000",
                    "leizilla_ro_casacivil_lei_5001-6000",
                ],
            ),
            patch(
                "leizilla.publisher._fetch_existing_index",
                side_effect=[None, good],  # first item has no index (404)
            ),
        ):
            assert list_raw_ids("ro", "casacivil") == {
                "leizilla-raw-ro-casacivil-lei-00005"
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


class TestFetchExistingIndex:
    """_fetch_existing_index distingue 404 (ausente → None) de falha transitória
    (5xx/timeout → IndexFetchError), para o chamador nunca sobrescrever histórico."""

    def _http_error(self, code: int) -> Exception:
        import urllib.error

        return urllib.error.HTTPError(
            url="http://ia/index.csv", code=code, msg="x", hdrs=None, fp=None
        )

    def test_404_returns_none(self):
        from leizilla.publisher import _fetch_existing_index

        with patch("urllib.request.urlopen", side_effect=self._http_error(404)):
            assert _fetch_existing_index("leizilla_ro_casacivil_lei_1-1000") is None

    def test_transient_error_raises(self):
        from leizilla.publisher import _fetch_existing_index, IndexFetchError

        import pytest

        with patch("urllib.request.urlopen", side_effect=self._http_error(503)):
            with pytest.raises(IndexFetchError):
                _fetch_existing_index("leizilla_ro_casacivil_lei_1-1000")

    def test_timeout_raises(self):
        from leizilla.publisher import _fetch_existing_index, IndexFetchError

        import pytest

        with patch("urllib.request.urlopen", side_effect=OSError("timeout")):
            with pytest.raises(IndexFetchError):
                _fetch_existing_index("leizilla_ro_casacivil_lei_1-1000")


class TestResolveUuid5AndIndex:
    """_resolve_uuid5_and_index mescla o index.csv do item (append-only) e estende
    o UUIDv5 em caso de colisão (mesmo nome curto, bytes diferentes)."""

    def test_appends_to_existing_index(self):
        from leizilla.publisher import _resolve_uuid5_and_index
        from leizilla.ia_utils import merge_index_row, uuid5_name

        existing = merge_index_row(
            None,
            tipo="lei",
            numero=1,
            rendicao="",
            formato="pdf",
            uuid5="old",
            sha256="hold",
            captured_at="2026-05-30T00:00:00+00:00",
        )
        with patch("leizilla.publisher._fetch_existing_index", return_value=existing):
            uuid5, merged = _resolve_uuid5_and_index(
                "leizilla_ro_casacivil_lei_1-1000",
                b"new bytes",
                tipo="lei",
                numero=2,
                rendicao="",
                formato="pdf",
            )
        assert uuid5 == uuid5_name(b"new bytes")
        # Prior row preserved; new row appended.
        assert "lei,1," in merged and "lei,2," in merged

    def test_extends_uuid5_on_collision(self):
        from leizilla.publisher import _resolve_uuid5_and_index
        from leizilla.ia_utils import merge_index_row, uuid5_name

        short = uuid5_name(b"new bytes")
        # Pre-seed the index with the same short name bound to DIFFERENT bytes.
        existing = merge_index_row(
            None,
            tipo="lei",
            numero=1,
            rendicao="",
            formato="pdf",
            uuid5=short,
            sha256="different-sha",
            captured_at="2026-05-30T00:00:00+00:00",
        )
        with patch("leizilla.publisher._fetch_existing_index", return_value=existing):
            uuid5, _merged = _resolve_uuid5_and_index(
                "leizilla_ro_casacivil_lei_1-1000",
                b"new bytes",
                tipo="lei",
                numero=2,
                rendicao="",
                formato="pdf",
            )
        # Extended to the full UUIDv5 to avoid clobbering the colliding entry.
        assert uuid5 == uuid5_name(b"new bytes", length=32)
        assert uuid5 != short
