"""ETL: Leizilla XML v0.1 → Parquet v0.1 (tabela versoes, §3.1 SCHEMA.md)."""

from __future__ import annotations

import datetime
import hashlib
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Optional

import duckdb

NS = "https://leizilla.org/lei/0.1"

# Token map — mirrored from check_schema_consistency.py (§4.2 SCHEMA.md).
# Single source of truth for path → tipo mapping.
_NORMATIVO_TOKENS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^titulo-lei$"), "titulo-lei"),
    (re.compile(r"^ementa$"), "ementa"),
    (re.compile(r"^preambulo$"), "preambulo"),
    (re.compile(r"^art-\d+(-[a-z])?$"), "artigo"),
    (re.compile(r"^par-(\d+|unico)$"), "paragrafo"),
    (re.compile(r"^inc-\d+$"), "inciso"),
    (re.compile(r"^ali-[a-z]$"), "alinea"),
    (re.compile(r"^item-\d+$"), "item"),
    (re.compile(r"^anexo-\d+$"), "anexo"),
    (re.compile(r"^disp-transitoria-\d+$"), "disposicao-transitoria"),
    (re.compile(r"^disp-final-\d+$"), "disposicao-final"),
]

_ORGANIZACIONAL_TOKENS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^liv-\d+$"), "livro"),
    (re.compile(r"^parte-\d+$"), "parte"),
    (re.compile(r"^tit-\d+$"), "titulo"),
    (re.compile(r"^cap-\d+$"), "capitulo"),
    (re.compile(r"^sec-\d+$"), "secao"),
    (re.compile(r"^subsec-\d+$"), "subsecao"),
]

_ORGANIZACIONAL_TIPOS = {t for _, t in _ORGANIZACIONAL_TOKENS}

_RE_URN_LEX = re.compile(
    r"^urn:lex:br"
    r"(?P<locais>(;[a-z][a-z0-9.]*)*)"
    r":(?P<autoridade>[a-z][a-z0-9.]*(;[a-z][a-z0-9.]*)*)"
    r":(?P<tipo>[a-z][a-z0-9.]*)"
    r":(?P<data>\d{4}(-\d{2}-\d{2})?)"
    r"(;(?P<numero>[a-z0-9.\-]+))?"
    r"(?P<paths>(![a-z0-9._\-]+)*)$"
)


def path_to_tipo(path: str) -> Optional[str]:
    """Return dispositivo tipo for a path, or None if unrecognized (§4.2)."""
    if not path:
        return None
    for pat, tipo in _NORMATIVO_TOKENS + _ORGANIZACIONAL_TOKENS:
        if pat.match(path):
            return tipo
    # Composite path walk (e.g. art-5-par-2-inc-3, tit-2-cap-1)
    parts = path.split("-")
    i = 0
    last_tipo: Optional[str] = None
    composite_class: Optional[str] = None
    while i < len(parts):
        matched = False
        for take in (3, 2):
            if i + take > len(parts):
                continue
            candidate = "-".join(parts[i : i + take])
            for pat, tipo in _NORMATIVO_TOKENS + _ORGANIZACIONAL_TOKENS:
                if pat.match(candidate):
                    this_class = (
                        "organizacional" if tipo in _ORGANIZACIONAL_TIPOS else "normativo"
                    )
                    if composite_class is not None and this_class != composite_class:
                        return None  # mixed-class composite — invalid
                    composite_class = this_class
                    last_tipo = tipo
                    i += take
                    matched = True
                    break
            if matched:
                break
        if not matched:
            return None
    return last_tipo


def _parse_date(s: Optional[str]) -> Optional[datetime.date]:
    if not s:
        return None
    try:
        return datetime.date.fromisoformat(s)
    except ValueError:
        return None


def _extract_data_publicacao(urn_lex: Optional[str]) -> Optional[datetime.date]:
    if not urn_lex:
        return None
    m = _RE_URN_LEX.match(urn_lex)
    if not m:
        return None
    data_str = m.group("data") or ""
    if len(data_str) == 4:  # year-only URN — no precise date anchor
        return None
    return _parse_date(data_str)


