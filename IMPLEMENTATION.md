# IMPLEMENTATION.md — Leizilla → franklinbaldo stack

> **Documento vivo.** Este arquivo espelha o plano de migração e é atualizado a cada PR. Sempre que uma decisão for tomada, um problema for descoberto, ou um milestone fechar, edite aqui. O git log deste arquivo é a memória institucional da migração.

---

## Status atual

| Milestone | Status | PR | Notas |
|---|---|---|---|
| **M0.1** — Documento vivo + SCHEMA.md design | 🟢 done | #6 | Aprovado em re-review; merged em main. |
| **M0.2a** — Schema v1 (tentativa) | 🔴 superseded | #7 | XSD `header` + `rotulo` + `<bloco-livre>` + etc. Substituído pelo redesign first-principles. Fica como referência histórica. |
| **M0.2b** — Redesign first-principles | 🟢 done | #8 #9 #10 #12 | SCHEMA.md reescrito + XSD enxuto + 6 fixtures + consistency checker + CI wire + XSLT Leizilla→LexML validado contra XSD oficial bundled (PRs #8-#12 merged). |
| **M0.3** — URN canônica + close pendentes §8 | 🟢 done | #13 | URN LEX contra spec CGPID 2008 oficial; política re-scrape; robots.txt princípio. 3 pendentes deferidos para M2/M4. |
| **M1** — Foundation (package + ADRs + entes + fontes) | 🟢 done | #14 | Package `src/leizilla/`; ADRs 0004–0009; rename `origem→ente`; `entes.py`; `fontes/ro.py`. |
| **M2.1** — Wayback client + robots.txt + publisher sidecar | 🟢 done | #15 | `wayback.py` + `robots.py` + `publisher.upload_raw` + PDF renomeado para {ia_id}.pdf. 34 testes. |
| **M2.2** — scraper.py + `scrape` CLI + fix ids no crawler | 🟢 done | #18 | `scraper.scrape_one()` orquestra robots→wayback→fetch→upload_raw. CLI `scrape` para assembleia/RO. 10 testes. |
| **M2.3** — CI workflow + `internetarchive` dep | 🟢 done | #20 | `rondonia_crawler.yml` atualizado para `uv run leizilla scrape`. `internetarchive` em pyproject.toml. |
| **M3.1** — OCR fetch + LLM parse → parser.py | 🟢 done | #17 | `parser.fetch_ocr` + `parse_law` (Haiku, fail-closed: confidence/tipo/numero/ano obrigatórios). 27 testes. |
| **M3.2** — publisher.upload_parsed() | 🟢 done | #19 | Sobe `law.xml` + `parsed_meta.json` para IA item canônico. 18 testes. |
| **M3 restante** — `parse --upload` + XSD gate + `parse-all` batch | 🟢 done | #21 | CLI integra parser→publisher; `_xsd_gate` via xmllint (bloqueia upload quando inválido); `parse-all` itera range coddoc. 15 testes. |
| **M2.4** — Rate-limit por host | 🟢 done | #25 | `make_rate_limiter` por `hostname`: scraping paralelo de múltiplas fontes sem serializar. 12 testes. |
| M2 restante — casacivil discovery + outros entes | ⚪ todo | — | casacivil.ro.gov.br (padrão de URL a auditar); fontes/{sp,federal}.py. |
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
7. **ZIP raw bulk (padrão ficha) + Parquet single-table denormalizado + IA item para distribuição.** Manifest CSV no IA como source of truth (padrão baliza). Uma única tabela `versoes` (grain: lei × dispositivo × versão) cobre tudo durante M0–M4; estrutura emerge via `SELECT DISTINCT`. Pode evoluir para tabelas separadas se DuckDB-WASM ficar gargalo (decisão em M5).
8. **Vigente compilado é canônico, histórico via timeline.** Parsed item = "como deve estar vigente hoje" (best-effort). Versões anteriores acessíveis via date picker. Fontes (DO, Casa Civil, Assembleia) cross-verificam — não competem por autoridade.
9. **Wayback Machine é caminho primário de fetch.** Crawler não bate na fonte original — dispara Wayback save de `fonte_url` + `pdf_url`, depois fetch o PDF do snapshot Wayback para upload na nossa coleção IA. Fail-open: se Wayback falha, fallback de download direto. Polite com sites .gov.br frágeis + testemunha externa automática. Detalhes em SCHEMA.md §0.5.
10. **Crawler respeita robots.txt e rate-limita.** Robots.txt rejeição é **permanente** para aquela URL (sem retry); rate-limit baseline de **1 request/segundo por host** em fallback direto. Wayback bot (princípio 9) atua como buffer — bates diretas só no fail-open. ADR-0008 formal em M1.

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

