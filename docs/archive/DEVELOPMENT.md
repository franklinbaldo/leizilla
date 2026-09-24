> [!WARNING]
> **ARQUIVADO** (2026-09-24): guia pré-M1 — layout `src/` flat, CLI com flags
> mortas (`--origem`, `download`/`upload` sem `--ente`), schema `leis` de
> ADR-0003 hoje superado pelo modelo dispositivo-cêntrico de
> [`docs/SCHEMA.md`](../SCHEMA.md). Setup de desenvolvimento e comandos
> atuais vivem em [`CLAUDE.md`](../../CLAUDE.md) (seção "Development setup" /
> "Everyday commands" / "CLI reference"). Movido de `docs/` para
> `docs/archive/` conforme
> [RFC-0002 — Governança documental](../rfc/0002-governanca-documental.md).
> Preservado como histórico; conteúdo original intacto abaixo.

# 🛠️ Development Guide

Guia técnico para desenvolvimento diário no Leizilla.

## 📁 Estrutura de Pastas

```
leizilla/
├── src/                    # Código fonte (flat structure)
│   ├── config.py          # Configurações centralizadas
│   ├── crawler.py         # Playwright crawling
│   ├── storage.py         # Operações DuckDB
│   ├── publisher.py       # Upload para Internet Archive
│   └── cli.py             # Interface linha de comando
├── tests/                  # Testes unitários
│   ├── test_storage.py    # Testes do storage
│   └── test_crawler.py    # Testes do crawler
├── data/                   # Dados locais (gitignored)
│   ├── .gitkeep
│   ├── leizilla.duckdb    # Banco local (criado automaticamente)
│   └── temp/              # PDFs temporários
├── docs/                   # Documentação
│   ├── adr/               # Architecture Decision Records
│   └── DEVELOPMENT.md     # Este guia
├── .env.example           # Template de variáveis de ambiente
├── pyproject.toml         # Configuração Python
└── cli.py               # Interface linha de comando
```

## 🗃️ DuckDB Local

### **Localização**

- **Path**: `data/leizilla.duckdb` (será criado automaticamente)
- **Gitignore**: Incluído, não será commitado
- **Backup**: Via Internet Archive (futuro)

### **Schema Definido** (conforme ADR-0003)

```sql
-- Tabela principal de leis
CREATE TABLE leis (
  id VARCHAR PRIMARY KEY,                    -- "rondonia-lei-2025-001"
  titulo TEXT NOT NULL,
  numero VARCHAR,
  ano INTEGER,
  data_publicacao DATE,
  tipo_lei VARCHAR,                          -- "lei", "decreto", "portaria"
  origem VARCHAR NOT NULL,                   -- "rondonia", "federal", etc.
  texto_completo TEXT,                       -- OCR do Internet Archive
  texto_normalizado TEXT,                    -- Texto limpo para busca
  metadados JSON,                           -- Metadados flexíveis
  url_original VARCHAR,
  url_pdf_ia VARCHAR,                       -- URL do PDF no IA
  hash_conteudo VARCHAR,                    -- SHA-256 para deduplicação
  status VARCHAR DEFAULT 'ativo',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Índices principais
CREATE INDEX idx_leis_origem ON leis(origem);
CREATE INDEX idx_leis_ano ON leis(ano);
CREATE INDEX idx_leis_data ON leis(data_publicacao);
CREATE INDEX idx_leis_tipo ON leis(tipo_lei);
```

### **Comandos DuckDB Úteis**

```bash
# Entrar no DuckDB interativo
duckdb data/leizilla.duckdb

# Verificar tabelas
.tables

# Ver schema
.schema leis

# Exportar para Parquet
COPY leis TO 'data/leis_rondonia_2025.parquet' (FORMAT PARQUET)
WHERE origem = 'rondonia' AND ano = 2025;

# Busca por texto
SELECT id, titulo, ano FROM leis
WHERE texto_normalizado LIKE '%meio ambiente%';

# Estatísticas básicas
SELECT origem, COUNT(*) as total FROM leis GROUP BY origem;
```

## 🌐 Variáveis de Ambiente

Crie `.env` na raiz do projeto:

```bash
# Internet Archive (para upload e OCR)
IA_ACCESS_KEY=your_access_key
IA_SECRET_KEY=your_secret_key

# Opcional: configuração de crawler
CRAWLER_DELAY=2000  # ms entre requests
CRAWLER_RETRIES=3
CRAWLER_TIMEOUT=30000  # ms

# Opcional: configuração DuckDB
DUCKDB_PATH=data/leizilla.duckdb
```

**Nunca commite `.env`!** Ele está no `.gitignore`.

## 🖥️ Interface de Linha de Comando

O Leizilla possui uma CLI completa para todas as operações. Existem **duas formas** de executar comandos:

### **Método 1: Comandos uv diretos (recomendado)**

Sempre funcionam, não precisam de ambiente ativo:

```bash
# Descobrir leis (crawling)
uv run leizilla discover --origem rondonia --year 2024

# Baixar PDFs descobertos
uv run leizilla download --origem rondonia --limit 10

# Upload para Internet Archive
uv run leizilla upload --limit 5

# Exportar dataset
uv run leizilla export --origem rondonia --year 2024

# Buscar leis no banco
uv run leizilla search --origem rondonia --text "meio ambiente"

# Estatísticas
uv run leizilla stats
```

### **CLI com Subcomandos**

Interface moderna com argumentos nomeados:

```bash
# Comandos do pipeline (argumentos explícitos)
uv run leizilla discover --origem rondonia --year 2024
uv run leizilla download --origem rondonia --limit 10
uv run leizilla upload --limit 5
uv run leizilla export --origem rondonia --year 2024
uv run leizilla pipeline --origem rondonia --year 2024 --limit 10
```

## ⚡ Scripts de Desenvolvimento

O projeto usa CLI moderna com Typer, sem dependências externas de build tools.

### **Comandos de Desenvolvimento**

```bash
# Setup inicial (rode uma vez)
uv run leizilla dev setup         # Instala deps + pre-commit hooks

# Qualidade de código
uv run leizilla dev check         # Roda tudo: lint + format + typecheck + test
uv run leizilla dev lint          # Verificar problemas (ruff check)
uv run leizilla dev format        # Aplicar formatação (ruff format)
uv run leizilla dev test          # Executar testes (pytest)
```

### **Comandos Diretos (alternativos)**

```bash
# Usar ferramentas diretamente quando necessário
uv run ruff check .               # Lint direto
uv run ruff format .              # Formatação direta
uv run mypy .                     # Type checking direto
uv run pytest                     # Testes diretos
```

### **Vantagens da CLI Typer**

- ✅ **Interface moderna**: Help automático com `--help`
- ✅ **Tipo-segura**: Validação automática de argumentos
- ✅ **Zero configuração**: Sem arquivos extras de build
- ✅ **Subcomandos**: Organização clara (`dev`, `pipeline`)
- ✅ **Portabilidade**: Funciona em qualquer máquina com uv

## 🔍 Debug & Logs

### **Logging Básico**

```python
import logging

# Configure no módulo principal
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)
logger.info("Processando PDF: %s", filename)
```

### **Debug Crawler**

```bash
# Debug de descoberta com apenas 1 resultado
uv run leizilla discover --origem rondonia --year 2024

# Debug de download com limite baixo
uv run leizilla download --origem rondonia --limit 1

# Salvar logs
uv run leizilla discover --origem rondonia 2>&1 | tee logs/crawler.log
```

### **Debug DuckDB**

```python
import duckdb

# Enable query profiling
conn = duckdb.connect('data/leizilla.duckdb')
conn.execute("PRAGMA enable_profiling")
conn.execute("PRAGMA profiling_output = 'query_profile.json'")
```

## 📝 Como Adicionar ADR

1. **Crie arquivo numerado**:

   ```bash
   cp docs/adr/0001-projeto-estatico-duckdb-torrent.md \
      docs/adr/000X-sua-decisao.md
   ```

2. **Edite conteúdo**:
   - Contexto claro do problema
   - Alternativas consideradas
   - Decisão tomada e justificativa
   - Consequências esperadas

