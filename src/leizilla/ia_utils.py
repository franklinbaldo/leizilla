"""Internet Archive publishing & retrieval utility functions.

Centralizes range logic, key parsing, and transparent URL resolution
between publisher.py (M4 staging) and parser.py (M2 parser pipeline).
"""

import re
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


def get_ia_filename(tipo: str, num: int, suffix: str) -> str:
    """Retorna o nome do arquivo padronizado para o IA.

    Os arquivos físicos são salvos puramente pelo número de 6 dígitos
    (ex: 005120.pdf, 005120_djvu.txt, 005120_meta.json). Como o tipo de norma
    já é segregado no range identifier (que atua como uma pasta no IA),
    omitimos o tipo de norma no nome do arquivo físico para evitar redundância.
    """
    return f"{num:06d}{suffix}"


def resolve_ia_id_to_url(ia_id: str, suffix: str) -> str:
    """Resolve um raw IA ID para a URL de download direto correspondente.

    Resolve de forma transparente chaves legadas e novos ranges / fallbacks:
      1. Ranges com underscores (ex: leizilla_ro_casacivil_5001-6000/005120_djvu.txt)
      2. Itens de Fallback (ex: leizilla-raw_ro_casacivil_fallback/chave_djvu.txt)
      3. Itens legados externos ou per-item clássicos (sem tradução)

    Usa a lista de entes conhecidos do catálogo para garantir resolução
    determinística sem as ambiguidades de hifens em expressões regulares.
    """
    if not ia_id.startswith("leizilla-raw-"):
        return f"https://archive.org/download/{ia_id}/{ia_id}{suffix}"

    content = ia_id[len("leizilla-raw-") :]

    # Procura o ente de maior comprimento para casar corretamente (ex: ro-porto-velho antes de ro)
    matched_ente = None
    for slug in sorted(list_slugs(), key=len, reverse=True):
        if content.startswith(f"{slug}-"):
            matched_ente = slug
            break

    if not matched_ente:
        # Fallback de segurança se não casar com nenhum ente conhecido
        return f"https://archive.org/download/{ia_id}/{ia_id}{suffix}"

    # Extrai fonte e chave
    rest = content[len(matched_ente) + 1 :]
    if "-" not in rest:
        return f"https://archive.org/download/{ia_id}/{ia_id}{suffix}"

    fonte, chave = rest.split("-", 1)

    tipo, num = parse_chave_numeric(chave)

    if num > 0:
        range_ia_id = get_range_identifier(matched_ente, fonte, tipo, num)
        filename = get_ia_filename(tipo, num, suffix)
        return f"https://archive.org/download/{range_ia_id}/{filename}"
    else:
        # Fallback de itens não-numéricos consolidados com underscores '_'
        range_ia_id = f"leizilla-raw_{matched_ente.lower()}_{fonte.lower()}_fallback"
        return f"https://archive.org/download/{range_ia_id}/{chave.lower()}{suffix}"
