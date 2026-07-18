"""Tests for leizilla.parser — HTTP and LLM (litellm) fully mocked."""

import contextlib

import json
from unittest.mock import MagicMock, patch

import pytest

from leizilla import parser

_IA_ID = "leizilla-raw-ro-casacivil-coddoc-09999"
# URL that resolve_raw_url would produce for a captured raw item (content-addressed).
_RESOLVED = "https://archive.org/download/leizilla-raw-ro-casacivil-3f/3f8a_djvu.txt"
_RESOLVED_HTML = "https://archive.org/download/leizilla-raw-ro-casacivil-3f/3f8a.html"

_VALID_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<lei xmlns="https://leizilla.org/lei/0.1" schema-version="0.1"'
    ' urn-lex="urn:lex:br;rondonia:estadual:lei:1999-06-15;9999"'
    ' vigente-em="2026-05-20">'
    '<dispositivo path="ementa">'
    "<versao><texto>Institui o Dia Estadual.</texto>"
    f'<fonte ia-id="{_IA_ID}"/></versao>'
    "</dispositivo>"
    '<dispositivo path="art-1">'
    "<versao><texto>Fica instituído.</texto>"
    f'<fonte ia-id="{_IA_ID}"/></versao>'
    "</dispositivo>"
    "</lei>"
)

_LLM_OK = json.dumps(
    {
        "xml": _VALID_XML,
        "confidence": 0.9,
        "tipo": "lei",
        "numero": "9999",
        "ano": 1999,
        "urn_lex": "urn:lex:br;rondonia:estadual:lei:1999-06-15;9999",
    }
)


def _make_llm_response(response_text: str) -> MagicMock:
    """Resposta fake no formato OpenAI que o litellm.completion retorna."""
    message = MagicMock()
    message.content = response_text
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    response.usage.prompt_tokens = 100
    response.usage.completion_tokens = 200
    return response


@contextlib.contextmanager
def _llm(response_text: str, keys: dict | None = None):
    """Mocka litellm.completion + chaves no config; yield o mock da chamada."""
    if keys is None:
        keys = {"ANTHROPIC_API_KEY": "test-key"}
    attrs = {
        "ANTHROPIC_API_KEY": keys.get("ANTHROPIC_API_KEY"),
        "GEMINI_API_KEY": keys.get("GEMINI_API_KEY"),
        "LLM_MODEL": keys.get("LLM_MODEL"),
    }
    with patch(
        "litellm.completion", return_value=_make_llm_response(response_text)
    ) as m:
        with patch.multiple(parser.config, **attrs):
            yield m


def _make_urlopen_resp(body: str) -> MagicMock:
    resp = MagicMock()
    resp.read.return_value = body.encode("utf-8")
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


class TestFetchOcr:
    def test_returns_text_on_success(self):
        # resolve_raw_url maps the raw_id → content-addressed URL via the index;
        # then the OCR file at that URL is fetched. Both mocked.
        with patch("leizilla.parser.resolve_raw_url", return_value=_RESOLVED):
            with patch(
                "urllib.request.urlopen", return_value=_make_urlopen_resp("OCR text")
            ):
                assert parser.fetch_ocr(_IA_ID) == "OCR text"

    def test_returns_none_when_unresolved(self):
        # Index/source_key not published yet → resolve returns None → no fetch.
        with patch("leizilla.parser.resolve_raw_url", return_value=None):
            assert parser.fetch_ocr(_IA_ID) is None

    def test_returns_none_on_network_error(self):
        with patch("leizilla.parser.resolve_raw_url", return_value=_RESOLVED):
            with patch("urllib.request.urlopen", side_effect=OSError("404")):
                assert parser.fetch_ocr(_IA_ID) is None

    def test_returns_none_on_timeout(self):
        with patch("leizilla.parser.resolve_raw_url", return_value=_RESOLVED):
            with patch("urllib.request.urlopen", side_effect=TimeoutError()):
                assert parser.fetch_ocr(_IA_ID) is None

    def test_fetches_the_resolved_url(self):
        captured: list[str] = []

        def capture(req, **kw):  # type: ignore[no-untyped-def]
            captured.append(req.full_url)
            raise OSError("stop")

        with patch("leizilla.parser.resolve_raw_url", return_value=_RESOLVED):
            with patch("urllib.request.urlopen", side_effect=capture):
                parser.fetch_ocr(_IA_ID)

        assert captured == [_RESOLVED]


