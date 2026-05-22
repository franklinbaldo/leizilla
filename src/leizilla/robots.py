"""Verificação de robots.txt — rejeição é permanente (ADR-0008, princípio #10).

Cache em memória por processo (lru_cache). robots.txt é lido uma vez por host.
Fallback fail-open: ausência de robots.txt = acesso permitido.
"""

import urllib.parse
import urllib.robotparser
from functools import lru_cache
from typing import Optional

_LEIZILLA_AGENT = "leizilla"


@lru_cache(maxsize=512)
def _load_robots(robots_url: str) -> Optional[urllib.robotparser.RobotFileParser]:
    """Carrega e parseia robots.txt de robots_url. Cached por URL."""
    rp = urllib.robotparser.RobotFileParser(robots_url)
    try:
        rp.read()
        return rp
    except Exception:
        return None  # sem robots.txt → fail-open


def is_allowed(url: str) -> bool:
    """Retorna True se leizilla-crawler pode acessar url.

    False é permanente — não tente novamente essa URL (ADR-0008).
    URL malformada retorna False.
    """
    parsed = urllib.parse.urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return False
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    parser = _load_robots(robots_url)
    if parser is None:
        return True  # fail-open: sem robots.txt = permitido
    return bool(parser.can_fetch(_LEIZILLA_AGENT, url))
