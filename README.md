# 🦖 **Leizilla**

> **O dinossauro que devora PDFs jurídicos e cospe dados abertos.**

Sistema de indexação de documentos legais brasileiros que **já funciona**. Projeto-irmão do **CausaGanha**, com foco exclusivo em **indexar todas as leis brasileiras**, começando por **Rondônia**. Infra mínima, transparência radical e 100% estático — sem servidores, sem backend para manter.

---

## ✅ Estado atual

**MVP Funcional**: Pipeline completo implementado com crawler, armazenamento DuckDB, upload para Internet Archive e exportação de datasets.

### 🚀 O que já funciona:

- ✅ **CLI completa** com comandos discover/download/upload/export/search
- ✅ **Crawler assíncrono** com Playwright para sites governamentais
- ✅ **Schema DuckDB** completo com operações CRUD
- ✅ **Integração Internet Archive** para OCR gratuito e distribuição
- ✅ **Exportação Parquet/JSONL** para datasets abertos
- ✅ **CLI moderna** com Typer e subcomandos
- ✅ **Ambiente de desenvolvimento** com type checking e linting

---

## 🛠️ Stack implementada

| Domínio           | Ferramenta / Serviço         | Status                                               |
| ----------------- | ---------------------------- | ---------------------------------------------------- |
| **Linguagem**     | **Python 3.12**              | ✅ Implementado                                      |
| **Crawling**      | **Playwright** + **AnyIO**   | ✅ Crawler assíncrono funcional                      |
| **ETL & Storage** | **DuckDB**                   | ✅ Schema completo + CRUD                            |
| **Backup & OCR**  | **Internet Archive**         | ✅ Upload e integração                               |
| **Distribuição**  | **Parquet** + **JSON Lines** | ✅ Exportação implementada                           |
| **Build & CI**    | **GitHub Actions** + **uv**  | ✅ Scripts automatizados (linting, Rondônia crawler) |
| **Dependências**  | **uv**                       | ✅ Ambiente configurado                              |
| **Qualidade**     | **ruff** + **mypy**          | ✅ Linting e tipos                                   |

---

## 🤖 CI/CD (GitHub Actions)

O projeto utiliza GitHub Actions para automação de tarefas:

1.  **Linting**: A cada push ou pull request para a branch `main`, o código é verificado com Ruff (linter e formatter) e Mypy (type checking). Veja o workflow em `.github/workflows/lint.yml`.
2.  **Rondônia Law Crawler**:
    - **O quê**: Este workflow automatizado descobre novas leis no portal de Rondônia, baixa os PDFs correspondentes e os envia para o Internet Archive.
    - **Quando**: Roda semanalmente (todos os domingos à meia-noite UTC) e pode ser disparado manualmente.
    - **Arquivo**: `.github/workflows/rondonia_crawler.yml`
    - **Scripts principais**:
      - `scripts/run_rondonia_crawler.py`: Handles crawling laws and uploading them.
      - `scripts/backup_database.py`: Handles backing up the `leizilla.duckdb` database file.
    - **Configuração (Requerido)**: Para que o upload para o Internet Archive funcione, os seguintes secrets precisam ser configurados no repositório GitHub (`Settings > Secrets and variables > Actions`):
      - `IA_ACCESS_KEY`: Sua chave de acesso do Internet Archive.
      - `IA_SECRET_KEY`: Sua chave secreta do Internet Archive.
    - **Funcionamento**:
      - O script `run_rondonia_crawler.py` utiliza `LeisCrawler` para buscar leis (atualmente configurado para um pequeno range de `coddoc` IDs para demonstração) e `InternetArchivePublisher` para o upload dos PDFs.
      - Em seguida, o script `backup_database.py` é executado. Ele primeiro tenta realizar um `CHECKPOINT` no DuckDB para garantir consistência, e depois usa `InternetArchivePublisher` para fazer upload do arquivo `data/leizilla.duckdb` para uma coleção dedicada no Internet Archive (atualmente `leizilla-database-backups`). Este passo de backup é configurado para tentar rodar mesmo que o passo de crawling de leis falhe.
      - A configuração de `PYTHONPATH` no workflow garante que os módulos em `src/` sejam encontrados por ambos os scripts.

