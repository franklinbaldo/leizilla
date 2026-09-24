# 🦖 **Leizilla**

> **O dinossauro que devora PDFs jurídicos e cospe dados abertos.**

Leizilla é um projeto de indexação de legislação brasileira, começando por Rondônia. O objetivo é transformar fontes oficiais e documentos preservados em um acervo pesquisável, auditável e reutilizável — com publicação estática, sem backend de aplicação para manter.

## 🌐 Usar o Leizilla

- **Portal público:** https://franklinbaldo.github.io/leizilla/
- **Dataset Rondônia v0 no Internet Archive:** https://archive.org/details/leizilla-dataset-ro-v0
- **Parquet usado pelo próprio portal:** https://archive.org/download/leizilla-dataset-ro-v0/versoes.parquet
- **Metadados da release:** https://archive.org/download/leizilla-dataset-ro-v0/dataset_meta.json

O portal consulta o Parquet diretamente no navegador com DuckDB-WASM. A página de dados também mostra uma consulta mínima reproduzível para testar o mesmo artefato fora do site.

## ✅ Estado atual

O primeiro dataset público de Rondônia (**RO v0**) já foi publicado no Internet Archive e o frontend está apontando para esse artefato.

Isso significa **dataset publicado**, não **cobertura completa de Rondônia**. A cobertura ainda é incremental: o pipeline continua ampliando e conferindo as fontes, e o roadmap mantém como próximo marco a cobertura estadual mais completa e releases recorrentes.

Hoje o projeto já possui:

- portal Astro/Svelte estático com busca e navegação sobre o dataset;
- DuckDB-WASM no cliente, lendo o Parquet público diretamente;
- páginas de lei, cobertura e evidências/proveniência;
- pipeline de descoberta, coleta, parse/ETL e publicação;
- preservação de documentos e artefatos no Internet Archive;
- exportação de dados estruturados e metadados de release;
- CLI Python para operações locais e de desenvolvimento;
- workflows de CI, coleta, release e deploy.

## 🔄 Como os dados chegam ao portal

A cadeia pública é, em linhas gerais:

```text
fontes oficiais
    ↓
descoberta e coleta
    ↓
documentos preservados / evidências
    ↓
parse + ETL
    ↓
dataset versionado no Internet Archive
    ↓
Parquet + dataset_meta.json
    ↓
portal estático / DuckDB-WASM
```

O portal não mantém uma cópia privada dos dados: o Parquet público é o artefato consultado pela interface e pode ser reutilizado independentemente.

## 🔎 Consultar o dataset fora do site

Com DuckDB instalado, uma verificação mínima é:

```sql
SELECT count(*)
FROM read_parquet(
  'https://archive.org/download/leizilla-dataset-ro-v0/versoes.parquet'
);
```

Para conferir a release, compare o resultado e os demais dados do artefato com `dataset_meta.json`, que registra metadados como contagem, hash e revisão de origem quando disponíveis.

## 🛠️ Desenvolvimento local

O projeto usa Python 3.12+ e `uv`.

```bash
git clone https://github.com/franklinbaldo/leizilla.git
cd leizilla
uv sync --dev
uv run leizilla --help
```

Alguns comandos disponíveis no CLI:

```bash
# descobrir documentos
uv run leizilla discover --origem rondonia --start-coddoc 1 --end-coddoc 10

# baixar documentos descobertos
uv run leizilla download --origem rondonia --limit 5

# consultar estatísticas locais
uv run leizilla stats

# buscar no banco local
uv run leizilla search --text "lei complementar"
```

Para desenvolvimento e operação, leia também [CLAUDE.md](CLAUDE.md), [CONTRIBUTING.md](CONTRIBUTING.md) e as decisões em [`docs/`](docs/).

## 🧱 Stack

| Domínio | Ferramenta / serviço |
| --- | --- |
| Linguagem | Python 3.12 |
| Portal | Astro + Svelte |
| Consulta no navegador | DuckDB-WASM |
| ETL / armazenamento local | DuckDB |
| Coleta | Playwright + AnyIO |
| Preservação / distribuição | Internet Archive |
| Dados publicados | Parquet + metadados de release |
| Automação | GitHub Actions |
| Dependências Python | uv |
| Qualidade | Ruff + mypy + testes |

## 🗺 Roadmap

O roadmap foi re-baselineado pela [RFC-0004](docs/rfc/0004-go-live-rondonia.md); a governança documental está na [RFC-0002](docs/rfc/0002-governanca-documental.md).

| Período | Entregável | Estado |
| --- | --- | --- |
| **Q3 / 2026** | Go-live do dataset RO v0 + frontend apontando para ele | ✅ Publicado; cobertura segue incremental |
| **Q4 / 2026** | Cobertura RO mais completa + releases recorrentes | 📋 Planejado |
| **Q1 / 2027** | Federal (Planalto 1988–presente) | 📋 Planejado |
| **Q2 / 2027** | Busca semântica + novo ente | 📋 Planejado |

O estado de publicação e o estado de cobertura são coisas diferentes: uma release pública pode existir enquanto a coleta e a reconciliação das fontes continuam avançando.

## 🔗 Projeto-irmão

O [CausaGanha](https://github.com/franklinbaldo/causaganha) compartilha com o Leizilla interesses em preservação, dados públicos e infraestrutura verificável, mas os dois projetos têm domínios e produtos próprios.

## Licença

- **Código:** MIT
- **Dados legais:** domínio público

> _Leizilla saiu da fase filhote — já tem um dataset público para devorar junto._ 🦖⚖️
