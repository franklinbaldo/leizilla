# IMPLEMENTATION.md — Leizilla → franklinbaldo stack

> **Documento vivo.** Este arquivo espelha o plano de migração e é atualizado a cada PR. Sempre que uma decisão for tomada, um problema for descoberto, ou um milestone fechar, edite aqui. O git log deste arquivo é a memória institucional da migração.

---

## Status atual

| Milestone | Status | PR | Notas |
|---|---|---|---|
| **M0** — Documento vivo + Design schema | 🟡 in-progress | #6 | M0.1 done; M0.2 reescrito após review dos 3 blockers; falta `leizilla-v0.1.xsd` + fixtures + decisões §10 do SCHEMA.md |
| M1 — Foundation (package + ADRs + deps) | ⚪ todo | — | Bloqueado por M0 |
| M2 — Crawler real + Raw upload | ⚪ todo | — | Bloqueado por M1 |
| M3 — OCR fetch + LLM parse + Leizilla XML | ⚪ todo | — | Bloqueado por M2 |
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
                ETAPA 2 (LLM/agentes parsing) → Leizilla XML + parsed_meta.json no IA
                                              ↓
                etl/consolidate                → Parquet v0.1 no IA (dataset item)
                                              ↓
                deploy-web                     → Astro+Svelte+Pico+DuckDB-WASM no GH Pages
```

### Princípios load-bearing (não violar sem RFC)

1. **Duas etapas no IA, sempre separadas.** Raw é imutável; parsed re-roda quantas vezes for preciso.
2. **OCR é responsabilidade do Internet Archive.** Nunca rodamos OCR local.
3. **Etapa 2 é pluggable.** Default: Claude Haiku via API. Alternativas: Claude Code routine com Opus, parser determinístico, curadoria manual.
4. **Múltiplas fontes por lei são esperadas.** Assembleia + Casa Civil + Diário Oficial fazem **cross-verificação** do vigente compilado — não competem por canonicidade. Divergências indicam possível erro de consolidação ou retificação não-aplicada; frontend exibe como "verificar", não como ranking de autoridade. Ver SCHEMA.md §0.2.
5. **Genérico por ente federativo desde dia 1.** Tudo parametrizado por `{ente}`.
6. **Leizilla XML é canônico, dispositivo-cêntrico.** Formato próprio (não fork). LexML é gate de CI (export reduzido sob demanda), não constraint estrutural. SSR híbrido: Astro renderiza páginas de detalhe; XSLT in-browser é fallback.
7. **ZIP raw bulk (padrão ficha) + Parquet relacional normalizado (3 tabelas com FKs: leis ← dispositivos ← versoes) + IA item para distribuição.** Ficha tem 1 Parquet por entidade; nosso modelo introduz normalização relacional explícita para suportar timeline temporal por dispositivo. Manifest CSV no IA como source of truth (padrão baliza).
9. **Wayback Machine é caminho primário de fetch.** Crawler não bate na fonte original — dispara Wayback save de `fonte_url` + `pdf_url`, depois fetch o PDF do snapshot Wayback para upload na nossa coleção IA. Fail-open: se Wayback falha, fallback de download direto. Polite com sites .gov.br frágeis + testemunha externa automática. Detalhes em SCHEMA.md §0.5.
8. **Vigente compilado é canônico, histórico via timeline.** Parsed item = "como deve estar vigente hoje" (best-effort). Versões anteriores acessíveis via date picker. Fontes (DO, Casa Civil, Assembleia) cross-verificam — não competem por autoridade.

---

## Stack confirmado

| Camada | Tecnologia | Versão |
|---|---|---|
| Backend | Python | 3.12 |
| ETL | DuckDB + PyArrow | latest |
| Storage canônico | Leizilla XML (formato próprio, dispositivo-cêntrico) | 0.1 |
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

### 2026-05-20 — Rewrite arquitetural pós-review #6 (3 blockers)

Parecer técnico de @franklinbaldo no PR #6 levantou 3 blockers que mudaram fundamentos do design. Resolvidos antes de fechar M0:

- **Blocker 1 — DO×vigente como tese de canonicidade**: hierarquia "DO > Casa Civil > Assembleia" foi descartada. Decisão: parsed item canônico é o **vigente compilado** (best-effort); histórico fica acessível via timeline de versões por dispositivo (date picker → "como era a lei em 2010-01-01?"). Fontes não competem por autoridade — cross-verificam a compilação. Documentado em `docs/SCHEMA.md` §0.2.

- **Blocker 2 — Alterações legislativas fora de escopo**: trazidas para v0.1. Schema Leizilla XML modela cada dispositivo como container de versões (`<versao numero="N" vigente-de="..." vigente-ate="..." alterado-por="urn:lex:...">`). `alteracoes.json` sidecar pré-computa relações (`alterada_por`, `altera`, `revogada_por`, `revoga`). Documentado em `docs/SCHEMA.md` §0.2, §4.3.

- **Blocker 3 — LeiML como NIH disfarçado**: fork LeiML abandonado. **Leizilla XML v0.1** é formato próprio escrito do zero, **dispositivo-cêntrico** (não lei-cêntrico — insight do usuário: "unidade básica é dispositivo, não a lei"). LexML vira gate de CI (XSLT export valida que conseguimos representação reduzida quando preciso para gov interop) — não constraint estrutural. Perdas conhecidas (divergencias, parse meta, bloco-livre) ficam documentadas no XSLT. Documentado em `docs/SCHEMA.md` §0.3, §4, §6.

Outras decisões do mesmo review já incorporadas em SCHEMA.md:
- `git_sha` 40 chars completo (não 7).
- Regex parsed `\d{5,}` (não `\d{5}`).
- Tipo Parquet `VARCHAR` (não `TEXT`).
- `urn_lex` nullable (data desconhecida não falsifica URN).
- Bundle `lexml.xsd` no repo (reprodutibilidade).
- Schema Parquet é v0.1 durante M0–M4, promove a v1 só em M5.
- SSR híbrido via Astro (suaviza princípio 6 — XSLT in-browser é fallback).
- Confiança baixa exibida explicitamente no frontend (banner LLM/OCR).

### 2026-05-20 — Wayback Machine como caminho primário de fetch

- **Decisão**: crawler dispara `POST /save` no Wayback Machine para `fonte_url` + `pdf_url`, depois **fetch o PDF do snapshot Wayback** (não da fonte original) para upload na nossa coleção IA. Fail-open: timeout/erro/rate-limit do Wayback → fallback para download direto da fonte, gravar `fetched_from: "source-fallback"` em `raw_meta.json.provenance_wayback`.
- **Não substitui IA**: nossa coleção continua sendo o archive primário (necessário para OCR automático que alimenta Etapa 2). Wayback é buffer + testemunha externa.
- **Por que**: (a) bate na fonte original uma única vez (via bot Wayback), polite com sites .gov.br frágeis; (b) timestamp Wayback é testemunha independente para auditoria forense; (c) reduz superfície de rate-limit do nosso lado.
- **Cache**: antes de disparar save, checar `GET https://archive.org/wayback/available?url=...`. Reusa snapshot < 24h.
- **Documentado em**: SCHEMA.md §0.5; sidecar em §2.1 (`provenance_wayback`).

