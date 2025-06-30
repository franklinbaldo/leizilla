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
import requests
from bs4 import BeautifulSoup

from playwright.async_api import async_playwright, Page, Browser
import config


class LeisCrawler:
    """Crawler para leis brasileiras usando Playwright."""
    
    def __init__(self, crawler_type: str = "playwright"):
        self.browser: Optional[Browser] = None
        self.delay = config.CRAWLER_DELAY
        self.retries = config.CRAWLER_RETRIES
        self.timeout = config.CRAWLER_TIMEOUT
        self.crawler_type = crawler_type
    
    async def start(self) -> None:
        """Inicia browser Playwright se o tipo de crawler for 'playwright'."""
        if self.crawler_type == "playwright":
            playwright = await async_playwright().start()
            self.browser = await playwright.chromium.launch(headless=True)
    
    async def stop(self) -> None:
        """Para browser Playwright se o tipo de crawler for 'playwright'."""
        if self.browser and self.crawler_type == "playwright":
            await self.browser.close()
    
    async def discover_rondonia_laws(self, 
                                   start_coddoc: int = 1,
                                   end_coddoc: int = 10) -> List[Dict[str, Any]]:
        """
        Descobre leis de Rondônia no portal oficial iterando por coddoc.
        Usa Playwright ou requests/BeautifulSoup dependendo do crawler_type.
        
        Args:
            start_coddoc: ID inicial do documento para busca.
            end_coddoc: ID final do documento para busca.
        
        Returns:
            Lista de metadados das leis descobertas.
        """
        discovered_laws = []
        base_url_template = "http://ditel.casacivil.ro.gov.br/COTEL/Livros/detalhes.aspx?coddoc={}"
        
        if self.crawler_type == "playwright":
            if not self.browser:
                await self.start()
            page = await self.browser.new_page()
            await page.set_extra_http_headers({
                'User-Agent': 'Mozilla/5.0 (compatible; Leizilla/1.0; +https://github.com/franklinbaldo/leizilla)'
            })
        elif self.crawler_type == "simple":
            session = requests.Session()
            session.headers.update({'User-Agent': 'Mozilla/5.0 (compatible; Leizilla/1.0; +https://github.com/franklinbaldo/leizilla)'})
        else:
            raise ValueError(f"Tipo de crawler '{self.crawler_type}' não suportado.")

        try:
            for coddoc in range(start_coddoc, end_coddoc + 1):
                url = base_url_template.format(coddoc)
                print(f"🔍 Buscando lei com coddoc {coddoc} em {url}...")
                
                try:
                    response_content = None
                    if self.crawler_type == "playwright":
                        response = await page.goto(url, timeout=self.timeout)
                        if not response or response.status != 200:
                            print(f"❌ Falha ao carregar página para coddoc {coddoc}: HTTP {response.status if response else 'Timeout'}")
                            continue
                        response_content = await page.content()
                    elif self.crawler_type == "simple":
                        response = session.get(url, timeout=self.timeout / 1000) # requests timeout in seconds
                        response.raise_for_status()
                        response_content = response.text
                    
                    if response_content:
                        # --- Extração de dados da página ---
                        # Esta parte precisa ser adaptada à estrutura HTML real do site.
                        # Assumindo que o título, número, ano e link do PDF estão em elementos específicos.
                        
                        soup = BeautifulSoup(response_content, 'html.parser')
                        
                        # Exemplo de extração (placeholder - precisa de inspeção real do HTML)
                        title_element = soup.select_one('#container-main-offer h2')
                        title = title_element.get_text(strip=True) if title_element else f"Lei coddoc {coddoc}"
                        
                        # Try to extract number and year from the title or other elements
                        numero = "N/A"
                        ano = datetime.now().year
                        match_num_ano = re.search(r'Nº\s*(\d+)[^\d]*DE\s*(\d{4})', title)
                        if match_num_ano:
                            numero = match_num_ano.group(1)
                            ano = int(match_num_ano.group(2))
                        else:
                            # Fallback: try to find year in the URL or current year
                            match_year_url = re.search(r'(\d{4})', url)
                            if match_year_url:
                                ano = int(match_year_url.group(1))
                        
                        # Find PDF link
                        pdf_link_element = soup.select_one('a[href$=".pdf"]')
                        pdf_url = urljoin(url, pdf_link_element['href']) if pdf_link_element and 'href' in pdf_link_element.attrs else None
                        
                        if pdf_url:
                            discovered_laws.append({
                                'id': f"rondonia-coddoc-{coddoc}", # Using coddoc as part of ID
                                'titulo': title,
                                'numero': numero,
                                'ano': ano,
                                'data_publicacao': f"{ano}-01-01", # Placeholder, try to extract real date
                                'tipo_lei': "lei", # Can be refined based on content
                                'origem': "rondonia",
                                'url_original': url, # URL da página da lei
                                'url_pdf_ia': None, # Será preenchido após upload para IA
                                'metadados': {
                                    'coddoc': coddoc,
                                    'fonte': 'Ditel COTEL RO',
                                    'descoberto_em': datetime.now().isoformat(),
                                    'status_crawling': 'descoberto',
                                    'pdf_url_found': pdf_url # Store the found PDF URL
                                }
                            })
                            print(f"✅ Descoberta: {title} (coddoc: {coddoc}, PDF: {pdf_url})")
                        else:
                            print(f"⚠️ Nenhuma URL de PDF encontrada para coddoc {coddoc}")
                    
                except Exception as e:
                    print(f"❌ Erro ao processar coddoc {coddoc} ({url}): {e}")
                
                # Delay entre requests
                await asyncio.sleep(self.delay / 1000)
        
        finally:
            if self.crawler_type == "playwright":
                await page.close()
            # No need to close session for requests, it's handled by 'with' statement
        
        return discovered_laws
    
    async def download_pdf(self, url: str, output_path: Path) -> bool:
        """
        Download de PDF de lei.
        Usa Playwright ou requests dependendo do crawler_type.
        
        Args:
            url: URL do PDF
            output_path: Caminho para salvar o arquivo
            
        Returns:
            True se download foi bem-sucedido
        """
        if self.crawler_type == "playwright":
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
        
        elif self.crawler_type == "simple":
            try:
                response = requests.get(url, timeout=self.timeout / 1000) # requests timeout in seconds
                response.raise_for_status()
                
                content_type = response.headers.get('content-type', '')
                if 'pdf' not in content_type.lower():
                    print(f"❌ Conteúdo não é PDF: {content_type}")
                    return False
                
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(response.content)
                
                print(f"✅ PDF baixado: {output_path.name} ({len(response.content)} bytes)")
                return True
            
            except requests.exceptions.RequestException as e:
                print(f"❌ Erro no download (requests): {e}")
                return False
            except Exception as e:
                print(f"❌ Erro inesperado no download (requests): {e}")
                return False
        else:
            print(f"❌ Tipo de crawler '{self.crawler_type}' não suportado para download.")
            return False
    
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


async def discover_laws_rondonia(start_coddoc: int = 1, end_coddoc: int = 10) -> List[Dict[str, Any]]:
    """
    Função utilitária para descobrir leis de Rondônia.
    
    Args:
        start_coddoc: ID inicial do documento para busca.
        end_coddoc: ID final do documento para busca.
        
    Returns:
        Lista de leis descobertas
    """
    crawler = LeisCrawler()
    
    try:
        laws = await crawler.discover_rondonia_laws(start_coddoc=start_coddoc, end_coddoc=end_coddoc)
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
    asyncio.run(discover_laws_rondonia(start_coddoc=1, end_coddoc=5))