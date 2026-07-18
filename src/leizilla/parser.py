"""OCR fetch + LLM parse → Leizilla XML v0.1 (M3 pipeline stage).

Etapa 2 do pipeline:
  raw IA item (_djvu.txt OCR) → LLM (LiteLLM) → Leizilla XML + parsed_meta.json

Princípio load-bearing #2: OCR é responsabilidade do IA; LLM só lê _djvu.txt.
Princípio load-bearing #3: Etapa 2 pluggable; model é parâmetro — qualquer id
LiteLLM serve (RFC-0006). Precedência: --model > LLM_MODEL > auto pela chave.
"""

import json
import logging
import math
import os
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional, Tuple

from leizilla import config
from leizilla.ia_utils import resolve_raw_url

logger = logging.getLogger(__name__)

_HAIKU = "claude-haiku-4-5"
_GEMINI_FLASH = "gemini/gemini-2.5-flash"

# Prefixo do modelo → env vars aceitas para o provider (fail-fast antes de
# queimar um batch; modelos de providers não mapeados são validados pelo
# próprio LiteLLM em runtime). RFC-0006 §3.
_PROVIDER_ENV_VARS: Tuple[Tuple[Tuple[str, ...], Tuple[str, ...]], ...] = (
    (("gemini/",), ("GEMINI_API_KEY", "GOOGLE_API_KEY")),
    (("claude", "anthropic/"), ("ANTHROPIC_API_KEY",)),
    (("openai/", "gpt-"), ("OPENAI_API_KEY",)),
)
_USER_AGENT = "leizilla-crawler/0.1"
_MIN_CONFIDENCE = 0.5
_OCR_CHAR_LIMIT = 8000
_HTML_CHAR_LIMIT = 32000  # HTML has markup overhead; more chars needed

# URN local name per ente code (CGPID §5.6)
_ENTE_URN: Dict[str, str] = {
    "ro": "rondonia",
    "sp": "sao.paulo",
    "rj": "rio.de.janeiro",
    "mg": "minas.gerais",
    "df": "distrito.federal",
    "federal": "federal",
}

_SYSTEM_INTRO_OCR = "Parse Brazilian law OCR text into a JSON object."
_SYSTEM_INTRO_HTML = (
    "Parse Brazilian law HTML page into a JSON object. "
    "Ignore navigation bars, headers, footers, and script elements; "
    "extract only the normative text (ementa, artigos, parágrafos, incisos)."
)

