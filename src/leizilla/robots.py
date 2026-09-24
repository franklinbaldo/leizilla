"""Verificação de robots.txt — rejeição é permanente (ADR-0008, princípio #10).

Cache em memória por processo, mas **só de desfechos confirmados**: um robots.txt
lido e parseado com sucesso (200), ou a ausência confirmada dele (404). Uma
falha de *fetch* (403/429/5xx/timeout/erro de rede) é tratada como transitória —
falha aberta só para a chamada atual, sem poluir o cache (issue #121: antes, um
403 do WAF fazia o ``RobotFileParser`` setar ``disallow_all=True`` e isso ficava
cacheado para sempre via ``lru_cache``, bloqueando o host inteiro pro resto da
vida do processo mesmo sendo um bloqueio transitório do WAF, não uma regra real
de robots.txt).
Fallback fail-open: ausência de robots.txt (ou fetch que falhou) = acesso permitido.
"""

import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from typing import Dict, Optional, Tuple

_LEIZILLA_AGENT = "leizilla-crawler"
_USER_AGENT = (
    "leizilla-crawler/0.1 (legal-indexer; https://github.com/franklinbaldo/leizilla)"
)

# Cache só de desfechos CONFIRMADOS (200 parseado, ou 404 confirmado = sem
# robots.txt). Chave: robots_url. Ausência de entrada aqui não implica
# "permitido" — significa "ainda não confirmamos", e o próximo `is_allowed`
# tenta buscar de novo (fail-open só na chamada, nunca cacheado como bloqueio).
_confirmed_cache: Dict[str, Optional[urllib.robotparser.RobotFileParser]] = {}


def _fetch_robots(
    robots_url: str,
) -> Tuple[bool, Optional[urllib.robotparser.RobotFileParser]]:
    """Busca e parseia ``robots_url``. Retorna ``(confirmado, parser)``.

    ``confirmado=True`` só quando o desfecho é um fato durável, seguro de
    cachear para sempre: um corpo 200 parseado com sucesso, ou um 404
    (confirma que não existe robots.txt — não há regras a aplicar).

    ``confirmado=False`` cobre qualquer falha de fetch que pode ser
    transitória — 401/403 (WAF), 429, 5xx, timeout, erro de DNS/rede. Nesses
    casos o parser devolvido é sempre ``None`` (fail-open para esta chamada),
    e o chamador NÃO deve cachear o resultado, para que uma tentativa
    posterior possa recuperar as regras reais.
    """
    req = urllib.request.Request(robots_url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status = getattr(resp, "status", 200)
            body = resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return True, None  # confirmado: sem robots.txt → tudo permitido
        return False, None  # 401/403/429/5xx/... → transitório, não cacheia
    except Exception:
        return False, None  # timeout/DNS/rede → transitório, não cacheia

    if status == 404:
        return True, None
    if status != 200:
        return False, None  # status inesperado → trata como transitório

    try:
        text = body.decode("utf-8", errors="replace")
    except Exception:
        return False, None

    rp = urllib.robotparser.RobotFileParser()
    rp.parse(text.splitlines())
    return True, rp


def _load_robots(robots_url: str) -> Optional[urllib.robotparser.RobotFileParser]:
    """Carrega e parseia robots.txt de robots_url.

    Cacheia apenas desfechos confirmados (ver :func:`_fetch_robots`) — uma
    falha de fetch transitória nunca fica presa no cache.
    """
    if robots_url in _confirmed_cache:
        return _confirmed_cache[robots_url]
    confirmed, parser = _fetch_robots(robots_url)
    if confirmed:
        _confirmed_cache[robots_url] = parser
    return parser


def is_allowed(url: str) -> bool:
    """Retorna True se leizilla-crawler pode acessar url.

    False é permanente — não tente novamente essa URL (ADR-0008). Só
    acontece quando um robots.txt foi de fato buscado e parseado (ou já
    estava confirmado em cache) e contém uma regra de disallow aplicável.
    URL malformada retorna False.
    """
    parsed = urllib.parse.urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return False
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    parser = _load_robots(robots_url)
    if parser is None:
        return True  # fail-open: sem robots.txt (ou fetch falhou) = permitido
    return bool(parser.can_fetch(_LEIZILLA_AGENT, url))
