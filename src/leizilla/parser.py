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
import re
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

# Grammar for a validated legal "numero" (issue #127): digits, optionally
# followed by a single letter suffix for a law split/renumbered after
# promulgation (e.g. "Lei 72-A" — a distinct law from "Lei 72", never a
# rounding/formatting variant of it). Case-insensitive on input; the suffix
# is normalized to lowercase before it is used anywhere downstream (ia_id,
# URN numero segment, numero_lei column — etl.py's `_RE_URN_LEX` and
# scripts/check_schema_consistency.py mirror this same grammar in lowercase
# form). A bare `numero_str.isdigit()` gate used to reject these laws
# outright, silently dropping them at parse time.
_RE_NUMERO = re.compile(r"^\d+(?:-[A-Za-z])?$")

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
# Issue #151 item 4 flagged (but deliberately did not reject) OCR beyond this
# limit via `texto_truncado` in parsed_meta.json — raising the limit itself
# was named there as the follow-up. Confirmed live 2026-09-25 (issue #201/
# #220 investigation): leizilla-ro-lei-00004-1983's raw OCR is 12788 chars;
# at the old 8000-char limit, the LLM only ever saw ~63% of the law and
# correctly parsed just what it received — 3 dispositivos instead of the
# 20 in the previously published (pre-regression) version, silently
# shrinking the released dataset by 17 rows. 24000 covers that document
# (and the free-tier model's real context budget) with margin; genuinely
# longer OCR still gets flagged via `texto_truncado` rather than rejected.
_OCR_CHAR_LIMIT = 24000
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
- "numero": law number as string — digits, optionally with a single letter
  suffix when the law was split/renumbered after promulgation (e.g. "9999"
  or "72-a"). Use the letter EXACTLY as printed in the source but lowercase
  it here; do NOT drop the suffix — "72-a" and "72" are different laws.
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
- Every N is a plain arabic ordinal (1, 2, 3, ...), even when the source
  prints the inciso/item as a roman numeral (I, II, III, IV...) or an
  ordinal word — convert it to the arabic position. Never copy a roman
  numeral, an uppercase letter, or anything outside [a-z0-9-] into a path
  segment; the only place a letter belongs in an identifier is the law's
  own "numero" suffix (e.g. "72-a"), never a dispositivo path.