---

## 🌐 Pipeline implementado

1. **Descoberta**: `uv run leizilla discover --origem rondonia --start-coddoc 1 --end-coddoc 10` - encontra leis no portal oficial
2. **Download**: `uv run leizilla download --origem rondonia --limit 5` - baixa PDFs para processamento local
3. **Upload IA**: `uv run leizilla upload --limit 3` - envia para Internet Archive (OCR gratuito + torrents)
4. **Exportação**: `uv run leizilla export --origem rondonia --year 2020` - gera datasets Parquet/JSONL
5. **Pipeline completo**: `uv run leizilla pipeline --origem rondonia --year 2020 --limit 5` - executa tudo em sequência

---

## 🚀 Começar agora

### **Instalação e uso**

```bash
# 1. Instalar uv (gerenciador Python ultra-rápido)
curl -LsSf https://astral.sh/uv/install.sh | sh  # Linux/macOS
# ou no Windows: powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# 2. Clonar e configurar
git clone https://github.com/franklinbaldo/leizilla.git
cd leizilla
uv venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
uv sync --dev

# 3. Configurar ambiente (opcional - apenas para upload IA)
# export IA_ACCESS_KEY="sua_chave"
# export IA_SECRET_KEY="sua_chave_secreta"

# 4. Verificar instalação
uv run leizilla dev setup
```

### **Usar o sistema**

```bash
# Pipeline básico - descobrir e baixar leis de Rondônia 2020
uv run leizilla discover --origem rondonia --start-coddoc 1 --end-coddoc 10
uv run leizilla download --origem rondonia --limit 5

# Ver estatísticas
uv run leizilla stats

# Buscar no banco local
uv run leizilla search --text "lei complementar"

# Pipeline completo automatizado
uv run leizilla pipeline --origem rondonia --start-coddoc 1 --end-coddoc 10 --limit 10 --crawler-type simple
```

### **Comandos disponíveis**

| Finalidade            | Comando                     | Exemplo                                                                                             |
| --------------------- | --------------------------- | --------------------------------------------------------------------------------------------------- |
| **Descobrir leis**    | `uv run leizilla discover`  | `uv run leizilla discover --origem rondonia --start-coddoc 1 --end-coddoc 10 --crawler-type simple` |
| **Download PDFs**     | `uv run leizilla download`  | `uv run leizilla download --origem rondonia --limit 5`                                              |
| **Upload para IA**    | `uv run leizilla upload`    | `uv run leizilla upload --limit 3`                                                                  |
| **Exportar dados**    | `uv run leizilla export`    | `uv run leizilla export --origem rondonia`                                                          |
| **Pipeline completo** | `uv run leizilla pipeline`  | `uv run leizilla pipeline --origem rondonia --start-coddoc 1 --end-coddoc 10`                       |
| **Desenvolvimento**   | `uv run leizilla dev check` | `uv run leizilla dev setup`, `uv run leizilla dev test`                                             |

**💡 Vantagem**: Interface CLI moderna com Typer, help integrado (`--help`) e zero dependências extras!

---

## 📊 Estrutura do projeto

```
src/                   # Código-fonte (estrutura flat)
├── config.py         # Configuração centralizada
├── storage.py         # Schema DuckDB + operações
├── crawler.py         # Web crawling assíncrono
├── publisher.py       # Internet Archive + exports
└── cli.py             # Interface linha de comando
tests/                 # Testes automatizados
docs/adr/              # Decisões arquiteturais
data/                  # Dados locais (gitignored)
  └─ leizilla.duckdb   # Banco DuckDB local
```