_SYSTEM = """\
{input_intro} Output ONLY valid JSON — no markdown fences, no explanation.

Required fields:
- "xml": complete Leizilla XML v0.1 string (see format below)
- "confidence": float 0.0–1.0 (how well you parsed the text)
- "tipo": document type slug — "lei", "decreto", "lei-complementar", etc.
- "numero": law number as string, digits only (e.g. "9999")
- "ano": year as integer
- "urn_lex": URN LEX string (see URN rules); null only if the text has no date at all

Leizilla XML v0.1 format (namespace https://leizilla.org/lei/0.1):

<?xml version="1.0" encoding="UTF-8"?>
<lei xmlns="https://leizilla.org/lei/0.1" schema-version="0.1"
     urn-lex="urn:lex:br;{ente_name}:estadual:lei:YYYY-MM-DD;NUMERO"
     vigente-em="{today}">
  <dispositivo path="ementa">
    <versao><texto>Ementa text here.</texto><fonte ia-id="{ia_id}"/></versao>
  </dispositivo>
  <dispositivo path="art-1">
    <versao><texto>Caput text.</texto><fonte ia-id="{ia_id}"/></versao>
    <dispositivo path="art-1-par-unico">
      <versao><texto>Parágrafo único text.</texto><fonte ia-id="{ia_id}"/></versao>
    </dispositivo>
  </dispositivo>
  <dispositivo path="art-2">
    <versao><texto>Art. 2 text.</texto><fonte ia-id="{ia_id}"/></versao>
  </dispositivo>
</lei>

Path rules:
- Normative paths (global): ementa, preambulo, art-N, art-N-par-unico, art-N-par-M, art-N-inc-N, art-N-inc-N-ali-a
- Organizational paths (namespaced): tit-N, tit-N-cap-N, tit-N-cap-N-sec-N
- Use lower-case with hyphens only, first char must be a-z
- Paths MUST be unique within the document. Before you output, verify no two
  <dispositivo> share the same path. If the source repeats an article/inciso
  number, emit it once (the authoritative occurrence) — never a duplicate path.

Provenance (mandatory):
- Every <versao> MUST contain exactly one <fonte ia-id="{ia_id}"/>, with the
  ia-id EXACTLY "{ia_id}" — never empty, never omitted, never a different value.

URN rules — the urn-lex on <lei> and the "urn_lex" field must be identical:
  state laws (ente={ente_name}):  urn:lex:br;{ente_name}:estadual:TIPO:YYYY-MM-DD;NUMERO
  federal laws (ente=federal):    urn:lex:br:federal:TIPO:YYYY-MM-DD;NUMERO
- TIPO is the LexML token for THIS document — NOT always "lei". The "lei" in the
  example above is illustrative; replace it per this map (LexML uses dots in the
  URN token, never hyphens):
    lei                    -> lei
    lei complementar       -> lei.complementar
    decreto                -> decreto
    decreto-lei            -> decreto.lei
    emenda constitucional  -> emenda.constitucional
    medida provisória      -> medida.provisoria
    resolução              -> resolucao
    portaria               -> portaria
- YYYY-MM-DD is the law's ACTUAL publication/enactment date read from the text
  (the dateline, "Publicada no D.O.E. de…", or the closing "Palácio…, em DD de
  MÊS de AAAA"). Use a year-only date (just YYYY) when the day/month are missing.
  Do NOT substitute today's date into the URN.
- NUMERO is the digits-only law number (same value as the "numero" field).

Use vigente-em={today} — this is the "as of" reference for the snapshot and is
independent of the publication date encoded in the URN.

If text is unreadable, not a law, or confidence < 0.5, output only:
{{"confidence": 0.0, "error": "brief reason"}}
"""


@dataclass
class ParseResult:
    xml: str
    parsed_meta: Dict[str, Any]
    confidence: float
    ia_id_parsed: str
    input_tokens: int = field(default=0)
    output_tokens: int = field(default=0)


def fetch_ocr(ia_id: str, timeout: int = 30) -> Optional[str]:
    """Fetch OCR text (_djvu.txt) for a raw IA item. Returns None on failure.

    Resolution is content-addressed (ADR-0010): the raw_id is mapped through the
    (ente, fonte) index to the current capture's content hash. A None URL means
    the index/source_key isn't published yet — treated as "OCR not available".
    """
    url = resolve_raw_url(ia_id, "_djvu.txt", timeout=timeout)
    if url is None:
        return None
    req = urllib.request.Request(url)
    req.add_header("User-Agent", _USER_AGENT)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")  # type: ignore[no-any-return]
    except Exception:
        return None


def fetch_html(url: str, timeout: int = 30) -> Optional[str]:
    """Fetch HTML content from an official law portal. Returns None on failure.

    Used for sources like Planalto that publish HTML, not PDF (M3.4).
    Caller is responsible for rate-limiting and robots.txt (same as fetch_ocr).
    urllib raises HTTPError (subclass of URLError) for non-2xx responses,
    so no explicit status-code check is needed.
    """
    try:
        from leizilla.wayback import to_raw_url

        url = to_raw_url(url)
        req = urllib.request.Request(url)
        req.add_header("User-Agent", _USER_AGENT)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")  # type: ignore[no-any-return]
    except (urllib.error.URLError, OSError, ValueError):
        return None