### 2026-05-20 — Caput como índice 0 implícito (Opção D)

- **Decisão**: caput não é elemento separado no Leizilla XML. Todo `<dispositivo>` container (artigo, parágrafo, inciso) tem `<versoes>` opcional carregando **seu próprio texto intrínseco** — que corresponde semanticamente ao "caput" na terminologia jurídica. Sem `<dispositivo tipo="caput">`.
- **Insight do usuário**: "caput é como um índice 0". Conceitualmente o caput é o "filho zero" do container; serialização XML deixa implícito via `<versoes>` no próprio container.
- **Aplica recursivamente**: parágrafo com incisos também tem caput (seu texto antes dos incisos). Inciso com alíneas idem.
- **URN**: `urn:lex:...!art-5` resolve para o texto intrínseco (caput) do art-5. Sub-itens via `!art-5!par-1`.
- **Parquet**: 1 row por dispositivo. Row do container **é** o caput. Sem row extra.
- **Export LexML**: XSLT wrap mecânico — `<dispositivo path="art-5"><versoes>...</versoes>` vira `<Artigo><Caput><Texto>...</Texto></Caput>`.
- **Documentado em**: SCHEMA.md §4.3.

### 2026-05-20 — LGPD: leis públicas não despublicam

- **Posição cravada**: leis estaduais e federais são atos públicos por força da CF (art. 5º LX, art. 84 IV, art. 37 caput). LGPD (Lei 13.709/2018) não autoriza despublicação de norma pública e não está acima da Constituição.
- **Citação de pessoas físicas em leis antigas** (nomeações, aposentadorias, concessões individuais — comuns em leis estaduais pré-2000) faz parte do ato administrativo público original. Indexar e republicar é **continuidade do ato**, não tratamento novo de dados pessoais sujeito a consentimento.
- **Não rodamos triagem/redação** de nomes. Documentar formalmente em ADR-0009 (Claude routines + ética) em M1.