class TestFetchHtml:
    def test_returns_html_on_success(self):
        with patch(
            "urllib.request.urlopen",
            return_value=_make_urlopen_resp("<html>Lei texto</html>"),
        ):
            assert (
                parser.fetch_html("https://example.gov.br/lei/1")
                == "<html>Lei texto</html>"
            )

    def test_returns_none_on_network_error(self):
        with patch("urllib.request.urlopen", side_effect=OSError("timeout")):
            assert parser.fetch_html("https://example.gov.br/lei/1") is None

    def test_returns_none_on_url_error(self):
        import urllib.error

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("name not found"),
        ):
            assert parser.fetch_html("https://example.gov.br/lei/1") is None

    def test_returns_none_on_malformed_url(self):
        assert parser.fetch_html("not-a-url-at-all") is None

    def test_sets_user_agent_header(self):
        captured_req: list = []

        def capture(req, **kw):  # type: ignore[no-untyped-def]
            captured_req.append(req)
            raise OSError("stop")

        with patch("urllib.request.urlopen", side_effect=capture):
            parser.fetch_html("https://example.gov.br/lei/1")

        assert captured_req[0].get_header("User-agent") == parser._USER_AGENT


class TestFetchIaHtml:
    def test_fetches_the_resolved_url(self):
        captured: list[str] = []

        def capture(req, **kw):  # type: ignore[no-untyped-def]
            captured.append(req.get_full_url())
            raise OSError("stop")

        with patch("leizilla.parser.resolve_raw_url", return_value=_RESOLVED_HTML):
            with patch("urllib.request.urlopen", side_effect=capture):
                parser.fetch_ia_html(_IA_ID)

        assert captured == [_RESOLVED_HTML]

    def test_returns_none_when_unresolved(self):
        with patch("leizilla.parser.resolve_raw_url", return_value=None):
            assert parser.fetch_ia_html(_IA_ID) is None

    def test_returns_html_on_success(self):
        with patch("leizilla.parser.resolve_raw_url", return_value=_RESOLVED_HTML):
            with patch(
                "urllib.request.urlopen",
                return_value=_make_urlopen_resp("<html>Lei federal</html>"),
            ):
                assert parser.fetch_ia_html(_IA_ID) == "<html>Lei federal</html>"

    def test_returns_none_on_network_error(self):
        with patch("leizilla.parser.resolve_raw_url", return_value=_RESOLVED_HTML):
            with patch("urllib.request.urlopen", side_effect=OSError("timeout")):
                assert parser.fetch_ia_html(_IA_ID) is None


class TestExtractJson:
    def test_direct_json(self):
        result = parser._extract_json('{"a": 1}')
        assert result == {"a": 1}

    def test_json_wrapped_in_text(self):
        result = parser._extract_json('Here is the result: {"a": 1} done.')
        assert result == {"a": 1}

    def test_returns_none_on_invalid(self):
        assert parser._extract_json("not json at all") is None

    def test_returns_none_on_empty(self):
        assert parser._extract_json("") is None


class TestIsWellFormed:
    def test_valid_xml(self):
        assert parser._is_well_formed("<root><child/></root>") is True

    def test_invalid_xml(self):
        assert parser._is_well_formed("<root>UNCLOSED") is False

    def test_empty_string(self):
        assert parser._is_well_formed("") is False

    def test_non_string_returns_false(self):
        assert parser._is_well_formed({"key": "value"}) is False  # type: ignore[arg-type]
        assert parser._is_well_formed(42) is False  # type: ignore[arg-type]
        assert parser._is_well_formed(None) is False  # type: ignore[arg-type]


