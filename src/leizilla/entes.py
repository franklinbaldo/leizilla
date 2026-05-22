"""Catálogo de entes federativos suportados pelo Leizilla.

Slug: kebab-case, {uf} para estados, 'federal' para União,
'{uf}-{municipio}' para municípios (ex: 'ro-porto-velho').
"""

from dataclasses import dataclass
from typing import List


@dataclass
class Ente:
    slug: str
    nome: str
    tipo: str  # 'federal' | 'estadual' | 'municipal'
    uf: str  # ISO 3166-2:BR sem BR-, ex: 'RO'. 'BR' para federal.


ENTES: List[Ente] = [
    Ente("federal", "União Federal", "federal", "BR"),
    # Estados + DF
    Ente("ac", "Acre", "estadual", "AC"),
    Ente("al", "Alagoas", "estadual", "AL"),
    Ente("am", "Amazonas", "estadual", "AM"),
    Ente("ap", "Amapá", "estadual", "AP"),
    Ente("ba", "Bahia", "estadual", "BA"),
    Ente("ce", "Ceará", "estadual", "CE"),
    Ente("df", "Distrito Federal", "estadual", "DF"),
    Ente("es", "Espírito Santo", "estadual", "ES"),
    Ente("go", "Goiás", "estadual", "GO"),
    Ente("ma", "Maranhão", "estadual", "MA"),
    Ente("mg", "Minas Gerais", "estadual", "MG"),
    Ente("ms", "Mato Grosso do Sul", "estadual", "MS"),
    Ente("mt", "Mato Grosso", "estadual", "MT"),
    Ente("pa", "Pará", "estadual", "PA"),
    Ente("pb", "Paraíba", "estadual", "PB"),
    Ente("pe", "Pernambuco", "estadual", "PE"),
    Ente("pi", "Piauí", "estadual", "PI"),
    Ente("pr", "Paraná", "estadual", "PR"),
    Ente("rj", "Rio de Janeiro", "estadual", "RJ"),
    Ente("rn", "Rio Grande do Norte", "estadual", "RN"),
    Ente("ro", "Rondônia", "estadual", "RO"),
    Ente("rr", "Roraima", "estadual", "RR"),
    Ente("rs", "Rio Grande do Sul", "estadual", "RS"),
    Ente("sc", "Santa Catarina", "estadual", "SC"),
    Ente("se", "Sergipe", "estadual", "SE"),
    Ente("sp", "São Paulo", "estadual", "SP"),
    Ente("to", "Tocantins", "estadual", "TO"),
]

_BY_SLUG = {e.slug: e for e in ENTES}


def get_ente(slug: str) -> Ente:
    """Retorna Ente pelo slug. Lança KeyError se não encontrado."""
    return _BY_SLUG[slug]


def list_slugs() -> List[str]:
    return [e.slug for e in ENTES]
