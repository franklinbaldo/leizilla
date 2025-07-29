# ADR 0004: Avaliação do uso de `dlt` (Data Load Tool)

**Data:** 2025-07-28
**Status:** Proposto
**Responsáveis:** Jules

## Contexto

### Problema Identificado

O pipeline de dados do Leizilla, embora funcional, é customizado e pode se tornar complexo de manter e extender. O `crawler.py` e o `storage.py` contém lógicas específicas para extração e armazenamento de dados que poderiam ser substituídas por uma ferramenta mais robusta e padronizada.

### O que é `dlt`?

`dlt` (Data Load Tool) é uma biblioteca Python de código aberto que simplifica a criação de pipelines de dados. Ela oferece:

*   **Extração de dados simplificada**: Suporte para APIs REST, bancos de dados SQL, arquivos e fontes customizadas.
*   **Inferência e evolução de schema**: `dlt` detecta automaticamente o schema dos dados e o adapta a mudanças.
*   **Normalização de dados**: Transforma dados semi-estruturados (como JSONs aninhados) em tabelas relacionais.
*   **Carregamento para múltiplos destinos**: Suporte nativo para DuckDB, PostgreSQL, BigQuery, etc.
*   **Manutenção automatizada**: Lida com carregamento incremental, contratos de dados e alertas.

## Decisão

### Proposta: Adotar `dlt` para o Pipeline de Dados

Propõe-se a adoção do `dlt` para substituir partes do pipeline de dados atual do Leizilla, especificamente as responsabilidades de `crawler.py` e `storage.py`.

#### 1. **Substituição do Crawler**

O crawler customizado em `crawler.py` seria substituído por uma fonte `dlt`. Como as fontes de dados do Leizilla são sites governamentais que exigem Playwright, criaríamos um `dlt.resource` customizado que encapsula a lógica do Playwright.

**Exemplo de implementação:**

```python
import dlt
from dlt.sources.helpers import requests
from playwright.sync_api import sync_playwright

@dlt.resource(name="leis_rondonia")
def get_leis_rondonia(start_coddoc: int, end_coddoc: int):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        for coddoc in range(start_coddoc, end_coddoc + 1):
            # Lógica do crawler atual para extrair os dados da lei
            lei_data = extrair_dados_lei(page, coddoc)
            if lei_data:
                yield lei_data
        browser.close()

def extrair_dados_lei(page, coddoc):
    # ... lógica de extração com Playwright ...
    return {"coddoc": coddoc, "titulo": "...", ...}

```

#### 2. **Simplificação do Armazenamento**

A lógica de criação de tabelas, inserção e atualização de dados em `storage.py` seria substituída pelo `dlt.pipeline`.

**Exemplo de implementação:**

```python
import dlt

# Configuração do pipeline dlt
pipeline = dlt.pipeline(
    pipeline_name="leizilla_rondonia",
    destination="duckdb",
    dataset_name="leis"
)

# Fonte de dados
leis_resource = get_leis_rondonia(start_coddoc=1, end_coddoc=100)

# Execução do pipeline
load_info = pipeline.run(leis_resource)

print(load_info)
```

`dlt` cuidaria de:

*   Criar a tabela `leis_rondonia` no DuckDB se ela não existir.
*   Inferir o schema da tabela a partir dos dados retornados por `get_leis_rondonia`.
*   Inserir os novos dados na tabela.
*   Adicionar metadados de carregamento para rastreabilidade.

## Alternativas Consideradas

### 1. **Manter a Implementação Atual**

*   **Prós**: Já está funcionando, sem novas dependências.
*   **Contras**: Maior custo de manutenção, menos robustez, reinventa a roda de funcionalidades que `dlt` já oferece.
*   **Rejeitado**: A longo prazo, a complexidade de manter uma solução customizada supera os benefícios de não adicionar uma nova dependência.

### 2. **Usar outras ferramentas de ETL (e.g., Airflow, Prefect)**

*   **Prós**: Ferramentas poderosas e flexíveis.
*   **Contras**: Mais complexas de configurar e manter, overkill para o escopo do Leizilla.
*   **Rejeitado**: `dlt` oferece um bom equilíbrio entre simplicidade e poder, alinhado com a filosofia do projeto.

## Consequências

### **Positivas**

*   **Redução de código customizado**: Menos código para manter, testar e documentar.
*   **Maior robustez**: `dlt` é uma biblioteca testada e mantida pela comunidade, com funcionalidades de tratamento de erros e retentativas.
*   **Facilidade de extensão**: Adicionar novas fontes de dados ou destinos se torna mais simples.
*   **Melhoria na qualidade dos dados**: `dlt` oferece contratos de dados para garantir a qualidade e o formato dos dados.
*   **Transparência**: `dlt` gera metadados sobre os carregamentos, o que aumenta a transparência do pipeline.

### **Negativas**

*   **Nova dependência**: Adiciona o `dlt` como uma nova dependência do projeto.
*   **Curva de aprendizado**: A equipe precisará aprender a usar o `dlt`.
*   **Refatoração**: Exige um esforço inicial para refatorar o código existente.

### **Mitigações**

*   A documentação do `dlt` é extensa e a comunidade é ativa.
*   A refatoração pode ser feita de forma incremental, começando com uma fonte de dados.

## Plano de Implementação

### **Fase 1: Prova de Conceito**

1.  Criar um novo script em `scripts/` para um pipeline com `dlt` para uma das fontes de dados (e.g., Rondônia).
2.  Validar que o `dlt` consegue extrair e carregar os dados corretamente no DuckDB.
3.  Comparar o resultado com o pipeline atual.

### **Fase 2: Refatoração**

1.  Substituir o `crawler.py` e o `storage.py` pela implementação com `dlt`.
2.  Atualizar a CLI em `cli.py` para usar o novo pipeline.
3.  Atualizar a documentação do projeto.

### **Fase 3: Extensão**

1.  Usar `dlt` para adicionar novas fontes de dados.
2.  Explorar funcionalidades avançadas do `dlt`, como carregamento incremental e contratos de dados.

## Conclusão

A adoção do `dlt` representa um investimento inicial em refatoração que trará benefícios significativos a longo prazo em termos de manutenibilidade, robustez e escalabilidade do pipeline de dados do Leizilla. A proposta está alinhada com a filosofia do projeto de usar ferramentas modernas e eficientes para resolver problemas complexos de dados.
