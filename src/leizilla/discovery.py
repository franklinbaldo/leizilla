"""Módulo de descobrimento de recursos legislativos (Discovery).

Lê manifestos declarativos por ente e popula a tabela de discovered_resources.
"""

import json
import logging
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Callable

from leizilla.storage import DuckDBStorage

logger = logging.getLogger(__name__)


class DiscoveryStrategyProtocol(Protocol):
    """Protocolo para estratégias de descoberta de recursos."""

    def __init__(self, config: Dict[str, Any], ente: str, fonte: str) -> None: ...

    def run(self) -> List[Dict[str, Any]]: ...


def parse_filename(filename: str) -> tuple[Optional[str], Optional[str]]:
    """Extrai tipo_documento e chave formatada do nome do arquivo.

    Exemplos:
      L5120.pdf    -> ("lei", "lei-05120")
      LC312.pdf    -> ("lc", "lc-00312")
      D1234.pdf    -> ("decreto", "decreto-01234")
      EC10.pdf     -> ("ec", "ec-00010")
      Res50.pdf    -> ("resolucao", "resolucao-00050")
      Port100.pdf  -> ("portaria", "portaria-00100")
      DEC1026.pdf  -> ("decreto", "decreto-01026")
      DL11.pdf     -> ("decreto-lei", "decreto-lei-00011")
    """
    # Remove extensão e limpa espaços
    name = filename.rsplit(".", 1)[0].strip().upper()
    # Ordered from longest prefix to shortest to avoid partial matches
    if name.startswith("PORT"):
        num_part = name[4:]
        if num_part.isdigit():
            return "portaria", f"portaria-{int(num_part):05d}"
    elif name.startswith("RES"):
        num_part = name[3:]
        if num_part.isdigit():
            return "resolucao", f"resolucao-{int(num_part):05d}"
    elif name.startswith("DEC"):
        num_part = name[3:]
        if num_part.isdigit():
            return "decreto", f"decreto-{int(num_part):05d}"
    elif name.startswith("LC"):
        num_part = name[2:]
        if num_part.isdigit():
            return "lc", f"lc-{int(num_part):05d}"
    elif name.startswith("EC"):
        num_part = name[2:]
        if num_part.isdigit():
            return "ec", f"ec-{int(num_part):05d}"
    elif name.startswith("DL"):
        num_part = name[2:]
        if num_part.isdigit():
            return "decreto-lei", f"decreto-lei-{int(num_part):05d}"
    elif name.startswith("L"):
        num_part = name[1:]
        if num_part.isdigit():
            return "lei", f"lei-{int(num_part):05d}"
    elif name.startswith("D"):
        num_part = name[1:]
        if num_part.isdigit():
            return "decreto", f"decreto-{int(num_part):05d}"
    return None, None


