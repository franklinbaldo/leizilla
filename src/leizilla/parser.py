"""OCR fetch + LLM parse → Leizilla XML v0.1 (M3 pipeline stage).

Etapa 2 do pipeline:
  raw IA item (_djvu.txt OCR) → LLM (via LiteLLM) → Leizilla XML + parsed_meta.json

Princípio load-bearing #2: OCR é responsabilidade do IA; LLM só lê _djvu.txt.
Princípio load-bearing #3: Etapa 2 pluggable; model é parâmetro.
"""

import json
import math
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional

import litellm

from leizilla import config
from leizilla.ia_utils import resolve_ia_id_to_url

_DEFAULT_MODEL = "claude-haiku-4-5"
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
- "numero": law number as string (e.g. "9999")
- "ano": year as integer
- "urn_lex": URN LEX string, or null if date cannot be determined

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
- Paths must be unique within the document
- Use lower-case with hyphens only, first char must be a-z

URN format for state laws (ente={ente_name}):
  urn:lex:br;{ente_name}:estadual:lei:YYYY-MM-DD;NUMERO
For federal laws (ente=federal):
  urn:lex:br:federal:lei:YYYY-MM-DD;NUMERO

Use vigente-em={today} unless you know a better date.
All dispositivos share the same fonte ia-id: {ia_id}

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


def fetch_ocr(
    ia_id: str, timeout: int = 30, hash_8: Optional[str] = None
) -> Optional[str]:
    """Fetch OCR text (_djvu.txt) for a raw IA item. Returns None on failure."""
    url = resolve_ia_id_to_url(ia_id, "_djvu.txt", hash_8=hash_8)
    req = urllib.request.Request(url)
    req.add_header("User-Agent", _USER_AGENT)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")  # type: ignore[no-any-return]
    except urllib.error.HTTPError as exc:
        if exc.code == 404 and not hash_8:
            try:
                from leizilla.ia_utils import (
                    parse_chave_numeric,
                    get_range_identifier,
                    discover_hash_from_manifest,
                )
                from leizilla.entes import list_slugs

                if ia_id.startswith("leizilla-raw-"):
                    content = ia_id[len("leizilla-raw-") :]
                    matched_ente = None
                    for slug in sorted(list_slugs(), key=len, reverse=True):
                        if content.startswith(f"{slug}-"):
                            matched_ente = slug
                            break
                    if matched_ente:
                        rest = content[len(matched_ente) + 1 :]
                        if "-" in rest:
                            fonte, chave = rest.split("-", 1)
                            tipo, num = parse_chave_numeric(chave)
                            if num > 0:
                                range_ia_id = get_range_identifier(
                                    matched_ente, fonte, tipo, num
                                )
                                prefix = f"{num:06d}_"
                            else:
                                range_ia_id = f"leizilla_{matched_ente.lower()}_{fonte.lower()}_fallback"
                                prefix = f"{chave.lower()}_"

                            discovered_hash = discover_hash_from_manifest(
                                range_ia_id, prefix
                            )
                            if discovered_hash:
                                retry_url = resolve_ia_id_to_url(
                                    ia_id, "_djvu.txt", hash_8=discovered_hash
                                )
                                retry_req = urllib.request.Request(retry_url)
                                retry_req.add_header("User-Agent", _USER_AGENT)
                                with urllib.request.urlopen(
                                    retry_req, timeout=timeout
                                ) as resp:
                                    return resp.read().decode("utf-8", errors="replace")
            except Exception:
                pass
        return None
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
        req = urllib.request.Request(url)
        req.add_header("User-Agent", _USER_AGENT)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")  # type: ignore[no-any-return]
    except (urllib.error.URLError, OSError, ValueError):
        return None


def fetch_ia_html(
    ia_id: str, timeout: int = 30, hash_8: Optional[str] = None
) -> Optional[str]:
    """Fetch HTML from IA raw item (for HTML sources like Planalto, M2.7+).

    IA stores HTML as {ia_id}.html alongside raw_meta.json when uploaded via
    upload_raw_html. Delegates to fetch_html for uniform error handling.
    """
    url = resolve_ia_id_to_url(ia_id, ".html", hash_8=hash_8)
    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", _USER_AGENT)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code == 404 and not hash_8:
            try:
                from leizilla.ia_utils import (
                    parse_chave_numeric,
                    get_range_identifier,
                    discover_hash_from_manifest,
                )
                from leizilla.entes import list_slugs

                if ia_id.startswith("leizilla-raw-"):
                    content = ia_id[len("leizilla-raw-") :]
                    matched_ente = None
                    for slug in sorted(list_slugs(), key=len, reverse=True):
                        if content.startswith(f"{slug}-"):
                            matched_ente = slug
                            break
                    if matched_ente:
                        rest = content[len(matched_ente) + 1 :]
                        if "-" in rest:
                            fonte, chave = rest.split("-", 1)
                            tipo, num = parse_chave_numeric(chave)
                            if num > 0:
                                range_ia_id = get_range_identifier(
                                    matched_ente, fonte, tipo, num
                                )
                                prefix = f"{num:06d}_"
                            else:
                                range_ia_id = f"leizilla_{matched_ente.lower()}_{fonte.lower()}_fallback"
                                prefix = f"{chave.lower()}_"

                            discovered_hash = discover_hash_from_manifest(
                                range_ia_id, prefix
                            )
                            if discovered_hash:
                                retry_url = resolve_ia_id_to_url(
                                    ia_id, ".html", hash_8=discovered_hash
                                )
                                return fetch_html(retry_url, timeout=timeout)
            except Exception:
                pass
        return None
    except Exception:
        return None


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
    model: str = _DEFAULT_MODEL,
    input_type: str = "ocr",
) -> Optional[ParseResult]:
    """Parse law text → Leizilla XML via LiteLLM.

    Args:
        ocr_text: Source text — OCR text from IA (_djvu.txt) or raw HTML.
        ia_id: IA raw item ID (for ocr) or source identifier (for html).
        ente: Federative entity code (ro, sp, federal, …).
        model: LiteLLM model ID (e.g. "claude-haiku-4-5", "gpt-4o-mini").
        input_type: "ocr" (default) or "html". Adjusts prompt and char limit.

    Returns None when confidence < _MIN_CONFIDENCE or output is malformed.
    Raises RuntimeError when ANTHROPIC_API_KEY is not configured.
    """
    api_key = config.ANTHROPIC_API_KEY
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")

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

    response = litellm.completion(
        model=model,
        max_tokens=4096,
        api_key=api_key,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": f"{user_prefix}:\n\n{ocr_text[:char_limit]}"},
        ],
    )

    raw = response.choices[0].message.content or ""
    result = _extract_json(raw)
    if result is None:
        return None

    try:
        confidence = float(result.get("confidence", 0.0))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(confidence) or confidence < _MIN_CONFIDENCE:
        return None

    xml = result.get("xml", "")
    if not xml or not _is_well_formed(xml):
        return None

    tipo = result.get("tipo")
    numero = result.get("numero")
    ano = result.get("ano")
    if not tipo or numero is None or not ano:
        return None
    numero_str = str(numero).strip()
    if not numero_str.isdigit():
        return None
    try:
        ano = int(ano)
    except (TypeError, ValueError):
        return None
    ia_id_parsed = f"leizilla-{ente}-{tipo}-{numero_str.zfill(5)}-{ano}"

    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "prompt_tokens", 0)
    output_tokens = getattr(usage, "completion_tokens", 0)

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
