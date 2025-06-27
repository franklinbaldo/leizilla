# Configuração de Integração Contínua (CI)

## Objetivo

Automatizar o processo de build, teste e verificação de qualidade do código do Projeto XYZ a cada alteração (push ou pull request), garantindo que o código na branch principal seja sempre estável e que os padrões de desenvolvimento sejam seguidos.

## Ferramenta de CI Escolhida

*   **Opção Principal:** GitHub Actions (devido à integração nativa com o GitHub, facilidade de configuração para projetos hospedados no GitHub e um generoso plano gratuito para projetos públicos e privados).
*   **Alternativas (a considerar se houver requisitos específicos):** Jenkins, GitLab CI/CD, CircleCI, Travis CI.

## Pipeline de CI Proposto (GitHub Actions)

O pipeline será definido em um arquivo YAML na pasta `.github/workflows/ci.yml`.

**Eventos de Gatilho:**

*   `push` para as branches `main` (ou `master`) e `develop`.
*   `pull_request` para a branch `main` (ou `master`).

**Jobs:**

1.  **`lint_and_format` (Linting e Formatação):**
    *   **Passos:**
        1.  Checkout do código.
        2.  Configurar o ambiente da linguagem principal (ex: Node.js, Python).
        3.  Instalar dependências.
        4.  Executar o linter (ex: ESLint, Flake8, Pylint).
        5.  Executar o verificador de formatação (ex: Prettier --check, Black --check).
    *   **Objetivo:** Garantir que o código adere aos padrões de estilo e formatação definidos no `CONTRIBUTING.md`. Falhar se houver erros de linting ou formatação.

2.  **`unit_tests` (Testes Unitários):**
    *   **Depende de:** `lint_and_format` (opcional, mas recomendado para falhar rápido se a formatação estiver errada).
    *   **Matriz de Estratégia (Opcional):** Pode rodar testes em diferentes versões da linguagem ou sistemas operacionais, se necessário.
        ```yaml
        strategy:
          matrix:
            node-version: [16.x, 18.x] # Exemplo para Node.js
            # python-version: [3.8, 3.9, 3.10] # Exemplo para Python
            os: [ubuntu-latest] # , windows-latest, macos-latest
        ```
    *   **Passos:**
        1.  Checkout do código.
        2.  Configurar o ambiente da linguagem principal (usando a versão da matriz, se aplicável).
        3.  Instalar dependências.
        4.  Executar os testes unitários (ex: `npm test`, `pytest`).
        5.  (Opcional) Fazer upload dos artefatos de cobertura de teste (ex: para Codecov, Coveralls).
    *   **Objetivo:** Garantir que todas as unidades de código funcionam conforme o esperado e que não há regressões. Falhar se algum teste não passar.

3.  **`build_project` (Build do Projeto - se aplicável):**
    *   **Depende de:** `unit_tests`.
    *   **Aplicável para:** Projetos que precisam de um passo de compilação ou empacotamento (ex: frontend com Webpack/Rollup, Java com Maven/Gradle, Go).
    *   **Passos:**
        1.  Checkout do código.
        2.  Configurar o ambiente da linguagem/build.
        3.  Instalar dependências.
        4.  Executar o comando de build (ex: `npm run build`, `mvn package`).
        5.  (Opcional) Arquivar os artefatos de build para download ou deploy.
    *   **Objetivo:** Garantir que o projeto pode ser construído/compilado com sucesso.

4.  **`security_scan` (Verificação de Segurança - Opcional, mas Recomendado):**
    *   **Depende de:** `unit_tests` (ou `build_project` se o scan for no artefato).
    *   **Ferramentas:**
        *   Análise Estática de Segurança de Aplicação (SAST) - ex: Snyk, SonarQube (com SonarScanner), CodeQL (do GitHub).
        *   Verificação de dependências vulneráveis - ex: `npm audit`, `pip-audit`, Snyk, Dependabot (do GitHub).
    *   **Passos:**
        1.  Checkout do código.
        2.  Configurar a ferramenta de scan.
        3.  Executar o scan.
    *   **Objetivo:** Identificar potenciais vulnerabilidades de segurança no código ou nas dependências. Pode ser configurado para apenas avisar ou para falhar o build dependendo da criticidade.

## Configuração Detalhada (Exemplo GitHub Actions - `.github/workflows/ci.yml`)