def fetch_ia_html(ia_id: str, timeout: int = 30) -> Optional[str]:
    """Fetch HTML from IA raw item (for HTML sources like Planalto, M2.7+).

    IA stores HTML content-addressed as {hash}.html inside the range item, mapped
    via the (ente, fonte) index (ADR-0010). Delegates to fetch_html for uniform
    error handling. A None URL means the index/source_key isn't published yet.
    """
    url = resolve_raw_url(ia_id, ".html", timeout=timeout)
    if url is None:
        return None
    return fetch_html(url, timeout=timeout)


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Extract JSON from LLM response, handling wrapped or embedded JSON.

    Uses JSONDecoder.raw_decode to scan for object start positions — avoids
    the ReDoS risk of greedy regex on untrusted LLM output with nested braces.
    """
    text = text.strip()
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for i, char in enumerate(text):
        if char == "{":
            try:
                obj, _ = decoder.raw_decode(text, i)
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                continue
    return None


def required_env_for(model: str) -> Optional[Tuple[str, ...]]:
    """Env vars aceitas para o provider do modelo, ou None se não mapeado."""
    for prefixes, env_vars in _PROVIDER_ENV_VARS:
        if any(model.startswith(p) for p in prefixes):
            return env_vars
    return None


def _key_present(env_var: str) -> bool:
    """True se a chave está disponível (via config ou ambiente), sem ler o valor."""
    if env_var in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        return bool(config.GEMINI_API_KEY or os.getenv(env_var))
    return bool(getattr(config, env_var, None) or os.getenv(env_var))


def default_model() -> str:
    """Modelo default: LLM_MODEL > chave Anthropic > chave Gemini (RFC-0006 §2).

    LLM_MODEL é normalizado (strip) antes do teste de truthiness — um valor
    só-espaço deve cair para o modo auto, não ser tratado como um id de
    modelo válido (mesma normalização de doctor.check_llm_key).
    """
    llm_model = (config.LLM_MODEL or "").strip()
    if llm_model:
        return llm_model
    if config.ANTHROPIC_API_KEY:
        return _HAIKU
    if config.GEMINI_API_KEY:
        return _GEMINI_FLASH
    raise RuntimeError(
        "Nenhuma chave LLM configurada — defina GEMINI_API_KEY (ou GOOGLE_API_KEY), "
        "ANTHROPIC_API_KEY ou OPENAI_API_KEY; opcionalmente LLM_MODEL para escolher "
        "o modelo (RFC-0006)"
    )


def _is_well_formed(xml_str: str) -> bool:
    """Check XML well-formedness using stdlib parser."""
    if not isinstance(xml_str, str):
        return False
    try:
        ET.fromstring(xml_str)
        return True
    except ET.ParseError:
        return False


def parse_law(
    ocr_text: str,
    ia_id: str,
    ente: str,
    model: Optional[str] = None,
    input_type: str = "ocr",
) -> Optional[ParseResult]:
    """Parse law text → Leizilla XML via LLM (LiteLLM, RFC-0006).

    Args:
        ocr_text: Source text — OCR text from IA (_djvu.txt) or raw HTML.
        ia_id: IA raw item ID (for ocr) or source identifier (for html).
        ente: Federative entity code (ro, sp, federal, …).
        model: LiteLLM model id (e.g. "gemini/gemini-2.5-flash",
            "claude-haiku-4-5"). None → LLM_MODEL ou auto pela chave disponível.
        input_type: "ocr" (default) or "html". Adjusts prompt and char limit.

    Returns None when confidence < _MIN_CONFIDENCE or output is malformed.
    Raises RuntimeError when no LLM key is configured for the chosen model
    (fail-fast: não queima um batch inteiro por falta de credencial).
    """
    if model is None:
        model = default_model()
    required = required_env_for(model)
    if required is not None and not any(_key_present(v) for v in required):
        raise RuntimeError(f"{' ou '.join(required)} not configured (modelo {model})")

    if input_type not in ("ocr", "html"):
        raise ValueError(f"input_type deve ser 'ocr' ou 'html', got {input_type!r}")

    if input_type == "html":
        char_limit = _HTML_CHAR_LIMIT
        input_intro = _SYSTEM_INTRO_HTML
        user_prefix = f"Parse this law HTML page (ente={ente}, url={ia_id})"
    else:
        char_limit = _OCR_CHAR_LIMIT
        input_intro = _SYSTEM_INTRO_OCR
        user_prefix = f"Parse this law OCR text (ente={ente}, raw-id={ia_id})"

    today = date.today().isoformat()
    ente_name = _ENTE_URN.get(ente, ente)
    system = _SYSTEM.format(
        input_intro=input_intro, today=today, ia_id=ia_id, ente_name=ente_name
    )

    # Import lazy: litellm é pesado e não deve atrasar comandos que não parseiam.
    import litellm

    litellm.drop_params = True  # descarta cache_control em providers sem suporte
    response = litellm.completion(
        model=model,
        max_tokens=4096,
        messages=[
            {
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": system,
                        # Prompt caching (Anthropic): no content block, nunca no
                        # root da mensagem — a objeção que fechou a PR #59.
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            },
            {
                "role": "user",
                "content": f"{user_prefix}:\n\n{ocr_text[:char_limit]}",
            },
        ],
    )

    raw = (response.choices[0].message.content or "") if response.choices else ""
    result = _extract_json(raw)
    if result is None:
        logger.warning("%s: LLM response has no extractable JSON: %r", ia_id, raw[:300])
        return None

    try:
        confidence = float(result.get("confidence", 0.0))
    except (TypeError, ValueError):
        logger.warning(
            "%s: non-numeric confidence value: %r", ia_id, result.get("confidence")
        )
        return None
    if not math.isfinite(confidence) or confidence < _MIN_CONFIDENCE:
        logger.warning(
            "%s: confidence %.2f below threshold %.2f — reason: %s",
            ia_id,
            confidence,
            _MIN_CONFIDENCE,
            result.get("error", "(LLM não informou motivo)"),
        )
        return None

    xml = result.get("xml", "")
    if not xml or not _is_well_formed(xml):
        logger.warning(
            "%s: confidence %.2f mas xml ausente/malformado", ia_id, confidence
        )
        return None

    tipo = result.get("tipo")
    numero = result.get("numero")
    ano = result.get("ano")
    if not tipo or numero is None or not ano:
        logger.warning(
            "%s: confidence %.2f mas campos obrigatórios ausentes "
            "(tipo=%r numero=%r ano=%r)",
            ia_id,
            confidence,
            tipo,
            numero,
            ano,
        )
        return None
    numero_str = str(numero).strip()
    if not numero_str.isdigit():
        logger.warning("%s: numero não numérico: %r", ia_id, numero)
        return None
    try:
        ano = int(ano)
    except (TypeError, ValueError):
        logger.warning("%s: ano inválido: %r", ia_id, result.get("ano"))
        return None
    ia_id_parsed = f"leizilla-{ente}-{tipo}-{numero_str.zfill(5)}-{ano}"

    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "prompt_tokens", 0) or 0
    output_tokens = getattr(usage, "completion_tokens", 0) or 0

    parsed_meta: Dict[str, Any] = {
        "leizilla_meta_version": "0.1",
        "ia_id_raw": ia_id,
        "ia_id_parsed": ia_id_parsed,
        "ente": ente,
        "tipo": tipo,
        "parse_method": f"{model}+{input_type}",
        "confianca_parse_global": confidence,
        "parse_timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "fontes_consultadas": [ia_id],
        "tem_divergencia": False,
        "num_divergencias": 0,
    }

    return ParseResult(
        xml=xml,
        parsed_meta=parsed_meta,
        confidence=confidence,
        ia_id_parsed=ia_id_parsed,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