def _parse_lei_fields(
    lei_id: str, urn_lex: Optional[str]
) -> tuple[str, Optional[str], int]:
    """Return (tipo_lei, numero_lei, ano_lei). URN-primary, lei_id as fallback."""
    if urn_lex:
        m = _RE_URN_LEX.match(urn_lex)
        if m:
            tipo = m.group("tipo")
            numero = m.group("numero")
            data = m.group("data") or ""
            ano = int(data[:4]) if len(data) >= 4 else 0
            return tipo, numero, ano
    # Heuristic fallback: leizilla-{ente}-{tipo}-{numero}-{ano}
    parts = lei_id.split("-")
    if len(parts) >= 5 and parts[0] == "leizilla":
        try:
            ano_s, num_s, tipo_s = parts[-1], parts[-2], parts[-3]
            if len(ano_s) == 4 and ano_s.isdigit() and num_s.isdigit():
                return tipo_s, num_s.lstrip("0") or "0", int(ano_s)
        except (IndexError, ValueError):
            pass
    return "desconhecido", None, 0


def _normalize_texto(texto: str) -> str:
    normalized = unicodedata.normalize("NFC", texto)
    return re.sub(r"\s+", " ", normalized).strip()


def _hash_texto(texto: str) -> str:
    return "sha256:" + hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _iter_dispositivos(parent: ET.Element) -> list[ET.Element]:
    return parent.findall(f"{{{NS}}}dispositivo")


