"""Módulo de descobrimento de recursos legislativos (Discovery).

Lê manifestos declarativos por ente e popula a tabela de discovered_resources.
"""

import json
import logging
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from leizilla.storage import DuckDBStorage

logger = logging.getLogger(__name__)


def parse_filename(filename: str) -> tuple[Optional[str], Optional[str]]:
    """Extrai tipo_documento e chave formatada do nome do arquivo (ex: L5120.pdf -> lei, lei-05120)."""
    # Remove extensão e limpa espaços
    name = filename.rsplit(".", 1)[0].strip().upper()
    if name.startswith("LC"):
        num_part = name[2:]
        if num_part.isdigit():
            return "lc", f"lc-{int(num_part):05d}"
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

    def __init__(self, config: Dict[str, Any], ente: str, fonte: str):
        self.prefix = config["prefix"]
        self.ente = ente
        self.fonte = fonte

    def run(self) -> List[Dict[str, Any]]:
        logger.info(f"Rodando Wayback CDX Discovery para {self.ente}/{self.fonte}...")
        url = f"https://web.archive.org/cdx/search/cdx?url={urllib.parse.quote(self.prefix)}&matchType=prefix&output=json"
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
                    # Se não casar com os padrões comuns, use fallback baseado no nome limpo
                    name_clean = filename.rsplit(".", 1)[0].replace(" ", "_")
                    tipo, chave = "documento", f"fallback-{name_clean}"

                wayback_url = f"https://web.archive.org/web/{timestamp}/{orig_url}"
                resources.append(
                    {
                        "url": orig_url,
                        "ente": self.ente,
                        "fonte": self.fonte,
                        "tipo_documento": tipo,
                        "chave": chave,
                        "status": "pending",
                        "wayback_snapshot": wayback_url,
                    }
                )
        return resources


class SequentialDiscovery:
    """Estratégia de descobrimento baseada em templates de URLs sequenciais."""

    def __init__(self, config: Dict[str, Any], ente: str, fonte: str):
        self.templates = config["templates"]
        self.start = int(config["start"])
        self.end = int(config["end"])
        self.ente = ente
        self.fonte = fonte

    def run(self) -> List[Dict[str, Any]]:
        logger.info(
            f"Rodando Sequential Discovery para {self.ente}/{self.fonte} (de {self.start} a {self.end})..."
        )
        resources = []
        for num in range(self.start, self.end + 1):
            for tmpl in self.templates:
                url = tmpl.format(num=num)
                filename = url.split("/")[-1]
                tipo, chave = parse_filename(filename)
                if not tipo or not chave:
                    tipo, chave = "lei", f"seq-{num:05d}"
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
        return resources


class PlaywrightCrawlerDiscovery:
    """Estratégia de descobrimento que usa o LeisCrawler (Playwright) para o portal ALRO."""

    def __init__(self, config: Dict[str, Any], ente: str, fonte: str):
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
            if pdf_url:
                resources.append(
                    {
                        "url": pdf_url,
                        "ente": self.ente,
                        "fonte": self.fonte,
                        "tipo_documento": "lei",  # ALRO scrape padrão é lei
                        "chave": law.get("chave", f"coddoc-{law.get('coddoc'):05d}"),
                        "status": "pending",
                        "wayback_snapshot": None,
                    }
                )
        return resources


STRATEGIES = {
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
        return json.load(f)  # type: ignore[no-any-return]


def run_discovery(ente: str, storage: DuckDBStorage) -> int:
    """Lê o manifesto do ente, executa todas as estratégias de descoberta e salva os resources."""
    manifest = load_manifest(ente)
    total_added = 0

    for fonte, fonte_cfg in manifest.get("fontes", {}).items():
        for discovery_cfg in fonte_cfg.get("discovery", []):
            strategy_name = discovery_cfg.get("strategy")
            strategy_cls = STRATEGIES.get(strategy_name)

            if not strategy_cls:
                logger.warning(
                    f"Estratégia de descoberta '{strategy_name}' não suportada/encontrada."
                )
                continue

            try:
                runner = strategy_cls(discovery_cfg, ente, fonte)
                resources = runner.run()  # type: ignore[attr-defined]
                logger.info(
                    f"Estratégia '{strategy_name}' descobriu {len(resources)} resources."
                )

                for res in resources:
                    storage.insert_resource(res)
                    total_added += 1

            except Exception as e:
                logger.error(
                    f"Falha ao executar estratégia '{strategy_name}' para {ente}/{fonte}: {e}"
                )

    return total_added
