"""Crawler Playwright-based para portais oficiais de leis."""

import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests
from playwright.async_api import Browser, Page, async_playwright

from leizilla import config


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

                    law: Dict[str, Any] = {
                        "id": f"ro-assembleia-coddoc-{coddoc:05d}",
                        "ente": "ro",
                        "fonte": "assembleia",
                        "chave": f"coddoc-{coddoc:05d}",
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
                    logging.getLogger(__name__).debug("coddoc %d skipped: %s", coddoc, exc)
                    continue

            await browser.close()

        return laws

    async def download_pdf(self, url: str, dest: Path) -> bool:
        """Baixa PDF da URL para destino local. Retorna True em sucesso."""
        for attempt in range(self.retries):
            try:
                response = requests.get(url, timeout=self.timeout_ms / 1000, stream=True)
                response.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                return True
            except Exception:
                if attempt < self.retries - 1:
                    await asyncio.sleep(2**attempt)
        return False