class TestParseLaw:
    def test_returns_result_on_valid_response(self):
        with _llm(_LLM_OK):
            result = parser.parse_law("ocr text", _IA_ID, "ro")

        assert result is not None
        assert result.confidence == pytest.approx(0.9)
        assert result.ia_id_parsed == "leizilla-ro-lei-09999-1999"
        assert "lei" in result.xml

    def test_parsed_meta_structure(self):
        with _llm(_LLM_OK):
            result = parser.parse_law("ocr text", _IA_ID, "ro")

        assert result is not None
        meta = result.parsed_meta
        assert meta["leizilla_meta_version"] == "0.1"
        assert meta["ia_id_raw"] == _IA_ID
        assert meta["ia_id_parsed"] == "leizilla-ro-lei-09999-1999"
        assert meta["ente"] == "ro"
        assert meta["tipo"] == "lei"
        assert meta["parse_method"] == f"{parser._HAIKU}+ocr"
        assert meta["tem_divergencia"] is False
        assert "parse_timestamp" in meta

    def test_token_counts_recorded(self):
        with _llm(_LLM_OK):
            result = parser.parse_law("ocr text", _IA_ID, "ro")

        assert result is not None
        assert result.input_tokens == 100
        assert result.output_tokens == 200

    def test_returns_none_when_confidence_below_threshold(self):
        low = json.dumps({"confidence": 0.3, "error": "bad OCR"})
        with _llm(low):
            assert parser.parse_law("ocr text", _IA_ID, "ro") is None

    def test_returns_none_when_confidence_non_numeric(self):
        bad_conf = json.dumps(
            {
                "confidence": "high",
                "xml": _VALID_XML,
                "tipo": "lei",
                "numero": "1",
                "ano": 2000,
            }
        )
        with _llm(bad_conf):
            assert parser.parse_law("ocr text", _IA_ID, "ro") is None

    def test_returns_none_when_confidence_nan(self):
        import math

        nan_conf = json.dumps(
            {
                "confidence": math.nan,
                "xml": _VALID_XML,
                "tipo": "lei",
                "numero": "1",
                "ano": 2000,
            }
        )
        with _llm(nan_conf):
            assert parser.parse_law("ocr text", _IA_ID, "ro") is None

    def test_returns_none_when_tipo_missing(self):
        no_tipo = json.dumps(
            {"xml": _VALID_XML, "confidence": 0.9, "numero": "1", "ano": 2000}
        )
        with _llm(no_tipo):
            assert parser.parse_law("ocr text", _IA_ID, "ro") is None

    def test_returns_none_when_numero_missing(self):
        no_num = json.dumps(
            {"xml": _VALID_XML, "confidence": 0.9, "tipo": "lei", "ano": 2000}
        )
        with _llm(no_num):
            assert parser.parse_law("ocr text", _IA_ID, "ro") is None

    def test_returns_none_when_ano_missing(self):
        no_ano = json.dumps(
            {"xml": _VALID_XML, "confidence": 0.9, "tipo": "lei", "numero": "1"}
        )
        with _llm(no_ano):
            assert parser.parse_law("ocr text", _IA_ID, "ro") is None

    def test_returns_none_on_malformed_json(self):
        with _llm("This is NOT json!!!"):
            assert parser.parse_law("ocr text", _IA_ID, "ro") is None

    def test_returns_none_on_malformed_xml(self):
        bad = json.dumps(
            {
                "xml": "<lei>UNCLOSED",
                "confidence": 0.9,
                "tipo": "lei",
                "numero": "9999",
                "ano": 1999,
            }
        )
        with _llm(bad):
            assert parser.parse_law("ocr text", _IA_ID, "ro") is None

    def test_returns_none_when_versao_has_no_fonte(self):
        xml_no_fonte = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<lei xmlns="https://leizilla.org/lei/0.1" schema-version="0.1"'
            ' urn-lex="urn:lex:br;rondonia:estadual:lei:1999-06-15;9999"'
            ' vigente-em="2026-05-20">'
            '<dispositivo path="ementa">'
            "<versao><texto>Sem fonte.</texto></versao>"
            "</dispositivo>"
            "</lei>"
        )
        bad = json.dumps(
            {
                "xml": xml_no_fonte,
                "confidence": 0.9,
                "tipo": "lei",
                "numero": "9999",
                "ano": 1999,
            }
        )
        with _llm(bad):
            assert parser.parse_law("ocr text", _IA_ID, "ro") is None

    def test_returns_none_when_versao_has_multiple_fontes(self):
        xml_multi_fonte = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<lei xmlns="https://leizilla.org/lei/0.1" schema-version="0.1"'
            ' urn-lex="urn:lex:br;rondonia:estadual:lei:1999-06-15;9999"'
            ' vigente-em="2026-05-20">'
            '<dispositivo path="ementa">'
            "<versao><texto>Duas fontes.</texto>"
            f'<fonte ia-id="{_IA_ID}"/><fonte ia-id="{_IA_ID}-outra"/></versao>'
            "</dispositivo>"
            "</lei>"
        )
        bad = json.dumps(
            {
                "xml": xml_multi_fonte,
                "confidence": 0.9,
                "tipo": "lei",
                "numero": "9999",
                "ano": 1999,
            }
        )
        with _llm(bad):
            assert parser.parse_law("ocr text", _IA_ID, "ro") is None

    def test_returns_none_when_fonte_ia_id_mismatches(self):
        xml_wrong_fonte = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<lei xmlns="https://leizilla.org/lei/0.1" schema-version="0.1"'
            ' urn-lex="urn:lex:br;rondonia:estadual:lei:1999-06-15;9999"'
            ' vigente-em="2026-05-20">'
            '<dispositivo path="ementa">'
            "<versao><texto>Fonte errada.</texto>"
            '<fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00001"/></versao>'
            "</dispositivo>"
            "</lei>"
        )
        bad = json.dumps(
            {
                "xml": xml_wrong_fonte,
                "confidence": 0.9,
                "tipo": "lei",
                "numero": "9999",
                "ano": 1999,
            }
        )
        with _llm(bad):
            assert parser.parse_law("ocr text", _IA_ID, "ro") is None

    def test_raises_when_no_key_configured(self):
        empty = {"ANTHROPIC_API_KEY": None}
        with _llm(_LLM_OK, keys=empty):
            with patch.dict("os.environ", {}, clear=True):
                with pytest.raises(RuntimeError, match="Nenhuma chave LLM"):
                    parser.parse_law("ocr text", _IA_ID, "ro")

    def test_raises_when_key_missing_for_explicit_anthropic_model(self):
        with _llm(_LLM_OK, keys={"GEMINI_API_KEY": "g-key"}):
            with patch.dict("os.environ", {}, clear=True):
                with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
                    parser.parse_law("ocr text", _IA_ID, "ro", model="claude-opus-4-7")

    def test_raises_when_key_missing_for_gemini_model(self):
        with _llm(_LLM_OK, keys={"ANTHROPIC_API_KEY": "a-key"}):
            with patch.dict("os.environ", {}, clear=True):
                with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
                    parser.parse_law(
                        "ocr text", _IA_ID, "ro", model="gemini/gemini-2.5-flash"
                    )

    def test_unmapped_provider_skips_key_prevalidation(self):
        # Provider fora do mapa: LiteLLM valida em runtime; parse segue normal.
        with _llm(_LLM_OK, keys={}) as m:
            with patch.dict("os.environ", {}, clear=True):
                result = parser.parse_law(
                    "ocr text", _IA_ID, "ro", model="mistral/mistral-small"
                )

        assert result is not None
        _, kwargs = m.call_args
        assert kwargs.get("model") == "mistral/mistral-small"

    def test_uses_model_parameter(self):
        with _llm(_LLM_OK) as m:
            parser.parse_law("ocr text", _IA_ID, "ro", model="claude-opus-4-7")

        _, kwargs = m.call_args
        assert kwargs.get("model") == "claude-opus-4-7"

    def test_gemini_used_by_default_when_only_gemini_key(self):
        with _llm(_LLM_OK, keys={"GEMINI_API_KEY": "g-key"}) as m:
            result = parser.parse_law("ocr text", _IA_ID, "ro")

        assert result is not None
        _, kwargs = m.call_args
        assert kwargs.get("model") == parser._GEMINI_FLASH
        assert result.parsed_meta["parse_method"] == f"{parser._GEMINI_FLASH}+ocr"

    def test_llm_model_env_overrides_auto_default(self):
        keys = {"ANTHROPIC_API_KEY": "a-key", "LLM_MODEL": "anthropic/claude-opus-4-7"}
        with _llm(_LLM_OK, keys=keys) as m:
            parser.parse_law("ocr text", _IA_ID, "ro")

        _, kwargs = m.call_args
        assert kwargs.get("model") == "anthropic/claude-opus-4-7"

    def test_system_prompt_has_cache_control_in_content_block(self):
        # RFC-0006: cache_control vive no content block (nunca no root da msg).
        with _llm(_LLM_OK) as m:
            parser.parse_law("ocr text", _IA_ID, "ro")

        _, kwargs = m.call_args
        system_msg = kwargs["messages"][0]
        assert system_msg["role"] == "system"
        block = system_msg["content"][0]
        assert block["cache_control"] == {"type": "ephemeral"}
        assert "cache_control" not in system_msg

    def test_zero_pads_numero(self):
        short_numero = json.dumps(
            {
                "xml": _VALID_XML,
                "confidence": 0.85,
                "tipo": "lei",
                "numero": "42",
                "ano": 1990,
            }
        )
        with _llm(short_numero):
            result = parser.parse_law("ocr text", _IA_ID, "ro")

        assert result is not None
        assert result.ia_id_parsed == "leizilla-ro-lei-00042-1990"

    def test_truncates_ocr_to_limit(self):
        long_ocr = "x" * 20000
        with _llm(_LLM_OK) as m:
            parser.parse_law(long_ocr, _IA_ID, "ro")

        _, kwargs = m.call_args
        user_content = kwargs["messages"][1]["content"]
        assert len(user_content) < 20000 + 100  # headers + truncated body
        assert "x" * (parser._OCR_CHAR_LIMIT + 1) not in user_content

    def test_html_input_type_uses_html_char_limit(self):
        long_html = "<p>" + "x" * 40000 + "</p>"
        with _llm(_LLM_OK) as m:
            parser.parse_law(
                long_html,
                "https://example.gov.br/lei/1",
                "federal",
                input_type="html",
            )

        _, kwargs = m.call_args
        user_content = kwargs["messages"][1]["content"]
        assert "x" * (parser._HTML_CHAR_LIMIT + 1) not in user_content
        assert len(user_content) <= parser._HTML_CHAR_LIMIT + 200

    def test_html_input_type_sets_parse_method(self):
        html_ia_id = "https://example.gov.br/lei/1"
        xml_html_source = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<lei xmlns="https://leizilla.org/lei/0.1" schema-version="0.1"'
            ' urn-lex="urn:lex:br;rondonia:estadual:lei:1999-06-15;9999"'
            ' vigente-em="2026-05-20">'
            '<dispositivo path="ementa">'
            "<versao><texto>Institui o Dia Estadual.</texto>"
            f'<fonte ia-id="{html_ia_id}"/></versao>'
            "</dispositivo>"
            "</lei>"
        )
        ok_html = json.dumps(
            {
                "xml": xml_html_source,
                "confidence": 0.9,
                "tipo": "lei",
                "numero": "9999",
                "ano": 1999,
                "urn_lex": "urn:lex:br;rondonia:estadual:lei:1999-06-15;9999",
            }
        )
        with _llm(ok_html):
            result = parser.parse_law(
                "html content",
                html_ia_id,
                "ro",
                input_type="html",
            )

        assert result is not None
        assert result.parsed_meta["parse_method"] == f"{parser._HAIKU}+html"

    def test_html_input_type_includes_url_in_user_message(self):
        url = "https://example.gov.br/lei/9999"
        with _llm(_LLM_OK) as m:
            parser.parse_law("html content", url, "ro", input_type="html")

        _, kwargs = m.call_args
        user_content = kwargs["messages"][1]["content"]
        assert url in user_content

    def test_invalid_input_type_raises(self):
        with _llm(_LLM_OK):
            with pytest.raises(ValueError, match="input_type"):
                parser.parse_law("content", "id", "ro", input_type="htlm")