```yaml
name: CI Pipeline XYZ

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main ]

jobs:
  lint_and_format:
    name: Lint and Format Check
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Set up Node.js # Mudar para a linguagem do projeto
        uses: actions/setup-node@v3
        with:
          node-version: '18' # Mudar versão conforme necessário
          cache: 'npm' # Mudar para pip, etc.
      - name: Install dependencies
        run: npm install # Mudar para pip install -r requirements.txt, etc.
      - name: Run Linter
        run: npm run lint # Mudar para o comando do linter
      - name: Check Formatting
        run: npm run format:check # Mudar para o comando de verificação de formatação

  unit_tests:
    name: Unit Tests
    needs: lint_and_format # Opcional, pode rodar em paralelo
    runs-on: ${{ matrix.os || 'ubuntu-latest' }}
    strategy:
      fail-fast: false # Continuar outros jobs da matriz mesmo se um falhar
      matrix:
        # Exemplo para Node.js - ajuste para sua linguagem/necessidades
        node-version: [16.x, 18.x]
        os: [ubuntu-latest]
        # Exemplo para Python
        # python-version: ['3.8', '3.9', '3.10']
        # os: [ubuntu-latest]

    steps:
      - uses: actions/checkout@v3
      - name: Set up Environment (e.g., Python ${{ matrix.python-version }})
        # Exemplo para Python:
        # uses: actions/setup-python@v4
        # with:
        #   python-version: ${{ matrix.python-version }}
        #   cache: 'pip'
        # Exemplo para Node.js:
        uses: actions/setup-node@v3
        with:
          node-version: ${{ matrix.node-version }}
          cache: 'npm'
      - name: Install dependencies
        # Exemplo para Python:
        # run: |
        #   python -m pip install --upgrade pip
        #   pip install -r requirements.txt
        #   pip install pytest # ou o que for usado para testes
        # Exemplo para Node.js:
        run: npm install
      - name: Run Unit Tests
        # Exemplo para Python:
        # run: pytest
        # Exemplo para Node.js:
        run: npm test
      # - name: Upload coverage reports to Codecov
      #   uses: codecov/codecov-action@v3
      #   with:
      #     token: ${{ secrets.CODECOV_TOKEN }} # Adicionar ao GitHub Secrets
      #     files: ./coverage/clover.xml,./coverage/cobertura-coverage.xml # Ajustar caminhos
      #     fail_ci_if_error: true

  # build_project: # Descomente e ajuste se o projeto tiver um passo de build
  #   name: Build Project
  #   needs: unit_tests
  #   runs-on: ubuntu-latest
  #   steps:
  #     - uses: actions/checkout@v3
  #     - name: Set up Node.js # Ajustar para a linguagem/ferramenta de build
  #       uses: actions/setup-node@v3
  #       with:
  #         node-version: '18'
  #         cache: 'npm'
  #     - name: Install dependencies
  #       run: npm install
  #     - name: Build
  #       run: npm run build
  #     - name: Upload build artifact (opcional)
  #       uses: actions/upload-artifact@v3
  #       with:
  #         name: build-output
  #         path: ./dist # Ajustar para o diretório de output do build

  # security_scan: # Descomente e ajuste para adicionar verificações de segurança
  #   name: Security Scan
  #   needs: unit_tests # ou build_project
  #   runs-on: ubuntu-latest
  #   steps:
  #     - uses: actions/checkout@v3
  #     - name: Run Snyk to check for vulnerabilities
  #       uses: snyk/actions/node@master # Escolha a ação Snyk apropriada para sua linguagem
  #       env:
  #         SNYK_TOKEN: ${{ secrets.SNYK_TOKEN }} # Adicionar ao GitHub Secrets
  #       with:
  #         command: monitor # ou 'test' para falhar o build em vulnerabilidades
  #         args: --all-projects --org=seu-org-snyk
```

## Passos de Implementação

1.  **Escolher a Ferramenta de CI:** Confirmar o uso do GitHub Actions ou selecionar outra.
2.  **Criar o Arquivo de Workflow:** Adicionar `.github/workflows/ci.yml` ao repositório.
3.  **Configurar o Job de Linting/Formatação:**
    *   Adicionar os scripts necessários ao `package.json` ou `Makefile`, etc.
    *   Configurar o passo no workflow.
4.  **Configurar o Job de Testes Unitários:**
    *   Garantir que os comandos de teste estejam funcionando localmente.
    *   Configurar o passo no workflow, incluindo matrizes se necessário.
    *   (Opcional) Configurar upload de cobertura de testes.
5.  **Configurar o Job de Build (se aplicável):**
    *   Adicionar scripts de build.
    *   Configurar o passo no workflow.
6.  **Configurar Verificações de Segurança (Opcional):**
    *   Criar contas nas plataformas de segurança (ex: Snyk, SonarCloud).
    *   Adicionar tokens/chaves como "Secrets" no GitHub.
    *   Configurar os passos no workflow.
7.  **Testar o Pipeline:** Fazer um push para uma branch de teste ou abrir um PR para verificar se o pipeline é acionado e executado corretamente.
8.  **Proteger a Branch Principal:** Configurar regras de proteção de branch no GitHub para exigir que os checks de CI passem antes de permitir o merge para `main`.

## Benefícios

*   Feedback rápido sobre a qualidade do código.
*   Detecção precoce de bugs e regressões.
*   Consistência nos padrões de código.
*   Redução do risco de integrar código defeituoso na branch principal.
*   Automação de tarefas repetitivas.
*   Maior confiança para refatorar e adicionar novas funcionalidades.

Este plano de configuração de CI ajudará o Projeto XYZ a manter um alto padrão de qualidade e estabilidade.
