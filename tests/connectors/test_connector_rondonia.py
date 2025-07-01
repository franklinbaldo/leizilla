import pytest
from pathlib import Path  # Apenas uma importação de Path
from unittest.mock import AsyncMock, MagicMock, patch
import sys

# Adicionar o diretório src ao sys.path para permitir importações de módulos locais
PROJECT_ROOT_TEST = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT_TEST))  # noqa: E402 - Necessário para imports de src

from src.connectors.rondonia import RondoniaConnector  # noqa: E402
from src.connectors.base import BaseConnector  # noqa: E402

# ---- Fixtures ----


@pytest.fixture
def rondonia_connector_instance():
    """Retorna uma instância do RondoniaConnector."""
    with patch("src.connectors.rondonia.config") as mock_config:
        mock_config.CRAWLER_DELAY = 10
        mock_config.CRAWLER_RETRIES = 1
        mock_config.CRAWLER_TIMEOUT = 5000
        connector = RondoniaConnector()
    return connector


# ---- Mocks para Playwright ----


def create_mock_playwright_element(
    text_content_val: str = "", get_attribute_val: str = ""
):
    element_mock = AsyncMock()
    element_mock.text_content = AsyncMock(return_value=text_content_val)
    element_mock.get_attribute = AsyncMock(return_value=get_attribute_val)
    return element_mock


@pytest.fixture
def mock_playwright_page():
    page_mock = AsyncMock()
    title_element_mock = create_mock_playwright_element(
        text_content_val="LEI Nº 5.775, DE 27 DE DEZEMBRO DE 2023"
    )
    pdf_link_element_mock = create_mock_playwright_element(
        get_attribute_val="http://ditel.casacivil.ro.gov.br/uploads/00001/2023/5775.pdf"
    )
    empty_element_mock = AsyncMock()
    empty_element_mock.first = create_mock_playwright_element()
    empty_element_mock.get_attribute = AsyncMock(return_value=None)
    locators_map = {
        "#container-main-offer h2": title_element_mock,
        'a[href$=".pdf"]': pdf_link_element_mock,
        "#seletor_que_nao_existe": empty_element_mock,
    }

    def locator_side_effect(selector_str):
        final_element_mock = locators_map.get(selector_str, empty_element_mock)
        locator_obj_mock = AsyncMock()
        locator_obj_mock.first = final_element_mock
        return locator_obj_mock

    page_mock.locator = MagicMock(side_effect=locator_side_effect)

    async def default_goto_side_effect(url, *args, **kwargs):
        print(f"DEFAULT MOCK_PLAYWRIGHT_PAGE GOTO CALLED for URL: {url}")
        response_mock = AsyncMock()
        response_mock.status = 200
        response_mock.headers = {"content-type": "text/html"}
        response_mock.body = AsyncMock(return_value=b"Default mock response from fixture")
        return response_mock

    page_mock.goto = AsyncMock(side_effect=default_goto_side_effect) # Default goto uses the printing side_effect
    return page_mock


@pytest.fixture
def mock_playwright_browser(mock_playwright_page):
    browser_mock = AsyncMock()
    browser_mock.new_page = AsyncMock(return_value=mock_playwright_page)
    browser_mock.is_connected = MagicMock(return_value=True)
    return browser_mock


# ---- Testes ----


# @pytest.mark.asyncio # Removido - Teste não é async
def test_rondonia_connector_instanciacao(
    rondonia_connector_instance: RondoniaConnector,
):  # Removido async
    """Testa se o conector de Rondônia pode ser instanciado."""
    assert rondonia_connector_instance is not None
    assert isinstance(rondonia_connector_instance, BaseConnector)
    assert rondonia_connector_instance.ORIGEM == "rondonia"


