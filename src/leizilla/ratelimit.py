"""Per-host rate limiting shared by scraper.py and publisher.py (ADR-0008).

Extracted from scraper.py so publisher.py can reuse it for IA upload pacing
without an import cycle (scraper.py already imports InternetArchivePublisher
from publisher.py).
"""

import threading
import time
from typing import Callable, Dict
from urllib.parse import urlparse

_RATE_LIMIT_S = 1.0


def make_rate_limiter(min_interval: float = _RATE_LIMIT_S) -> Callable[[str], None]:
    """Rate limiter por host: garante >= min_interval entre batidas no mesmo host.

    Hosts diferentes não bloqueiam uns aos outros — permite scraping paralelo
    de múltiplas fontes (assembleia + casacivil + ...) sem serializar por fonte.

    Seguro entre threads: cada chamada reserva, sob lock, o próximo instante livre
    do host e dorme fora do lock. Assim a colheita e o pedido assíncrono de Save
    Page Now (ADR-0016) dividem **o mesmo** orçamento de ~1 req/s por host, em vez
    de cada um ter o seu.
    """
    next_slot: Dict[str, float] = {}
    lock = threading.Lock()

    def limiter(url: str) -> None:
        host = urlparse(url).hostname or ""
        with lock:
            now = time.monotonic()
            # Primeira batida em um host nunca espera. Usamos um sentinela explícito
            # (host ausente no dict) em vez de 0.0: o epoch de time.monotonic() é
            # arbitrário, então comparar com 0.0 poderia provocar um sleep espúrio
            # na primeira chamada (hosts distintos devem permanecer independentes).
            reserved = next_slot.get(host)
            start = now if reserved is None or reserved <= now else reserved
            next_slot[host] = start + min_interval
        if start > now:
            time.sleep(start - now)

    return limiter