### 2026-05-20 — Custo LLM diluído no tempo, sem ressalva de design

- **Estimativa realista**: ~$40–100/ente (5k leis × 10k tokens × Haiku), revisada do "<$5" inicial.
- **Aceitável**: ingestão é one-shot por lei; custo amortiza no tempo. Re-parsing pontual via fill-gaps é marginal. Não é fator de bloqueio para design.

### 2026-05-20 — Re-scrape sob auditoria; nova fonte sob auditoria

- **Re-scrape**: NÃO é automático. Só dispara quando auditoria periódica de qualidade conclui que o raw está degradado (e.g., versão do PDF foi corrigida pela fonte, ou OCR muito ruim para LLM extrair). Novo raw item vira `{chave}-r{N}` (revisão); raw anterior permanece imutável (princípio 1).
- **Nova fonte por ente**: processo paralelo de auditoria periódica avalia se fontes adicionais oficiais devem ser declaradas em `src/leizilla/fontes/{ente}.py` (e.g., portal de transparência que reúne consolidados).
- **Cadência**: pendente — definir em M1 se é trimestral, anual, ou demand-driven.

### 2026-05-20 — Renomear `origem` → `ente` em CLI e schema (M1)

- **Decisão**: a coluna `origem` no DuckDB schema (storage.py:44) e a flag `--origem` no CLI (cli.py:29,69,169,199,260) serão renomeadas para `ente`. SCHEMA.md já assume `ente` em todo o Parquet v0.1 e identifiers IA.
- **Quando**: migração executa em M1 junto com o restructure do package (`src/` → `src/leizilla/`). Não fazemos compat shim — o pipeline atual não tem dados em produção, é só desenvolvimento.
- **Por quê**: `origem` era nome herdado da fase pré-stack-franklinbaldo (ADR-0003); `ente` é mais preciso (ente federativo) e generaliza para União/estados/municípios.
- **Por que registrar agora**: reviewer #6 apontou que o log de decisões não tinha entrada explícita; sem isso, no M1 vão aparecer dois nomes convivendo sem rastreio.

### 2026-05-20 — Fixes Codex no PR #6

- **P1 fallback parsed sem `{fonte}`**: pattern em §1.3 dizia `leizilla-{ente}-{tipo}-fallback-{chave}` mas regex em §5 exigia `{fonte}`. Corrigido: fallback sempre inclui `{fonte}` para evitar colisão. SCHEMA.md §1.3, §5.3.
- **P2 `id` Parquet sem zero-pad**: descrição da coluna `id` em §3 não explicitava que `numero` é zero-padded. Corrigido: lookup `id → IA item` é literal, sem normalização extra. SCHEMA.md §3.1, §5.3.

### 2026-05-20 — Migração para stack franklinbaldo iniciada
- **Decisão**: adotar Astro + Svelte + Pico + DuckDB-WASM, mirror do que já funciona em verne/cobogo/franklinbaldo.github.io.
- **Justificativa**: stack provada, build static, zero servidor, integra DuckDB-WASM nativamente.

### 2026-05-20 — LeiML em vez de LexML cru ⚠️ **SUPERSEDED**

> **Superseded por** "Rewrite arquitetural pós-review #6 (3 blockers)" acima (mesmo dia). LeiML foi abandonado como fork — formato canônico atual é **Leizilla XML v0.1** (formato próprio, escrito do zero, dispositivo-cêntrico). LexML não é mais round-trip, é gate de CI one-way. Mantido aqui apenas como audit trail da iteração.

- ~~**Decisão**: criar formato próprio `LeiML` v0.1 (namespace `https://leizilla.org/leiml/0.1`), inspirado em LexML mas modernizado.~~
- ~~**Justificativa**: LexML/e-PING parado desde ~2010, XSD pesado, tooling Python esparso.~~
- ~~**Constraint inviolável**: LeiML é 100% exportável para LexML via `leiml-to-lexml.xsl`. CI valida round-trip a cada PR.~~
- **URN compartilhado**: `urn:lex:br;...` (padrão LEX é OK e estável). _Esta parte permanece válida._

### 2026-05-20 — OCR delegado ao Internet Archive
- **Decisão**: não rodar OCR local em circunstância alguma. Upload PDF → IA OCR automático → poll `_djvu.txt`.
- **Trade-off aceito**: latência de horas até OCR disponível; manifest CSV rastreia `ocr_ready` separado de `raw_uploaded`.

