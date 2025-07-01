# Contribuindo com Novos Conectores para o Leizilla

Agradecemos seu interesse em expandir o Leizilla para novas fontes de dados normativos! Este guia detalha como você pode criar e testar um novo conector.

## Sumário

1.  [Visão Geral do Processo](#visao-geral-do-processo)
2.  [Pré-requisitos](#pre-requisitos)
3.  [Usando o Gerador de Esqueleto de Conector](#usando-o-gerador-de-esqueleto-de-conector)
4.  [Implementando `discover_laws`](#implementando-discover_laws)
    *   [Estrutura dos Metadados Retornados](#estrutura-dos-metadados-retornados)
    *   [Lidando com Paginação](#lidando-com-paginacao)
    *   [Gerenciamento de Sessões HTTP e Headers](#gerenciamento-de-sessoes-http-e-headers)
    *   [Resiliência e Retentativas](#resiliencia-e-retentativas)
5.  [Implementando `download_pdf`](#implementando-download_pdf)
6.  [Escrevendo Testes para seu Conector](#escrevendo-testes-para-seu-conector)
    *   [Configurando o Ambiente de Teste](#configurando-o-ambiente-de-teste)
    *   [Usando `pytest` e Mocks](#usando-pytest-e-mocks)
    *   [Exemplo de Teste (Estrutura)](#exemplo-de-teste-estrutura)
7.  [Boas Práticas e Dicas](#boas-praticas-e-dicas)
8.  [Submetendo sua Contribuição](#submetendo-sua-contribuicao)

## Visão Geral do Processo

Contribuir com um novo conector envolve os seguintes passos principais:

1.  **Analisar a Fonte de Dados:** Entender como o portal da nova origem (ex: diário oficial de um município, portal de leis de um estado) disponibiliza os atos normativos e seus PDFs.
2.  **Gerar o Esqueleto:** Usar o comando CLI do Leizilla para criar a estrutura básica do seu conector.
3.  **Implementar a Descoberta:** Codificar a lógica para encontrar novas leis/atos e extrair seus metadados básicos (`discover_laws`).
4.  **Implementar o Download:** Codificar a lógica para baixar o arquivo PDF de uma lei/ato específico (`download_pdf`).
5.  **Escrever Testes:** Garantir que seu conector funciona corretamente e lida com casos comuns.
6.  **Submeter:** Abrir um Pull Request com sua contribuição.

## Pré-requisitos

*   Python 3.9+
*   Poetry (para gerenciamento de dependências - `uv` também é suportado para execução)
*   Git
*   Familiaridade com `asyncio` em Python.
*   Conhecimento básico de web scraping (HTML, CSS selectors, XPath) e requisições HTTP.
*   Opcional, mas recomendado: Playwright (se a fonte de dados exigir renderização JavaScript pesada ou interações complexas).

Configure o ambiente de desenvolvimento do Leizilla seguindo as instruções no `README.md` ou `docs/DEVELOPMENT.md`.

## Usando o Gerador de Esqueleto de Conector

O Leizilla fornece um comando para gerar rapidamente o arquivo base para seu novo conector:

```bash
uv run leizilla connector new --name NOME_DA_ORIGEM
```

Substitua `NOME_DA_ORIGEM` por um identificador em minúsculas para a sua fonte (ex: `acre`, `sao_paulo_municipio`, `parana`). Evite espaços ou caracteres especiais; use underscores se necessário.

Exemplo:
```bash
uv run leizilla connector new --name rio_grande_do_sul
```
Isso criará o arquivo `src/connectors/rio_grande_do_sul.py` com uma classe `RioGrandeDoSulConnector(BaseConnector)` e os métodos `discover_laws` e `download_pdf` prontos para serem preenchidos.

O nome fornecido também será usado como o atributo `ORIGEM` na classe do conector, que é o identificador único usado internamente pelo Leizilla.

## Implementando `discover_laws`

Este método assíncrono é responsável por encontrar leis/atos na fonte de dados e retornar uma lista de dicionários, cada um contendo metadados sobre uma lei descoberta.

```python
# Em src/connectors/seu_conector.py
from .base import BaseConnector
from typing import List, Dict, Any, Optional
# Suas importações (httpx, playwright, etc.)

class SeuConector(BaseConnector):
    ORIGEM = "nome_da_origem"

    async def discover_laws(self, **kwargs) -> List[Dict[str, Any]]:
        discovered_laws: List[Dict[str, Any]] = []

        # Pega o último marcador processado, se o monitor fornecer
        last_marker = kwargs.get('last_processed_marker')
        # Use este marcador para evitar reprocessar itens já vistos.
        # O formato do marcador (ID, data, etc.) depende da sua estratégia.

        # Sua lógica de descoberta aqui...
        # Ex: Iterar por páginas, fazer requisições a APIs, etc.

        # Para cada lei encontrada:
        #   law_meta = { ... metadados ... }
        #   discovered_laws.append(law_meta)

        return discovered_laws
```

### Estrutura dos Metadados Retornados

Cada dicionário na lista retornada por `discover_laws` deve conter, no mínimo, as seguintes chaves (consulte `src/connectors/base.py` e o schema em `src/storage.py` para referência completa):

*   `id` (str): Um identificador único para esta lei *dentro desta origem*. Sugestão: combine a origem, tipo, número e ano. Ex: `"rondonia-lei-123-2023"`.
*   `titulo` (str): O título completo da lei ou ato normativo.
*   `origem` (str): Deve ser igual ao atributo `self.ORIGEM` do seu conector.
*   `url_original_lei` (Optional[str]): A URL da página HTML onde a lei pode ser visualizada (se houver).
*   `url_pdf_original` (Optional[str]): A URL direta para o arquivo PDF da lei. Essencial para a etapa de download.
*   `data_publicacao` (Optional[str]): Data de publicação da lei no formato `"YYYY-MM-DD"`.
*   `numero` (Optional[str]): O número oficial da lei/ato.
*   `ano` (Optional[int]): O ano de publicação/vigência da lei.
*   `tipo_lei` (Optional[str]): Tipo do ato (ex: 'lei', 'decreto', 'portaria', 'lei complementar', 'lei ordinaria').
*   `metadados_coleta` (dict): Um dicionário para quaisquer outros dados relevantes extraídos durante a coleta que não se encaixam nos campos principais.
    *   `fonte_declarada` (str): Nome do portal ou fonte de onde os dados foram extraídos (ex: "Diário Oficial do Estado X", "Portal da Legislação Y").
    *   `descoberto_em_conector` (str): Timestamp ISO 8601 de quando o conector descobriu o item (geralmente `datetime.now().isoformat()`).
    *   Outros campos específicos da fonte.

### Lidando com Paginação

Muitos portais listam leis em múltiplas páginas. Seu `discover_laws` precisará implementar a lógica para navegar por essas páginas até que todas as leis (ou todas as *novas* leis, se estiver usando um marcador) sejam encontradas.

*   **Estratégias Comuns:**
    *   Verificar por um link "Próxima Página".
    *   Iterar por números de página em um padrão de URL (`?page=1`, `?page=2`, ...).
    *   Algumas fontes podem carregar mais itens via JavaScript (requer Playwright ou análise de chamadas de XHR).
*   **Cuidado com Loops Infinitos:** Certifique-se de que sua lógica de paginação tem uma condição de parada clara (ex: não há mais link "Próxima", a página não retorna novos itens, atinge um limite máximo de páginas para evitar sobrecarga).

### Gerenciamento de Sessões HTTP e Headers

*   **User-Agent:** É uma boa prática definir um User-Agent que identifique o Leizilla. Ex: `'User-Agent': 'Mozilla/5.0 (compatible; Leizilla/1.0; +https://github.com/leizilla/leizilla)'`.
*   **Sessões (`httpx.AsyncClient`):** Para múltiplas requisições ao mesmo host, use um `httpx.AsyncClient` para reutilizar conexões (melhora a performance) e gerenciar cookies automaticamente, se necessário.
    ```python
    import httpx
    async with httpx.AsyncClient(headers={"User-Agent": "Leizilla..."}) as client:
        response = await client.get("...")
    ```
*   **Headers Adicionais:** Alguns sites podem exigir outros headers (ex: `Referer`, `Accept`). Analise as requisições do seu navegador para identificar se são necessários.
*   **Playwright:** Se estiver usando Playwright, você pode definir headers extras ao criar uma nova página (`page.set_extra_http_headers(...)`) ou em rotas (`page.route` para interceptar e modificar requisições).

### Resiliência e Retentativas

Conexões de rede podem falhar. Considere implementar uma lógica simples de retentativas para requisições HTTP. Bibliotecas como `tenacity` podem ajudar, ou você pode implementar um loop simples com `asyncio.sleep`.

## Implementando `download_pdf`

Este método assíncrono recebe os metadados de uma lei (como retornado por `discover_laws`) e um `output_path` (Path) onde o PDF deve ser salvo.

```python
# Em src/connectors/seu_conector.py
from pathlib import Path

async def download_pdf(self, law_metadata: Dict[str, Any], output_path: Path) -> bool:
    pdf_url = law_metadata.get('url_pdf_original')
    if not pdf_url:
        # Logar ou imprimir um aviso
        return False

    # Sua lógica de download aqui...
    # Ex: Usar httpx para baixar o conteúdo e salvar em output_path
    try:
        # Exemplo com httpx (instale com `uv pip install httpx[http2]`)
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.get(pdf_url, timeout=60.0) # Timeout de 60s
            response.raise_for_status() # Levanta exceção para erros HTTP

            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'wb') as f:
                f.write(response.content)
            return True
    except httpx.HTTPStatusError as e:
        print(f"Erro HTTP ao baixar {pdf_url}: {e.response.status_code}")
        return False
    except Exception as e:
        print(f"Erro ao baixar {pdf_url}: {e}")
        return False
```

*   **Verifique `content-type`:** Se possível, verifique se o `content-type` da resposta é `application/pdf`.
*   **Tratamento de Erros:** Retorne `False` se o download falhar por qualquer motivo (URL inválida, erro de rede, conteúdo não é PDF, etc.). Logue o erro.
*   **Playwright para Downloads:** Se o download do PDF exigir interação JavaScript ou passar por redirecionamentos complexos, pode ser necessário usar Playwright:
    ```python
    # Exemplo com Playwright (requer self.browser inicializado)
    # page = await self.browser.new_page()
    # try:
    #     async with page.expect_download(timeout=60000) as download_info: # Timeout 60s
    #         await page.goto(pdf_url) # Ou clique em um link que inicia o download
    #     download = await download_info.value
    #     await download.save_as(output_path)
    #     return True
    # except Exception as e:
    #     print(f"Erro ao baixar PDF com Playwright: {e}")
    #     return False
    # finally:
    #     await page.close()
    ```

## Escrevendo Testes para seu Conector

Testes são essenciais para garantir que seu conector funcione como esperado e para facilitar a manutenção futura. Usamos `pytest` e `pytest-asyncio`.

### Configurando o Ambiente de Teste

Certifique-se de ter as dependências de desenvolvimento instaladas:
```bash
uv pip install -e ".[dev]"
# ou poetry install --with dev
```

Crie um novo arquivo de teste em `tests/connectors/`, por exemplo, `tests/connectors/test_seu_conector.py`.

### Usando `pytest` e Mocks

*   **`pytest-asyncio`:** Para testar funções `async`, marque seus testes com `@pytest.mark.asyncio`.
*   **Mocks (`unittest.mock` ou `pytest-mock`):** Você precisará "mockar" (simular) as requisições HTTP para que seus testes não dependam de uma conexão de rede real ou do estado atual do site externo.
    *   Para `httpx`, você pode usar `respx` ou mockar `httpx.AsyncClient.get` diretamente.
    *   Para `Playwright`, você pode usar `page.route()` para interceptar requisições e fornecer respostas falsas, ou mockar métodos do Playwright se a interação for mais complexa.

### Exemplo de Teste (Estrutura)

```python
# tests/connectors/test_seu_conector.py
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch # Para AsyncMock

# Importe seu conector
from src.connectors.seu_conector import SeuConector
# Se precisar de BaseConnector para type hints ou isinstance
from src.connectors.base import BaseConnector

@pytest.fixture
def conector_instance():
    """Retorna uma instância do seu conector."""
    return SeuConector()

@pytest.mark.asyncio
async def test_discover_laws_sucesso(conector_instance: SeuConector, httpx_mock): # httpx_mock se usar respx
    # Conteúdo HTML/JSON simulado que o site retornaria
    mock_html_pagina_1 = """
    <html><body>
        <a href="/lei1.pdf">Lei 1 (PDF)</a>
        <a href="/pagina2">Próxima Página</a>
    </body></html>
    """
    mock_html_pagina_2 = """
    <html><body>
        <a href="/lei2.pdf">Lei 2 (PDF)</a>
    </body></html>
    """

    # Configurar o mock para httpx (exemplo com respx)
    # from respx import MockRouter
    # router = MockRouter()
    # router.get("http://portal.example.com/leis").respond(text=mock_html_pagina_1)
    # router.get("http://portal.example.com/pagina2").respond(text=mock_html_pagina_2)
    # with router:
    #     discovered = await conector_instance.discover_laws()

    # Exemplo com patch direto (mais simples para começar)
    with patch('httpx.AsyncClient.get', new_callable=AsyncMock) as mock_get:
        # Configurar múltiplos retornos se houver paginação
        mock_get.side_effect = [
            AsyncMock(text=mock_html_pagina_1, status_code=200, headers={'Content-Type': 'text/html'}),
            AsyncMock(text=mock_html_pagina_2, status_code=200, headers={'Content-Type': 'text/html'}),
            # Adicione um mock para parar a paginação, ex: retornar um erro 404 ou página vazia
            AsyncMock(status_code=404)
        ]

        discovered = await conector_instance.discover_laws()

    assert len(discovered) == 2
    # Verifique a estrutura dos metadados da primeira lei
    assert discovered[0]['id'] == "nome_da_origem-..." # Adapte
    assert discovered[0]['titulo'] == "Lei 1" # Adapte
    assert discovered[0]['url_pdf_original'].endswith("/lei1.pdf")
    # ... mais assertions ...

@pytest.mark.asyncio
async def test_download_pdf_sucesso(conector_instance: SeuConector, tmp_path: Path):
    mock_law_metadata = {
        "id": "nome_da_origem-lei1-2023",
        "origem": "nome_da_origem",
        "titulo": "Lei Teste 1",
        "url_pdf_original": "http://portal.example.com/lei1.pdf"
    }
    output_file = tmp_path / "test_lei.pdf"

    # Conteúdo binário simulado do PDF
    mock_pdf_content = b"%PDF-1.4 fake pdf content..."

    with patch('httpx.AsyncClient.get', new_callable=AsyncMock) as mock_get:
        mock_get.return_value = AsyncMock(content=mock_pdf_content, status_code=200, headers={'Content-Type': 'application/pdf'})

        success = await conector_instance.download_pdf(mock_law_metadata, output_file)

    assert success is True
    assert output_file.exists()
    assert output_file.read_bytes() == mock_pdf_content

@pytest.mark.asyncio
async def test_download_pdf_falha_url(conector_instance: SeuConector, tmp_path: Path):
    mock_law_metadata_sem_url = {"id": "test-id", "titulo": "Sem URL"}
    output_file = tmp_path / "test_lei.pdf"

    success = await conector_instance.download_pdf(mock_law_metadata_sem_url, output_file)
    assert success is False
    assert not output_file.exists()

# Adicione mais testes para casos de erro, paginação, diferentes tipos de leis, etc.
```
Consulte `tests/connectors/test_connector_rondonia.py` (a ser criado na Fase 6) para um exemplo mais completo.

## Boas Práticas e Dicas

*   **Seja Respeitoso:** Não sobrecarregue os servidores da fonte de dados. Use delays apropriados entre requisições (`asyncio.sleep(SEGUNDOS)`). O Leizilla pode ter configurações globais de delay, mas seu conector pode precisar de ajustes específicos.
*   **Logging:** Use `print()` ou o sistema de logging do Leizilla (se disponível para conectores) para informar sobre o progresso e erros. Mensagens claras ajudam na depuração.
*   **Tratamento de Exceções:** Envolva chamadas de rede e parsing de HTML/JSON em blocos `try...except` para lidar com erros de forma graciosa.
*   **Código Limpo e Comentado:** Escreva código legível e adicione comentários onde a lógica não for óbvia.
*   **Idempotência:** Idealmente, `discover_laws` (quando usado com marcadores) e `download_pdf` devem ser idempotentes (rodá-los múltiplas vezes com os mesmos inputs não deve causar efeitos colaterais indesejados ou duplicatas). O sistema Leizilla (DB e monitor) ajuda com isso, mas o conector deve ser bem comportado.
*   **Testes Locais:** Antes de submeter, teste seu conector localmente. Você pode criar um pequeno script que instancia seu conector e chama os métodos `discover_laws` e `download_pdf` para verificar a saída. O template gerado por `leizilla connector new` incluirá um bloco `if __name__ == "__main__":` que pode ser adaptado para isso.

## Submetendo sua Contribuição

1.  Faça um "fork" do repositório Leizilla.
2.  Crie uma nova "branch" para seu conector (ex: `feature/conector-nome-da-origem`).
3.  Adicione seu arquivo de conector em `src/connectors/`.
4.  Adicione seu arquivo de teste em `tests/connectors/`.
5.  Certifique-se de que todos os testes estão passando (`uv run pytest`).
6.  Execute as verificações de lint e formatação (`uv run ruff check .` e `uv run ruff format .`).
7.  Faça "commit" das suas alterações com uma mensagem clara.
8.  Faça "push" da sua branch para o seu fork.
9.  Abra um "Pull Request" (PR) para o repositório principal do Leizilla.
    *   No PR, descreva a fonte de dados que seu conector cobre.
    *   Mencione quaisquer particularidades ou desafios encontrados.
    *   Se possível, forneça exemplos de URLs ou como a fonte de dados funciona.

A equipe do Leizilla revisará seu PR, fornecerá feedback e, uma vez aprovado, integrará seu conector ao projeto. Obrigado por sua contribuição!
