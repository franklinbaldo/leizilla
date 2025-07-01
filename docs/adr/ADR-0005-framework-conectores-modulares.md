# ADR-0005: Framework de Conectores Modulares para Coleta de Dados

**Status:** Proposto

**Contexto:**

O Leizilla precisa coletar atos normativos de diversas fontes (nível federal, estadual, municipal), cada uma com seu próprio portal, estrutura de dados e método de acesso. Uma abordagem monolítica para a coleta seria difícil de manter e escalar. É necessária uma arquitetura que permita adicionar suporte a novas fontes de forma rápida e isolada.

**Decisão:**

Implementaremos um Framework de Conectores Modulares. Cada fonte de dados será suportada por um "Conector" individual, que é uma classe Python responsável pela lógica específica de descoberta e download para aquela fonte.

**Detalhes da Arquitetura:**

1.  **Interface Base (`BaseConnector`):**
    *   Localização: `src/connectors/base.py`
    *   Define uma classe abstrata `BaseConnector` com métodos que todos os conectores concretos devem implementar.
    *   Métodos Abstratos Principais:
        *   `async discover_laws(self, **kwargs) -> List[Dict[str, Any]]`: Responsável por encontrar novos atos normativos na fonte e retornar uma lista de dicionários com seus metadados. Aceita `**kwargs` para permitir passagem de parâmetros específicos do monitor ou CLI (ex: `last_processed_marker`, `limit`).
        *   `async download_pdf(self, law_metadata: Dict[str, Any], output_path: Path) -> bool`: Responsável por baixar o arquivo PDF de um ato normativo específico, dado seus metadados e um caminho de saída. Retorna `True` em sucesso, `False` em falha.
    *   Atributo de Classe Obrigatório:
        *   `ORIGEM` (str): Um identificador único em minúsculas para a fonte de dados que o conector gerencia (ex: `"rondonia"`, `"alagoas"`). Este ID é usado para referenciar o conector no CLI, no banco de dados e nos logs.

2.  **Estrutura de Diretório dos Conectores:**
    *   Todos os arquivos de conectores residirão em `src/connectors/`.
    *   Cada conector será implementado em seu próprio arquivo Python (ex: `src/connectors/rondonia.py`, `src/connectors/acre.py`).
    *   O nome do arquivo deve corresponder (ou ser similar) ao `ORIGEM` do conector.

3.  **Carregamento Dinâmico de Conectores:**
    *   O CLI do Leizilla (especificamente em `src/cli.py`) implementa uma função `load_connectors()` que varre o diretório `src/connectors/` na inicialização.
    *   Ele importa dinamicamente cada módulo Python encontrado (que não comece com `_` e não seja `base.py`).
    *   Dentro de cada módulo, procura por classes que herdem de `BaseConnector`.
    *   Instancia cada classe de conector encontrada e a armazena em um dicionário global, mapeando o `ORIGEM` do conector para sua instância.
    *   Uma função `get_connector(origem: str)` permite que outras partes do sistema (como os comandos do CLI) obtenham uma instância de um conector carregado pelo seu `ORIGEM`.

4.  **Ferramentas de Desenvolvimento de Conectores (CLI):**
    *   `leizilla connector list`: Lista todos os conectores carregados dinamicamente, mostrando sua `ORIGEM`, nome da classe e módulo.
    *   `leizilla connector new --name <nome_origem>`: Gera um arquivo de esqueleto (`.py`) para um novo conector, já com a estrutura da classe, o atributo `ORIGEM` preenchido, e os métodos `discover_laws` e `download_pdf` prontos para implementação. Isso acelera o desenvolvimento de novos conectores.

5.  **Estratégia de Extensibilidade:**
    *   Para adicionar suporte a uma nova fonte de dados, um desenvolvedor precisa:
        1.  Usar `leizilla connector new --name nova_fonte` para criar o arquivo do conector.
        2.  Implementar a lógica de scraping/coleta em `discover_laws` para a `nova_fonte`.
        3.  Implementar a lógica de download de PDF em `download_pdf` para a `nova_fonte`.
        4.  (Idealmente) Escrever testes para o novo conector em `tests/connectors/`.
    *   Uma vez que o arquivo do conector é adicionado a `src/connectors/`, o sistema de carregamento dinâmico o tornará automaticamente disponível para uso pelo Leizilla (ex: via `leizilla discover --origem nova_fonte` ou pelo comando `leizilla monitor`).

**Motivação:**

*   **Modularidade:** Isola a lógica de cada fonte de dados, tornando o código mais fácil de entender, manter e testar.
*   **Extensibilidade:** Simplifica significativamente o processo de adicionar novas fontes. Desenvolvedores podem focar apenas na lógica específica da nova fonte sem precisar entender profundamente o núcleo do Leizilla.
*   **Manutenibilidade:** Se a forma de acesso a uma fonte de dados mudar, apenas o conector correspondente precisa ser atualizado.
*   **Contribuição da Comunidade:** Uma arquitetura de conectores clara e ferramentas de scaffolding (como `connector new`) reduzem a barreira para contribuições da comunidade.
*   **Paralelização Futura:** Embora não seja o foco inicial, uma arquitetura baseada em conectores independentes facilita a execução paralela da coleta de diferentes fontes no futuro.

**Consequências:**

*   **Contrato da Interface:** A estabilidade da interface `BaseConnector` é crucial. Mudanças nela podem exigir atualizações em todos os conectores existentes.
*   **Desafios de Conectores Complexos:** Algumas fontes podem ser particularmente difíceis de scrapear (ex: requerem JavaScript pesado, CAPTCHAs, logins complexos). A interface `BaseConnector` deve ser flexível o suficiente, e os conectores podem precisar de bibliotecas adicionais (ex: Playwright, soluções anti-CAPTCHA).
*   **Gerenciamento de Dependências Específicas de Conectores:** Se um conector necessitar de uma biblioteca pesada não usada por outros (ex: uma biblioteca específica de uma API governamental), isso adiciona essa dependência ao projeto como um todo. (Mitigação: Poderia-se explorar "extras" opcionais no `pyproject.toml` para dependências de conectores muito específicos no futuro, se isso se tornar um problema).
*   **Descoberta de Parâmetros Específicos:** A passagem de `**kwargs` para `discover_laws` é flexível, mas não há um mecanismo padronizado para um conector declarar quais parâmetros específicos ele aceita. Isso pode exigir documentação por conector ou convenções.

**Alternativas Consideradas:**

*   **Configuração Baseada em JSON/YAML para Scrapers Genéricos:** Tentar definir regras de scraping em arquivos de configuração para um motor genérico. Considerado muito limitado para a variedade e complexidade das fontes governamentais.
*   **Abordagem Monolítica:** Ter toda a lógica de coleta em uma única grande classe ou módulo. Rejeitada por falta de escalabilidade e manutenibilidade.

Este framework de conectores é fundamental para a estratégia de longo prazo do Leizilla de se tornar uma plataforma abrangente de indexação de atos normativos, capaz de se adaptar e crescer com a ajuda da comunidade.