### 2026-05-20 — Duas etapas separadas no IA
- **Decisão**: raw items e parsed items são IA items distintos. Raw é imutável após upload; parsed pode ser re-uploadado quantas vezes preciso.
- **Justificativa**: isola falhas de parsing do scraping; permite trocar estratégia de Etapa 2 sem re-scraping.

### 2026-05-20 — Slug `{fonte}` é token único `[a-z]+`, sem hífens
- **Decisão**: cada fonte tem **um único slug canônico** (`casacivil`, `diario`, `assembleia`) usado idêntico em IA identifier, `raw_meta.fonte`, `parsed_meta.fontes_consultadas`, elemento `<fonte-canonica>` em Leizilla XML, coluna Parquet `fonte_canonica`, e enum `FONTES`.
- **Justificativa**: rascunho inicial misturava `diario`, `diario_oficial`, `diario-oficial` em locais diferentes — flagged pelo Codex em #6. Reconciliação determinística requer um único valor; hífen no slug quebra parsing do identifier `leizilla-raw-{ente}-{fonte}-{chave}` (ambiguidade entre fim de fonte e início de chave).
- **Documentado em**: `docs/SCHEMA.md` §5 "Slug `{fonte}`".

### 2026-05-20 — Múltiplas fontes oficiais com tracking de divergência (atualizado pós-rewrite)
- **Decisão**: cada lei pode ter N raw items (um por fonte: Assembleia, Casa Civil, Diário Oficial). Parsed item compila o vigente e expõe divergências.
- **Cross-verificação, não ranking**: ~~Hierarquia Diário Oficial > Casa Civil > Assembleia~~ — descartada na reescrita. Fontes cross-verificam o vigente compilado; divergência sinaliza "verificar", não "fonte X ganha". Ver SCHEMA.md §0.2.
- **Divergências registradas** em `parsed_meta.json.tem_divergencia` + `parsed_meta.json.num_divergencias` (flag rápido), tabela Parquet `versoes.divergencias` (JSON com diff por versão de dispositivo), e elemento `<divergencia>` em `law.xml`.
- **Frontend**: `LawCard.svelte` mostra badge "⚠ Divergência entre fontes" com modal; banner adicional se `confianca_parse < 0.8` ou `parse_method` for LLM.

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
uv run pytest tests/test_lexml_export.py -v  # gate CI: Leizilla XML → LexML (one-way)
```

---

## Referência rápida — IA identifiers

| Tipo | Pattern | Exemplo |
|---|---|---|
| Raw (individual) | `leizilla-raw-{ente}-{fonte}-{chave}` | `leizilla-raw-ro-casacivil-coddoc-00042` |
| Raw (bundle ZIP) | `leizilla-bundle-{ente}-{fonte}-{periodo}` | `leizilla-bundle-ro-casacivil-2026-W20` |
| Parsed (lei canônica) | `leizilla-{ente}-{tipo}-{numero:05d}-{ano}` | `leizilla-ro-lei-01234-2003` |
| Dataset (Parquet) | `leizilla-dataset-{ente}-v{N}` | `leizilla-dataset-ro-v1` |

Slug `{ente}`: `ro`, `sp`, `federal`, `ro-porto-velho` (kebab-case, UF-municipio).

Naming formal e regras de fallback: ver `docs/SCHEMA.md` (M0.2).

---

## Próximos passos imediatos

- [x] **M0.1**: `IMPLEMENTATION.md` criado e mantido.
- [x] **M0.2**: `docs/SCHEMA.md` v1 (granularidade IA, layout ZIP, naming).
- [x] **M0.2**: reescrita pós-review #6 (dispositivo-cêntrico, timeline temporal, formato próprio).
- [ ] **M0.2**: rascunhar `docs/schemas/leizilla-v0.1.xsd`.
- [ ] **M0.2**: fixtures de 3 leis representativas em `tests/fixtures/leizilla_xml/` (incluindo uma com alterações e uma com `<bloco-livre>`).
- [ ] **M0.2**: rascunhar `scripts/leizilla-to-lexml.xsl` + teste CI de validação contra `lexml.xsd`.
- [ ] **M0.2**: resolver decisões pendentes em `docs/SCHEMA.md` §10 (URN dialect, compressão Parquet, política re-scrape, LGPD).
- [ ] **M0.3**: aprofundar inspirações concretas em `docs/SCHEMA.md` §8 (paths exatos de arquivos em ficha/baliza/causaganha).
- [ ] Re-review do PR #6 após reescrita; aprovação → fechar M0 → abrir M1.