### 2026-05-22 — M2.4: Rate-limit por host (supersede M2.2 global limiter)

`make_rate_limiter()` agora retorna `Callable[[str], None]` (recebe URL) em vez de
`Callable[[], None]`. Closure mantém `Dict[str, float]` com `last[host]` por `urlparse(url).hostname` (normalizado, sem port ou credenciais no key).

**Por que**: M2 restante inclui casacivil + assembleia scraping em paralelo. Rate-limit
global serializaria as duas fontes mesmo quando são hosts distintos — cada fonte
ficaria esperando o cooldown da outra. Com tracking por host, `al.ro.leg.br` e
`casacivil.ro.gov.br` têm buckets independentes.

**Interface**: `scrape_one(..., rate_limiter)` agora passa `pdf_url` para o limiter
(era chamada sem args). Callers existentes que usam `make_rate_limiter()` recebem o
comportamento correto automaticamente — a CLI cria o limiter e passa para `scrape_one`.

**Sem breaking change real**: nenhum código externo chamava `limiter()` diretamente
(era criado e passado como opaque callable). Testes atualizados para verificar que
`rate_mock` é chamado com `_PDF_URL`.

### 2026-05-22 — M3 restante: `parse --upload` + XSD gate + `parse-all` batch

Integra M3.1 (`parser.py`) e M3.2 (`publisher.upload_parsed`) via CLI, completando
o pipeline Etapa 2 end-to-end: OCR fetch → LLM parse → XSD validate → IA upload.

**`_xsd_gate(xml_content)`** — helper em `cli.py`:
- Localiza `docs/schemas/leizilla-v0.1.xsd` via `Path(__file__).parents[2]`.
- Escreve XML em tmp file; roda `xmllint --schema ... --noout`; apaga tmp em `finally`.
- Fail-open: schema ausente ou `xmllint` não instalado → avisa + retorna True.
- Retorna False (e printa aviso) se xmllint retorna non-zero (validação falhou).

**`parse --upload/--no-upload`** (default `--no-upload`):
- Com `--upload`: chama `_xsd_gate`, depois `InternetArchivePublisher().upload_parsed()`.
- Upload falhou → exit code 1 com mensagem "Upload falhou: {error}".
- Sem `--upload`: comportamento existente (stdout XML) — zero breaking change.

**`parse-all`** — novo comando batch:
- `--start-coddoc / --end-coddoc / --ente / --fonte / --model / --upload/--no-upload / --limit`.
- Itera `leizilla-raw-{ente}-{fonte}-coddoc-{N:05d}` no range; skip silencioso se OCR ausente.
- Conta falhas de parse sem abortar; relatório final: "Batch concluído: N parseados, N falhos[, N uploaded]".
- Default `--upload` (True) para uso batch; `--no-upload` para dry-run.

**Decisões**:
- `parse-all` usa range coddoc (não query DuckDB) porque `scraper.scrape_one()` não
  insere `ia_id_raw` no DuckDB, e o schema atual não tem essa coluna. Range coddoc
  é o mesmo mecanismo que o `scrape` CLI usa — consistente e sem dependência nova.
  Limitação documentada: gaps no range (coddocs sem raw item) resultam em "OCR indisponível
  — skip" sem erro, o que é comportamento correto para um range parcialmente populado.
- `_xsd_gate` é fail-open apenas para ferramentas ausentes: `xmllint` não instalado
  ou schema não encontrado → retorna True (pipeline continua). Quando `xmllint`
  está presente e encontra erros → retorna False e o upload é **bloqueado** (exit 1 em
  `parse --upload`; skip + contagem de erro em `parse-all`). Distinção importante:
  fail-open é para falta de ferramental, não para XML inválido detectado.
- `parse-all` exit 1 se qualquer upload falhou (seja por XSD inválido ou por falha de rede/IA).
  Falhas de parse (LLM confiança baixa) não propagam exit 1 — são esperadas em batches parciais.
- 15 testes em `tests/test_cli_parse.py` cobrem todos os branches.

### 2026-05-22 — M3.1: OCR fetch + LLM parse → Leizilla XML

Implementa a primeira metade de M3 (Etapa 2 do pipeline) independentemente de M2
(M3 só precisa de `ia_id` como string — não chama funções de M2 diretamente).

