"""Crawler Playwright-based para portais oficiais de leis."""

import asyncio
import logging
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from playwright.async_api import Browser, Page, async_playwright

from leizilla import config

_CASACIVIL_FILES_BASE = "http://ditel.casacivil.ro.gov.br/COTEL/Livros/Files"
_CASACIVIL_FONTE_URL = "http://ditel.casacivil.ro.gov.br/COTEL/Livros/"

# Tipos normativos reconhecíveis no título de uma página de norma, do mais
# específico para o mais genérico (ordem importa: "lei complementar" antes de
# "lei", "decreto-lei" antes de "decreto"). Mapeia para o vocabulário de tipo.
_TITULO_TIPOS: List[Tuple[str, str]] = [
    ("lei complementar", "lc"),
    ("decreto-lei", "decreto-lei"),
    ("decreto lei", "decreto-lei"),
    ("emenda constitucional", "emenda-constitucional"),
    ("medida provisoria", "medida-provisoria"),
    ("decreto", "decreto"),
    ("resolucao", "resolucao"),
    ("portaria", "portaria"),
    ("lei", "lei"),
]


def _strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn"
    )


def parse_titulo_identity(titulo: str) -> Optional[Tuple[str, int]]:
    """Extrai ``(tipo, número)`` do título de uma página de norma, ou ``None``.

    Ex.: ``"LEI Nº 5.120, DE 22 DE JUNHO DE 1999" → ("lei", 5120)``;
    ``"LEI COMPLEMENTAR Nº 42…" → ("lc", 42)``. O número é ancorado no ``Nº``
    para não confundir com o ano. Retorna ``None`` quando o tipo ou o número não
    podem ser determinados com confiança — o chamador trata como não-identificado
    (reject-until-identified, ADR-0011).
    """
    t = _strip_accents(titulo or "").lower()
    tipo = next((vocab for needle, vocab in _TITULO_TIPOS if needle in t), None)
    if tipo is None:
        return None
    # Número ancorado num marcador ordinal REAL (º/°/.) após um "n" em fronteira de
    # palavra — exige pelo menos um desses marcadores para não casar o "n" de
    # palavras comuns como "ano"/"no" seguidas de um ano (ex.: "RESOLUÇÃO ... ANO
    # 2020" não deve render número 2020). Cobre "nº", "n°", "n.", "n.º".
    m = re.search(r"\bn[º°o.\s]*[º°.]\s*(\d[\d.]*)", t)
    if not m:
        return None
    numero = int(m.group(1).replace(".", ""))
    if numero <= 0:
        return None
    return tipo, numero


def discover_casacivil_laws(
    tipo: str = "lei",
    start_num: int = 1,
    end_num: int = 100,
) -> List[Dict[str, Any]]:
    """Enumera leis da Casa Civil de Rondônia por número sequencial.

    Não usa Playwright — PDFs disponíveis diretamente via HTTP sem JS.
    URL pattern: ditel.casacivil.ro.gov.br/COTEL/Livros/Files/{prefix}{N}.pdf
      tipo="lei" → prefix "L"  (leis ordinárias)
      tipo="lc"  → prefix "LC" (leis complementares)

    Não verifica existência aqui — scrape_one resolve via Wayback/direct e
    falha graciosamente se o arquivo não existir.
    """
    if tipo not in ("lei", "lc"):
        raise ValueError(f"tipo deve ser 'lei' ou 'lc', recebeu '{tipo}'")

    if start_num > end_num:
        logging.getLogger(__name__).warning(
            "discover_casacivil_laws: start_num=%d > end_num=%d — range vazio",
            start_num,
            end_num,
        )

    prefix = "L" if tipo == "lei" else "LC"
    nome = "Lei Complementar" if tipo == "lc" else "Lei"
    laws: List[Dict[str, Any]] = []

    for num in range(start_num, end_num + 1):
        chave = f"{tipo}-{num:05d}"
        law: Dict[str, Any] = {
            "id": f"ro-casacivil-{chave}",
            "ente": "ro",
            "fonte": "casacivil",
            "chave": chave,
            "titulo": f"{nome} nº {num} (Rondônia)",
            "url_original": _CASACIVIL_FONTE_URL,
            "url_pdf_original": f"{_CASACIVIL_FILES_BASE}/{prefix}{num}.pdf",
        }
        laws.append(law)

    return laws


