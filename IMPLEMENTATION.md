# IMPLEMENTATION.md — Leizilla → franklinbaldo stack

> **Documento vivo.** Este arquivo espelha o plano de migração e é atualizado a cada PR. Sempre que uma decisão for tomada, um problema for descoberto, ou um milestone fechar, edite aqui. O git log deste arquivo é a memória institucional da migração.

**Plano-mãe (read-only):** `/root/.claude/plans/eu-quero-fazer-esse-iterative-trinket.md` (não versionado — é o handoff do Claude Code).

---

## Status atual

| Milestone | Status | PR | Notas |
|---|---|---|---|
| **M0** — Documento vivo + Design schema | 🟡 in-progress | — | M0.1 done; M0.2 rascunho em `docs/SCHEMA.md`; falta `leiml-v0.1.xsd` e fixtures |
| M1 — Foundation (package + ADRs + deps) | ⚪ todo | — | Bloqueado por M0 |
| M2 — Crawler real + Raw upload | ⚪ todo | — | Bloqueado por M1 |
| M3 — OCR fetch + LLM parse + LeiML | ⚪ todo | — | Bloqueado por M2 |
| M4 — Parquet + release dataset | ⚪ todo | — | Bloqueado por M3 |
| M5 — Frontend Astro+Svelte+Pico | ⚪ todo | — | Pode rodar em paralelo a M4 |
| M6 — GitHub Actions | ⚪ todo | — | Depende de M2–M5 |
| M7 — Claude Code routines | ⚪ todo | — | Depende de M6 |

Legenda: ⚪ todo · 🟡 in-progress · 🟢 done · 🔴 blocked

---

## Visão arquitetural (resumo executivo)

```
Fonte oficial → ETAPA 1 (raw IA item)        → IA OCR automático (_djvu.txt)
                                              ↓
                ETAPA 2 (LLM/agentes parsing) → LeiML XML + parsed_meta.json no IA
                                              ↓
                etl/consolidate                → Parquet v1 no IA (dataset item)
                                              ↓
                deploy-web                     → Astro+Svelte+Pico+DuckDB-WASM no GH Pages
```

### Princípios load-bearing (não violar sem RFC)

1. **Duas etapas no IA, sempre separadas.** Raw é imutável; parsed re-roda quantas vezes for preciso.
2. **OCR é responsabilidade do Internet Archive.** Nunca rodamos OCR local.
3. **Etapa 2 é pluggable.** Default: Claude Haiku via API. Alternativas: Claude Code routine com Opus, parser determinístico, curadoria manual.
4. **Múltiplas fontes por lei são esperadas.** Assembleia + Casa Civil + Diário Oficial; reconciliação com hierarquia DO > Casa Civil > Assembleia.
5. **Genérico por ente federativo desde dia 1.** Tudo parametrizado por `{ente}`.
6. **LeiML é canônico, HTML é apresentação.** LeiML exportável para LexML (CI round-trip). HTML renderizado no browser via XSLT/JS.
7. **ZIP raw bulk, Parquet analytics, IA item distribuição.** Padrão ficha.

---

## Stack confirmado

| Camada | Tecnologia | Versão |
|---|---|---|
| Backend | Python | 3.12 |
| ETL | DuckDB + PyArrow | latest |
| Storage canônico | LeiML XML (nosso fork de LexML) | 0.1 |
| Storage distribuído | Internet Archive | — |
| Frontend framework | Astro | 6.3 |
| Frontend components | Svelte | 5.55 |
| CSS | Pico CSS | 2.1 |
| Browser DB | DuckDB-WASM | 1.28 |
| Data fetching | TanStack Svelte Query | 6.1 |
| Hosting | GitHub Pages | — |
| LLM parsing | Claude Haiku | `claude-haiku-4-5-20251001` |
| LLM fallback | Claude Opus | `claude-opus-4-7` |

---

## Decisões técnicas (log cronológico)

Toda decisão importante recebe entrada aqui com data. Não delete entradas — supersede com nova entrada referenciando a anterior.

### 2026-05-20 — Migração para stack franklinbaldo iniciada
- **Decisão**: adotar Astro + Svelte + Pico + DuckDB-WASM, mirror do que já funciona em verne/cobogo/franklinbaldo.github.io.
- **Justificativa**: stack provada, build static, zero servidor, integra DuckDB-WASM nativamente.