- Paths MUST be unique within the document. Before you output, verify no two
  <dispositivo> share the same path. If the source appears to repeat an
  article/inciso number (OCR duplication, ambiguous renumbering), do NOT pick
  one occurrence and silently drop the other — that discards normative text.
  If the repeated occurrences carry the same content, merge them into a
  single <dispositivo> keeping the full text. If they conflict and cannot be
  safely disambiguated, fold the ambiguous text into the enclosing
  dispositivo's path as running text instead of guessing a split — or, if
  even that is unsafe, set "confidence" below 0.5 and explain the ambiguity
  in "error" rather than emitting a document that silently lost text.

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
- YYYY-MM-DD is the date of the ACT ITSELF — signature/promulgation date, not
  the publication date (LexML Parte 2 §10.1 treats publication as a separate
  event from the norm's representative date). Read it from the closing
  formula ("Palácio…, em DD de MÊS de AAAA") or an equivalent signature
  dateline. Do NOT use a "Publicada no D.O.E. de…" notice for this date —
  that is the publication date, and using it here would produce a different
  URN for the same norm depending on which notice the source happens to
  carry. Use a year-only date (just YYYY) when the day/month of the act's own
  date are missing. Do NOT substitute today's date into the URN.
- NUMERO is the same value as the "numero" field: digits, optionally with a
  lowercase "-x" suffix (e.g. "9999" or "72-a"). Never strip the suffix.
- If "urn_lex" is null (no date found at all), OMIT the urn-lex attribute
  from <lei> entirely — do not write the literal text "null", an empty
  string, or any placeholder. Downstream tooling recovers identity from
  the law's own number/year when urn-lex is absent; a literal "null"
  string is invalid and gets the whole document rejected.

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


def _get_text(url: str, timeout: int) -> Optional[str]:
    req = urllib.request.Request(url)
    req.add_header("User-Agent", _USER_AGENT)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")  # type: ignore[no-any-return]
    except Exception:
        return None


def _strip_name_prefix(url: str) -> Optional[str]:
    """Drop a ``{tipo}-{numero}`` filename prefix from a resolved raw URL.

    ``ia_utils.raw_filename`` names current raw files ``{name_prefix}_{uuid5}
    {suffix}`` (ADR-0011), but a handful of early captures (issue #201) only
    ever got an IA-derived product (``_djvu.txt``, ``.html``, …) under their
    original, unprefixed upload name ``{uuid5}{suffix}`` — IA's derive queue
    ran once, against the first filename an identical-content upload used, and
    never re-ran for the later prefixed duplicate. Returns None when the
    filename carries no such prefix to strip.
    """
    base, _, filename = url.rpartition("/")
    prefix, sep, rest = filename.partition("_")
    if not sep or not re.match(r"^[a-z][a-z0-9-]*-\d+(-[a-z])?$", prefix):
        return None
    return f"{base}/{rest}"


def fetch_ocr(ia_id: str, timeout: int = 30) -> Optional[str]:
    """Fetch OCR text (_djvu.txt) for a raw IA item. Returns None on failure.

    Resolution is content-addressed (ADR-0010): the raw_id is mapped through the
    (ente, fonte) index to the current capture's content hash. A None URL means
    the index/source_key isn't published yet — treated as "OCR not available".
    """
    url = resolve_raw_url(ia_id, "_djvu.txt", timeout=timeout)
    if url is None:
        return None
    text = _get_text(url, timeout)
    if text is not None:
        return text
    fallback_url = _strip_name_prefix(url)
    if fallback_url is None:
        return None
    return _get_text(fallback_url, timeout)


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
    html = fetch_html(url, timeout=timeout)
    if html is not None:
        return html
    fallback_url = _strip_name_prefix(url)
    if fallback_url is None:
        return None
    return fetch_html(fallback_url, timeout=timeout)


def _try_parse_json_object(text: str) -> Optional[Dict[str, Any]]:
    """Try direct parse, then scan for embedded '{' start positions.

    Uses JSONDecoder.raw_decode to scan for object start positions — avoids
    the ReDoS risk of greedy regex on untrusted LLM output with nested braces.
    """
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


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Extract JSON from LLM response, handling wrapped or embedded JSON.

    Some models over-escape quotes inside a string field (e.g. a `"xml"`
    value containing `\\"` where plain `\"` was meant), which prematurely
    terminates the JSON string and breaks parsing (issue #201/dataset-
    release-integrity, item 4). When the direct parse fails, retry once
    with that one extra backslash collapsed before giving up.
    """
    text = text.strip()
    result = _try_parse_json_object(text)
    if result is not None:
        return result
    return _try_parse_json_object(text.replace('\\\\"', '\\"'))


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


_LEI_NS = "{https://leizilla.org/lei/0.1}"

# Strict roman numeral (1-3999, standard subtractive notation) — used only to
# recognize a `path` segment worth converting, never to accept malformed
# forms like "IIII".
_ROMAN_NUMERAL_RE = re.compile(
    r"^M{0,4}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$"
)
_ROMAN_VALUES = (
    (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
    (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
    (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
)  # fmt: skip
_PATH_ATTR_RE = re.compile(r'(path=")([^"]+)(")')


def _roman_to_arabic(token: str) -> Optional[int]:
    """Strict roman-numeral -> int, or None if `token` isn't one (1-3999)."""
    if not token or not _ROMAN_NUMERAL_RE.match(token):
        return None
    value, remaining = 0, token
    for arabic, roman in _ROMAN_VALUES:
        while remaining.startswith(roman):
            value += arabic
            remaining = remaining[len(roman) :]
    return value


def _normalize_roman_numeral_paths(xml: str) -> str:
    """Convert an uppercase-roman-numeral `-`-segment in any `path="..."`
    attribute to plain arabic (issue #201/#118 XSD gate: `DispositivoPath`
    only accepts `[a-z][a-z0-9-]*`).

    A model that ignores the prompt's "always arabic, never roman" rule
    (found live on item 4's reparse: `art-1-inc-III`) otherwise produces a
    well-formed, high-confidence XML that fails the release-boundary XSD
    gate outright. Scoped to `path` attribute values only — never touches
    roman numerals appearing in actual law prose (`<texto>` content).
    """

    def _fix_value(match: "re.Match[str]") -> str:
        segments = match.group(2).split("-")
        fixed = [
            str(arabic) if (arabic := _roman_to_arabic(seg)) is not None else seg
            for seg in segments
        ]
        return match.group(1) + "-".join(fixed) + match.group(3)

    return _PATH_ATTR_RE.sub(_fix_value, xml)


# Matches urn-lex="null" (any case, single or double quotes) — never a real
# URN, which always starts "urn:lex:br".
_NULL_URN_LEX_RE = re.compile(r'\burn-lex\s*=\s*(["\'])null\1', re.IGNORECASE)


def _strip_null_urn_lex(xml: str) -> str:
    """Drop a literal `urn-lex="null"` attribute (issue #201: item 13's
    reparse) rather than shipping it.

    The prompt already tells the model to OMIT the attribute entirely when
    no act date was found, and explains why: the XSD's urn-lex pattern
    requires "urn:lex:br...", so the literal string "null" fails validation
    and the whole document gets rejected at the release-boundary gate. Same
    class of issue as `_normalize_roman_numeral_paths` — a model ignoring an
    explicit prompt rule isn't something a stronger prompt can guarantee
    against, so this is the deterministic safety net. Downstream (etl.py's
    lei_id fallback) already knows how to recover identity from the parsed
    tipo/numero/ano fields when urn-lex is absent.
    """
    return _NULL_URN_LEX_RE.sub("", xml)


def _find_provenance_mismatch(root: ET.Element, ia_id: str) -> Optional[str]:
    """Check every <versao> carries exactly one <fonte ia-id="{ia_id}"/>.

    The XSD itself allows multiple <fonte> per <versao> (future multi-witness
    reconciliation) and only validates the ia-id's generic format, so a model
    that hallucinates an extra source or a different well-formed raw id would
    otherwise pass unnoticed. This narrower single-source invariant is what
    the prompt promises for LLM-parsed output specifically, so it is enforced
    here rather than in the XSD. Returns a reason string on mismatch, else
    None.
    """
    for versao in root.iter(f"{_LEI_NS}versao"):
        fontes = versao.findall(f"{_LEI_NS}fonte")
        if len(fontes) != 1:
            return f"versao com {len(fontes)} <fonte> (esperado exatamente 1)"
        fonte_id = fontes[0].get("ia-id")
        if fonte_id != ia_id:
            return f"fonte ia-id={fonte_id!r} != ia_id esperado {ia_id!r}"
    return None


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

    litellm.drop_params = True  # descarta params não suportados no provider

    system_block: Dict[str, Any] = {"type": "text", "text": system}
    if model.startswith(("claude", "anthropic/")):
        # Prompt caching (Anthropic only): no content block, nunca no root da
        # mensagem — a objeção que fechou a PR #59. `litellm.drop_params`
        # descarta params inválidos, mas não protege daqui: para Gemini,
        # litellm traduz `cache_control` numa cachedContent explícita em vez
        # de ignorá-la, e o free tier tem
        # TotalCachedContentStorageTokensPerModelFreeTier=0 — todo parse via
        # Gemini falhava com 429 RESOURCE_EXHAUSTED antes desta guarda
        # (achado ao investigar a issue #201/#205).
        system_block["cache_control"] = {"type": "ephemeral"}

    completion_kwargs: Dict[str, Any] = {}
    if model.startswith("gemini/"):
        # Gemini 2.5 Flash "thinking" tokens count against max_tokens, so on
        # this structured-extraction task they were consuming most of the
        # 4096-token budget before any visible output — item 4's reparse hit
        # finish_reason="length" with only 422 chars of JSON emitted (issue
        # #201/#196, run 36086040197, diagnosed via PR #215's logging).
        # reasoning_effort="disable" maps to thinkingBudget=0 in litellm,
        # freeing the whole budget for the actual JSON/XML response.
        completion_kwargs["reasoning_effort"] = "disable"

    response = litellm.completion(
        model=model,
        # Raised alongside _OCR_CHAR_LIMIT (24000 chars, ~6-8k tokens of
        # input): the previous 4096-token output budget was sized for the
        # old 8000-char input ceiling. A larger input with the same output
        # cap would just move the truncation from the input side to the
        # output side instead of fixing it.
        max_tokens=16000,
        **completion_kwargs,
        messages=[
            {
                "role": "system",
                "content": [system_block],
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
        finish_reason = (
            getattr(response.choices[0], "finish_reason", None)
            if response.choices
            else None
        )
        # Logs both ends of the response (not just the head) since a
        # max_tokens truncation — the response hitting the 4096-token cap
        # mid-XML, never closing its JSON string/object — only shows up at
        # the tail, and finish_reason == "length" confirms it outright.
        logger.warning(
            "%s: LLM response has no extractable JSON (finish_reason=%s, len=%d): "
            "head=%r tail=%r",
            ia_id,
            finish_reason,
            len(raw),
            raw[:300],
            raw[-300:],
        )
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

    xml = _normalize_roman_numeral_paths(xml)
    xml = _strip_null_urn_lex(xml)

    provenance_error = _find_provenance_mismatch(ET.fromstring(xml), ia_id)
    if provenance_error:
        logger.warning(
            "%s: confidence %.2f mas proveniência inválida: %s",
            ia_id,
            confidence,
            provenance_error,
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
    numero_match = _RE_NUMERO.match(numero_str)
    if not numero_match:
        logger.warning(
            "%s: numero fora do formato esperado (dígitos, opcionalmente "
            "'-' + uma letra): %r",
            ia_id,
            numero,
        )
        return None
    try:
        ano = int(ano)
    except (TypeError, ValueError):
        logger.warning("%s: ano inválido: %r", ia_id, result.get("ano"))
        return None
    # Zero-pad the digits (SCHEMA.md §1.3/§5.3); keep the letter suffix
    # attached, lowercased, so "72-A" and "72" never collide downstream
    # ("leizilla-ro-lei-00072-a-1999" vs "leizilla-ro-lei-00072-1999").
    numero_digits, _, numero_suffix = numero_str.partition("-")
    numero_id = numero_digits.zfill(5) + (
        f"-{numero_suffix.lower()}" if numero_suffix else ""
    )
    ia_id_parsed = f"leizilla-{ente}-{tipo}-{numero_id}-{ano}"

    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "prompt_tokens", 0) or 0
    output_tokens = getattr(usage, "completion_tokens", 0) or 0

    texto_truncado = len(ocr_text) > char_limit

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
        "texto_truncado": texto_truncado,
        "tamanho_texto_original": len(ocr_text),
    }

    return ParseResult(
        xml=xml,
        parsed_meta=parsed_meta,
        confidence=confidence,
        ia_id_parsed=ia_id_parsed,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