class LeisCrawler:
    """Crawler assíncrono para PDFs de leis estaduais e federais."""

    def __init__(self, crawler_type: str = "playwright"):
        self.crawler_type = crawler_type
        self.delay_ms = config.CRAWLER_DELAY
        self.retries = config.CRAWLER_RETRIES
        self.timeout_ms = config.CRAWLER_TIMEOUT

    async def discover_rondonia_laws(
        self,
        start_coddoc: int = 1,
        end_coddoc: int = 10,
    ) -> List[Dict[str, Any]]:
        """Descobre leis no portal da Assembleia Legislativa de Rondônia.

        Requer crawler_type="playwright" — o portal ALRO usa JavaScript para
        renderizar o conteúdo. Modo "simple" (requests+BS4) não implementado.
        """
        if self.crawler_type != "playwright":
            raise NotImplementedError(
                f"discover_rondonia_laws requer crawler_type='playwright'; "
                f"'{self.crawler_type}' não implementado para o portal ALRO."
            )
        laws = []
        base_url = "https://www.al.ro.leg.br"

        async with async_playwright() as playwright:
            browser: Browser = await playwright.chromium.launch(headless=True)
            page: Page = await browser.new_page()

            for coddoc in range(start_coddoc, end_coddoc + 1):
                try:
                    url = f"{base_url}/legislacao/leis/{coddoc}"
                    await page.goto(url, timeout=self.timeout_ms)
                    await page.wait_for_load_state("networkidle")

                    title_el = await page.query_selector("h1, h2, .title")
                    title = await title_el.inner_text() if title_el else f"Lei {coddoc}"

                    pdf_links = await page.query_selector_all("a[href$='.pdf']")
                    pdf_url = None
                    if pdf_links:
                        pdf_url = await pdf_links[0].get_attribute("href")
                        if pdf_url and not pdf_url.startswith("http"):
                            pdf_url = urljoin(base_url, pdf_url)

                    # Identidade normativa (ADR-0011): extraímos tipo+número do
                    # título. coddoc é só o índice de navegação da ALRO. Sem
                    # identidade, a chave fica como coddoc (será adiada na coleta).
                    identity = parse_titulo_identity(title)
                    if identity is not None:
                        tipo, numero = identity
                        chave = f"{tipo}-{numero:05d}"
                    else:
                        tipo = "documento"
                        chave = f"coddoc-{coddoc:05d}"

                    law: Dict[str, Any] = {
                        "id": f"ro-assembleia-{chave}",
                        "ente": "ro",
                        "fonte": "assembleia",
                        "tipo": tipo,
                        "chave": chave,
                        "titulo": title.strip(),
                        "url_original": url,
                        "url_pdf_original": pdf_url,
                        "coddoc": coddoc,
                        "data_descoberta": datetime.now().isoformat(),
                    }

                    ano_match = re.search(r"\b(19|20)\d{2}\b", title)
                    if ano_match:
                        law["ano"] = int(ano_match.group())

                    laws.append(law)
                    await asyncio.sleep(self.delay_ms / 1000)

                except Exception as exc:
                    logging.getLogger(__name__).debug(
                        "coddoc %d skipped: %s", coddoc, exc
                    )
                    continue

            await browser.close()

        return laws

    async def download_pdf(self, url: str, dest: Path) -> bool:
        """Baixa PDF da URL para destino local. Retorna True em sucesso."""
        for attempt in range(self.retries):
            try:
                response = requests.get(
                    url, timeout=self.timeout_ms / 1000, stream=True
                )
                response.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                return True
            except Exception:
                if attempt < self.retries - 1:
                    await asyncio.sleep(2**attempt)
        return False
