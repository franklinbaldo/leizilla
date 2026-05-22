"""Fontes de leis federais (slug: 'federal').

Fontes mapeadas:
- planalto: Portal da Legislação — Presidência da República / Casa Civil
  HTML compilado vigente. FONTE_CANONICA para federal.
  Desbloqueado em M3.4 (parser.fetch_html).
- camara: API REST pública (60 req/min). Útil para metadados estruturados.
- senado: API REST pública. Cobre legislação federal.
- dou: Diário Oficial da União. Cross-verificação de publicação original.
"""

import json
import urllib.error
import urllib.request
from functools import lru_cache
from typing import Any, Callable, Dict, List, Optional

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

# URL templates por tipo — usados para leis pré-2003 (números antigos)
_PLANALTO_BASE = "https://www.planalto.gov.br/ccivil_03"
_PLANALTO_LEGACY_URLS: Dict[str, str] = {
    "lei": f"{_PLANALTO_BASE}/leis/L{{num}}.htm",
    "lcp": f"{_PLANALTO_BASE}/leis/lcp/Lcp{{num}}.htm",
    "decreto": f"{_PLANALTO_BASE}/decreto/D{{num}}.htm",
}

# Prefixos de tipo no path year-scoped (subdiretório e nome de arquivo)
_PLANALTO_YEAR_SUBDIR: Dict[str, str] = {
    "lei": "lei",
    "lcp": "lei",     # LCPs ficam em /lei/, não /lcp/
    "decreto": "decreto",
}
_PLANALTO_YEAR_PREFIX: Dict[str, str] = {
    "lei": "l",
    "lcp": "lcp",
    "decreto": "d",
}

# Ranges de 4 anos usados pelo Planalto (confirmados empiricamente)
_ATO_RANGES = [
    (2003, 2006),
    (2007, 2010),
    (2011, 2014),
    (2015, 2018),
    (2019, 2022),
    (2023, 2026),
]

# Câmara API: sigla por tipo de ato
_CAMARA_SIGLA: Dict[str, str] = {
    "lei": "LEI",
    "lcp": "LCP",
    "decreto": "DEL",
}


def _ato_range_for_year(year: int) -> str:
    """Retorna o segmento de path `_ato{start}-{end}` para o ano dado."""
    for start, end in _ATO_RANGES:
        if start <= year <= end:
            return f"_ato{start}-{end}"
    raise ValueError(f"Ano {year} fora dos ranges Planalto conhecidos (2003-2026)")


def planalto_year_scoped_url(tipo: str, numero: int, year: int) -> str:
    """Constrói URL year-scoped do Planalto para lei federal pós-2002."""
    ato = _ato_range_for_year(year)
    subdir = _PLANALTO_YEAR_SUBDIR[tipo]
    prefix = _PLANALTO_YEAR_PREFIX[tipo]
    return f"{_PLANALTO_BASE}/{ato}/{year}/{subdir}/{prefix}{numero}.htm"


@lru_cache(maxsize=2048)
def _camara_year_lookup(tipo: str, numero: int) -> Optional[int]:
    """Busca o ano de publicação de um ato federal via API Câmara. Fail-open.

    Endpoint: dadosabertos.camara.leg.br/api/v2/legislacoes
    Rate limit: 60 req/min (Câmara). Cache via lru_cache por (tipo, numero).
    """
    sigla = _CAMARA_SIGLA.get(tipo)
    if sigla is None:
        return None
    url = (
        f"https://dadosabertos.camara.leg.br/api/v2/legislacoes"
        f"?siglaTipo={sigla}&numero={numero}&itens=1&formato=json"
    )
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310
            data = json.loads(resp.read().decode())
            dados = data.get("dados", [])
            if dados:
                ano = dados[0].get("ano")
                if ano is not None:
                    return int(ano)
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError):
        pass
    return None


def discover_planalto_laws(
    tipo: str,
    start_num: int,
    end_num: int,
    *,
    year_lookup_fn: Callable[[str, int], Optional[int]] = _camara_year_lookup,
) -> List[Dict[str, Any]]:
    """Gera candidatos de URL do Planalto para o range de números.

    Para números correspondentes a leis pré-2003 (ou quando o lookup de ano
    falhar), usa o padrão legado `/ccivil_03/leis/L{N}.htm`. Para pós-2002,
    usa o padrão year-scoped `/_ato{range}/{ano}/{tipo}/{prefix}{N}.htm`.

    `year_lookup_fn` é injetável para testes (padrão: Câmara API com cache).

    Args:
        tipo: "lei", "lcp", ou "decreto"
        start_num: número inicial (inclusive)
        end_num: número final (inclusive)
        year_lookup_fn: função (tipo, numero) → ano ou None; fail-open

    Returns:
        Lista de lei_data dicts com url_original, ente, fonte, chave, tipo.
    """
    if tipo not in _PLANALTO_LEGACY_URLS:
        raise ValueError(f"tipo deve ser {list(_PLANALTO_LEGACY_URLS)}, got {tipo!r}")

    legacy_template = _PLANALTO_LEGACY_URLS[tipo]
    laws = []
    for num in range(start_num, end_num + 1):
        year = year_lookup_fn(tipo, num)
        if year is not None and year >= 2003:
            try:
                url = planalto_year_scoped_url(tipo, num, year)
            except ValueError:
                url = legacy_template.format(num=num)
        else:
            url = legacy_template.format(num=num)

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