class TestDefaultModel:
    """Precedência de modelo da RFC-0006 §2: LLM_MODEL > Anthropic > Gemini."""

    def _cfg(self, **attrs):
        base = {"LLM_MODEL": None, "ANTHROPIC_API_KEY": None, "GEMINI_API_KEY": None}
        base.update(attrs)
        return patch.multiple(parser.config, **base)

    def test_llm_model_env_wins(self):
        with self._cfg(LLM_MODEL="openai/gpt-4o-mini", ANTHROPIC_API_KEY="a"):
            assert parser.default_model() == "openai/gpt-4o-mini"

    def test_anthropic_key_selects_haiku(self):
        with self._cfg(ANTHROPIC_API_KEY="a-key", GEMINI_API_KEY="g-key"):
            assert parser.default_model() == parser._HAIKU

    def test_gemini_key_selects_gemini_flash(self):
        with self._cfg(GEMINI_API_KEY="g-key"):
            assert parser.default_model() == parser._GEMINI_FLASH

    def test_no_keys_raises_with_guidance(self):
        with self._cfg():
            with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
                parser.default_model()

    def test_whitespace_only_llm_model_falls_back_to_auto(self):
        # LLM_MODEL="   " não é um id de modelo válido — deve cair para o modo
        # auto, igual a doctor.check_llm_key (que faz env.get(...).strip()).
        with self._cfg(LLM_MODEL="   ", GEMINI_API_KEY="g-key"):
            assert parser.default_model() == parser._GEMINI_FLASH

    def test_llm_model_is_stripped(self):
        with self._cfg(LLM_MODEL="  gemini/gemini-2.5-flash  "):
            assert parser.default_model() == "gemini/gemini-2.5-flash"


class TestRequiredEnvFor:
    def test_gemini_prefix(self):
        assert parser.required_env_for("gemini/gemini-2.5-flash") == (
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
        )

    def test_claude_bare_and_anthropic_prefix(self):
        assert parser.required_env_for("claude-haiku-4-5") == ("ANTHROPIC_API_KEY",)
        assert parser.required_env_for("anthropic/claude-opus-4-7") == (
            "ANTHROPIC_API_KEY",
        )

    def test_openai_prefixes(self):
        assert parser.required_env_for("openai/gpt-4o-mini") == ("OPENAI_API_KEY",)
        assert parser.required_env_for("gpt-4o") == ("OPENAI_API_KEY",)

    def test_unknown_provider_returns_none(self):
        assert parser.required_env_for("mistral/mistral-small") is None
