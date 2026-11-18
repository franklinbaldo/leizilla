"""Defeitos da fonte: normas que **não fecham por defeito do arquivo oficial**.

Uma norma cuja sequência de artigos não fecha entra na fila ``nao-fecha`` do re-OCR
(ADR-0019) esperando que o OCR seja o culpado. Quando alguém leu as páginas e o texto
que falta não está em nenhuma imagem (uma folha faltando no arquivo da fonte, uma
numeração com lacuna), o re-OCR não tem o que ganhar e a norma voltaria à fila a cada
versão do motor. O arquivo ``docs/okf/defeitos-da-fonte.json`` registra esses casos, cada
um com o motivo e a evidência; é pequeno, revisado à mão e commitado.

Cada entrada vale para **os bytes que foram inspecionados** (``sha256_fonte``): uma captura
nova da mesma norma, com outro hash, volta à fila e perde a nota, porque o defeito pode ter
sido corrigido pela fonte. O que a lista faz: (a) a fila ``nao-fecha`` pula a norma;
(b) ``build-textos`` copia ``nota`` para a coluna ``defeito_fonte`` de ``textos``, que o
portal mostra na página da norma. **Não** marca a norma como fechando.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Optional

SCHEMA_VERSION = 1
DEFAULT_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "okf" / "defeitos-da-fonte.json"
)

#: Tipos de defeito aceitos (o que o arquivo oficial tem de errado).
TIPOS = frozenset({"arquivo-incompleto", "numeracao-com-lacuna", "ilegivel-na-fonte"})

_REQUIRED = (
    "texto_id",
    "sha256_fonte",
    "tipo",
    "nota",
    "motivo",
    "evidencia",
    "data",
    "verificado_por",
)


def validate_defeitos(data: Mapping[str, Any]) -> list[str]:
    """Violações do formato do arquivo (lista vazia se OK)."""
    problems: list[str] = []
    if data.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"schema_version deve ser {SCHEMA_VERSION}")
    entries = data.get("defeitos")
    if not isinstance(entries, list):
        return [*problems, "defeitos deve ser uma lista"]
    seen: set[str] = set()
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            problems.append(f"defeitos[{i}]: não é objeto")
            continue
        for key in _REQUIRED:
            value = entry.get(key)
            if not isinstance(value, str) or not value.strip():
                problems.append(f"defeitos[{i}]: campo {key!r} ausente ou vazio")
        if entry.get("tipo") not in TIPOS:
            problems.append(f"defeitos[{i}]: tipo {entry.get('tipo')!r} desconhecido")
        sha = str(entry.get("sha256_fonte") or "")
        if sha and (len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha)):
            problems.append(
                f"defeitos[{i}]: sha256_fonte não é um sha256 em minúsculas"
            )
        tid = str(entry.get("texto_id") or "")
        if tid in seen:
            problems.append(f"defeitos[{i}]: texto_id repetido ({tid})")
        seen.add(tid)
    return problems


def load_defeitos(path: Optional[Path] = None) -> dict[str, dict[str, Any]]:
    """Lê a lista como ``texto_id → entrada``.

    O arquivo padrão ausente dá lista vazia (a fila funciona sem ele); um arquivo
    existente porém malformado levanta ``ValueError``: uma lista que deixou de valer em
    silêncio faria a fila voltar a gastar OCR, e um erro de sintaxe deve aparecer.
    """
    target = path or DEFAULT_PATH
    if not target.is_file():
        if path is not None:
            raise ValueError(f"arquivo de defeitos da fonte não encontrado: {target}")
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"defeitos da fonte ilegível ({target}): {exc}") from exc
    problems = validate_defeitos(data) if isinstance(data, dict) else ["não é objeto"]
    if problems:
        raise ValueError(
            f"defeitos da fonte inválido ({target}): {'; '.join(problems)}"
        )
    return {str(e["texto_id"]): dict(e) for e in data["defeitos"]}


def defeito_de(
    row: Mapping[str, Any], defeitos: Optional[Mapping[str, Mapping[str, Any]]]
) -> Optional[Mapping[str, Any]]:
    """A entrada que vale para esta linha (mesma norma e **mesmos bytes**), ou ``None``."""
    if not defeitos:
        return None
    entry = defeitos.get(str(row.get("texto_id") or ""))
    if entry is None:
        return None
    if str(entry.get("sha256_fonte")) != str(row.get("sha256_fonte") or ""):
        return None
    return entry