@pytest.mark.asyncio  # Re-adicionado
@patch("playwright.async_api.async_playwright")
async def test_rondonia_discover_laws_simulado(
    mock_async_playwright_entry,
    rondonia_connector_instance: RondoniaConnector,
    mock_playwright_browser,
    mock_playwright_page,
):
    playwright_context_manager_mock = AsyncMock()
    playwright_context_manager_mock.start = AsyncMock(
        return_value=playwright_context_manager_mock
    )
    playwright_context_manager_mock.chromium.launch = AsyncMock(
        return_value=mock_playwright_browser
    )
    mock_async_playwright_entry.return_value = playwright_context_manager_mock

    # Более конкретный мок для page.goto в этом тесте
    mock_discover_response = AsyncMock()
    mock_discover_response.status = 200
    async def new_goto_mock_discover(url, *args, **kwargs):
        print(f"MOCK CALLED (discover test): page.goto('{url}')")
        # Здесь мы ожидаем, что URL будет страницей деталей, а не PDF
        # Настроим мок так, чтобы он возвращал успешный статус для страницы деталей
        # и позволял дальнейшим page.locator()... работать как настроено в фикстуре mock_playwright_page
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.headers = {"content-type": "text/html"} # Пример заголовка
        mock_response.body = AsyncMock(return_value=b"<html><body>Mocked page</body></html>")
        return mock_response

    # Применяем side_effect к существующему моку mock_playwright_page.goto из фикстуры
    mock_playwright_page.goto.side_effect = new_goto_mock_discover

    discovered_laws = await rondonia_connector_instance.discover_laws(
        start_coddoc=1, end_coddoc=1
    )
    print(f"Discovered laws in test: {discovered_laws}") # Добавим вывод
    assert len(discovered_laws) == 1
    law1 = discovered_laws[0]
    assert law1["origem"] == "rondonia"
    assert "LEI Nº 5.775" in law1["titulo"]
    assert law1["ano"] == 2023
    assert law1["numero"] == "5.775"
    assert (
        law1["url_pdf_original"]
        == "http://ditel.casacivil.ro.gov.br/uploads/00001/2023/5775.pdf"
    )
    assert law1["metadados_coleta"]["coddoc"] == 1
    await rondonia_connector_instance.close()


@pytest.mark.asyncio  # Re-adicionado
@patch("playwright.async_api.async_playwright")
async def test_rondonia_download_pdf_simulado(
    mock_async_playwright_entry,
    rondonia_connector_instance: RondoniaConnector,
    mock_playwright_browser,
    mock_playwright_page,
    tmp_path: Path,
):
    playwright_context_manager_mock = AsyncMock()
    playwright_context_manager_mock.start = AsyncMock(
        return_value=playwright_context_manager_mock
    )
    playwright_context_manager_mock.chromium.launch = AsyncMock(
        return_value=mock_playwright_browser
    )
    mock_async_playwright_entry.return_value = playwright_context_manager_mock
    mock_pdf_response = AsyncMock()
    mock_pdf_response.status = 200
    mock_pdf_response.headers = {"content-type": "application/pdf"}
    mock_pdf_response.body = AsyncMock(return_value=b"%PDF-fake-content-for-download")

    law_metadata = { # Moved law_metadata definition earlier to be used in side_effect
        "id": "rondonia-coddoc-1",
        "origem": "rondonia",
        "titulo": "LEI Nº 5.775, DE 27 DE DEZEMBRO DE 2023",
        "url_pdf_original": "http://ditel.casacivil.ro.gov.br/uploads/00001/2023/5775.pdf",
    }

    async def goto_side_effect(url, **kwargs):
        print(f"MOCK CALLED (download test): page.goto('{url}')") # Diagnostic print
        if law_metadata["url_pdf_original"] == url: # Exact match
            print(f"MOCK MATCHED PDF URL (download test): '{url}'")
            return mock_pdf_response # This has .status = 200
        # For any other URL (e.g. if there's a redirect page first)
        print(f"MOCK DID NOT MATCH PDF URL (download test): '{url}', returning generic 200")
        mock_generic_response = AsyncMock()
        mock_generic_response.status = 200
        mock_generic_response.headers = {"content-type": "text/html"}
        mock_generic_response.body = AsyncMock(return_value=b"<html>Generic Page</html>")
        return mock_generic_response

    # Применяем side_effect к существующему моку mock_playwright_page.goto из фикстуры
    mock_playwright_page.goto.side_effect = goto_side_effect

    output_file = tmp_path / "lei_rondonia_teste.pdf"
    success = await rondonia_connector_instance.download_pdf(law_metadata, output_file)
    # The following lines were duplicated and caused an IndentationError. They are removed.
    # "titulo": "LEI Nº 5.775, DE 27 DE DEZEMBRO DE 2023",
    # "url_pdf_original": "http://ditel.casacivil.ro.gov.br/uploads/00001/2023/5775.pdf",
    # }
    # output_file = tmp_path / "lei_rondonia_teste.pdf"
    # success = await rondonia_connector_instance.download_pdf(law_metadata, output_file)
    assert success is True
    assert output_file.exists()
    assert output_file.read_bytes() == b"%PDF-fake-content-for-download"
    mock_playwright_page.goto.assert_any_call(
        law_metadata["url_pdf_original"], timeout=rondonia_connector_instance.timeout
    )
    await rondonia_connector_instance.close()