def xml_to_rows(xml_content: str, lei_id: str, ente: str) -> list[dict[str, Any]]:
    """Parse Leizilla XML v0.1 into versoes rows per SCHEMA.md §3.1."""
    root = ET.fromstring(xml_content)

    urn_lex = root.get("urn-lex")
    vigente_em = _parse_date(root.get("vigente-em"))
    data_publicacao = _extract_data_publicacao(urn_lex)
    tipo_lei, numero_lei, ano_lei = _parse_lei_fields(lei_id, urn_lex)

    rev_root = root.find(f"{{{NS}}}revogacao")
    lei_cols: dict[str, Any] = {
        "lei_id": lei_id,
        "ente": ente,
        "tipo_lei": tipo_lei,
        "numero_lei": numero_lei,
        "ano_lei": ano_lei,
        "data_publicacao": data_publicacao,
        "urn_lex_lei": urn_lex,
        "vigente_em": vigente_em,
        "lei_revogada": rev_root is not None,
        "lei_revogada_em": _parse_date(rev_root.get("em")) if rev_root is not None else None,
        "lei_revogada_por": rev_root.get("por") if rev_root is not None else None,
        "lei_revogada_tipo": rev_root.get("tipo") if rev_root is not None else None,
    }

    rows: list[dict[str, Any]] = []

    def _process(
        parent_elem: ET.Element,
        parent_path: Optional[str],
        ancestor_em: Optional[datetime.date],
    ) -> None:
        for idx, disp in enumerate(_iter_dispositivos(parent_elem)):
            path = disp.get("path", "")
            tipo = path_to_tipo(path) or "desconhecido"

            rev = disp.find(f"{{{NS}}}revogacao")
            disp_rev_em = _parse_date(rev.get("em")) if rev is not None else None

            disp_cols: dict[str, Any] = {
                "dispositivo_path": path,
                "dispositivo_tipo": tipo,
                "dispositivo_ordem": idx,
                "dispositivo_parent_path": parent_path,
                "dispositivo_revogado": rev is not None,
                "dispositivo_revogado_em": disp_rev_em,
                "dispositivo_revogado_por": rev.get("por") if rev is not None else None,
                "dispositivo_revogado_tipo": rev.get("tipo") if rev is not None else None,
                "urn_dispositivo": f"{urn_lex}!{path}" if urn_lex else None,
            }

            versoes_elems = disp.findall(f"{{{NS}}}versao")

            # Resolve `em` for each versao (explicit or inherited)
            versao_ems: list[Optional[datetime.date]] = []
            for v in versoes_elems:
                em_s = v.get("em")
                versao_ems.append(
                    _parse_date(em_s) if em_s else (ancestor_em or data_publicacao)
                )

            for v_idx, versao in enumerate(versoes_elems):
                em = versao_ems[v_idx]
                alterado_por = versao.get("alterado-por")

                # Infer `ate` — next versao start, dispositivo revogacao,
                # lei-level revogacao total, or None (still vigente).
                if v_idx + 1 < len(versoes_elems):
                    ate: Optional[datetime.date] = versao_ems[v_idx + 1]
                elif disp_rev_em is not None:
                    ate = disp_rev_em
                elif lei_cols["lei_revogada_em"] is not None:
                    ate = lei_cols["lei_revogada_em"]
                else:
                    ate = None

                inicio_elem = versao.find(f"{{{NS}}}inicio")
                if inicio_elem is not None:
                    inicio_tipo = inicio_elem.get("tipo", "data-publicacao")
                elif alterado_por:
                    inicio_tipo = "texto-lei-alteradora"
                else:
                    inicio_tipo = "data-publicacao"

                texto_elem = versao.find(f"{{{NS}}}texto")
                texto = texto_elem.text if texto_elem is not None else None

                fontes_list: list[dict[str, Any]] = []
                for fonte in versao.findall(f"{{{NS}}}fonte"):
                    ia_id = fonte.get("ia-id", "")
                    div_s = fonte.get("diverge")
                    diverge = (div_s or "").strip().lower() in ("true", "1")
                    td = fonte.find(f"{{{NS}}}texto") if diverge else None
                    fontes_list.append(
                        {
                            "ia_id": ia_id,
                            "diverge": diverge,
                            "texto_divergente": td.text if td is not None else None,
                        }
                    )

                versao_id = f"{path}#{em.isoformat() if em else 'unknown'}"

                rows.append(
                    {
                        **lei_cols,
                        **disp_cols,
                        "versao_id": versao_id,
                        "em": em,
                        "ate": ate,
                        "alterado_por": alterado_por,
                        "inicio_tipo": inicio_tipo,
                        "texto": texto,
                        "texto_normalizado": _normalize_texto(texto) if texto else None,
                        "fontes": json.dumps(fontes_list, ensure_ascii=False),
                        "num_fontes": len(fontes_list),
                        "tem_divergencia": any(f["diverge"] for f in fontes_list),
                        "hash_texto": _hash_texto(texto) if texto else None,
                        "quality": None,
                    }
                )

            # Pass first versao's resolved em to children as their ancestor_em
            child_ancestor_em = versao_ems[0] if versao_ems else ancestor_em
            _process(disp, path, child_ancestor_em)

    _process(root, None, data_publicacao)
    return rows


def consolidate_xmls(
    xml_items: list[tuple[str, str, str]],
) -> list[dict[str, Any]]:
    """Convert multiple (lei_id, ente, xml_content) items to versoes rows."""
    rows: list[dict[str, Any]] = []
    for lei_id, ente, xml_content in xml_items:
        rows.extend(xml_to_rows(xml_content, lei_id, ente))
    return rows


def _json_default(obj: object) -> str:
    if isinstance(obj, datetime.date):
        return obj.isoformat()
    raise TypeError(f"not serializable: {type(obj)}")


def write_parquet(rows: list[dict[str, Any]], output_path: Path) -> None:
    """Write versoes rows to Parquet (SNAPPY) via DuckDB read_json_auto."""
    import os
    import tempfile

    if not rows:
        raise ValueError("rows is empty — nothing to write")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".ndjson")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, default=_json_default, ensure_ascii=False) + "\n")

        conn = duckdb.connect()
        try:
            # Use parameterized ? to avoid SQL string interpolation for file paths
            conn.execute("CREATE TABLE _rows AS SELECT * FROM read_json_auto(?)", [tmp_path])
            conn.table("_rows").write_parquet(str(output_path), compression="snappy")
        finally:
            conn.close()
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
