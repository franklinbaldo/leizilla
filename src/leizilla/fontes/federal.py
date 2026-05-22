"""Fontes de leis federais (slug: 'federal').

Fontes mapeadas:
- planalto: Portal da Legislação — Presidência da República / Casa Civil
  HTML compilado vigente. FONTE_CANONICA para federal.
  Desbloqueado em M3.4 (parser.fetch_html).
- camara: API REST pública (60 req/min). Útil para metadados estruturados.
- senado: API REST pública. Cobre legislação federal.
- dou: Diário Oficial da União. Cross-verificação de publicação original.
"""

from typing import Any, Dict, List

FONTES = ["planalto", "camara", "senado", "dou"]
FONTE_CANONICA = "planalto"

URLS = {
    "planalto": "https://www.planalto.gov.br/ccivil_03/",
    "camara": "https://www.camara.leg.br/legislacao/",
    "senado": "https://legis.senado.leg.br/norma/",
    "dou": "https://www.in.gov.br/",
}

APIS = {
    "camara": "https://dadosabertos.camara.leg.br/api/v2/",
    "senado": "https://legis.senado.leg.br/dadosabertos/",
}

# URL templates por tipo de ato normativo no Planalto
_PLANALTO_BASE = "https://www.planalto.gov.br/ccivil_03"
_PLANALTO_URLS: Dict[str, str] = {
    "lei": f"{_PLANALTO_BASE}/leis/L{{num}}.htm",
    "lcp": f"{_PLANALTO_BASE}/leis/lcp/Lcp{{num}}.htm",
    "decreto": f"{_PLANALTO_BASE}/decreto/D{{num}}.htm",
}


def discover_planalto_laws(
    tipo: str,
    start_num: int,
    end_num: int,
) -> List[Dict[str, Any]]:
    """Gera candidatos de URL do Planalto para o range de números.

    Análogo a discover_casacivil_laws: retorna candidatos sem verificar
    existência — scrape_one_html trata 404/timeout via robots+wayback.

    Args:
        tipo: "lei", "lcp", ou "decreto"
        start_num: número inicial (inclusive)
        end_num: número final (inclusive)

    Returns:
        Lista de lei_data dicts com url_original, ente, fonte, chave, tipo.
    """
    template = _PLANALTO_URLS.get(tipo)
    if template is None:
        raise ValueError(f"tipo deve ser {list(_PLANALTO_URLS)}, got {tipo!r}")

    laws = []
    for num in range(start_num, end_num + 1):
        url = template.format(num=num)
        chave = f"{tipo}-{num:05d}"
        laws.append(
            {
                "ente": "federal",
                "fonte": "planalto",
                "chave": chave,
                "tipo": tipo,
                "numero": num,
                "url_original": url,
            }
        )
    return laws