3. **Link no PR**:

   ```markdown
   ## ADR

   Esta PR implementa a decisão da ADR-000X: [Título](docs/adr/000X-sua-decisao.md)
   ```

## 📊 Diagramas Mermaid

### **Fluxo de Dados Completo**

```mermaid
graph TD
    A[Fonte Oficial] --> B[Playwright Crawler]
    B --> C[PDF Download]
    C --> D[Internet Archive Upload]
    D --> E[OCR Automático]
    E --> F[DuckDB ETL]
    F --> G[Parquet Export]
    G --> H[GitHub Release]
    G --> I[Torrent P2P]
    H --> J[DuckDB-WASM Frontend]
    I --> J
```

### **Arquitetura de Componentes** (futuro)

```mermaid
graph LR
    subgraph "Local Development"
        A[Crawler] --> B[DuckDB]
        B --> C[Exporter]
    end

    subgraph "Internet Archive"
        D[PDF Storage]
        E[OCR Service]
        F[Shared Database]
    end

    subgraph "Distribution"
        G[GitHub Releases]
        H[Torrents]
        I[Static Frontend]
    end

    C --> D
    D --> E
    E --> F
    F --> G
    F --> H
    G --> I
    H --> I
```

## 🧪 Testes & Qualidade

### **Estrutura de Testes**

```
tests/
├── test_crawler.py        # Testes do crawler
├── test_extractor.py      # Testes de extração
├── test_database.py       # Testes DuckDB
├── conftest.py           # Fixtures pytest
└── fixtures/             # Dados de teste
    ├── sample.pdf
    └── expected_output.json
```

### **Mocking APIs Externas**

```python
import pytest
from unittest.mock import Mock, patch

@patch('requests.get')
def test_download_pdf(mock_get):
    mock_get.return_value.content = b'fake pdf content'
    # test implementation
```

### **Testes de Performance**

```python
import pytest
import time

@pytest.mark.performance
def test_duckdb_query_speed():
    start = time.time()
    # execute query
    duration = time.time() - start
    assert duration < 1.0  # Should be under 1 second
```

## 🚀 CI/CD Pipeline

### **GitHub Actions**

- **Lint**: ruff check + format
- **Type Check**: mypy
- **Tests**: pytest com coverage
- **Build**: Verificar se package instala

### **Comandos Locais**

```bash
# Simular CI completo
uv run leizilla dev check

# Individual
uv run leizilla dev lint      # ruff check
uv run leizilla dev format    # ruff format
uv run leizilla dev test      # pytest

# Diretos
uv run mypy .                 # type checking direto
```

## 📚 Referências Úteis

### **Tecnologias Core**

- [DuckDB Python API](https://duckdb.org/docs/api/python/overview)
- [Playwright Python](https://playwright.dev/python/)
- [uv Package Manager](https://github.com/astral-sh/uv)
- [Internet Archive CLI](https://archive.org/developers/internetarchive/)

### **ADRs Existentes**

- [ADR-0001: Internet Archive como Pilar Central](../adr/0001-projeto-estatico-duckdb-torrent.md)
- [ADR-0002: Frontend Estático Vanilla](../adr/0002-frontend-estatico-vanilla.md)
- [ADR-0003: Schema DuckDB para Leis](../adr/0003-schema-duckdb-leis.md)

### **Padrões do Projeto**

- **Conventional Commits**: `feat`, `fix`, `docs`, `style`, `refactor`, `test`
- **Python Style**: ruff defaults + type hints obrigatórios
- **File Organization**: src-layout com flat structure

---

## 🔧 Troubleshooting

### **uv não funciona**

```bash
# Instalar uv
curl -LsSf https://astral.sh/uv/install.sh | sh
# ou
pip install uv
```

### **DuckDB locked**

```bash
# Verificar processos
lsof data/leizilla.duckdb
# Matar se necessário
kill <PID>
```

### **Playwright não instala browsers**

```bash
uv run playwright install
```

### **Testes falham por timeout**

```bash
# Aumentar timeout
uv run pytest --timeout=60
```

Este guia será atualizado conforme o projeto evolui. Sempre consulte a versão mais recente no repositório.
