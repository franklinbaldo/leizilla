"""Verificação de robots.txt — rejeição explícita é permanente (ADR-0008).

Cache em memória por processo (lru_cache). robots.txt é lido uma vez por host.
Falhas HTTP/rede ao obter robots.txt são tratadas como indisponibilidade temporária
e portanto fail-open; somente uma regra Disallow realmente parseada bloqueia a URL.
"""

import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from functools import lru_cache
from typing import Optional

_LEIZILLA_AGENT = "leizilla-crawler"


@lru_cache(maxsize=512)
def _load_robots(robots_url: str) -> Optional[urllib.robotparser.RobotFileParser]:
    """Carrega e parseia robots.txt de robots_url. Cached por URL.

    RobotFileParser.read() converte respostas 401/403 em disallow_all. Isso torna
    uma resposta transitória de WAF indistinguível de um Disallow: / explícito e,
    como o resultado é cacheado, pode causar perda permanente de documentos.
    Fazemos o fetch explicitamente: falha de transporte/HTTP significa
    "robots indisponível" (fail-open); bloqueio só vem do conteúdo parseado.
    """
    req = urllib.request.Request(robots_url)
    req.add_header("User-Agent", _LEIZILLA_AGENT)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
        return None

    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(robots_url)
    parser.parse(text.splitlines())
    return parser


def is_allowed(url: str) -> bool:
    """Retorna True se leizilla-crawler pode acessar url.

    False representa uma proibição explícita e permanente para aquela URL
    (ADR-0008). URL malformada retorna False. Falha ao obter robots.txt é
    temporária e retorna True (fail-open).
    """
    parsed = urllib.parse.urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return False
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    parser = _load_robots(robots_url)
    if parser is None:
        return True
    return bool(parser.can_fetch(_LEIZILLA_AGENT, url))
