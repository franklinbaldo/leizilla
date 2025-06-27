"""
Módulo de crawling para Leizilla.

Coleta PDFs de leis dos portais oficiais usando Playwright.
"""

import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin, urlparse
from datetime import datetime
import re

from playwright.async_api import async_playwright, Page, Browser
import config


class LeisCrawler:
    """Crawler para leis brasileiras usando Playwright."""
    
    def __init__(self):
        self.browser: Optional[Browser] = None
        self.delay = config.CRAWLER_DELAY
        self.retries = config.CRAWLER_RETRIES
        self.timeout = config.CRAWLER_TIMEOUT
    
    async def start(self) -> None:
        """Inicia browser Playwright."""
        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(headless=True)
    
    async def stop(self) -> None:
        """Para browser Playwright."""
        if self.browser:
            await self.browser.close()
    
    async def discover_rondonia_laws(self, 
                                   start_year: int = 2020,
                                   end_year: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Descobre leis de Rondônia no portal oficial.
        
        Args:
            start_year: Ano inicial para busca
            end_year: Ano final (padrão: ano atual)
        
        Returns:
            Lista de metadados das leis descobertas
        """
        if not self.browser:
            await self.start()
        
        if end_year is None:
            end_year = datetime.now().year
        
        page = await self.browser.new_page()
        await page.set_extra_http_headers({
            'User-Agent': 'Mozilla/5.0 (compatible; Leizilla/1.0; +https://github.com/franklinbaldo/leizilla)'
        })
        
        discovered_laws = []
        
        # Portal de Rondônia - URL base (precisa ser investigada)
        # Nota: URL placeholder - precisa ser ajustada para portal real
        base_url = "https://www.tjro.jus.br"  # Placeholder
        
        try:
            for year in range(start_year, end_year + 1):
                print(f"🔍 Buscando leis de {year}...")
                
                # Aqui seria implementada a lógica específica do portal
                # Por enquanto, retorna estrutura de exemplo
                year_laws = await self._crawl_year_rondonia(page, year)
                discovered_laws.extend(year_laws)
                
                # Delay entre requests
                await asyncio.sleep(self.delay / 1000)
        
        finally:
            await page.close()
        
        return discovered_laws
    
    async def _crawl_year_rondonia(self, page: Page, year: int) -> List[Dict[str, Any]]:
        """
        Crawl específico para um ano em Rondônia.
        
        NOTA: Esta é uma implementação placeholder.
        Precisa ser adaptada para o portal real de Rondônia.
        """
        laws = []
        
        # Estrutura de exemplo - deve ser substituída por crawling real
        example_law = {
            'id': f"rondonia-lei-{year}-001",
            'titulo': f"Lei Exemplo {year}",
            'numero': "001",
            'ano': year,
            'data_publicacao': f"{year}-01-15",
            'tipo_lei': "lei",
            'origem': "rondonia",
            'url_original': f"https://exemplo.ro.gov.br/lei-{year}-001.pdf",
            'metadados': {
                'fonte': 'Portal Rondônia',
                'descoberto_em': datetime.now().isoformat(),
                'status_crawling': 'descoberto'
            }
        }
        
        laws.append(example_law)
        
        return laws
    
    async def download_pdf(self, url: str, output_path: Path) -> bool:
        """
        Download de PDF de lei.
        
        Args:
            url: URL do PDF
            output_path: Caminho para salvar o arquivo
            
        Returns:
            True se download foi bem-sucedido
        """
        if not self.browser:
            await self.start()
        
        page = await self.browser.new_page()
        
        try:
            # Navegar para URL
            response = await page.goto(url, timeout=self.timeout)
            
            if not response or response.status != 200:
                print(f"❌ Falha no download: HTTP {response.status if response else 'Timeout'}")
                return False
            
            # Verificar se é PDF
            content_type = response.headers.get('content-type', '')
            if 'pdf' not in content_type.lower():
                print(f"❌ Conteúdo não é PDF: {content_type}")
                return False
            
            # Salvar arquivo
            content = await response.body()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(content)
            
            print(f"✅ PDF baixado: {output_path.name} ({len(content)} bytes)")
            return True
        
        except Exception as e:
            print(f"❌ Erro no download: {e}")
            return False
        
        finally:
            await page.close()
    
    def extract_lei_metadata(self, url: str) -> Dict[str, Any]:
        """
        Extrai metadados de uma lei a partir da URL.
        
        Args:
            url: URL da lei
            
        Returns:
            Metadados extraídos
        """
        # Parse básico da URL para extrair informações
        parsed = urlparse(url)
        filename = Path(parsed.path).name
        
        # Regex para extrair número e ano (placeholder)
        # Deve ser ajustado para padrões reais dos portais
        patterns = [
            r'lei[-_](\d{4})[-_](\d+)',  # lei-2024-123
            r'(\d{4})[-_](\d+)',         # 2024-123
            r'lei(\d+)[-_](\d{4})',      # lei123-2024
        ]
        
        for pattern in patterns:
            match = re.search(pattern, filename.lower())
            if match:
                if len(match.groups()) >= 2:
                    # Determinar qual é ano e qual é número
                    g1, g2 = match.groups()[:2]
                    if len(g1) == 4:  # g1 é ano
                        ano, numero = int(g1), g2
                    else:  # g2 é ano
                        ano, numero = int(g2), g1
                    
                    break
        else:
            # Fallback se não conseguir extrair
            ano = datetime.now().year
            numero = "unknown"
        
        return {
            'numero': numero,
            'ano': ano,
            'filename': filename,
            'url_original': url,
            'extracted_at': datetime.now().isoformat()
        }


async def discover_laws_rondonia(start_year: int = 2020) -> List[Dict[str, Any]]:
    """
    Função utilitária para descobrir leis de Rondônia.
    
    Args:
        start_year: Ano inicial para busca
        
    Returns:
        Lista de leis descobertas
    """
    crawler = LeisCrawler()
    
    try:
        laws = await crawler.discover_rondonia_laws(start_year=start_year)
        print(f"🎯 Descobertas {len(laws)} leis de Rondônia")
        return laws
    
    finally:
        await crawler.stop()


async def download_lei_pdf(url: str, filename: str) -> bool:
    """
    Função utilitária para download de PDF de lei.
    
    Args:
        url: URL do PDF
        filename: Nome do arquivo para salvar
        
    Returns:
        True se download foi bem-sucedido
    """
    crawler = LeisCrawler()
    output_path = config.TEMP_DIR / filename
    
    try:
        return await crawler.download_pdf(url, output_path)
    
    finally:
        await crawler.stop()


if __name__ == "__main__":
    # Teste básico
    asyncio.run(discover_laws_rondonia(start_year=2024))