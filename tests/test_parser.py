"""Tests for leizilla.parser — HTTP and LiteLLM API fully mocked."""

import json
from unittest.mock import MagicMock, patch

import pytest

from leizilla import parser
from leizilla.ia_utils import resolve_ia_id_to_url

_IA_ID = "leizilla-raw-ro-casacivil-coddoc-09999"

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


def _make_litellm_response(response_text: str) -> MagicMock:
    """Create a mock LiteLLM completion response (OpenAI-compatible format)."""
    msg = MagicMock()
    msg.content = response_text
    choice = MagicMock()
    choice.message = msg
    response = MagicMock()
    response.choices = [choice]
    response.usage.prompt_tokens = 100
    response.usage.completion_tokens = 200
    return response


def _make_urlopen_resp(body: str) -> MagicMock:
    resp = MagicMock()
    resp.read.return_value = body.encode("utf-8")
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


class TestFetchOcr:
    def test_returns_text_on_success(self):
        with patch(
            "urllib.request.urlopen", return_value=_make_urlopen_resp("OCR text")
        ):
            assert parser.fetch_ocr(_IA_ID) == "OCR text"

    def test_returns_none_on_network_error(self):
        with patch("urllib.request.urlopen", side_effect=OSError("404")):
            assert parser.fetch_ocr(_IA_ID) is None

    def test_returns_none_on_timeout(self):
        with patch("urllib.request.urlopen", side_effect=TimeoutError()):
            assert parser.fetch_ocr(_IA_ID) is None

    def test_constructs_djvu_url_fallback(self):
        captured: list[str] = []

        def capture(req, **kw):  # type: ignore[no-untyped-def]
            captured.append(req.full_url)
            raise OSError("stop")

        non_numeric_id = "leizilla-raw-ro-casacivil-nonnumeric"
        with patch("urllib.request.urlopen", side_effect=capture):
            parser.fetch_ocr(non_numeric_id)

        expected = resolve_ia_id_to_url(non_numeric_id, "_djvu.txt")
        assert captured == [expected]

    def test_constructs_djvu_url_range(self):
        captured: list[str] = []

        def capture(req, **kw):  # type: ignore[no-untyped-def]
            captured.append(req.full_url)
            raise OSError("stop")

        with patch("urllib.request.urlopen", side_effect=capture):
            parser.fetch_ocr(_IA_ID)

        expected = resolve_ia_id_to_url(_IA_ID, "_djvu.txt")
        assert captured == [expected]


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
    def test_constructs_ia_html_url_fallback(self):
        captured: list[str] = []

        def capture(req, **kw):  # type: ignore[no-untyped-def]
            captured.append(req.get_full_url())
            raise OSError("stop")

        non_numeric_id = "leizilla-raw-ro-casacivil-nonnumeric"
        with patch("urllib.request.urlopen", side_effect=capture):
            parser.fetch_ia_html(non_numeric_id)

        expected = resolve_ia_id_to_url(non_numeric_id, ".html")
        assert captured == [expected]

    def test_constructs_ia_html_url_range(self):
        captured: list[str] = []

        def capture(req, **kw):  # type: ignore[no-untyped-def]
            captured.append(req.get_full_url())
            raise OSError("stop")

        with patch("urllib.request.urlopen", side_effect=capture):
            parser.fetch_ia_html(_IA_ID)

        expected = resolve_ia_id_to_url(_IA_ID, ".html")
        assert captured == [expected]

    def test_returns_html_on_success(self):
        with patch(
            "urllib.request.urlopen",
            return_value=_make_urlopen_resp("<html>Lei federal</html>"),
        ):
            assert parser.fetch_ia_html(_IA_ID) == "<html>Lei federal</html>"

    def test_returns_none_on_network_error(self):
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
        resp = _make_litellm_response(_LLM_OK)
        with patch("litellm.completion", return_value=resp):
            with patch.object(parser.config, "ANTHROPIC_API_KEY", "test-key"):
                result = parser.parse_law("ocr text", _IA_ID, "ro")

        assert result is not None
        assert result.confidence == pytest.approx(0.9)
        assert result.ia_id_parsed == "leizilla-ro-lei-09999-1999"
        assert "lei" in result.xml

    def test_parsed_meta_structure(self):
        resp = _make_litellm_response(_LLM_OK)
        with patch("litellm.completion", return_value=resp):
            with patch.object(parser.config, "ANTHROPIC_API_KEY", "test-key"):
                result = parser.parse_law("ocr text", _IA_ID, "ro")

        assert result is not None
        meta = result.parsed_meta
        assert meta["leizilla_meta_version"] == "0.1"
        assert meta["ia_id_raw"] == _IA_ID
        assert meta["ia_id_parsed"] == "leizilla-ro-lei-09999-1999"
        assert meta["ente"] == "ro"
        assert meta["tipo"] == "lei"
        assert meta["parse_method"] == f"{parser._DEFAULT_MODEL}+ocr"
        assert meta["tem_divergencia"] is False
        assert "parse_timestamp" in meta

    def test_token_counts_recorded(self):
        resp = _make_litellm_response(_LLM_OK)
        with patch("litellm.completion", return_value=resp):
            with patch.object(parser.config, "ANTHROPIC_API_KEY", "test-key"):
                result = parser.parse_law("ocr text", _IA_ID, "ro")

        assert result is not None
        assert result.input_tokens == 100
        assert result.output_tokens == 200

    def test_returns_none_when_confidence_below_threshold(self):
        low = json.dumps({"confidence": 0.3, "error": "bad OCR"})
        resp = _make_litellm_response(low)
        with patch("litellm.completion", return_value=resp):
            with patch.object(parser.config, "ANTHROPIC_API_KEY", "test-key"):
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
        resp = _make_litellm_response(bad_conf)
        with patch("litellm.completion", return_value=resp):
            with patch.object(parser.config, "ANTHROPIC_API_KEY", "test-key"):
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
        resp = _make_litellm_response(nan_conf)
        with patch("litellm.completion", return_value=resp):
            with patch.object(parser.config, "ANTHROPIC_API_KEY", "test-key"):
                assert parser.parse_law("ocr text", _IA_ID, "ro") is None

    def test_returns_none_when_tipo_missing(self):
        no_tipo = json.dumps(
            {"xml": _VALID_XML, "confidence": 0.9, "numero": "1", "ano": 2000}
        )
        resp = _make_litellm_response(no_tipo)
        with patch("litellm.completion", return_value=resp):
            with patch.object(parser.config, "ANTHROPIC_API_KEY", "test-key"):
                assert parser.parse_law("ocr text", _IA_ID, "ro") is None

    def test_returns_none_when_numero_missing(self):
        no_num = json.dumps(
            {"xml": _VALID_XML, "confidence": 0.9, "tipo": "lei", "ano": 2000}
        )
        resp = _make_litellm_response(no_num)
        with patch("litellm.completion", return_value=resp):
            with patch.object(parser.config, "ANTHROPIC_API_KEY", "test-key"):
                assert parser.parse_law("ocr text", _IA_ID, "ro") is None

    def test_returns_none_when_ano_missing(self):
        no_ano = json.dumps(
            {"xml": _VALID_XML, "confidence": 0.9, "tipo": "lei", "numero": "1"}
        )
        resp = _make_litellm_response(no_ano)
        with patch("litellm.completion", return_value=resp):
            with patch.object(parser.config, "ANTHROPIC_API_KEY", "test-key"):
                assert parser.parse_law("ocr text", _IA_ID, "ro") is None

    def test_returns_none_on_malformed_json(self):
        resp = _make_litellm_response("This is NOT json!!!")
        with patch("litellm.completion", return_value=resp):
            with patch.object(parser.config, "ANTHROPIC_API_KEY", "test-key"):
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
        resp = _make_litellm_response(bad)
        with patch("litellm.completion", return_value=resp):
            with patch.object(parser.config, "ANTHROPIC_API_KEY", "test-key"):
                assert parser.parse_law("ocr text", _IA_ID, "ro") is None

    def test_raises_when_no_llm_key_configured(self):
        with (
            patch.object(parser.config, "ANTHROPIC_API_KEY", None),
            patch.object(parser.config, "OPENROUTER_API_KEY", None),
            patch.object(parser.config, "GEMINI_API_KEY", None),
        ):
            with pytest.raises(RuntimeError, match="chave de LLM"):
                parser.parse_law("ocr text", _IA_ID, "ro")

    def test_uses_model_parameter(self):
        resp = _make_litellm_response(_LLM_OK)
        with patch("litellm.completion", return_value=resp) as mock_completion:
            with patch.object(parser.config, "ANTHROPIC_API_KEY", "test-key"):
                parser.parse_law("ocr text", _IA_ID, "ro", model="claude-opus-4-7")

        _, kwargs = mock_completion.call_args
        assert kwargs.get("model") == "claude-opus-4-7"

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
        resp = _make_litellm_response(short_numero)
        with patch("litellm.completion", return_value=resp):
            with patch.object(parser.config, "ANTHROPIC_API_KEY", "test-key"):
                result = parser.parse_law("ocr text", _IA_ID, "ro")

        assert result is not None
        assert result.ia_id_parsed == "leizilla-ro-lei-00042-1990"

    def test_truncates_ocr_to_limit(self):
        long_ocr = "x" * 20000
        resp = _make_litellm_response(_LLM_OK)
        with patch("litellm.completion", return_value=resp) as mock_completion:
            with patch.object(parser.config, "ANTHROPIC_API_KEY", "test-key"):
                parser.parse_law(long_ocr, _IA_ID, "ro")

        _, kwargs = mock_completion.call_args
        user_content = kwargs["messages"][1]["content"]
        assert len(user_content) < 20000 + 100  # headers + truncated body
        assert "x" * (parser._OCR_CHAR_LIMIT + 1) not in user_content

    def test_html_input_type_uses_html_char_limit(self):
        long_html = "<p>" + "x" * 40000 + "</p>"
        resp = _make_litellm_response(_LLM_OK)
        with patch("litellm.completion", return_value=resp) as mock_completion:
            with patch.object(parser.config, "ANTHROPIC_API_KEY", "test-key"):
                parser.parse_law(
                    long_html,
                    "https://example.gov.br/lei/1",
                    "federal",
                    input_type="html",
                )

        _, kwargs = mock_completion.call_args
        user_content = kwargs["messages"][1]["content"]
        assert "x" * (parser._HTML_CHAR_LIMIT + 1) not in user_content
        assert len(user_content) <= parser._HTML_CHAR_LIMIT + 200

    def test_html_input_type_sets_parse_method(self):
        resp = _make_litellm_response(_LLM_OK)
        with patch("litellm.completion", return_value=resp):
            with patch.object(parser.config, "ANTHROPIC_API_KEY", "test-key"):
                result = parser.parse_law(
                    "html content",
                    "https://example.gov.br/lei/1",
                    "ro",
                    input_type="html",
                )

        assert result is not None
        assert result.parsed_meta["parse_method"] == f"{parser._DEFAULT_MODEL}+html"

    def test_html_input_type_includes_url_in_user_message(self):
        url = "https://example.gov.br/lei/9999"
        resp = _make_litellm_response(_LLM_OK)
        with patch("litellm.completion", return_value=resp) as mock_completion:
            with patch.object(parser.config, "ANTHROPIC_API_KEY", "test-key"):
                parser.parse_law("html content", url, "ro", input_type="html")

        _, kwargs = mock_completion.call_args
        user_content = kwargs["messages"][1]["content"]
        assert url in user_content

    def test_invalid_input_type_raises(self):
        with patch.object(parser.config, "ANTHROPIC_API_KEY", "test-key"):
            with pytest.raises(ValueError, match="input_type"):
                parser.parse_law("content", "id", "ro", input_type="htlm")
