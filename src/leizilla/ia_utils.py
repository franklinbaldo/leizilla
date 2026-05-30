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


def get_range_identifier(ente: str, fonte: str, num: int) -> str:
    """Gera o ID do item consolidado do range (ex: 'leizilla-ro-casacivil-5001-6000').

    Ranges são intencionalmente heterogêneos e genéricos (sem o tipo jurídico no nome
    do item) para assegurar acoplamento robusto com chaves sequenciais da fonte antes
    do processamento de OCR e parse.
    """
    start, end = get_range_bounds(num)
    return f"leizilla-{ente.lower()}-{fonte.lower()}-{start:04d}-{end:04d}"


def resolve_ia_id_to_url(ia_id: str, suffix: str) -> str:
    """Resolve um raw IA ID para a URL de download direto correspondente.

    Resolve de forma transparente chaves legadas e novos ranges / fallbacks:
      1. Ranges numéricos (ex: leizilla-ro-casacivil-5001-6000/coddoc-05120_djvu.txt)
      2. Itens de Fallback (ex: leizilla-raw-ro-casacivil-fallback/chave_djvu.txt)
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

    # TODO: No futuro, se houver fontes com hifens em municípios (ex: assembleia-legislativa),
    # o split por "-" pode precisar ser adaptado a partir da esquerda usando uma lista
    # de fontes mapeadas, de forma análoga a entes.
    fonte, chave = rest.split("-", 1)

    tipo, num = parse_chave_numeric(chave)

    if num > 0:
        range_ia_id = get_range_identifier(matched_ente, fonte, num)
        return f"https://archive.org/download/{range_ia_id}/{chave.lower()}{suffix}"
    else:
        # Fallback de itens não-numéricos consolidados
        range_ia_id = f"leizilla-raw-{matched_ente.lower()}-{fonte.lower()}-fallback"
        return f"https://archive.org/download/{range_ia_id}/{chave.lower()}{suffix}"
