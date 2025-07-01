import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin
from datetime import datetime
import re

from playwright.async_api import async_playwright, Browser  # Page removida
# from playwright.async_api import Page # Page removida

from .base import BaseConnector
import config  # Supondo que config está acessível


class RondoniaConnector(BaseConnector):
    """Conector para leis do estado de Rondônia."""

    ORIGEM = "rondonia"

    def __init__(self):
        self.browser: Optional[Browser] = None
        self.playwright = None
        self.delay = config.CRAWLER_DELAY
        self.retries = config.CRAWLER_RETRIES
        self.timeout = config.CRAWLER_TIMEOUT

    async def _start_browser(self) -> None:
        """Inicia o browser Playwright se ainda não estiver iniciado."""
        if not self.browser or not self.browser.is_connected():
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(headless=True)

    async def _stop_browser(self) -> None:
        """Para o browser Playwright."""
        if self.browser and self.browser.is_connected():
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
            self.playwright = (
                None  # Garante que na próxima vez o playwright seja reiniciado
            )

    async def discover_laws(
        self, start_coddoc: int = 1, end_coddoc: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Descobre leis de Rondônia no portal oficial iterando por coddoc.

        Args:
            start_coddoc: ID inicial do documento para busca.
            end_coddoc: ID final do documento para busca.

        Returns:
            Lista de metadados das leis descobertas.
        """
        await self._start_browser()
        if (
            not self.browser
        ):  # Adicionando uma verificação para o caso de falha na inicialização
            print("❌ Browser não pôde ser iniciado.")
            return []

        page = await self.browser.new_page()
        await page.set_extra_http_headers(
            {
                "User-Agent": "Mozilla/5.0 (compatible; Leizilla/1.0; +https://github.com/franklinbaldo/leizilla)"
            }
        )

        discovered_laws = []
        base_url_template = (
            "http://ditel.casacivil.ro.gov.br/COTEL/Livros/detalhes.aspx?coddoc={}"
        )

        try:
            for coddoc in range(start_coddoc, end_coddoc + 1):
                url = base_url_template.format(coddoc)
                print(
                    f"🔍 [RondoniaConnector] Buscando lei com coddoc {coddoc} em {url}..."
                )

                try:
                    response = await page.goto(url, timeout=self.timeout)
                    if not response or response.status != 200:
                        print(
                            f"❌ [RondoniaConnector] Falha ao carregar página para coddoc {coddoc}: HTTP {response.status if response else 'Timeout'}"
                        )
                        continue

                    title_element_text = await page.locator(
                        "#container-main-offer h2"
                    ).first.text_content()
                    title = (
                        title_element_text.strip()
                        if title_element_text
                        else f"Lei coddoc {coddoc}"
                    )

                    numero = "N/A"
                    ano = datetime.now().year  # Default
                    match_num_ano = re.search(
                        r"Nº\s*([\d\.]+)[^\d]*DE\s*(\d{1,2})\s*DE\s*([A-ZÇÃÕÁÉÍÓÚ]+)\s*DE\s*(\d{4})",
                        title.upper(),
                    )
                    data_publicacao_str = f"{ano}-01-01"  # Placeholder

                    if match_num_ano:
                        numero = match_num_ano.group(1)
                        # Tentar converter dia, mês (por extenso) e ano para data
                        # Esta parte pode precisar de um mapeamento de mês para número
                        # Por simplicidade, vamos focar em extrair o ano por enquanto
                        ano_match = match_num_ano.group(4)
                        if ano_match:
                            ano = int(ano_match)
                        # A data de publicação real precisaria de um parsing mais robusto
                        # data_publicacao_str = ...
                    else:
                        # Fallback se o regex principal falhar
                        match_simple_num_ano = re.search(
                            r"Nº\s*([\d\.]+).*(\d{4})", title
                        )
                        if match_simple_num_ano:
                            numero = match_simple_num_ano.group(1)
                            ano_simple = match_simple_num_ano.group(2)
                            if ano_simple:
                                ano = int(ano_simple)
                        else:
                            match_year_url = re.search(r"(\d{4})", url)
                            if match_year_url:
                                ano = int(match_year_url.group(1))

                    pdf_link_element = await page.locator(
                        'a[href$=".pdf"]'
                    ).first.get_attribute("href")
                    pdf_url_original = (
                        urljoin(url, pdf_link_element) if pdf_link_element else None
                    )

                    if pdf_url_original:
                        discovered_laws.append(
                            {
                                "id": f"{self.ORIGEM}-coddoc-{coddoc}",
                                "titulo": title,
                                "numero": numero,
                                "ano": ano,
                                "data_publicacao": data_publicacao_str,
                                "tipo_lei": "lei",
                                "origem": self.ORIGEM,
                                "url_original_lei": url,
                                "url_pdf_original": pdf_url_original,
                                "url_pdf_ia": None,
                                "metadados_coleta": {
                                    "coddoc": coddoc,
                                    "fonte_declarada": "Ditel COTEL RO",
                                    "descoberto_em": datetime.now().isoformat(),
                                    "status_coleta": "descoberto",
                                },
                            }
                        )
                        print(
                            f"✅ [RondoniaConnector] Descoberta: {title} (coddoc: {coddoc}, PDF: {pdf_url_original})"
                        )
                    else:
                        print(
                            f"⚠️ [RondoniaConnector] Nenhuma URL de PDF encontrada para coddoc {coddoc}"
                        )

                except Exception as e:
                    print(
                        f"❌ [RondoniaConnector] Erro ao processar coddoc {coddoc} ({url}): {e}"
                    )

                await asyncio.sleep(self.delay / 1000.0)  # Convertendo para segundos

        finally:
            await page.close()
            # Não vamos parar o browser aqui, para que possa ser reutilizado se `download_pdf` for chamado em sequência
            # O browser será parado no `__del__` ou explicitamente.

        return discovered_laws

    async def download_pdf(
        self, law_metadata: Dict[str, Any], output_path: Path
    ) -> bool:
        """
        Baixa o PDF de uma lei específica para o caminho fornecido.
        """
        pdf_url_original = law_metadata.get("url_pdf_original")
        if not pdf_url_original:
            print(
                f"❌ [RondoniaConnector] URL do PDF não encontrada nos metadados para {law_metadata.get('id')}"
            )
            return False

        await self._start_browser()
        if not self.browser:
            print("❌ [RondoniaConnector] Browser não pôde ser iniciado para download.")
            return False

        page = await self.browser.new_page()

        try:
            print(
                f"⬇️ [RondoniaConnector] Baixando PDF de {pdf_url_original} para {output_path}..."
            )
            response = await page.goto(pdf_url_original, timeout=self.timeout)

            if not response or response.status != 200:
                print(
                    f"❌ [RondoniaConnector] Falha no download: HTTP {response.status if response else 'Timeout'} para {pdf_url_original}"
                )
                return False

            content_type = response.headers.get("content-type", "")
            if "pdf" not in content_type.lower():
                print(
                    f"❌ [RondoniaConnector] Conteúdo não é PDF: {content_type} para {pdf_url_original}"
                )
                return False

            content = await response.body()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(content)

            print(
                f"✅ [RondoniaConnector] PDF baixado: {output_path.name} ({len(content)} bytes)"
            )
            return True

        except Exception as e:
            print(f"❌ [RondoniaConnector] Erro no download de {pdf_url_original}: {e}")
            return False

        finally:
            await page.close()

    async def close(self):
        """Fecha o browser e para o Playwright."""
        await self._stop_browser()

    # Para garantir que o browser seja fechado quando o objeto for destruído
    # No entanto, é melhor chamar explicitamente `close()`
    async def __aenter__(self):
        await self._start_browser()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


# Exemplo de como poderia ser usado (para teste, não parte da classe)
async def main_test():
    connector = RondoniaConnector()
    async with connector:  # Usa __aenter__ e __aexit__
        # Teste discover_laws
        print("--- Testando discover_laws ---")
        discovered = await connector.discover_laws(start_coddoc=1, end_coddoc=2)
        print(f"Descobertas: {len(discovered)} leis.")
        for law in discovered:
            print(law)
            # Teste download_pdf para a primeira lei descoberta com PDF
            if law.get("url_pdf_original"):
                print(f"\n--- Testando download_pdf para {law['id']} ---")
                temp_dir = Path("temp_test_downloads")
                temp_dir.mkdir(exist_ok=True)
                file_name = f"{law['id']}.pdf"
                output_file = temp_dir / file_name

                success = await connector.download_pdf(law, output_file)
                if success:
                    print(f"PDF de teste salvo em: {output_file.resolve()}")
                else:
                    print(f"Falha ao baixar PDF de teste para {law['id']}")
                break  # Baixar apenas um para o teste

    # Demonstração de uso sem o context manager
    # connector_manual = RondoniaConnector()
    # await connector_manual._start_browser()
    # laws = await connector_manual.discover_laws(1,2)
    # if laws and laws[0].get('url_pdf_original'):
    #    await connector_manual.download_pdf(laws[0], Path("temp_test_downloads") / "manual.pdf")
    # await connector_manual.close()


if __name__ == "__main__":
    # Para executar o teste: python -m src.connectors.rondonia
    # É necessário que a pasta 'src' seja reconhecida como parte do PYTHONPATH
    # ou executar de uma forma que permita importações relativas (ex: uv run ...)

    # Adicionando o diretório pai ao sys.path para permitir import relativo de 'config'
    # Isso é um hack para execução direta do script, não ideal para produção.
    import sys

    sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
    # Agora, teoricamente, `import config` e `from .base import BaseConnector` deveriam funcionar
    # No entanto, para `from .base import BaseConnector` funcionar, o módulo precisa ser executado como parte de um pacote.
    # A melhor forma de testar seria através de um script de teste no nível raiz do projeto.

    # Corrigindo a importação de config para o teste direto
    try:
        import config
    except ModuleNotFoundError:
        # Se 'config' não for encontrado, tentamos importar de um local relativo
        # Isso é útil se estiver executando o script diretamente de dentro de src/connectors
        # E 'config.py' estiver em 'src/'
        # Ajuste o path conforme a estrutura real do seu projeto
        # Exemplo: from .. import config
        # Por enquanto, vamos assumir que o PYTHONPATH está configurado ou estamos usando um runner como 'uv'
        print(
            "AVISO: config.py não encontrado. Usando valores padrão ou esperando erro."
        )

        # Definindo valores padrão para config caso não seja importado (para teste básico)
        class MockConfig:
            CRAWLER_DELAY = 1000
            CRAWLER_RETRIES = 3
            CRAWLER_TIMEOUT = 30000

        config = MockConfig()

    asyncio.run(main_test())
