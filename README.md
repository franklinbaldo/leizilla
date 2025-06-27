# 🦖 **Leizilla**

> **O dinossauro que devora PDFs jurídicos e cospe dados abertos.**

Projeto-irmão do **CausaGanha**, mas com foco exclusivo em **indexar todas as leis brasileiras**, começando por **Rondônia**. Infra mínima, transparência radical e 100 % estático — sem servidores, sem backend para manter.

---

## 🚧 Estado atual

Fase **pré-MVP**: escolhendo ferramentas, validando custos e montando POC. Sem pastas nem código aqui — só a visão de stack.

---

## 🛠️ Tecnologias escolhidas (v1)

| Domínio | Ferramenta / Serviço | Por que? |
|---------|----------------------|---------|
| **Linguagem** | **Python 3.12** | Ecossistema maduro para scraping e ETL. |
| **Crawling** | **Playwright** + **AnyIO** | Renderiza JS moderno; IO assíncrono robusto. |
| **ETL & Storage** | **DuckDB** (SQL + Relational API) | Banco embutido, analítico, exporta Parquet; perfeito para datasets estáticos. |
| **Backup & OCR** | **Internet Archive** | Upload gratuito; OCR automático + torrent seeding nativo. |
| **Distribuição de dados** | - **Parquet** (analytics colunar)<br>- **JSON Lines** (pipelines)<br>- **Torrent** (gerado pelo IA) | Formatos agnósticos + canal P2P resiliente. |
| **Client-side busca** | **DuckDB-WASM** | Consulta SQL direta no navegador, sem backend. |
| **Build & CI** | **GitHub Actions** (matriz) | Orquestra crawl, ETL, upload, release — zero infra própria. |
| **Dependências** | **uv** | Instalação veloz + lockfile determinístico. |
| **Qualidade** | **ruff** (lint) + **mypy** (tipos) | Código limpo e tipado desde o dia 1. |

---

## 🌐 Fluxo de dados (alto nível)

1. **Crawler** baixa PDFs diretamente das fontes oficiais (prioridade Rondônia).  
2. Faz upload imediato ao **Internet Archive**, que gera OCR e arquivos torrent.  
3. Baixa o texto OCR do IA, normaliza e grava em **DuckDB + Parquet**.  
4. Publica datasets via release no GitHub e espelho torrent/IA.  
5. Frontend estático usa **DuckDB-WASM** para busca no navegador.  

---

## 🗺 Roadmap resumido

| Trimestre | Entregável |
|-----------|-----------|
| **Q3 / 2025** | MVP Rondônia (todas leis estaduais + constituição) em Parquet/JSONL. |
| **Q4 / 2025** | Cobertura federal 1988-presente; releases mensais via torrent. |
| **Q1 / 2026** | Frontend estático (HTML/JS) com busca SQL client-side. |
| **Q2 / 2026** | **Pesquisa semântica**: embeddings (Sentence-Transformers ou Gemini) salvos dentro do DuckDB para similarity search (via `vector()` extension). |
| **Além** | Plugins para Assembleias de SP, RJ, MG; mirror datasets no HuggingFace. |

---

## 🚀 Começar agora

### **Experimentar o código**
```bash
# 1. Instalar uv (gerenciador Python ultra-rápido)
curl -LsSf https://astral.sh/uv/install.sh | sh  # Linux/macOS
# ou no Windows: powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# 2. Clonar e configurar
git clone https://github.com/franklinbaldo/leizilla.git
cd leizilla
uv venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
uv sync --dev

# 3. Verificar se tudo funciona
just check
```

### **Contribuir com o projeto**
- **Sugestões de fontes**: links de portais de legislação pouco conhecidos
- **Feedback de stack**: ideias mais baratas ou simples são bem-vindas
- **Testes de custo**: comparativos de tempo/custo usando OCR do IA em larga escala

**Código pronto?** Leia **[CONTRIBUTING.md](CONTRIBUTING.md)** para o fluxo completo.

---

## Licença

- **Código**: MIT.  
- **Dados legais**: domínio público.  

> *Leizilla ainda é filhote — mas o apetite já é de T-Rex. Junte-se antes que ele devore tudo sozinho.* 🦖⚖️
