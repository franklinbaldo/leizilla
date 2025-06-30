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

| Domínio | Ferramenta / Serviço | Status |
|---------|----------------------|--------|
| **Linguagem** | **Python 3.12** | ✅ Implementado |
| **Crawling** | **Playwright** + **AnyIO** | ✅ Crawler assíncrono funcional |
| **ETL & Storage** | **DuckDB** | ✅ Schema completo + CRUD |
| **Backup & OCR** | **Internet Archive** | ✅ Upload e integração |
| **Distribuição** | **Parquet** + **JSON Lines** | ✅ Exportação implementada |
| **Build & CI** | **GitHub Actions** + **uv** | ✅ Scripts automatizados |
| **Dependências** | **uv** | ✅ Ambiente configurado |
| **Qualidade** | **ruff** + **mypy** | ✅ Linting e tipos |

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

| Finalidade | Comando | Exemplo |
|-----------|---------|---------|
| **Descobrir leis** | `uv run leizilla discover` | `uv run leizilla discover --origem rondonia --start-coddoc 1 --end-coddoc 10 --crawler-type simple` |
| **Download PDFs** | `uv run leizilla download` | `uv run leizilla download --origem rondonia --limit 5` |
| **Upload para IA** | `uv run leizilla upload` | `uv run leizilla upload --limit 3` |
| **Exportar dados** | `uv run leizilla export` | `uv run leizilla export --origem rondonia` |
| **Pipeline completo** | `uv run leizilla pipeline` | `uv run leizilla pipeline --origem rondonia --start-coddoc 1 --end-coddoc 10` |
| **Desenvolvimento** | `uv run leizilla dev check` | `uv run leizilla dev setup`, `uv run leizilla dev test` |

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

---

## 🗺 Roadmap

| Período | Entregável | Status |
|---------|-----------|--------|
| **Q3 / 2025** | MVP Rondônia completo em Parquet/JSONL | ✅ **Implementado** |
| **Q4 / 2025** | Cobertura federal 1988-presente; releases mensais | 🔄 Em progresso |
| **Q1 / 2026** | Frontend estático (HTML/JS) com busca SQL client-side | 📋 Planejado |
| **Q2 / 2026** | Pesquisa semântica com embeddings no DuckDB | 📋 Planejado |

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

> *Leizilla saiu da fase filhote — já é um T-Rex devorando PDFs e cuspindo dados estruturados. Junte-se à revolução dos dados abertos!* 🦖⚖️