**parser.py** — três funções públicas:
- `fetch_ocr(ia_id)` → baixa `{ia_id}_djvu.txt` do IA via HTTP stdlib (fail-open).
- `parse_law(ocr_text, ia_id, ente, model)` → chama Claude Haiku com prompt em cache
  (ephemeral `cache_control`); extrai JSON com `xml`, `confidence`, `tipo`, `numero`, `ano`;
  valida well-formedness; retorna `ParseResult` ou `None` se `confidence < 0.5`.
- `ParseResult` dataclass: `xml`, `parsed_meta`, `confidence`, `ia_id_parsed`, `input_tokens`, `output_tokens`.

**config.py** — `ANTHROPIC_API_KEY` adicionado (env var).

**CLI `parse`** — `leizilla parse --raw-id <ia_id> [--ente ro] [--model claude-haiku-4-5] [--output path]`

**Testes** — 27 testes em `tests/test_parser.py` (HTTP + Anthropic API totalmente mockados).
Fixes P1 endereçados: `numero` digit-only validado; `typer.Exit` não capturado por `except Exception`; `_is_well_formed` com isinstance guard.

**Decisões**:
- Modelo primário `claude-haiku-4-5` (custo baixo); `--model claude-opus-4-7` para fallback manual.
- OCR truncado em 8000 chars para manter custo baixo no Haiku (200K ctx).
- `confidence < 0.5` ou `not math.isfinite(confidence)` → None (fail-closed).
- `tipo`, `numero`, `ano` obrigatórios — ausência retorna None em vez de fabricar identifier.
- XML bem-formado verificado via `xml.etree.ElementTree`; XSD validation fica para CI gate em M3.2.
- Upload do parsed item para IA fica em M3.2 (separação de concerns, M3.1 já útil standalone).
- `ia_id_parsed = leizilla-{ente}-{tipo}-{numero:05d}-{ano}` conforme SCHEMA.md §1.3.
- Prompt com `cache_control: ephemeral` no system prompt para caching do template.
- `anthropic` adicionado como dep sem constraint de versão (consistente com demais deps).

### 2026-05-22 — M3.2: upload_parsed como método puro; CLI aguarda M3.1

`InternetArchivePublisher.upload_parsed(ia_id_parsed, xml_content, parsed_meta)` aceita
primitivos (strings + dict) em vez de `ParseResult` diretamente — evita dependência
circular entre publisher e parser, e permite testar sem instanciar o parser.

