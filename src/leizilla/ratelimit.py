"""Per-host rate limiting shared by scraper.py and publisher.py (ADR-0008).

Extracted from scraper.py so publisher.py can reuse it for IA upload pacing
without an import cycle (scraper.py already imports InternetArchivePublisher
from publisher.py).
"""

import time
from typing import Callable, Dict
from urllib.parse import urlparse

_RATE_LIMIT_S = 1.0


def make_rate_limiter(min_interval: float = _RATE_LIMIT_S) -> Callable[[str], None]:
    """Rate limiter por host: garante >= min_interval entre baterias diretas no mesmo host.

    Hosts diferentes não bloqueiam uns aos outros — permite scraping paralelo
    de múltiplas fontes (assembleia + casacivil + ...) sem serializar por fonte.
    """
    last: Dict[str, float] = {}

    def limiter(url: str) -> None:
        host = urlparse(url).hostname or ""
        # Primeira batida em um host nunca espera. Usamos um sentinela explícito
        # (host ausente no dict) em vez de 0.0: o epoch de time.monotonic() é
        # arbitrário, então `monotonic() - 0.0` pode ser < min_interval logo após
        # o boot e provocar um sleep espúrio na primeira chamada (hosts distintos
        # devem permanecer independentes).
        previous = last.get(host)
        if previous is not None:
            elapsed = time.monotonic() - previous
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
        last[host] = time.monotonic()

    return limiter
