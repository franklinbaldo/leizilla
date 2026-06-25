"""Internet Archive publishing & retrieval utility functions.

Centralizes range logic, key parsing, and transparent URL resolution
between publisher.py (M4 staging) and parser.py (M2 parser pipeline).
"""

import hashlib
import re
import uuid
from typing import Optional
from leizilla.entes import list_slugs


def parse_chave_numeric(chave: str) -> tuple[str, int]:
    """Extrai o tipo e o número da chave (ex: 'lei-05120' -> ('lei', 5120)).

    Retorna o tipo em minúsculas e o número inteiro correspondente.
    """
    match = re.match(r"^([a-zA-Z-]+)-(\d+)$", chave)
    if match:
        return match.group(1).lower(), int(match.group(2))
    return "documento", 0


def get_range_bounds(num: int, range_size: int = 1000) -> tuple[int, int]:
    """Calcula os limites inferior e superior do range (ex: 5120 -> (5001, 6000)).

    Nota de Design: Limites superiores como 10000 vão expandir para 5 dígitos.
    Isso é intencional e esperado para acomodar os ranges sem perda de valor.
    """
    if num <= 0:
        return 1, range_size
    start = ((num - 1) // range_size) * range_size + 1
    end = start + range_size - 1
    return start, end


def get_range_identifier(ente: str, fonte: str, tipo: str, num: int) -> str:
    """Gera o ID do item consolidado do range (ex: 'leizilla_ro_casacivil_5001-6000').

    Utiliza underscores '_' como delimitador de seções e mantém hifens '-' livres
    para uso interno nas seções. Omitimos o tipo 'coddoc' nos identificadores de
    range por não se tratar de um tipo jurídico de documento.
    """
    start, end = get_range_bounds(num)
    ente_clean = ente.lower()
    fonte_clean = fonte.lower()
    tipo_clean = tipo.lower()

    if tipo_clean == "coddoc":
        return f"leizilla_{ente_clean}_{fonte_clean}_{start:04d}-{end:04d}"
    return f"leizilla_{ente_clean}_{fonte_clean}_{tipo_clean}_{start:04d}-{end:04d}"


def get_uuid5_hash(content: bytes) -> str:
    """Gera um hash determinístico de 8 caracteres baseado em UUIDv5 a partir dos bytes."""
    sha256 = hashlib.sha256(content).hexdigest()
    uuid_val = uuid.uuid5(uuid.NAMESPACE_DNS, sha256)
    return str(uuid_val)[:8]


def get_ia_filename(num: int, suffix: str, hash_8: Optional[str] = None) -> str:
    """Retorna o nome do arquivo padronizado para o IA.

    Os arquivos físicos são salvos com o número de 6 dígitos e o hash determinístico da versão
    (ex: 005120_a1b2c3d4.pdf, 005120_a1b2c3d4_djvu.txt, 005120_a1b2c3d4_meta.json).
    A desambiguação com hash é necessária pois o nome sem hash (ex: 005120.xml)
    é reservado para o arquivo canônico já formatado e parseado que será gerado na Etapa 2.
    """
    if hash_8:
        return f"{num:06d}_{hash_8}{suffix}"
    return f"{num:06d}{suffix}"


def discover_hash_from_manifest(range_ia_id: str, prefix: str) -> Optional[str]:
    """Tenta baixar o manifest.csv do IA para encontrar o hash da versão correspondente."""
    try:
        import urllib.request
        import csv

        url_manifest = f"https://archive.org/download/{range_ia_id}/manifest.csv"
        req = urllib.request.Request(
            url_manifest, headers={"User-Agent": "leizilla-crawler/0.1"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            lines = resp.read().decode("utf-8", errors="replace").splitlines()
            reader = csv.reader(lines)
            next(reader, None)  # cabeçalho
            for row in reader:
                if row and row[0].startswith(prefix):
                    filename_ia = row[0]
                    parts = filename_ia.split("_", 1)
                    if len(parts) == 2:
                        hash_part = parts[1].split(".", 1)[0]
                        if len(hash_part) == 8:
                            return hash_part
    except Exception:
        pass
    return None


def resolve_ia_id_to_url(ia_id: str, suffix: str, hash_8: Optional[str] = None) -> str:
    """Resolve um raw IA ID para a URL de download direto correspondente.

    Resolve de forma transparente chaves legadas e novos ranges / fallbacks:
      1. Ranges com underscores (ex: leizilla_ro_casacivil_5001-6000/005120_a1b2c3d4_djvu.txt)
      2. Itens de Fallback (ex: leizilla_ro_casacivil_fallback/chave_a1b2c3d4_djvu.txt)
      3. Itens legados externos ou per-item clássicos (sem tradução)

    Usa a lista de entes conhecidos do catálogo para garantir resolução
    determinística sem as ambiguidades de hifens em expressões regulares.
    """
    if not ia_id.startswith("leizilla-raw-"):
        return f"https://archive.org/download/{ia_id}/{ia_id}{suffix}"

    content = ia_id[len("leizilla-raw-"):]

    matched_ente = None
    for slug in sorted(list_slugs(), key=len, reverse=True):
        if content.startswith(f"{slug}-"):
            matched_ente = slug
            break

    if not matched_ente:
        return f"https://archive.org/download/{ia_id}/{ia_id}{suffix}"

    rest = content[len(matched_ente) + 1:]
    if "-" not in rest:
        return f"https://archive.org/download/{ia_id}/{ia_id}{suffix}"

    fonte, chave = rest.split("-", 1)
    tipo, num = parse_chave_numeric(chave)

    if num > 0:
        range_ia_id = get_range_identifier(matched_ente, fonte, tipo, num)

        if not hash_8:
            try:
                from leizilla.storage import DuckDBStorage
                import json as _json

                db = DuckDBStorage()
                db_id = f"{matched_ente}-{fonte}-{chave}"
                lei = db.get_lei(db_id)
                if lei and lei.get("metadados"):
                    meta = _json.loads(lei["metadados"])
                    if isinstance(meta, dict):
                        hash_8 = meta.get("hash_8")
            except Exception:
                pass

        filename = get_ia_filename(num, suffix, hash_8=hash_8)
        return f"https://archive.org/download/{range_ia_id}/{filename}"
    else:
        range_ia_id = f"leizilla_{matched_ente.lower()}_{fonte.lower()}_fallback"

        if not hash_8:
            try:
                from leizilla.storage import DuckDBStorage
                import json as _json

                db = DuckDBStorage()
                db_id = f"{matched_ente}-{fonte}-{chave}"
                lei = db.get_lei(db_id)
                if lei and lei.get("metadados"):
                    meta = _json.loads(lei["metadados"])
                    if isinstance(meta, dict):
                        hash_8 = meta.get("hash_8")
            except Exception:
                pass

        filename = f"{chave.lower()}_{hash_8}{suffix}" if hash_8 else f"{chave.lower()}{suffix}"
        return f"https://archive.org/download/{range_ia_id}/{filename}"