Decisão: CLI `parse --upload` adicionado nesta PR sem o comando `parse` (que vem em #17).
Quando #17 mergear, a próxima sessão adiciona o flag `--upload` ao `parse` command.

**Bugs encontrados e corrigidos na triagem desta sessão:**
- PR #15: PDF enviado para IA com nome temporário → OCR em `tmpXXX_djvu.txt` em vez de
  `{ia_id}_djvu.txt`. Fix: `shutil.copy2` para `{ia_id}.pdf` antes de `ia upload`.
- PR #17: `float()` sem try/except (ValueError em LLM response não-numérica), NaN passa
  gate (`nan < 0.5` = False), tipo/numero/ano com defaults fabricam identifier.
  Fix: math.isfinite + try/except + campos obrigatórios → None se ausentes.
- PR #16: `mergeable_state: dirty` após squash merge de #15. Cherry-pick limpo dos 3
  commits M2.2 em nova branch #18; PR #16 fechado com explicação.

### 2026-05-22 — M2.2: scraper.py + `scrape` CLI + ids corretos no crawler

`scraper.scrape_one(fonte_url, pdf_url, lei_data, publisher, rate_limiter)`:
implementa o pipeline M2 conforme princípios #9 e #10. robots check é permanente
(caller não retenta URL bloqueada). Wayback como primário; fallback direto com
rate_limiter() antes da chamada. Fail-open em todos os passos da rede. temp file
para upload e cleanup garantido em finally.

`make_rate_limiter(min_interval=1.0)` — closure com monotonic para garantir 1 req/s
entre chamadas diretas (princípio #10). Passado pelo caller para permitir mock em testes.

`crawler.discover_rondonia_laws()` — corrigido: id de `ro-casacivil-coddoc-N`
para `ro-assembleia-coddoc-N` (estava scrapeando ALRO mas usando slug errado);
adicionados campos `fonte: "assembleia"` e `chave: "coddoc-{N:05d}"` necessários
para `publisher._raw_identifier()` construir IA id correto sem duplicar prefixos.

CLI `scrape --ente ro --fonte assembleia --start-coddoc N --end-coddoc M`: 
discovery async (Playwright) + scrape_one sync para cada lei. Fontes além de
assembleia/ro delegam NotImplemented com mensagem clara.

Testes: 10 unitários em `tests/test_scraper.py`, HTTP 100% mockado.

**Próximos M2**: discovery casacivil.ro.gov.br (padrão de URL a auditar);
atualizar `rondonia_crawler.yml` para chamar `uv run leizilla scrape` em vez
do script `run_rondonia_crawler.py`; rate-limit por host (não global).

### 2026-05-22 — M3.1: OCR fetch + LLM parse → Leizilla XML

Implementa a primeira metade de M3 (Etapa 2 do pipeline) independentemente de M2
(M3 só precisa de `ia_id` como string — não chama funções de M2 diretamente).

**parser.py** — três funções públicas:
- `fetch_ocr(ia_id)` → baixa `{ia_id}_djvu.txt` do IA via HTTP stdlib (fail-open).
- `parse_law(ocr_text, ia_id, ente, model)` → chama Claude Haiku com prompt em cache
  (ephemeral `cache_control`); extrai JSON com `xml`, `confidence`, `tipo`, `numero`, `ano`;
  valida well-formedness; retorna `ParseResult` ou `None` se `confidence < 0.5`.
- `ParseResult` dataclass: `xml`, `parsed_meta`, `confidence`, `ia_id_parsed`, `input_tokens`, `output_tokens`.

**config.py** — `ANTHROPIC_API_KEY` adicionado (env var).

**CLI `parse`** — `leizilla parse --raw-id <ia_id> [--ente ro] [--model claude-haiku-4-5] [--output path]`

**Testes** — 27 testes em `tests/test_parser.py` (HTTP + Anthropic API totalmente mockados).
Fixes P1 endereçados: `numero` digit-only validado; `typer.Exit` não capturado por `except Exception`; `_is_well_formed` com isinstance guard.

**Decisões**:
- Modelo primário `claude-haiku-4-5` (custo baixo); `--model claude-opus-4-7` para fallback manual.
- OCR truncado em 8000 chars para manter custo baixo no Haiku (200K ctx).
- `confidence < 0.5` ou `not math.isfinite(confidence)` → None (fail-closed).
- `tipo`, `numero`, `ano` obrigatórios — ausência retorna None em vez de fabricar identifier.
- XML bem-formado verificado via `xml.etree.ElementTree`; XSD validation fica para CI gate em M3.2.
- Upload do parsed item para IA fica em M3.2 (separação de concerns, M3.1 já útil standalone).
- `ia_id_parsed = leizilla-{ente}-{tipo}-{numero:05d}-{ano}` conforme SCHEMA.md §1.3.
- Prompt com `cache_control: ephemeral` no system prompt para caching do template.
- `anthropic` adicionado como dep sem constraint de versão (consistente com demais deps).

### 2026-05-22 — M2.3: CI workflow atualizado + internetarchive em deps

`rondonia_crawler.yml` reescrito do zero. Versão antiga chamava
`python scripts/run_rondonia_crawler.py` (script legado, usava `upload_pdf`
e `download_pdf` — métodos que não existem mais) e `python scripts/backup_database.py`
(backup de DuckDB que não é mais o storage primário).

Nova versão: `uv run leizilla scrape --ente ro --fonte assembleia`. O comando
`scrape` (M2.2) orquestra tudo: robots check → Wayback → fetch → upload_raw.
Sem step de backup: DuckDB é staging local, não primary storage em CI.

`internetarchive` adicionado como dependência explícita em `pyproject.toml`.
Antes era instalado via `pip install internetarchive` no workflow — inconsistente
com o modelo uv. Com a dep declarada, `uv sync` instala o pacote no venv e
`ia` fica disponível para subprocess.run(["ia", "upload", ...]) dentro de
`uv run leizilla scrape`.

Adicionado `workflow_dispatch.inputs` (start_coddoc/end_coddoc) para trigger
manual com range configurável — útil para re-scrapes parciais e debugging.

### 2026-05-22 — M1: package `src/leizilla/`, rename origem→ente, ADRs, catálogo entes

Package restructure: todos os módulos movidos para `src/leizilla/` (layout src/ padrão);
`pyproject.toml` atualizado com `[tool.setuptools.packages.find] where = ["src"]` e
entry point `leizilla.cli:main`. Imports internos trocados para `from leizilla import X`.

`origem` → `ente`: coluna DuckDB, params de método, opções CLI, variáveis, mensagens,
testes. Sem migration script — sem dados de produção. `por_origem` → `por_ente` nas stats.
`DatabaseManager = DuckDBStorage` alias mantido para compat com código externo eventual.

`entes.py`: catálogo de 28 entes (federal + 26 UFs + DF) com dataclass `Ente`.
`fontes/ro.py`: fontes `casacivil` + `assembleia` para Rondônia com URLs e fonte canônica.

ADRs 0004–0009: formalizam decisões já tomadas em M0 (Wayback, IA identifiers,
XSD+checker, LexML export, robots.txt, LGPD). Nenhuma decisão nova — apenas registro
formal para rastreabilidade.

`test_storage.py`: import atualizado para `from leizilla import storage`;
`sqlite_master` → `information_schema.tables` (DuckDB não tem sqlite_master);
dados de teste atualizados para usar `ente` em vez de `origem`.

PR #3 fechada com explicação: abordagem connector-based de 2025-07-01 superseded
pelos pivôs arquiteturais de 2026-05 (PRs #6–#13).

### 2026-05-22 — M2.1: Wayback client + robots.txt + publisher sidecar

Primeira sub-tarefa de M2. Stacked em cima de M1 (PR #14, ainda não merged).

**wayback.py**: três funções puras com stdlib só (sem deps novas):
- `check_available(url)` → snapshot Wayback fresco (< 24h) ou None. Fail-open.
- `save_page(url)` → dispara POST/GET para `web.archive.org/save/`. Fail-open.
- `fetch_bytes(url)` → baixa bytes de qualquer URL (Wayback ou direto). Fail-open.

**robots.py**: `is_allowed(url)` com `lru_cache` por `robots.txt` URL. Rejeição
permanente conforme princípio #10 (callers NÃO devem retry URL bloqueada).
Fail-open: sem robots.txt = acesso permitido.

**publisher.py** atualizado: funções de construção de identifiers extraídas como
`_raw_identifier(ente, fonte, chave)` e `_bundle_identifier(ente, fonte, dt)`.
`build_raw_meta()` constrói `raw_meta.json` conforme SCHEMA.md §2.1 (hash_pdf,
provenance_wayback, fetched_from, ia_id_bundle). `upload_raw()` substitui
`upload_pdf()` — envia PDF + sidecar no mesmo IA item.

**Decisão sobre deps**: stdlib apenas (urllib.request + urllib.robotparser).
Evita depender de `httpx` ou `requests` enquanto M2 não define se o crawler
é sync ou async (Playwright vs. simples). Revisitar em M2 restante.

**Testes**: 34 novos (mock HTTP puro, sem rede). 132 total passam.

### 2026-05-21 — Fecha M0: URN LEX canônica + política re-scrape + robots.txt princípio

Resolve 3 dos 6 pendentes do SCHEMA.md §8.2. Os outros 3 (compressão Parquet, granularidade ZIP, custo LLM real) são genuinamente bloqueados por milestones futuros e ficaram deferidos com target explícito (M2, M4) em SCHEMA.md §8.3.

**URN LEX dialect** (§8.2.1): Baixei e li a spec oficial CGPID 2008 (`https://projeto.lexml.gov.br/documentacao/Parte-2-LexML-URN.pdf`, 73 páginas). Forma canônica é:

```
urn:lex:br(;LOCAL)*:AUTORIDADE:TIPO:DESCRITOR(!PATH)*
```

Diferenças vs. uso provisório (PRs #6-#12):

| Componente | Antes (errado) | Depois (canônico) |
|---|---|---|
| Local estado | `;estado:rondonia;` | `;rondonia:` (sem prefixo "estado:") |
| Local federal | `;federal;` | `:federal:` (não há local; vai direto pra autoridade) |
| Autoridade | implícita no tipo | `federal` / `estadual` / `municipal` explícito |
| Separadores | `;` em vários lugares | `:` entre LOCAL/AUTORIDADE/TIPO; `;` só dentro de LOCAL e DESCRITOR |
| Path-dispositivo | `!art-N` | `!artN` (formato LexML idArtigo, `_` interno) |

Atualizado: SCHEMA.md §5.6 reescrito com tabela de exemplos; XSD regex `UrnLex`; checker regex `_RE_URN_LEX`; 6 fixtures; tests de checker (4 helpers); tests de export LexML (continuam validando porque XSLT só copia URN). 93 tests pass + 1 skipped.

**Política re-scrape** (§8.2.4): PDF re-publicado pela fonte (hash diferente) NÃO vira novo raw item automaticamente. Só sob auditoria explícita (humana ou embeddings drift): novo raw vira `{chave}-r{N}`, raw anterior fica imutável. Implementação em M2.

**Robots.txt + rate limiting** (§8.2.5): Novo princípio load-bearing #10 em IMPLEMENTATION.md. Robots rejeição = permanente (sem retry); rate-limit baseline = 1 req/s por host. Wayback bot (princípio 9) já atua como buffer. ADR-0008 formal em M1.

**Deferred** (§8.3): compressão Parquet → M4 (precisa de Parquet writer e DuckDB-WASM real); granularidade ZIP → M2 (precisa de scrape real); custo LLM → M2/M3 (precisa de parse runs reais).

Com isso, **M0 fecha pragmaticamente**. M1 abre em sequência: package restructure + ADRs 0004-0010 + `origem→ente` rename em CLI/storage.

### 2026-05-21 — XSLT Leizilla→LexML + XSD oficial bundled (PR #11)

Último bullet de M0.2b. XSD oficial LexML brasileiro (`lexml-br-rigido.xsd` + dependências) recuperado de `https://projeto.lexml.gov.br/esquemas/` (a pasta índice está vazia mas arquivos individuais respondem 200). Bundle local em `tests/fixtures/lexml/` com:

- `lexml-br-rigido.xsd` (versão rígida) + `lexml-base.xsd` (core).
- `xml.xsd`, `xlink-href.xsd` — standards W3C.
- `mathml2.xsd` — **stub local** (oficial tem ~50 arquivos; MathML em leis é raríssimo).
- Patches nos `schemaLocation` pra apontar pros arquivos locais (offline-first).

XSLT (`scripts/leizilla-to-lexml.xsl`, XSLT 1.0 via xsltproc) mapeia:
- `<lei>` → `<LexML><Metadado><Identificacao URN/></Metadado><Norma/></LexML>`.
- `<dispositivo path="ementa">` → `<ParteInicial><Ementa/></ParteInicial>`; idem titulo-lei → `<Epigrafe>`, preambulo → `<Preambulo>`.
- `<dispositivo path="art-N">` → `<Artigo id="artN"><Rotulo/><Caput id="artN_cpt"><p/></Caput><Paragrafo/>*</Artigo>`.
- Path nesting Leizilla → ID LexML: insere `_cpt` implícito para inciso direto, letter→pos para alíneas (a→1, b→2), `subsec→sub` (alias LexML idAgregador).
- Organizacionais classificados pelo **último** token do path (`tit-2-cap-1` → `<Capitulo>`, não `<Titulo>`).

Perdas conhecidas (documentadas no XSLT header e SCHEMA.md §6.2):
- Timeline `<versao>`: colapsa para versão vigente única.
- `<fonte diverge="true">` + texto divergente: descartado.
- `<inicio tipo>`: descartado.
- `<revogacao>` parcial: vira `situacao="revogado"` no Artigo.
- `<revogacao>` total na lei: descartada (LexML `<Norma>` não tem attr `situacao`).
- Anexos: descartados (LexML requer `<ReferenciaAnexo>` em documentos separados).
- OCR ruim: já não existia no XML.

CI gate: workflow `schema-validate.yml` agora inclui xsltproc + roda XSLT contra cada fixture e valida o LexML resultante. 10 testes pytest em `tests/test_lexml_export.py` (6 parametrizados + 4 smoke).

### 2026-05-20 — Qualidade de parse não vive no XML (revisão em #9)

Auditoria de premissas durante o review do consistency checker (#9): a modelagem de "OCR ruim" como `<dispositivo path="ocr-ruim" quality="raw|low|medium|high">` carregava um problema imaginário. Premissas que quebram:

1. **OCR ruim é processo, não conteúdo.** Estado transiente do pipeline — modelo melhor + reprocessamento eventualmente resolve. Não é propriedade ontológica da lei.
2. **Audit por embeddings (§0.5) já cobre detecção.** Similaridade baixa entre `embedding(raw_djvu)` e `embedding(texto)` dispara auditoria. Pedir o LLM cravar `quality=raw` antecipadamente é o mesmo erro que `revisao-pendente`: o sistema que produz o texto não é o sistema que sabe se errou.
3. **`confianca_parse_global` no sidecar já é suficiente para filtros.** Flag duplicada no XML é redundância.
4. **Frontend não precisa de banner especial.** Texto cru tipo `LE| N° 42/8S` é visualmente óbvio pro usuário; pra automação, similaridade < threshold no audit dispara alerta.
5. **Path mágico `ocr-ruim` quebra o princípio "tipo deriva do path via token map".** OCR ruim não é tipo de dispositivo jurídico, é meta-status de parse. Mistura dimensões.

Política binária resultante:
- **Parse confiável**: publica parsed item normalmente.
- **Parse parcial**: publica; texto cru entra no `<texto>` do dispositivo regular, sem flag.
- **Parse falhou inteiro**: **não publica** parsed item. Fica só raw IA item.

Removidos: `OcrQuality` simpleType + attribute `quality` no XSD; token `ocr-ruim` do token map; invariante §7.9 (número fica reservado pra preservar chaves do checker/testes); fixture `with-ocr-ruim.xml`. Adicionado: `with-parse-parcial.xml` exercitando texto cru em dispositivo regular.

### 2026-05-20 — Redesign first-principles do Leizilla XML (supersede #7)

Auditoria a partir do princípio "dispositivo é a unidade básica" revelou que o XSD do PR #7 carregava ~10 conceitos derivados ou redundantes. Reescrita do zero. Diff radical:

- **Cai do XML**: `<header>` (URN cobre tudo), `<rotulo>` e `<rotulo_versao>` (derivados de `(tipo, path)` via token map), atributo `tipo` no dispositivo (deriva do `path`), atributo `parent` (nesting XML é o parent), atributo `urn` no dispositivo (deriva de `lei.urn-lex + "!" + path`), `<versoes>` wrapper (`<versao>` filha direta), `<versao numero="N">` (`em` é chave natural), `<fonte-canonica>` separado (não existe "fonte canônica" — existe texto canônico no `<texto>` da versão + fontes que corroboram ou divergem), `<anotacoes>` no XML (processo de parse vai para `parsed_meta.json` sidecar), `<bloco-livre>` elemento separado (OCR ruim vira `<dispositivo path="ocr-ruim" quality="raw">`).

- **Entra no XML**: herança de vigência implícita (`vigente-ate` é inferido, não armazenado; `em` herda do ancestral ou da `data-publicacao` da URN); `<inicio tipo="...">` com `<fonte>` filha quando proveniência da vigência é não-óbvia (vacatio, consolidacao, inferencia-llm, decisao-judicial); `<revogacao em em por? tipo>` rica como evento estruturado em vez de flag, com 5 tipos jurídicos (`expressa`, `tacita`, `caducidade`, `inconstitucionalidade`, `nao-recepcao`) e posição estrutural indicando escopo (raiz da `<lei>` = total; dentro de dispositivo = parcial); `<fonte>` como tag unificada em 4 contextos (versão, início, revogação na lei, revogação em dispositivo).

- **Auditoria por embeddings substitui flag manual**: LLM não sabe quando errou. Comparação `embedding(raw_djvu)` × `embedding(texto parseado)` por dispositivo detecta drift automaticamente. Sem `revisao-pendente` no XML. Plano detalhado em arquivo separado (M3+).

Resultado: XSD de ~235 linhas (vs. 359 do PR #7); 6 elementos (`<lei>`, `<dispositivo>`, `<versao>`, `<inicio>`, `<texto>`, `<fonte>`, `<revogacao>`); caso comum (lei pequena sem alterações) vira fixture de ~50 linhas com zero `em`/`vigente-ate`/`vigente-de`. Tabela de migração completa em `docs/SCHEMA.md` §9.

PR #7 marcado como superseded.

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

### 2026-05-20 — Parquet single table (versoes), denormalizado

- **Decisão**: uma única tabela `versoes` no Parquet, com grain (lei × dispositivo × versão). Metadados de lei e dispositivo denormalizados em cada row. Substitui o design anterior de 3 tabelas relacionais (`leis` + `dispositivos` + `versoes`).
- **Justificativa**: Parquet é read-only servido estaticamente do IA; dictionary encoding + SNAPPY mitigam a redundância. Zero JOIN em DuckDB-WASM = queries triviais + menos arquivos pro browser baixar (1 fetch). Estrutura (TOC, listagem) emerge via `SELECT DISTINCT`. Pré-agregados (num_dispositivos, num_divergencias) viram queries `COUNT(DISTINCT ...)` cacheáveis no client.
- **Trade-off aceito**: redundância de dados (lei metadata repetida por dispositivo-versão). Estimativa RO: 5k leis × ~30 dispositivos × ~2 versões = ~300k rows. Tamanho do Parquet medido em M4 com dados reais.
- **Revisitar em M5**: se DuckDB-WASM ficar gargalo (file size grande, latência de fetch), reavaliar split em 2 ou 3 tabelas. Por enquanto: single table.
- **Documentado em**: SCHEMA.md §3 (rewrite completo, com padrões de query exemplificados).

### 2026-05-20 — Dispositivo universal: tudo que é texto da lei

- **Decisão**: `<dispositivo>` é o elemento universal para qualquer texto da lei. `tipo` discrimina o papel.
- **Normativos** (têm `<texto>` em `<versoes>`): `titulo-lei`, `ementa`, `preambulo`, `artigo`, `paragrafo`, `inciso`, `alinea`, `item`, `anexo`, `disposicao-transitoria`, `disposicao-final`.
- **Organizacionais** (só `<rotulo>` em `<versoes>`, sem `<texto>`): `livro`, `parte`, `titulo`, `capitulo`, `secao`, `subsecao`. São uma **espécie** de dispositivo (insight do usuário), sem texto normativo próprio.
- **Header** carrega só metadados bibliográficos (ente, tipo, numero, ano, data, urn, vigente-em, revogada). `<ementa>` e nome oficial da lei migraram para dispositivos.
- **Parent obrigatório** em todo `<dispositivo>` (`parent=""` na raiz). Redundante com nesting XML mas explicitude força clareza.
- **Path normativo é global**: `art-5` permanece `art-5` independente do bloco organizacional acima. Citação forense direta = lookup literal.
- **Path organizacional namespaceia internamente**: `tit-1`, `tit-1-cap-1`, `tit-1-cap-1-sec-2`.
- **Sem coluna `eh_bloco`**: redundante com `tipo`; filtros via `WHERE texto IS NOT NULL` ou `WHERE tipo IN (...)`. Insight do usuário: "qualquer dispositivo tem um bloco que o agrupa em algum lugar, o XML permite isso" — não precisa de flag explícito.
- **Documentado em**: SCHEMA.md §0.1, §3.2, §4.2 (header slim), §4.3 (exemplo cobrindo titulo-lei + ementa + preambulo + blocos + articulação + anexo).

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
| Dataset (Parquet) | `leizilla-dataset-{ente}-v{N}` | `leizilla-dataset-ro-v0` (pré-M5; ver SCHEMA.md §3.5 mapping) |

Slug `{ente}`: `ro`, `sp`, `federal`, `ro-porto-velho` (kebab-case, UF-municipio).

Naming formal e regras de fallback: ver `docs/SCHEMA.md` (M0.2).

---

## Próximos passos imediatos

**M0.1 — fechado** ✅ (PR #6 merged).

**M0.2a — superseded** 🔴 (PR #7). Design v1 do XSD foi abandonado após auditoria first-principles. Fica como referência histórica.

**M0.2b — Redesign first-principles** ✅ (PRs #8 #9 #10 #12 merged).

**M0.3 — Fecha M0** ✅ (PR #13 merged):
- [x] **URN LEX canônica** contra spec CGPID 2008 — SCHEMA.md §5.6 + XSD regex + checker regex + 6 fixtures + tests atualizados.
- [x] **Política re-scrape** documentada (§8.2.4): `{chave}-r{N}` sob auditoria explícita, nunca automático.
- [x] **Robots.txt + rate-limit** como princípio load-bearing #10 em IMPLEMENTATION.md.
- [x] **Deferred** pendentes (§8.3): compressão Parquet → M4, granularidade ZIP → M2, custo LLM → M2/M3.

**M1 — Foundation** ✅ (PR #14):
- [x] Package restructure `src/` → `src/leizilla/` + `pyproject.toml` com `packages.find`.
- [x] ADRs 0004–0009 em `docs/adr/`.
- [x] Migração `origem` → `ente` em `cli.py` + `storage.py` + `test_storage.py`.
- [x] `src/leizilla/entes.py` com catálogo (federal + 26 UFs + DF).
- [x] `src/leizilla/fontes/ro.py` stub com fontes de Rondônia declaradas.

**M2.1 — Wayback + robots + publisher sidecar** ✅ (PR #15):
- [x] `wayback.py`: check_available + save_page + fetch_bytes.
- [x] `robots.py`: is_allowed com lru_cache por host.
- [x] `publisher.upload_raw()` + `build_raw_meta()` + `_raw_identifier()`.

**M2.2 — scraper.py + `scrape` CLI** (este PR):
- [x] `scraper.scrape_one()`: pipeline robots→wayback→fetch→upload_raw.
- [x] `scraper.make_rate_limiter()`: 1 req/s entre fallbacks diretos.
- [x] `crawler.discover_rondonia_laws()`: `fonte`+`chave` corretos no output.
- [x] CLI `scrape --ente ro --fonte assembleia --start-coddoc N --end-coddoc M`.
- [x] 10 testes unitários (HTTP mockado).

**M2 restante** (próximo):
- [ ] Discovery para `casacivil.ro.gov.br` (auditar padrão URL + campos).
- [ ] Atualizar `rondonia_crawler.yml` para usar `uv run leizilla scrape`.
- [ ] Rate-limit por host (não global) — preparação para múltiplas fontes em paralelo.