### 2026-05-20 — LeiML em vez de LexML cru
- **Decisão**: criar formato próprio `LeiML` v0.1 (namespace `https://leizilla.org/leiml/0.1`), inspirado em LexML mas modernizado.
- **Justificativa**: LexML/e-PING parado desde ~2010, XSD pesado, tooling Python esparso.
- **Constraint inviolável**: LeiML é 100% exportável para LexML via `leiml-to-lexml.xsl`. CI valida round-trip a cada PR.
- **URN compartilhado**: `urn:lex:br;...` (padrão LEX é OK e estável).

### 2026-05-20 — OCR delegado ao Internet Archive
- **Decisão**: não rodar OCR local em circunstância alguma. Upload PDF → IA OCR automático → poll `_djvu.txt`.
- **Trade-off aceito**: latência de horas até OCR disponível; manifest CSV rastreia `ocr_ready` separado de `raw_uploaded`.

### 2026-05-20 — Duas etapas separadas no IA
- **Decisão**: raw items e parsed items são IA items distintos. Raw é imutável após upload; parsed pode ser re-uploadado quantas vezes preciso.
- **Justificativa**: isola falhas de parsing do scraping; permite trocar estratégia de Etapa 2 sem re-scraping.

### 2026-05-20 — Múltiplas fontes oficiais com tracking de divergência
- **Decisão**: cada lei pode ter N raw items (um por fonte: Assembleia, Casa Civil, Diário Oficial). Parsed item reconcilia.
- **Hierarquia de autoridade**: Diário Oficial > Casa Civil > Assembleia. Divergências registradas em `parsed_meta.json.divergencias` e na coluna Parquet `tem_divergencia`.
- **Frontend**: `LawCard.svelte` mostra badge "⚠ Divergência entre fontes" com modal de diff.

---

## Problemas encontrados

> Adicione aqui qualquer obstáculo, bug, ou descoberta que mude o plano. Inclua data, descrição, e link para PR/issue de resolução (se houver).

_(vazio — preencher conforme implementação avança)_

---

## Como rodar localmente

### Pipeline backend (Python)

```bash
# Setup
uv venv && source .venv/bin/activate
uv sync --dev
uv run leizilla dev setup

# Pipeline completo (após M2)
uv run leizilla pipeline --ente ro --start-coddoc 1 --end-coddoc 10

# Etapas separadas
uv run leizilla scrape --ente ro --fonte casacivil --start-coddoc 1 --end-coddoc 10
uv run leizilla parse --ente ro --raw-ids leizilla-raw-ro-casacivil-coddoc-00001
uv run leizilla consolidate --ente ro
uv run leizilla release-dataset --ente ro --version 1
```

### Frontend (após M5)

```bash
cd web/
npm install
npm run dev    # http://localhost:4321
npm run build  # static build → dist/
```

### Testes

```bash
uv run leizilla dev check    # lint + format + typecheck + test
uv run pytest tests/test_leiml_export.py -v  # round-trip LeiML→LexML
```

---

## Referência rápida — IA identifiers

| Tipo | Pattern | Exemplo |
|---|---|---|
| Raw (individual) | `leizilla-raw-{ente}-{fonte}-{chave}` | `leizilla-raw-ro-casacivil-coddoc-00042` |
| Raw (bundle ZIP) | `leizilla-bundle-{ente}-{fonte}-{periodo}` | `leizilla-bundle-ro-casacivil-2026-W20` |
| Parsed (lei canônica) | `leizilla-{ente}-{tipo}-{numero}-{ano}` | `leizilla-ro-lei-01234-2003` |
| Dataset (Parquet) | `leizilla-dataset-{ente}-v{N}` | `leizilla-dataset-ro-v1` |

Slug `{ente}`: `ro`, `sp`, `federal`, `ro-porto-velho` (kebab-case, UF-municipio).

Naming formal e regras de fallback: ver `docs/SCHEMA.md` (M0.2).

---

## Próximos passos imediatos

- [ ] **M0.2**: escrever `docs/SCHEMA.md` com decisões de granularidade IA, layout ZIP, schema Parquet v1, schema LeiML v0.1
- [ ] **M0.2**: rascunhar `docs/schemas/leiml-v0.1.xsd`
- [ ] **M0.2**: fixtures de 3 leis representativas em `tests/fixtures/leiml/` validando round-trip LeiML→LexML
- [ ] **M0.3**: documentar inspirações concretas em `docs/SCHEMA.md` (links para arquivos específicos em ficha/baliza/causaganha)
- [ ] PR de M0 para review antes de iniciar M1
