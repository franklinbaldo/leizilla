"""Index-driven discovery for ordinary federal laws published by Planalto."""

from html.parser import HTMLParser
import re
import urllib.error
import urllib.request
from typing import Callable, Optional
from urllib.parse import urljoin, urlparse

PLANALTO_ORDINARY_LAWS_INDEX = (
    "https://www.planalto.gov.br/ccivil_03/leis/_lei-ordinaria.htm"
)
_INDEX_LABEL_RE = re.compile(
    r"^(?:\d{4}|\d{4}\s+a\s+\d{4}|Anteriores a 1960)$",
    re.IGNORECASE,
)
_LAW_BASENAME_RE = re.compile(r"^l(?P<num>\d+)\.htm$", re.IGNORECASE)
_PLANALTO_HOSTS = {"planalto.gov.br", "www.planalto.gov.br"}


class _AnchorCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.anchors: list[tuple[str, str]] = []
        self._href: Optional[str] = None
        self._text: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, Optional[str]]]
    ) -> None:
        if tag.lower() != "a" or self._href is not None:
            return
        href = next((value for key, value in attrs if key.lower() == "href"), None)
        if href:
            self._href = href
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            self.anchors.append((self._href, " ".join(self._text).strip()))
            self._href = None
            self._text = []


def _extract_anchors(html: str, base_url: str) -> list[tuple[str, str]]:
    parser = _AnchorCollector()
    parser.feed(html)
    return [(urljoin(base_url, href), text) for href, text in parser.anchors]


def fetch_planalto_html(url: str, timeout: float = 15.0) -> Optional[str]:
    req = urllib.request.Request(url, headers={"User-Agent": "leizilla-crawler/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.read().decode("latin-1", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return None


def _is_planalto_ccivil_url(url: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.scheme in {"http", "https"}
        and (parsed.hostname or "").lower() in _PLANALTO_HOSTS
        and parsed.path.lower().startswith("/ccivil_03/")
    )


def discover_ordinary_laws(
    *,
    index_url: str = PLANALTO_ORDINARY_LAWS_INDEX,
    fetch_fn: Callable[[str], Optional[str]] = fetch_planalto_html,
) -> list[dict[str, object]]:
    """Discover ordinary laws from Planalto's authoritative catalog pages."""
    try:
        master_html = fetch_fn(index_url)
    except Exception:
        master_html = None
    if not master_html:
        return []

    catalog_urls: list[str] = []
    seen_catalogs: set[str] = set()
    for url, label in _extract_anchors(master_html, index_url):
        label = " ".join(label.split())
        if not _INDEX_LABEL_RE.fullmatch(label) or not _is_planalto_ccivil_url(url):
            continue
        clean_url = url.split("#", 1)[0]
        key = clean_url.lower()
        if key not in seen_catalogs:
            seen_catalogs.add(key)
            catalog_urls.append(clean_url)

    laws: list[dict[str, object]] = []
    seen_numbers: set[int] = set()
    for catalog_url in catalog_urls:
        try:
            html = fetch_fn(catalog_url)
        except Exception:
            html = None
        if not html:
            continue

        for law_url, _label in _extract_anchors(html, catalog_url):
            if not _is_planalto_ccivil_url(law_url):
                continue
            parsed = urlparse(law_url)
            basename = parsed.path.rsplit("/", 1)[-1]
            match = _LAW_BASENAME_RE.fullmatch(basename)
            if not match:
                continue
            numero = int(match.group("num"))
            if numero in seen_numbers:
                continue
            seen_numbers.add(numero)
            clean_url = law_url.split("#", 1)[0].split("?", 1)[0]
            laws.append(
                {
                    "ente": "federal",
                    "fonte": "planalto",
                    "tipo": "lei",
                    "numero": numero,
                    "chave": f"lei-{numero:05d}",
                    "url_original": clean_url,
                }
            )
    return laws
