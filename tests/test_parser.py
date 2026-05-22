"""Tests for leizilla.parser — HTTP and Anthropic API fully mocked."""

import json
from unittest.mock import MagicMock, patch

import pytest

from leizilla import parser

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


def _make_anthropic_client(response_text: str) -> MagicMock:
    content_block = MagicMock()
    content_block.text = response_text
    message = MagicMock()
    message.content = [content_block]
    message.usage.input_tokens = 100
    message.usage.output_tokens = 200
    client = MagicMock()
    client.messages.create.return_value = message
    return client


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

    def test_constructs_djvu_url(self):
        captured: list[str] = []

        def capture(req, **kw):  # type: ignore[no-untyped-def]
            captured.append(req.full_url)
            raise OSError("stop")

        with patch("urllib.request.urlopen", side_effect=capture):
            parser.fetch_ocr(_IA_ID)

        expected = f"https://archive.org/download/{_IA_ID}/{_IA_ID}_djvu.txt"
        assert captured == [expected]


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
        client = _make_anthropic_client(_LLM_OK)
        with patch("anthropic.Anthropic", return_value=client):
            with patch.object(parser.config, "ANTHROPIC_API_KEY", "test-key"):
                result = parser.parse_law("ocr text", _IA_ID, "ro")

        assert result is not None
        assert result.confidence == pytest.approx(0.9)
        assert result.ia_id_parsed == "leizilla-ro-lei-09999-1999"
        assert "lei" in result.xml

    def test_parsed_meta_structure(self):
        client = _make_anthropic_client(_LLM_OK)
        with patch("anthropic.Anthropic", return_value=client):
            with patch.object(parser.config, "ANTHROPIC_API_KEY", "test-key"):
                result = parser.parse_law("ocr text", _IA_ID, "ro")

        assert result is not None
        meta = result.parsed_meta
        assert meta["leizilla_meta_version"] == "0.1"
        assert meta["ia_id_raw"] == _IA_ID
        assert meta["ia_id_parsed"] == "leizilla-ro-lei-09999-1999"
        assert meta["ente"] == "ro"
        assert meta["tipo"] == "lei"
        assert meta["parse_method"] == parser._HAIKU
        assert meta["tem_divergencia"] is False
        assert "parse_timestamp" in meta

    def test_token_counts_recorded(self):
        client = _make_anthropic_client(_LLM_OK)
        with patch("anthropic.Anthropic", return_value=client):
            with patch.object(parser.config, "ANTHROPIC_API_KEY", "test-key"):
                result = parser.parse_law("ocr text", _IA_ID, "ro")

        assert result is not None
        assert result.input_tokens == 100
        assert result.output_tokens == 200

    def test_returns_none_when_confidence_below_threshold(self):
        low = json.dumps({"confidence": 0.3, "error": "bad OCR"})
        client = _make_anthropic_client(low)
        with patch("anthropic.Anthropic", return_value=client):
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
        client = _make_anthropic_client(bad_conf)
        with patch("anthropic.Anthropic", return_value=client):
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
        client = _make_anthropic_client(nan_conf)
        with patch("anthropic.Anthropic", return_value=client):
            with patch.object(parser.config, "ANTHROPIC_API_KEY", "test-key"):
                assert parser.parse_law("ocr text", _IA_ID, "ro") is None

    def test_returns_none_when_tipo_missing(self):
        no_tipo = json.dumps(
            {"xml": _VALID_XML, "confidence": 0.9, "numero": "1", "ano": 2000}
        )
        client = _make_anthropic_client(no_tipo)
        with patch("anthropic.Anthropic", return_value=client):
            with patch.object(parser.config, "ANTHROPIC_API_KEY", "test-key"):
                assert parser.parse_law("ocr text", _IA_ID, "ro") is None

    def test_returns_none_when_numero_missing(self):
        no_num = json.dumps(
            {"xml": _VALID_XML, "confidence": 0.9, "tipo": "lei", "ano": 2000}
        )
        client = _make_anthropic_client(no_num)
        with patch("anthropic.Anthropic", return_value=client):
            with patch.object(parser.config, "ANTHROPIC_API_KEY", "test-key"):
                assert parser.parse_law("ocr text", _IA_ID, "ro") is None

    def test_returns_none_when_ano_missing(self):
        no_ano = json.dumps(
            {"xml": _VALID_XML, "confidence": 0.9, "tipo": "lei", "numero": "1"}
        )
        client = _make_anthropic_client(no_ano)
        with patch("anthropic.Anthropic", return_value=client):
            with patch.object(parser.config, "ANTHROPIC_API_KEY", "test-key"):
                assert parser.parse_law("ocr text", _IA_ID, "ro") is None

    def test_returns_none_on_malformed_json(self):
        client = _make_anthropic_client("This is NOT json!!!")
        with patch("anthropic.Anthropic", return_value=client):
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
        client = _make_anthropic_client(bad)
        with patch("anthropic.Anthropic", return_value=client):
            with patch.object(parser.config, "ANTHROPIC_API_KEY", "test-key"):
                assert parser.parse_law("ocr text", _IA_ID, "ro") is None

    def test_raises_when_api_key_missing(self):
        with patch.object(parser.config, "ANTHROPIC_API_KEY", None):
            with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
                parser.parse_law("ocr text", _IA_ID, "ro")

    def test_uses_model_parameter(self):
        client = _make_anthropic_client(_LLM_OK)
        with patch("anthropic.Anthropic", return_value=client):
            with patch.object(parser.config, "ANTHROPIC_API_KEY", "test-key"):
                parser.parse_law("ocr text", _IA_ID, "ro", model="claude-opus-4-7")

        _, kwargs = client.messages.create.call_args
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
        client = _make_anthropic_client(short_numero)
        with patch("anthropic.Anthropic", return_value=client):
            with patch.object(parser.config, "ANTHROPIC_API_KEY", "test-key"):
                result = parser.parse_law("ocr text", _IA_ID, "ro")

        assert result is not None
        assert result.ia_id_parsed == "leizilla-ro-lei-00042-1990"

    def test_truncates_ocr_to_limit(self):
        long_ocr = "x" * 20000
        client = _make_anthropic_client(_LLM_OK)
        with patch("anthropic.Anthropic", return_value=client):
            with patch.object(parser.config, "ANTHROPIC_API_KEY", "test-key"):
                parser.parse_law(long_ocr, _IA_ID, "ro")

        _, kwargs = client.messages.create.call_args
        user_content = kwargs["messages"][0]["content"]
        assert len(user_content) < 20000 + 100  # headers + truncated body
        assert "x" * (parser._OCR_CHAR_LIMIT + 1) not in user_content