## 💻 Especificação do Portal Frontend

A apresentação do portal público do Leizilla seguirá as seguintes diretrizes de design e funcionalidade:

* **Estilo e Apresentação Visual:** Interface moderna de alto padrão com tema **Dark Mode** e efeitos de **Glassmorphism**, com tipografia premium e micro-animações responsivas.
* **Mecanismo de Busca:** Barra de pesquisa unificada conectada diretamente ao **DuckDB-WASM** no lado do cliente. Filtros rápidos por **Ano**, **Tipo de Lei** e **Ente** que renderizam resultados e gráficos analíticos instantaneamente na tela.
* **Exibição dos Resultados:** Cada lei será apresentada individualmente mostrando título, resumo/ementa, data de publicação, link original para download do PDF arquivado no Internet Archive e um **visualizador de texto integrado (OCR)** com destaque dos termos pesquisados (*highlighting*).

---

## 🗺 Roadmap

Roadmap re-baselineado em 2026-07-07 pela [RFC-0004](docs/rfc/0004-go-live-rondonia.md)
(esta tabela é a única fonte do roadmap — regra da [RFC-0002](docs/rfc/0002-governanca-documental.md)).
O histórico do roadmap original (2025) está em [docs/archive/MASTERPLAN.md](docs/archive/MASTERPLAN.md).

| Período       | Entregável                                                                          | Status                                                              |
| ------------- | ----------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| **Q3 / 2026** | Go-live: dataset RO v0 publicado no IA + frontend apontando para ele                | 🔄 Em andamento — código pronto; aguarda ativação (secrets, runbook RFC-0004) |
| **Q4 / 2026** | Cobertura RO completa (assembleia + casacivil lei/lc) + releases semanais + M5.3    | 📋 Planejado                                                         |
| **Q1 / 2027** | Federal (Planalto 1988–presente) em produção                                        | 📋 Planejado                                                         |
| **Q2 / 2027** | Busca semântica (embeddings no DuckDB) + novo ente (SP)                             | 📋 Planejado                                                         |

> Nota de status honesto: o frontend (M5.1/M5.2) está pronto e o **M13 — Produto
> público v1** (página própria de lei, painel `/cobertura/`, evidência auditável)
> está em implementação, mas **nenhum dataset foi publicado no Internet Archive
> ainda** — o gargalo é ativação de produção (secrets nunca configurados), não
> código. Ver runbook na RFC-0004.

---

## 🔗 Links importantes

- **[CLAUDE.md](CLAUDE.md)**: Guia completo para desenvolvimento
- **[CONTRIBUTING.md](CONTRIBUTING.md)**: Como contribuir
- **[docs/adr/](docs/adr/)**: Decisões arquiteturais
- **[CausaGanha](https://github.com/franklinbaldo/causaganha)**: Projeto-irmão (validação Internet Archive)

---

## 🤝 Contribuir

### **Formas de ajudar:**

- **Testes de qualidade**: Executar pipeline em diferentes ambientes
- **Novas fontes**: Portais de legislação de outros estados
- **Otimizações**: Melhorias no crawler e processamento
- **Documentação**: Exemplos de uso e tutoriais

**Código pronto?** Leia **[CONTRIBUTING.md](CONTRIBUTING.md)** para o fluxo completo.

---

## 🔧 Tecnologias em destaque

- **Internet Archive**: OCR gratuito + distribuição P2P automática
- **DuckDB**: Banco analítico embarcado, exporta Parquet nativamente
- **Playwright**: Render completo de sites governamentais com JavaScript
- **uv**: Gerenciamento ultrarrápido de dependências Python

---

## Licença

- **Código**: MIT
- **Dados legais**: Domínio público

> _Leizilla saiu da fase filhote — já é um T-Rex devorando PDFs e cuspindo dados estruturados. Junte-se à revolução dos dados abertos!_ 🦖⚖️