class WaybackCdxDiscovery:
    """Estratégia de descobrimento que consulta a API CDX da Wayback Machine."""

    def __init__(self, config: Dict[str, Any], ente: str, fonte: str) -> None:
        self.prefix = config["prefix"]
        # Esquema canônico (do manifesto): normalizamos as URLs descobertas para ele de
        # modo que casem com as da estratégia sequencial — discovered_resources é keyed
        # pela URL literal, então http://…/L1.pdf e https://…/L1.pdf seriam duas linhas
        # (mesma norma colhida duas vezes). O snapshot http real fica em wayback_snapshot.
        self.canonical_scheme = "https" if self.prefix.startswith("https") else "http"
        self.ente = ente
        self.fonte = fonte

    def run(self) -> List[Dict[str, Any]]:
        logger.info(f"Rodando Wayback CDX Discovery para {self.ente}/{self.fonte}...")
        # Consulta sem esquema (urlkey é SURT, scheme-agnóstico): casa capturas http E
        # https — as históricas da DITEL são http-keyed, o download ao vivo é https
        # (Codex P1). Sem isto, um prefixo só-https perderia os snapshots antigos.
        prefix_key = re.sub(r"^https?://", "", self.prefix)
        url = f"https://web.archive.org/cdx/search/cdx?url={urllib.parse.quote(prefix_key)}&matchType=prefix&output=json"
        req = urllib.request.Request(
            url, headers={"User-Agent": "leizilla-crawler/0.1"}
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as response:
                data = json.loads(response.read().decode("utf-8"))
        except Exception as e:
            logger.error(f"Erro ao consultar a API CDX para {self.prefix}: {e}")
            return []

        if not data or len(data) <= 1:
            return []

        records = data[1:]
        resources = []

        for row in records:
            orig_url = row[2]
            status = row[4]
            timestamp = row[1]

            if orig_url.lower().endswith(".pdf") and status == "200":
                filename = orig_url.split("/")[-1]
                tipo, chave = parse_filename(filename)
                if not tipo or not chave:
                    # Identidade é evidência, não catraca (ADR-0011 §1): capturamos
                    # mesmo sem (tipo, número) no nome. Prefixo NÃO-identificante
                    # "documento-" garante que parse_identity devolva None — senão um
                    # stem com forma "{palavra}-{dígitos}" (ex.: "oficio-123") seria
                    # promovido a um range navegável espúrio em vez da área de espera
                    # _unidentified. O harvest key (nome do arquivo) fica preservado.
                    tipo, chave = "", f"documento-{filename.rsplit('.', 1)[0]}"

                # snapshot real (preserva o esquema arquivado, p.ex. http); a chave de
                # dedup (url) é normalizada para o esquema canônico do manifesto.
                wayback_url = f"https://web.archive.org/web/{timestamp}/{orig_url}"
                dedup_url = re.sub(
                    r"^https?://", f"{self.canonical_scheme}://", orig_url
                )
                resources.append(
                    {
                        "url": dedup_url,
                        "ente": self.ente,
                        "fonte": self.fonte,
                        "tipo_documento": tipo,
                        "chave": chave,
                        "status": "pending",
                        "wayback_snapshot": wayback_url,
                    }
                )
        return resources


_HEAD_RATE_LIMIT_S = 0.5


def _head_exists(url: str, timeout: float = 10.0) -> bool:
    """Retorna True se HEAD request retornar 200 ou 302 (arquivo existe no servidor)."""
    try:
        req = urllib.request.Request(
            url,
            method="HEAD",
            headers={"User-Agent": "leizilla-crawler/0.1"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status in (200, 302)
    except urllib.error.HTTPError as exc:
        return exc.code in (200, 302)
    except Exception:
        return False


class SequentialDiscovery:
    """Estratégia de descobrimento baseada em templates de URLs sequenciais."""

    def __init__(self, config: Dict[str, Any], ente: str, fonte: str) -> None:
        self.templates = config["templates"]
        self.start = int(config["start"])
        self.end = int(config["end"])
        self.ente = ente
        self.fonte = fonte
        self.head_check: bool = bool(config.get("head_check", False))

    def run(self, storage: Optional[DuckDBStorage] = None) -> List[Dict[str, Any]]:
        logger.info(
            f"Rodando Sequential Discovery para {self.ente}/{self.fonte} "
            f"(de {self.start} a {self.end}, head_check={self.head_check})..."
        )
        import time

        resources = []
        last_head_time = 0.0
        for num in range(self.start, self.end + 1):
            for tmpl in self.templates:
                url = tmpl.format(num=num)

                if storage:
                    try:
                        conn = storage.connect()
                        res = conn.execute(
                            "SELECT 1 FROM discovered_resources WHERE url = ?", [url]
                        ).fetchone()
                        if res:
                            continue
                    except Exception as e:
                        logger.warning(f"Error checking DB for URL {url}: {e}")

                if self.head_check:
                    # Rate-limit HEAD requests to avoid hammering the server
                    elapsed = time.monotonic() - last_head_time
                    if elapsed < _HEAD_RATE_LIMIT_S:
                        time.sleep(_HEAD_RATE_LIMIT_S - elapsed)
                    exists = _head_exists(url)
                    last_head_time = time.monotonic()
                    if not exists:
                        logger.debug(f"HEAD 404/error — skipping {url}")
                        continue

                filename = url.split("/")[-1]
                tipo, chave = parse_filename(filename)
                if not tipo or not chave:
                    # Captura mesmo sem identidade (ADR-0011 §1): vai à área de
                    # espera _unidentified. Prefixo NÃO-identificante "documento-"
                    # garante parse_identity → None mesmo para stems "{palavra}-{díg}".
                    tipo, chave = "", f"documento-{filename.rsplit('.', 1)[0]}"
                resources.append(
                    {
                        "url": url,
                        "ente": self.ente,
                        "fonte": self.fonte,
                        "tipo_documento": tipo,
                        "chave": chave,
                        "status": "pending",
                        "wayback_snapshot": None,
                    }
                )
        logger.info(
            f"Sequential Discovery concluído: {len(resources)} recursos encontrados "
            f"(head_check={self.head_check})"
        )
        return resources


class PlaywrightCrawlerDiscovery:
    """Estratégia de descobrimento que usa o LeisCrawler (Playwright) para o portal ALRO."""

    def __init__(self, config: Dict[str, Any], ente: str, fonte: str) -> None:
        self.start = int(config["start"])
        self.end = int(config["end"])
        self.ente = ente
        self.fonte = fonte

    def run(self) -> List[Dict[str, Any]]:
        logger.info(
            f"Rodando Playwright Discovery para {self.ente}/{self.fonte} (de {self.start} a {self.end})..."
        )
        # Como o LeisCrawler é assíncrono, rodamos no event loop
        import asyncio

        from leizilla.crawler import LeisCrawler

        crawler = LeisCrawler(crawler_type="playwright")

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        if loop.is_running():
            # Caso especial em ambientes assíncronos
            import nest_asyncio

            nest_asyncio.apply()

        laws = loop.run_until_complete(
            crawler.discover_rondonia_laws(start_coddoc=self.start, end_coddoc=self.end)
        )

        resources = []
        for law in laws:
            pdf_url = law.get("url_pdf_original")
            # Captura por contexto (ADR-0011 §1): o título da página rende
            # (tipo, número) em >90% (parse_titulo_identity) → vai ao catálogo;
            # o resíduo (coddoc puro) é preservado na área de espera _unidentified.
            if pdf_url:
                resources.append(
                    {
                        "url": pdf_url,
                        "ente": self.ente,
                        "fonte": self.fonte,
                        # tipo/chave da identidade extraída do título (ADR-0011);
                        # fallback para coddoc quando não identificável (adiado).
                        "tipo_documento": law.get("tipo", "documento"),
                        "chave": law.get("chave", f"coddoc-{law.get('coddoc'):05d}"),
                        "status": "pending",
                        "wayback_snapshot": None,
                    }
                )
        return resources


STRATEGIES: Dict[
    str, Callable[[Dict[str, Any], str, str], DiscoveryStrategyProtocol]
] = {
    "wayback-cdx": WaybackCdxDiscovery,
    "sequential": SequentialDiscovery,
    "playwright-crawler": PlaywrightCrawlerDiscovery,
}


def load_manifest(ente: str) -> Dict[str, Any]:
    """Carrega o arquivo de manifesto de um ente federativo."""
    manifest_path = Path(__file__).parent / "manifests" / f"{ente}.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifesto não encontrado para o ente: {ente}")
    with open(manifest_path, "r", encoding="utf-8") as f:
        data: Dict[str, Any] = json.load(f)
    return data


def discover_resources(ente: str, fonte: Optional[str] = None) -> List[Dict[str, Any]]:
    """Roda as estratégias do manifesto e **retorna** os resources (sem inserir).

    Diferente de ``run_discovery`` (que persiste), serve à reconciliação: re-deriva
    identidades com os extratores *atuais* (possivelmente melhorados), independente
    das linhas já gravadas em ``discovered_resources``. ``fonte`` filtra para uma
    fonte específica.
    """
    manifest = load_manifest(ente)
    out: List[Dict[str, Any]] = []
    for f, fonte_cfg in manifest.get("fontes", {}).items():
        if fonte is not None and f != fonte:
            continue
        for discovery_cfg in fonte_cfg.get("discovery", []):
            strategy_cls = STRATEGIES.get(discovery_cfg.get("strategy"))
            if not strategy_cls:
                logger.warning(
                    f"Estratégia '{discovery_cfg.get('strategy')}' não suportada."
                )
                continue
            try:
                out.extend(strategy_cls(discovery_cfg, ente, f).run())
            except Exception as e:
                logger.error(
                    f"Falha na estratégia '{discovery_cfg.get('strategy')}' "
                    f"para {ente}/{f}: {e}"
                )
    return out


def run_discovery(ente: str, storage: DuckDBStorage) -> int:
    """Lê o manifesto do ente, executa todas as estratégias e salva os resources."""
    resources = discover_resources(ente)
    for res in resources:
        storage.insert_resource(res)
    return len(resources)
