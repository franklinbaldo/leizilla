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
    page_mock.goto = AsyncMock(return_value=AsyncMock(status=200))
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
    discovered_laws = await rondonia_connector_instance.discover_laws(
        start_coddoc=1, end_coddoc=1
    )
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

    async def goto_side_effect(url, **kwargs):
        if "5775.pdf" in url:
            return mock_pdf_response
        return AsyncMock(status=200)

    mock_playwright_page.goto = AsyncMock(side_effect=goto_side_effect)
    law_metadata = {
        "id": "rondonia-coddoc-1",
        "origem": "rondonia",
        "titulo": "LEI Nº 5.775, DE 27 DE DEZEMBRO DE 2023",
        "url_pdf_original": "http://ditel.casacivil.ro.gov.br/uploads/00001/2023/5775.pdf",
    }
    output_file = tmp_path / "lei_rondonia_teste.pdf"
    success = await rondonia_connector_instance.download_pdf(law_metadata, output_file)
    assert success is True
    assert output_file.exists()
    assert output_file.read_bytes() == b"%PDF-fake-content-for-download"
    mock_playwright_page.goto.assert_any_call(
        law_metadata["url_pdf_original"], timeout=rondonia_connector_instance.timeout
    )
    await rondonia_connector_instance.close()
