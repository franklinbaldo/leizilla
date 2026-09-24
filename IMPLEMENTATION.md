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
| **M2.4** — Rate-limit por host | 🟢 done | 66aa4ac | `make_rate_limiter` por `hostname`: scraping paralelo de múltiplas fontes sem serializar. 12 testes. |
| **M2.5** — casacivil discovery | 🟢 done | #27 | `discover_casacivil_laws(tipo, start_num, end_num)` + CLI `scrape --fonte casacivil --tipo lei|lc`. URL: ditel.casacivil.ro.gov.br. 15 testes. (PR #26 fechado por conflito; #27 merged.) |
| **M2.6** — casacivil job no workflow | 🟢 done | #31 | `rondonia_crawler.yml` expandido com passos casacivil lei + lc; inputs `casacivil_start`/`casacivil_end`. |
| **M2 restante** — fontes SP + federal (stubs) | 🟢 done | #30 | `fontes/sp.py` + `fontes/federal.py`. SP pendente de auditoria de URL. |
| **M2.7** — Planalto federal HTML pipeline | 🟢 done | #37 | `discover_planalto_laws` + `upload_raw_html` + `scrape_one_html` + CLI `scrape --ente federal`. 30 testes. URLs legadas (pré-2002). |
| **M2.8** — `parse-all --input-type html` + chave federal | 🟢 done | #38 | `cmd_parse_all` suporta `--input-type html`; chave `tipo-NNNNN` para federal/planalto. 5 novos testes. |
| **M3.1** — OCR fetch + LLM parse → parser.py | 🟢 done | #17 | `parser.fetch_ocr` + `parse_law` (Haiku, fail-closed: confidence/tipo/numero/ano obrigatórios). 27 testes. |
| **M3.2** — publisher.upload_parsed() | 🟢 done | #19 | Sobe `law.xml` + `parsed_meta.json` para IA item canônico. 18 testes. |
| **M3.3** — `parse --upload` + XSD gate + `parse-all` batch | 🟢 done | #21 | CLI integra parser→publisher; `_xsd_gate` via xmllint (bloqueia upload quando inválido); `parse-all` itera range coddoc. 15 testes. |
| **M3.4** — `parse_law` aceita HTML + `fetch_html` | 🟢 done | cc00676 | `input_type="html"` em `parse_law`; `fetch_html(url)`; prompt adaptado; `_HTML_CHAR_LIMIT=32000`. 35 testes. |
| **M3.5** — CLI `parse --input-type html` + `fetch_ia_html` | 🟢 done | #35 | `fetch_ia_html(ia_id)` busca `{ia_id}.html` do IA; `--input-type ocr\|html` em `cmd_parse`. 314 testes. |
| **M4.1** — ETL XML→Parquet (etl.py + consolidate CLI) | 🟢 done | #28 | `xml_to_rows` + `write_parquet` + CLI `consolidate`. 76 testes. |
| **M4.2** — release-dataset CLI + publisher.upload_dataset | 🟢 done | #36 | Sobe dataset Parquet para IA; benchmark local §3.4. 229 testes. |
| **M4.3** — benchmark gatilhos §3.4 (testes) | 🟢 done | #39 | 6 testes para gatilhos file/rows/latência em `TestReleaseDatasetBenchmark`. Benchmark WASM real em M5.2. |
| **M5.1** — Frontend Astro+Svelte+DuckDB-WASM (foundation) | 🟢 done | #33 | `web/` Astro4+Svelte5+Pico2+DuckDB-WASM1.32. `deploy-web.yml` incluso. Merged. |
| **M5.2** — TanStack Query + paginação + filtros | 🟢 done | #43 | `LeiSearchUI.svelte` + filtros ente/ano + paginação. TanStack Query via bridge Svelte4 stores. Debounce cleanup + LIMIT/OFFSET safety. Merged. |
| **M6.1** — `parse-all --output-dir` + workflow parse-release | 🟢 done | #40 | `--output-dir` em `parse-all` + `parse-release.yml` (parse→consolidate→release). 2 novos testes. Merged. |
| **M6.2** — Deploy-web workflow | 🟢 done | #33 | `deploy-web.yml` — incluído em M5.1 (#33). Ativo. |
| **M6.3** — Planalto year-scoped URLs (pós-2002) | 🟢 done | #41 | `planalto_year_scoped_url` + `_camara_year_lookup` (Câmara API, lru_cache, circuit breaker, 429 sem abrir circuit). 47 novos testes. Fix SCHEMA.md. Merged. |
| **M7.1** — Claude Code routines: infra de automação | 🟢 done | #44 | `docs/routines/maintenance-prompt.md` + `claude-routine.yml` (schedule: seg+qui 10h UTC). Prompt canônico versionado no repo; workflow dispara sessões automáticas. |
| **M7.2** — Incremental tracking (check IA antes de parsear) | 🟢 done | #46 | `parse-all --skip-existing` via `list_parsed_raw_ids` com paginação cursor. 9 novos testes. Merged. |
| **M7.3** — Metadata IA enriquecida | 🟢 done | #48 | `_entity_coverage` helper + `language:pt`, `coverage:{ente}`, `description` nos 4 métodos de upload. Merged. |
| **M8.1** — `leizilla stats` via IA | 🟢 done | #49 | `count_ia_items(prefix)` + `cmd_stats --ente --ia`: mostra raw/parsed/dataset counts do IA. 9 novos testes. Merged. |
| **M8.2** — Observabilidade do pipeline (error rate) | 🟢 done | #50 | `--error-threshold` em `parse-all` + GitHub Step Summary + `check-credentials.yml`. Workflow `parse-release.yml` com `--error-threshold 20`. 5 novos testes. Merged. |
| **M9.1** — Melhoria do maintenance-prompt | 🟢 done | #51 | xsltproc na Phase 2E; instrução de conflito de sessões paralelas (Fase 1F); PRs range atualizado; princípio 7 mais preciso. Merged. |
| **M9.2** — check-credentials informacional | 🟢 done | #53 | `exit 0` em `pull_request`/`push`; só bloqueia em `workflow_dispatch`. Triggers `claude/**` e `pull_request: main`. Merged. |
| **M9.3** — `scrape --skip-existing` | 🟢 done | #54 | `list_raw_ids(ente, fonte)` + flag `--skip-existing/--no-skip-existing` em `cmd_scrape`. Evita re-scraping de itens já no IA. 10 novos testes. Merged. |
| **M9.4** — parse-release multi-fonte + skip-existing | 🟢 done | #55 | Três steps scheduled (assembleia + casacivil-lei + casacivil-lc); fix `--limit` (conta post-skip) + casacivil chave discriminant. Merged. |
| **M9.5** — `rondonia_crawler.yml` idempotente + ranges reais | 🟢 done | #57 | Schedule/dispatch split; `--skip-existing` por default; ranges 5000/6000/1300 (alinhados com parse-release). Inputs renomeados por fonte. Merged. |
| **M10.A** — manifest-driven discovery + harvest pipeline | 🟢 done | #60 | `discovery.py` (WaybackCdx + Sequential + PlaywrightCrawler); `manifests/ro.json`; `storage.discovered_resources`; `cmd_discover` + `cmd_harvest` CLI. Queue-based: discover popula DuckDB, harvest processa. |
| **M10.B** — `cmd_bundle_raw` + torrent bundling | 🟢 done | a8fee2b | `publisher.create_archive_item` + `cmd_bundle_raw`; consolida PDFs baixados em IA item único para torrent P2P. |
| **M10.C** — OCR pipeline (ocr.py + cmd_fetch_ocr) | 🟢 done | #61 | `ocr.py` (`clean_ocr_text`, `normalize_text`); `cmd_fetch_ocr` popula DuckDB com texto OCR do IA. Fix P1 (charset português). Merged. |
| **M10.2** — docs + manifest ranges + discover-harvest workflow | 🟢 done | #62 | IMPLEMENTATION.md atualizado; `manifests/ro.json` ranges reais (lei 1-6000, lc 1-1300, assembleia 1-5000); `discover-harvest.yml` workflow semanal. Merged. |
| **M11** — CI lint+test + mypy fixes | 🟢 done | #63 | `lint.yml` reescrito: `setup-uv@v5`, pytest adicionado; 8 erros mypy corrigidos em 6 arquivos (`storage`, `parser`, `crawler`, `discovery`, `publisher`, `cli`); ruff fix em `test_fetch_all_parsed.py`. Merged. |
| **M12.1** — DiscoveryStrategy base class + testes harvest pipeline | 🟢 done | #64 | `DiscoveryStrategy` base class elimina `type: ignore[attr-defined]`; 17 novos testes cobrem `storage.discovered_resources`, `SequentialDiscovery`, `run_discovery`, `harvest_pending_resources`. Merged. |
| **M12.2** — Otimização de Scrape e Parse-All via Consultas em Lote (Vetorização) | 🟢 done | #67 | Evita iterações sequenciais longas fazendo buscas em lote via API do Internet Archive e CDX da Wayback Machine. Merged. |
| **M13** — Produto público v1 | 🟢 done | — | Nome antigo: "frontend polish". Página própria por lei (`/lei/?id=…` — Texto/Versões/Evidências/Dados), busca agrupada por norma, home com manifesto + painel de cobertura, página `/cobertura/` (funil S1→S5), filtros derivados do dataset. Critérios de aceite (b)–(g) confirmados em main (`web/src/pages/{index,lei,cobertura}.astro`); (a) confirmado em produção em 2026-09-24 (ver log). |
| **M5.3** — Benchmark DuckDB-WASM real + FTS | 🔴 blocked | — | Aguarda dataset publicado (~100k+ rows RO). ILIKE no DuckDB columnar é suficiente para ~300k rows estimados; FTS só se benchmark in-browser medir > 1s. |
| **M13.1** — Releases imutáveis + ponteiro latest (issue #175) | 🟢 done | (rotina 2026-09-24) | `upload_dataset()` publica `leizilla-dataset-{ente}-v{N}-{revision}` (imutável, nunca reaproveitado) + atualiza `leizilla-dataset-{ente}-v{N}-latest` (ponteiro mutável com `latest.json`). Frontend (`db.ts`) aponta por padrão para o `-latest`; `ReleaseCitation.svelte` resolve o identifier imutável em runtime para citação. README/SCHEMA.md/`docs/okf/pipeline/release-dataset.md` atualizados. Ver log 2026-09-24. |
| **M14.1** — OPF fine-tune: fundação de prep de dados | 🟡 in-progress | — | ADR-0012 + ontologia `leizilla_normas_v1` + sampler estratificado (`opf-sample`) + helper `opf_annotate.py` vendorado + doc `docs/opf-finetune.md`. Fase 1 de 4 (prep → anotar → treinar Colab → integrar). |
| **M14.2** — OPF gold v0→v1 (anotação por subagentes + Fase 2.5 caminho 1) | 🟡 in-progress | — | v0: `data/opf/gold/` (6 leis federais reais, 251 spans) via subagentes LLM (shard-por-doc) + resolução determinística de offset + ensemble de avaliadores no eval slice. **v1 (2026-09-24)**: +13 docs reais de OCR ruidoso de RO/casacivil (train split; total 476 spans) via Fase 2.5 caminho 1 (`opf-sample`+`opf-bootstrap` pré-rotula com regex, um subagente por doc audita) — ver log 2026-09-24. Fase 2 de 4. |
| **M14.3** — OPF treino/eval (notebook Colab GPU) | 🟡 in-progress | — | `notebooks/opf_train_colab.ipynb` pronto (aponta pro `main`, gold v0 já commitado; 3 bugs reais de CLI achados em revisão e corrigidos — `--seed`→`--shuffle-seed`, `--checkpoint` ausente no train, `--label-space-json` inválido no eval). **Reativado por decisão do mantenedor em 2026-07-14** (não pelo gatilho de evidência da atualização de 2026-06-06 — o v0 segue single-fonte/texto limpo). Falta rodar no Colab (GPU), fora do alcance de sessões sem GPU/Drive interativo. Ver ADR-0012 "Atualização (2026-07-14)". |
| **M14.4** — Segmentador regex baseline + eval/errors/structure vs gold | 🟢 done | — | `segmenter.py` (Pattern B) + CLIs `opf-regex-eval` (`--errors`) e `opf-segment-check`. `evaluate_against_gold` (exact/overlap P/R/F1), `find_errors` (lista FP/FN/boundary com contexto — guiou as regras e achou drift de período no gold + provável omissão), `validate_structure` (validação da norma inteira sem gold: lacunas na numeração de artigos, fora de ordem, ementa/vigência ausentes). Regras: splitter ciente de abreviações/números, verbo operativo na revogação (notas `(Revogado pela…)` excluídas, precision 0.33→1.00 em compilados), strip de marcador líder, guard à direita, marcadores sem período final (gold normalizado). v0: exact micro-F1 **0.95** / overlap **0.99**. 28 testes. |
| **M15.1** — Instrumentação de cobertura S1-S4 (issue #174) | 🟡 in-progress | #185 | `coverage.py` agrega S1 (arquivado)→S4 (estruturado) por fonte/tipo direto do IA (index.csv + `archive.org/metadata` p/ `_djvu.txt`); `Optional[int]`/`ok_s1_s3`/`ok_s4` distinguem "não medido" de zero real. CLI `leizilla coverage [--json] [--upload]`; publica `coverage.json` no item IA do dataset (novo step diário em `parse-release.yml`, `continue-on-error`). `/cobertura/` ganha `FunilPanel.svelte` (fetch direto, não DuckDB-WASM — S1-S3 não vivem no Parquet). 22 testes offline. Baseline real medido (ver log) — falta merge + primeira publicação em produção. |

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
3. **Etapa 2 é pluggable.** Default: LiteLLM com Claude Haiku ou Gemini Flash pela chave disponível (RFC-0006). Alternativas: qualquer modelo LiteLLM via `--model`/`LLM_MODEL`, Claude Code routine com Opus, parser determinístico, curadoria manual.
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
| LLM parsing | LiteLLM (default: Claude Haiku ou Gemini Flash via chave disponível — RFC-0006) | `litellm` |
| LLM fallback | Qualquer modelo LiteLLM via `--model`/`LLM_MODEL` (ex. Claude Opus) | — |

---

## Decisões técnicas (log cronológico)

Toda decisão importante recebe entrada aqui com data. Não delete entradas — supersede com nova entrada referenciando a anterior.

### 2026-09-24 (sessão 5) — portfólio de PRs irmãs mergeado; achado real: falhas semanais do `rondonia_crawler` eram invisíveis por um bug de relatório

**Rotina agendada de portfólio, ampla.** Ao chegar, 11 PRs não-Dependabot
estavam abertas (a maioria criada minutos antes por sessões irmãs paralelas),
todas com CI verde e sem review pendente. Reconstruído o estado a partir do
repositório (sem `docs/okf/project-dag.md` em `main` — só na PR #177, ainda
aberta — então IMPLEMENTATION.md + issues seguiram como fonte de verdade,
conforme o `CLAUDE.md` vigente no início da sessão):

**Merges** (squash, um a um, atualizando cada branch contra o `main` mais
recente antes de mergear — `mergeable_state` exigia branch atualizada):
- #184 (docs, log da sessão 4) → `ed7be61`
- #183 (`parser.py`: flag de truncamento, item 4 da issue #151) → `e8988b7`
- #182 (`etl.py`: colisão de `versao_id`, item 2 da issue #151) → `5f5f0c3`
- #181 (`web/src/lib/db.ts`: leis revogadas na busca, item 1 da issue #151)

Essas quatro eram pequenas, single-purpose, sem sobreposição de arquivo entre
si — risco mínimo. PRs maiores (#177 DAG/OKR, #180 dataset imutável, #185
cobertura S1-S4, #186 xsd-gate+hygiene+testes web) e o conflito real entre
#178/#179 (ver abaixo) ficaram para reconciliação em sessão(ões) seguintes —
mergear todas ao mesmo tempo sem escalonar review para o mantenedor não é
prudente numa única passada.

**#178 vs #179 — conflito lógico real, não textual.** Ambas alegam concluir a
RFC-0003 Fase 1 com conclusões opostas: #178 decide que portar `cdx_max` para
`SequentialDiscovery` é desnecessário ("nenhum consumidor real" — baseado em
`manifests/ro.json` não ter nenhuma entrada `strategy: sequential` hoje);
#179 implementa esse porte e adiciona 8 entradas `sequential`/`cdx-auto` ao
manifesto do casacivil. Verificado diretamente: `manifests/ro.json` tem, sim,
um bloco `probe` (usado só por `cmd_scrape`, não por `discover`/`harvest`) com
exatamente os mesmos 8 templates que #179 cita — ou seja, a capacidade existe
no pipeline legado e falta no pipeline manifest-driven novo, que é
precisamente o gap que RFC-0003 pede para fechar. #178 está descrevendo
corretamente que não há consumidor **hoje** no lado `discovery`, mas errado ao
concluir que portar é desnecessário — a premissa da RFC é permitir que
`harvest` alcance paridade com `cmd_scrape`, não o contrário. Recomendação
para quem for reconciliar: mergear #179 (implementação substantiva) e não
#178 como está; a cobertura de teste nova de #178
(`test_wayback_html_response_triggers_fallback`,
`test_direct_fallback_rejects_non_pdf`) continua válida e pode ser
cherry-picked numa PR de teste separada, e o achado secundário de #178 (o
`playwright-crawler` de `assembleia` tem `end: 5000` hardcoded, sem
`cdx-auto`) é dívida real e distinta, ainda não endereçada em nenhuma PR.

**Achado do dia — causa raiz de #136/#140 (falhas semanais recorrentes
do `rondonia_crawler.yml`)**: os três jobs de scrape do workflow legado
(`scrape-casacivil-lei`, `scrape-casacivil-lc`) terminam `cancelled` (timeout)
em praticamente **toda** execução semanal desde julho — confirmado nos runs
reais via API do GitHub Actions, não suposição. Lendo o log completo do job
`casacivil-lei` de 2026-09-20 (run 35482879297): de ~308 itens processados em
3h, só **3 tiveram sucesso** — 99% de falha. As falhas vinham rotuladas
`Falha [fetch-failed]` (rede, ~129 casos) ou **`Falha [?]`** (176 casos, mais
da metade). O `[?]` não é "causa desconhecida real" — é um bug de relatório:
`cli.py` monta a linha com `result.get('reason', '?')`, mas
`publisher.upload_raw()` (chamado por dentro de `scraper.scrape_one`) reporta
suas próprias falhas (credencial ausente, índice do item ilegível, `ia`
CLI ausente, ou o `stderr` real do `subprocess.CalledProcessError` do
comando `ia upload`) sob a chave **`error`**, não `reason`. O texto real do
erro — que poderia ser exatamente o "Please reduce your request rate...
appears to be spam" que a sessão de 2026-07-14 já tinha confirmado em
produção (todos os números de um mesmo tipo dividem o mesmo IA item de range,
então centenas de uploads sequenciais ao mesmo identifier em poucas horas é
o padrão exato que dispara esse throttle) — nunca chegava ao log do
workflow. Meses de execuções semanais malsucedidas ficaram undiagnosticável
por causa desse bug de relatório, não por falta de tentativa de
investigação anterior.

**Fix mínimo** (`src/leizilla/cli.py`, dois pontos: laço de `casacivil`/
`assembleia` em `cmd_scrape` e o de `federal/planalto`): `detail =
result.get("reason") or result.get("error") or "?"` no lugar do
`.get("reason", "?")` direto. Teste novo
`test_casacivil_failure_surfaces_upload_error_detail` em
`tests/test_scrape_skip_existing.py` cobre o caso (`upload_raw`-style falha
só com `error`, sem `reason`) e falharia sem o fix. `uv run leizilla dev
check`: 784 passed, 13 skipped. `mypy src/ --ignore-missing-imports`: só os 3
erros pré-existentes de stub ausente, nenhum no arquivo tocado. **Não
resolvido nesta sessão**: a causa raiz do próprio `upload_raw` continuar
falhando (provavelmente o throttle de rate-limit do IA já documentado, mas
sem o texto real do erro ainda não dá para confirmar) — a próxima execução
semanal do `rondonia_crawler.yml` (ou um `workflow_dispatch` manual) vai
finalmente imprimir o texto real, e uma sessão futura deve ler esse log e
decidir se o `_run_ia_upload`'s `_RETRYABLE_IA_ERROR_RE` precisa de mais um
padrão, se o throughput de items/hora precisa de mais espaçamento, ou se
RFC-0003 Fase 2 (aposentar `rondonia_crawler.yml` em favor de
`discover-harvest.yml`, que não mostra o mesmo padrão de cancelamento) deve
avançar antes do previsto — as issues #136/#140 continuam abertas,
ligadas a esse achado, não fechadas (a causa raiz ainda não está corrigida,
só deixou de estar invisível).

**Não feito nesta sessão** (fora de escopo, registrado para a próxima):
reconciliar #177 (DAG/OKR — grande, própria, merece leitura e sessão de
review dedicada antes do merge, não uma passada rápida dentro de uma sessão
de portfólio), #180/#185/#186 (todas prontas e sem sobreposição lógica entre
si, mas grandes o suficiente para preferir revisão antes de mergear em
lote), issue #127 (contrato de `numero` com sufixo de letra — decisão de
design end-to-end, maior que "dívida pequena"), issue #167 (semântica de data
legada nos downloads — depende de #170, WIP de outra sessão, não tocado).

### 2026-09-24 (sessão 4, cont.) — issue #102: vitest + cobertura de `model.ts`/`format.ts` (frontend, workstream separado)

Segunda frente da mesma sessão de stewardship, escolhida por ser um workstream diferente (produto/frontend) das duas frentes de backend/pipeline já cobertas acima, sem sobreposição de arquivos com nenhuma das PRs de harvest/discovery em voo (#178/#179/#180/#181/#182/#183/#185). `web/` não tinha nenhum framework de teste configurado (`package.json` sem `devDependencies` nem script `test`) — issue #102 (aberta desde a M13/#101, "não bloqueante") pedia cobertura para a lógica pura de `web/src/components/lei/model.ts` e `web/src/lib/format.ts` (seleção de redação vigente, árvore de dispositivos, rótulos derivados do path, citação, exportação CSV/JSON), hoje só verificada manualmente.

- Adicionado `vitest` + `jsdom` como `devDependencies` (registry acessível no sandbox, `npm ping` confirmou); `vitest.config.ts` com `environment: 'jsdom'` (necessário para `location`/`navigator`/`document` usados em `absoluteLeiUrl`/`citation`/`copyText`); script `"test": "vitest run"`.
- `web/src/lib/format.test.ts` (26 testes) e `web/src/components/lei/model.test.ts` (17 testes): cobrem o escopo do issue — `currentRows()` (versão única, vigente vs. superseded, dispositivo inteiramente revogado mantendo a última redação, ordem de input invertida, empate de `em` entre duas versões abertas); `buildTree()` (artigo→parágrafo→inciso→alínea, bloco organizacional com filhos, `parent_path` órfão promovido a top-level, ordenação por `dispositivo_ordem`, ementa fora da árvore); `pathSegments`/`rotulo`/`breadcrumb` (art-1 ordinal, art-10 cardinal, art-5-a com sufixo de emenda, par-unico, inciso romano, alínea, capítulo/seção/subseção, token desconhecido fail-open); `citation`/`absoluteLeiUrl` (incluindo o teste do fallback de origem sem `location` explícito citado no issue); `rowsToCsv`/`rowsToJson` (escaping de vírgula/aspas/quebra de linha, bigint→number, datas→ISO); `groupHistorico`, `aggregateFontes`, `formatDate` (number/bigint/Date/string/null), `parseFontes` fail-open. Não coberto (fora do essencial de "modelagem/formatação", debit menor): `copyText`/`downloadBlob` (efeitos colaterais de DOM, não lógica de derivação).
- `deploy-web.yml`: novo step `Run unit tests` (`npm run test`) entre `npm ci` e o build, no job `build` que já roda em todo PR que toca `web/**` — regressão nessa lógica agora quebra CI antes do deploy, não só depois em smoke test manual.
- Validação: `npx vitest run` — 43 passed; `npm run build` — build Astro inalterado e verde.

**Achado fora de escopo, não corrigido aqui**: `npm audit` (produção, `--omit=dev`) mostra uma vulnerabilidade **crítica** em `astro@6.4.8` (XSS via atributos spread não escapados, GHSA-f48w-9m4c-m7f5) — pré-existente (versão do Astro inalterada por este PR; confirmado via `git diff package-lock.json`, nenhum diff no bloco `node_modules/astro`), já sinalizada pelo Dependabot do próprio GitHub e com fix disponível via PR #139 aberta (`astro` 6.4.8→7.1.3). Não mexida aqui — convention da rotina é pular PRs de Dependabot sem revisão própria, e um bump de major version do Astro merece sessão dedicada de teste (build + smoke visual), não algo encaixado de passagem. Registrado para quem revisar #139: a urgência é maior do que "dependency bump de rotina", é uma vulnerabilidade crítica em produção.

### 2026-09-24 (sessão 4) — issue #151, itens 3 e 5: `_xsd_gate` fail-closed em CI + higiene de docs/cadáveres

**Rotina agendada de stewardship de portfólio.** Estado reconstruído a partir do repo: `docs/okf/project-dag.md` ainda não existe em `main` (proposto pela PR aberta #177, não mergeada nesta sessão); fonte de status seguiu sendo este arquivo, por instrução do CLAUDE.md. Triagem do GitHub mostrou 12 PRs abertas, a maioria criada nas últimas horas por sessões paralelas cobrindo os itens 1/2/4 da issue #151 (PRs #181/#182/#183) e as issues #174/#175/#176 (PRs #185/#180/#179/#178). O comentário mais recente da issue #151 (18:54 UTC) já registrava os itens 3 e 5 como "ainda abertos — deixados para sessão de follow-up" — exatamente o par não coberto por nenhuma PR em voo, escolhido aqui para evitar duplicar trabalho já em andamento em outra branch.

**Item 3 — `_xsd_gate` deixava de validar XSD silenciosamente em CI**: `_xsd_gate` (`src/leizilla/cli.py`) capturava `FileNotFoundError` de `xmllint` ausente e retornava `True` incondicionalmente (fail-open), inclusive em `GITHUB_ACTIONS=true`; nenhum job de `parse-release.yml` instalava `libxml2-utils` (só `schema-validate.yml` o fazia) — o gate de integridade do pipeline diário de publicação dependia de um detalhe não documentado da imagem `ubuntu-latest`. Corrigido: `_xsd_gate` agora levanta `RuntimeError` quando `xmllint` está ausente **e** `GITHUB_ACTIONS=="true"` (capturado pelos `except RuntimeError` já existentes em `cmd_parse`/`cmd_parse_all`, virando `exit 1` visível em vez de sucesso silencioso); comportamento local inalterado (fail-open, sem travar dev sem `xmllint`). Adicionado step `Install xmllint` (`apt-get install -y libxml2-utils`) nos 4 jobs de `parse-release.yml` que chamam `parse-all --upload` (assembleia, casacivil-lei, casacivil-lc, dispatch) — o job `etl` não precisa (não chama `_xsd_gate`). 2 testes novos em `tests/test_cli_parse.py::TestXsdGate` (fail-open local vs. fail-closed em CI simulada via `monkeypatch.setenv("GITHUB_ACTIONS", "true")`).

**Item 5 — higiene de docs e cadáveres**: `README.md` tinha exemplos que falham hoje (`uv sync --dev` em vez de `--extra dev`; `discover --origem rondonia --start-coddoc…` — `discover` não aceita mais range algum, é 100% manifest-driven desde M10.A; `download`/`search` com `--origem` inexistente) — reescritos para `discover --ente ro`, `harvest --ente ro --limit 100`, `stats --ente ro`, `search --ente ro --text …`, cada um verificado com `--help` contra a CLI atual. `CLAUDE.md` tinha o mesmo drift na tabela de referência de CLI (`scrape`/`parse-all` com `--start-coddoc`/`--end-coddoc`, que não existem — o flag real é `--start`/`--end`); corrigido. `docs/DEVELOPMENT.md` (layout `src/` flat pré-M1, schema `leis` de ADR-0003, CLI com `--origem`) movido para `docs/archive/DEVELOPMENT.md` com banner RFC-0002 — conteúdo histórico preservado; `CONTRIBUTING.md` (única referência viva ao arquivo) redirecionado para `CLAUDE.md`/`docs/SCHEMA.md`. `scripts/backup_database.py` e `scripts/run_rondonia_crawler.py` deletados — ambos chamavam `publisher.upload_pdf()`, método removido desde M2.3 (confirmado: `grep -n "def upload_pdf" src/leizilla/publisher.py` não retorna nada; nenhuma outra referência viva aos scripts fora do próprio log histórico deste arquivo). `tests/test_e2e_rondonia.py` (classe-based, mais antigo) consolidado em `tests/test_rondonia_e2e.py` (function-based, mais novo e já cobria o mesmo cenário com melhor parsing de frontmatter YAML) — a única cobertura exclusiva do arquivo removido (`export_parquet`) foi portada como `test_parquet_export`; duplicação já apontada como follow-up pendente da RFC-0005.

**Validação**: `uv run leizilla dev check` — 777 passed, 13 skipped (778 vs. os 782 da sessão 3 refletem a consolidação de 5 testes duplicados, não perda de cobertura); `uv run mypy src/ --ignore-missing-imports` — só os 3 erros pré-existentes de stub `types-requests`, nenhum nos arquivos tocados; cada comando reescrito do README verificado com `--help` contra a CLI real antes de editar.

**Não feito nesta sessão**: `docs/okf/project-dag.md` (PR #177) não foi revisado/mergeado — decisão de merge de PR de outra sessão fica fora do escopo desta rotina sem revisão própria; M14 segue bloqueado para sessão headless (GPU/Colab); nenhuma das PRs #178–#185 foi tocada (workspaces de outras sessões, sem conflito com os arquivos desta).

### 2026-09-24 (sessão 4) — M15.1: instrumentação de cobertura S1-S4 (issue #174) + baseline real

**Rotina disparada por `issues.opened` (#174, aberta pelo mantenedor junto com
#175 e #176 — três recortes do próximo marco de roadmap, Q4/2026 "Cobertura RO
mais completa"; ver `Próximos passos imediatos` da sessão anterior, que já
apontava essa lacuna como o próximo passo natural).**

**FASE 1 — triagem**: #173 (harvest report parity, RFC-0003 Fase 1) já estava
mergeada em `main` quando esta sessão buscou a branch (CI ficou verde após a
sessão anterior abrir a PR). #170 (draft alheio) e #139/#142 (Dependabot)
seguem sem ação, mesma leitura das sessões anteriores.

**FASE 2 — #174 (S1-S4)**: implementado `src/leizilla/coverage.py` —
`compute_fonte_coverage(ente, fonte)` agrega, direto do IA (sem heurística
local nem DuckDB): **S1 arquivado** (toda linha de `index.csv` de um item de
range, identificada ou não — a área `_unidentified` conta aqui, ADR-0011 §1);
**S2 identificado** (linhas com `(tipo, número)` resolvido); **S3 com texto**
(HTML nativo conta na hora; PDF precisa do derivado `_djvu.txt` — checado via
`archive.org/metadata/{item}`, uma requisição por item de range, não por
arquivo); **S4 estruturado** (`list_parsed_raw_ids_strict`, variante
all-or-nothing de `list_parsed_raw_ids` pensada só pra isso — a versão
original é fail-open-pra-vazio de propósito, o que serve `parse-all
--skip-existing` mas viraria um S4 subcontado sem aviso aqui).

**Decisão de design revisada em meio à sessão**: a primeira versão fazia S1-S3
e S4 all-or-nothing *juntos* por fonte (um erro em qualquer um derrubava os
dois). O primeiro baseline real expôs o problema: `casacivil` media S1-S3 com
sucesso mas abortava antes de tentar S4 por causa de uma falha transitória em
outro grupo. Corrigido para dois flags independentes (`ok_s1_s3`/`ok_s4`) — são
consultas de dados diferentes (index.csv/metadata vs. parsed_meta.json), uma
falhar não deveria descartar a outra que já tinha sucedido.

**Achado ao rodar o baseline de verdade (não só testes mockados)**: a consulta
S4 (`list_parsed_raw_ids_strict`) fazia uma requisição HTTP por item parsed
sem retry — rodando contra a coleção real de RO (~20 itens parsed hoje),
~10% delas dava timeout transitório (medido isolando a chamada: 2 de 20).
All-or-nothing sem retry tornaria S4 praticamente sempre `null` em produção,
o oposto do "baseline reproduzível" que a issue pede. Adicionado retry curto
(3 tentativas, backoff de 1s, timeout 20s) tanto na listagem paginada quanto
no fetch por item — ainda all-or-nothing depois de esgotar as tentativas, só
não all-or-nothing na primeira flutuação de rede.

**Baseline real (2026-09-24T18:47Z, medido sem credenciais — API pública do
IA, leitura apenas)**:

```
ente=ro
casacivil: S1=1196 · S2=1196 · S3=540 · S4=20   (decreto: 307/307/215/0 · lei: 889/889/325/20)
assembleia: S1=0 · S2=0 · S3=0 · S4=0            (nenhum raw publicado ainda nessa fonte)
```

Consistente com o que a sessão de 2026-09-24 (sessão 2) já tinha registrado
lendo `list_raw_ids` diretamente ("casacivil tinha 1196 itens disponíveis" /
"assembleia retornou zero itens") — confirma que a agregação nova bate com o
que as outras partes do pipeline já sabiam, só que agora como número público
e por estágio.

**Publicação**: `leizilla coverage --upload` sobe `coverage.json` para o mesmo
item IA do dataset (`leizilla-dataset-{ente}-v{version}`); novo step no job
`etl` de `parse-release.yml` (diário, `continue-on-error: true` — instrumentação
não pode derrubar a release do dataset). Como esta sessão não tem
`IA_ACCESS_KEY`/`IA_SECRET_KEY`, a primeira publicação real fica para a
próxima execução agendada do workflow (secrets só existem em produção,
RFC-0004). `/cobertura/` ganha uma seção nova (`FunilPanel.svelte`) que busca
`coverage.json` diretamente (não é dado do Parquet, não passa pelo
DuckDB-WASM) — mostra `?` em vez de um número quando uma medição falhou, nunca
um 0 silencioso.

**Docs**: PRD §10.4 atualizado de "a implementar" para a implementação real;
`docs/SCHEMA.md` não muda (cobertura não é dado do modelo `versoes`, é
instrumentação de pipeline). `IMPLEMENTATION.md` (este arquivo) ganha M15.1.

**Não feito nesta sessão** (fora de escopo, PR própria — issue #174 pede
"fonte quando possível", não bloqueio total): quebra de S4 por fonte usa
`list_parsed_raw_ids_strict` (um `parsed_meta.json` fetch por item parsed do
*ente inteiro*, filtrado depois por fonte) — funciona, mas não escala
linearmente; se o acervo crescer para milhares de itens parsed, vale revisitar
(ex.: gravar `fonte` no próprio identifier do item parsed, ou aceitar S4 só
por tipo). Issues #175 (latest pointer) e #176 (cdx-auto discovery) — as duas
outras PRs abertas pelo mantenedor na mesma leva de #174 — não foram tocadas
nesta sessão (uma sub-tarefa por PR, conforme a rotina).

### 2026-09-24 (sessão 4) — RFC-0003 Fase 1 concluída: `cdx-auto` nas estratégias de discovery (issue #176)

Rotina disparada pela abertura da issue #176 (o pedaço da Fase 1 da RFC-0003
que a sessão 3 tinha deixado explicitamente para uma sessão própria, por
mexer em mais superfície). PR #173 (paridade de relatório harvest↔scrape,
sessão 3) já tinha sido mergeada em `main` (`9b78bdf`) antes desta sessão
começar.

**Mudança**: `src/leizilla/discovery.py` ganhou `resolve_cdx_max_by_tipo(prefix)`
— consulta a CDX API uma única vez para um prefixo e classifica cada PDF
casado via `parse_filename`, retornando o maior número arquivado por
`tipo_documento`; fail-safe (`{}`) em erro de rede, timeout ou resposta
vazia/malformada. `WaybackCdxDiscovery.run()` foi refatorado para reusar o
fetch (`_fetch_cdx_pdf_records`) sem mudar comportamento externo (mesmos
testes, sem alteração).

`SequentialDiscovery` agora aceita `"end": "cdx-auto"` no manifesto (além do
inteiro fixo já suportado): resolve o limite via `resolve_cdx_max_by_tipo()`
usando o diretório do primeiro template como prefixo CDX e o
`tipo_documento` derivado do próprio template; se a CDX não resolver nada
(vazia/erro/timeout), cai em `end_fallback` (default 10, configurável no
manifesto) — nunca propaga exceção nem aborta o discover. `"end"` que não é
inteiro nem `"cdx-auto"` levanta `ValueError` na construção da estratégia.

`manifests/ro.json` ganhou 8 entradas `sequential` (uma por tipo de
casacivil: lei, lc, decreto via `D`/`DEC`, decreto-lei, ec, resolução,
portaria), todas `"end": "cdx-auto"`, espelhando exatamente os mesmos
templates/`head_check` que o `probe` legado do `cmd_scrape` já usava — então
`discover → harvest` agora cobre o mesmo caso (probing sequencial até o
maior número arquivado) que antes só existia em `cmd_scrape`/casacivil. O
`probe` do manifesto e o próprio `cmd_scrape` **não foram tocados** — seguem
com sua própria lógica duplicada de `cdx_max`; substituí-la por um wrapper
fino sobre `discover`/`harvest` é Fase 2 (redirecionamento de workflow),
explicitamente fora do escopo desta issue/PR.

**Testes**: `tests/test_discovery.py` ganhou `TestResolveCdxMaxByTipo` (resposta
normal, filtro de status/mimetype, resposta vazia, timeout, erro de rede, JSON
malformado) e `TestSequentialDiscoveryCdxAuto` (resolução normal, fallback em
CDX vazia/erro, `end_fallback` customizado, `end` inválido levanta
`ValueError`, `start` além do fim resolvido não quebra, `end` fixo nunca
consulta a CDX). `test_run_discovery`/`test_run_discovery_scoped_to_fonte`
atualizados para o novo formato do manifesto de casacivil (8 estratégias
`sequential` a mais) e para mockar `CasacivilIndexDiscovery` explicitamente
(evita I/O real em teste unitário).

**Docs**: RFC-0003 marca a Fase 1 como concluída (#173 + #176); IMPLEMENTATION.md
("Próximos passos imediatos") e `docs/okf/discovery/strategies.md` atualizados
para descrever `"end": "cdx-auto"`.

**Validação**: `uv run leizilla dev check` — 796 passed, 13 skipped.
`uv run mypy src/ --ignore-missing-imports` — só os 3 erros pré-existentes de
stub ausente (`types-requests`), nenhum em arquivo tocado.

**Não iniciado nesta PR** (por escopo explícito da issue #176): Fase 2
(`rondonia_crawler.yml` → `discover`+`harvest`; `cmd_scrape` vira wrapper
fino) e Fase 3 (deprecação do `scrape`).

### 2026-09-24 (sessão 4) — 3 achados do review automatizado (issue #151) viram PRs pequenas e independentes

**Rotina agendada de portfólio.** Ao chegar, quatro PRs de sessões irmãs já
estavam abertas com CI verde e `mergeable_state: clean` sobre o mesmo `main`
(`9b78bdf`): #177 (`docs/okf/project-dag.md` — ledger OKR/DAG canônico,
ainda não mergeado, então não tratado aqui como fonte de verdade), #178/#179
(RFC-0003 Fase 1: teste de paridade harvest/scrape + `cdx-auto` no
discovery) e #180 (releases de dataset imutáveis + ponteiro `latest`,
fechando o "risco silencioso" nº1 da issue #151). Nenhuma foi tocada por
esta sessão — já estavam prontas para o mantenedor mergeliar; duplicar esse
trabalho desperdiçaria a sessão. **Atenção para quem for mergear em
sequência**: #180 e a PR desta sessão (#181) tocam `web/src/lib/db.ts` em
funções diferentes — conflito textual é possível dependendo da ordem de
merge, não de lógica.

Para não duplicar esse esforço, esta sessão verificou os 3 itens
**verificáveis e ainda não cobertos** da lista ordenada da issue #151
(revisão automatizada `stealth/ox-alpha` de 2026-08-24) contra o código
atual — todos os 3 se confirmaram reais — e abriu uma PR pequena e
independente para cada um:

1. **#181 — `web/src/lib/db.ts`: leis totalmente revogadas invisíveis.**
   `buildWhere()` tinha `ate IS NULL` incondicional; toda lei revogada por
   completo (todo dispositivo com `ate` preenchido, cascata do ETL) sumia
   da busca, dos filtros, de `getRecentLeis` e do `/lei/?id=…` (o usuário
   nunca chegava a ter o link). `DispositivoTree`/`model.ts` já sabiam
   renderizar o banner de "revogada" — só nunca recebiam a linha. Removido
   o filtro incondicional; modo-navegação e `getRecentLeis` agora preferem
   a versão vigente via `ORDER BY (ate IS NULL) DESC, …` com fallback para
   a última revogada, em vez de excluir a lei. `npm run build` limpo (sem
   suíte de teste de frontend ainda — gap conhecido, issue #102).
2. **#182 — `etl.py`: colisão de `versao_id` dentro do mesmo dispositivo.**
   Duas `<versao>` sem `em` no mesmo dispositivo herdam a mesma âncora →
   mesmo `versao_id` → `consolidate_xmls` levanta `ValueError` →
   `parse-release.yml` falha o dia inteiro sem publicar dataset nenhum.
   XSD-válido (checker de consistência não roda no pipeline de parse — só
   o XSD gate, fato canônico #13). Corrigido com sufixo `-v2`/`-v3` só em
   caso de colisão real; formato documentado inalterado no caso normal.
   Fixture de teste ficou inline em `test_etl.py` (não em
   `tests/fixtures/leizilla_xml/`, porque esse diretório também é o corpus
   "limpo" que `test_schema_consistency.py` varre — essa forma viola §7.07
   de propósito).
3. **#183 — `parser.py`: truncamento de OCR/HTML sem sinalização.**
   `parse_law` corta em `_OCR_CHAR_LIMIT`/`_HTML_CHAR_LIMIT` sem registrar
   nada — leis longas (orçamentos, estatutos) são publicadas como
   "completas" com confiança alta. Adicionado `texto_truncado` +
   `tamanho_texto_original` em `parsed_meta`; `docs/SCHEMA.md` atualizado.

Gates locais (mesmo SHA de cada branch, reconciliados por PR): `uv run
leizilla dev check` (787 passed/13 skipped no #182), `uv run pytest
tests/test_parser.py` (62 passed no #183), `npm run build` (#181), `mypy
src/ --ignore-missing-imports` limpo nos três.

**Itens da issue #151 ainda não endereçados** (registrados para a próxima
sessão, não duplicar): item 3 (`_xsd_gate` fail-open quando `xmllint`
ausente em CI — hoje só funciona por acidente da imagem `ubuntu-latest`) e
item 5 (higiene de docs: README/CLAUDE.md com flags de CLI mortas,
`scripts/backup_database.py`/`scripts/run_rondonia_crawler.py` chamando
`publisher.upload_pdf()` inexistente, teste e2e duplicado). Comentário
correspondente deixado na issue #151.

`docs/okf/project-dag.md` **não existe em `main`** nesta sessão (só na PR
#177, ainda aberta) — a próxima sessão deve tratá-lo como ledger canônico
só depois do merge; até lá, IMPLEMENTATION.md + `docs/rfc/` + issues
seguem sendo a fonte de verdade reconstruível.

### 2026-09-24 (sessão 3) — M13.1: releases de dataset imutáveis + ponteiro latest (issue #175)

**Rotina disparada por webhook `issues.opened`** (issue #175, aberta pelo mantenedor).

**Problema verificado**: `parse-release.yml` publica diariamente com `--version 0`, e o
mesmo identifier (`leizilla-dataset-ro-v0`) era usado tanto como "latest móvel" quanto
como artefato citado publicamente como release — `upload_dataset()` sobrescrevia o
mesmo item IA a cada publicação agendada, então citar `leizilla-dataset-ro-v0` hoje e
amanhã resolvia para conteúdos diferentes. Confirmado lendo `publisher.upload_dataset`,
`cli.cmd_release_dataset`, `parse-release.yml` e o fallback hardcoded em `web/src/lib/db.ts`.

**Correção — separar release imutável de ponteiro mutável**:
- `publisher._dataset_revision()`: timestamp UTC compacto (`YYYYMMDDtHHMMSSz`),
  IA-identifier-safe, auto-computado se não passado explicitamente.
- `upload_dataset()` agora publica `leizilla-dataset-{ente}-v{version}-{revision}` —
  nunca reaproveita um identifier existente, então cada release agendada é um item IA
  novo, permanentemente recuperável. `build_dataset_meta()` ganha o campo `revision`.
- Novo método `_publish_latest_pointer()` (chamado por padrão, `publish_latest=True`):
  reenvia o mesmo parquet/meta + um `latest.json` pequeno para o identifier fixo
  `leizilla-dataset-{ente}-v{version}-latest`, com `identifier`/`ia_url`/`parquet_url`
  apontando para o release imutável recém-publicado. Fail-open: falha no ponteiro não
  derruba a publicação do release imutável (já é o artefato citável); `cmd_release_dataset`
  ecoa um aviso nesse caso em vez de abortar.
- Frontend (`web/src/lib/db.ts`): fallback hardcoded trocado de `.../leizilla-dataset-ro-v0/...`
  para `.../leizilla-dataset-ro-v0-latest/...` — a URL que o portal consulta por padrão
  passa a ser explicitamente o ponteiro documentado como mutável, não mais um item que
  finge ser uma versão estável. Novo `fetchLatestPointer()` (fail-open) resolve
  `latest.json` em runtime para exibir o identifier imutável real. Novo componente
  compartilhado `ReleaseCitation.svelte` (usado em `HomePanel`, `cobertura.astro` e
  `Dados.svelte` — as três superfícies "página de dados" do produto) substitui o texto
  estático "Como citar" que citava o ponteiro móvel por uma citação resolvida em
  runtime contra o release imutável, com fallback honesto quando a resolução falha.
- Docs: README (`§ Releases imutáveis vs. ponteiro latest`), `docs/SCHEMA.md` §1.4/§5.5,
  `docs/okf/pipeline/release-dataset.md` — todos atualizados para descrever os dois
  identifiers e por que cada um existe.
- `parse-release.yml` não precisou de mudança — chama `release-dataset --version N` sem
  saber de `revision`/pointer, ambos internos ao comando.

**Testes**: 11 novos em `tests/test_publisher_dataset.py` (revisão default/explícita/
inválida, identifiers nunca reaproveitados, ponteiro publicado por padrão e
desabilitável, `latest.json` referenciando o release correto, falha do ponteiro não
derruba o release, CLI ecoando sucesso/aviso do ponteiro). `uv run pytest`: 793
passed/13 skipped (suíte completa, todos os testes existentes intactos). `uv run mypy
src/`: só os 3 erros pré-existentes de stub do `types-requests` (não tocam os
arquivos alterados). `npm run build` (web): passa sem erros de tipo.

**Não feito nesta sessão** (fora de escopo, não pedido pela issue): backfill de
`latest.json` para o item `leizilla-dataset-ro-v0` já publicado antes desta mudança
(a próxima execução do `parse-release.yml` já cobre isso publicando um release
imutável real + o ponteiro `-latest` pela primeira vez); migração/deleção do item
`v0` legado (releases antigas continuam diretamente recuperáveis por design — nunca
apagamos).


### 2026-09-24 (sessão 3) — merge PR #172; RFC-0003 doc-drift corrigido; harvest ganha paridade de relatório com scrape (Fase 1 parcial)

**FASE 1 — triagem**: 4 PRs abertas. #139/#142 (Dependabot) — anotadas e
puladas (regra da rotina). #170 (`steward/vigencia-data-ato-provenance`,
autor humano) — segue draft, marcada pelo próprio autor como "GREEN parcial",
com TODOs pendentes; não é desta rotina mexer em WIP alheio. #172
(`claude/ecstatic-franklin-llu93p`, gold v1 do OPF) — CI verde (4/4),
`mergeable_state: clean`, sem review bloqueante (só um comentário do bot
Codex avisando que bateu o limite de uso, não é uma review); mergeada via
squash (`5f4a22b`).

**FASE 2 — trabalho novo**: M14 (OPF) segue bloqueado para sessão headless
(M14.3 precisa de GPU/Colab interativo; M14.2 precisa de mais fontes RO
publicadas no IA — `assembleia` ainda não tem raw items). Ao revisar
"Próximos passos imediatos", achei doc-drift real: a RFC-0003
(convergência scrape→harvest) dizia "aguardando merge de #93 e #94" — ambas
estão mergeadas desde 07/2026, então a Fase 1 da RFC já podia ter começado.
Escolhi o pedaço mais estreito e reversível da Fase 1 — paridade de
relatório entre `harvest` e `scrape` — em vez da mudança maior (portar
`cdx_max` do CDX da Wayback para as estratégias de discovery), que mexe em
mais lugares e merece sessão própria:

- `scraper.harvest_pending_resources` agora popula `stats["items"]` (um dict
  por recurso processado: `status`/`chave`/`ia_id`/`ia_url` no sucesso,
  `status`/`chave`/`reason` na falha) — chave nova, não quebra os 3 contadores
  agregados que os testes existentes já checavam.
- `cli.cmd_harvest` itera `stats["items"]` e imprime `OK: <ia_id> → <ia_url>`
  / `Falha [reason]: <chave>` por recurso, igual ao que `cmd_scrape` já fazia
  — antes só saía o agregado (sucesso/falhas/robots-blocked), sem rastro de
  qual item falhou e por quê.
- 1 teste novo (`test_items_report_parity_with_scrape`) cobrindo sucesso +
  robots-blocked no mesmo lote. `uv run leizilla dev check`: 782 passed, 13
  skipped. `mypy src/ --ignore-missing-imports`: só os 3 erros pré-existentes
  de stub ausente (`types-requests`), nenhum nos arquivos tocados.
- RFC-0003 e a entrada correspondente em "Próximos passos imediatos"
  atualizadas para não ficar em drift (princípio 2): status "aprovado, Fase 1
  em andamento"; registrado explicitamente o que falta (cdx_max→discovery;
  Fases 2/3 ainda não iniciadas).

**FASE 3 — encerramento**: ver PR desta sessão (branch
`claude/ecstatic-franklin-bzz7x0`) para o resumo final.

### 2026-09-24 (sessão 2) — M14.2: gold v1 via Fase 2.5 caminho 1 sobre OCR real de RO; PRs #115/#116 corrigidas para "merged"

**Rotina agendada, FASE 1**: única PR aberta acionável era #170 (draft de outra
sessão, já triada — sem ação). #139/#142 são Dependabot (skip). A entrada de
log anterior deste mesmo dia registrava #115/#116 como abertas aguardando CI;
checagem direta no GitHub mostrou ambas **mergeadas pelo mantenedor**
diretamente (`merged_by: franklinbaldo`, 15:53:14 e 15:57:46 UTC) — fora do
fluxo desta rotina, então nada para essa sessão fazer ali além de corrigir o
texto que tinha ficado em drift (princípio 2 do prompt de rotina: "docs e
código nunca ficam em drift").

**FASE 2 — M14.2, Fase 2.5 caminho 1 (`docs/opf-finetune.md`), primeira
execução real**: com `opf-bootstrap` disponível (mergeado nesta mesma janela),
esta sessão rodou o caminho barato de escala do gold pela primeira vez sobre
dados publicados de verdade:

1. `opf-sample --ente ro --fontes assembleia,casacivil --n 60` — `assembleia`
   retornou **zero** itens (`list_raw_ids` vazio; nenhum raw publicado ainda
   nessa fonte). `casacivil` tinha 1196 itens disponíveis; amostra de 60
   rendeu 13 documentos com OCR utilizável (limiar de 200 chars).
2. `opf-bootstrap` pré-rotulou os 13 com o segmentador regex: 240 spans,
   aviso correto de `ementa` zerada na amostra (decretos/leis de casacivil
   raramente têm uma linha de ementa isolada como as leis federais do v0).
3. **Anotação por subagentes (skill `llm-work-via-subagents`, não script com
   API key)** — 13 subagentes em paralelo, um por documento, cada um
   auditando (confirmar/corrigir/completar) o pré-rótulo regex contra o OCR
   real, seguindo o método "regex-bootstrap + subagent audit" do PR #116.
   Cobertura final: `ementa` foi capturada em **todos os 13** (regex tinha 0)
   — os subagentes acharam a linha de ementa mesmo sem o padrão ALL-CAPS
   típico do federal.
4. **Correção de consistência entre documentos (papel do orquestrador, não
   dos subagentes)**: `opf_annotate.py validate` pegou 14 erros reais de
   overlap (BIOES permite um span por região) — em 2 documentos (`vigencia`/
   `revogacao` incluindo o marcador `Art. N -` que já tinha seu próprio
   `art_marcador`) e em 2 documentos com leituras de algarismo romano
   ambíguas (`"III -"` contém `"II -"` como substring de cauda, que por sua
   vez contém `"I -"`) que um subagente havia deixado duplicadas em vez de
   substituídas. Corrigido programaticamente (manter o span mais longo em
   cada overlap) + um caso de julgamento divergente entre subagentes: 3 de 4
   documentos com o padrão "texto novo de outra lei citado literalmente"
   (uma lei que alterra outra) trataram esse texto citado como hard-negative
   (não é a estrutura própria deste documento) — o 4º manteve os marcadores
   citados; corrigido manualmente para consistência com os outros 3, com nota
   registrada no arquivo de trabalho. `opf_annotate.py validate` limpo (0
   erros, 0 warnings) após as correções; `from-spans` resolveu as 13×`finds`
   sem nenhum erro de match ambíguo.
5. **Promovido para `data/opf/gold/train.jsonl`** (nunca para `val`/`test`:
   Fase 2.5 é explícita que a auditoria de um único subagente não atinge a
   barra do ensemble de 4 papéis que o eval slice exige). `manifest.json`
   atualizado: `train` 4→17 docs, `total_spans` 251→476, `ente_fonte` ganha
   `ro/casacivil`, `known_limitations` reescrito (eval slice segue v0-only;
   `ro/assembleia` sem itens raw; ver achado abaixo).
6. **Achado por sinal, não por exemplo isolado (ao contrário do
   `lei-00001-1983` mencionado em 2026-07-14)**: `leizilla opf-regex-eval`
   contra o gold v1 mostra o baseline regex caindo de **0.95 → 0.86 F1
   exato** (overlap 0.99→0.94), concentrado nas categorias por cue de frase
   (`ementa` exato 0.24, `revogacao` 0.33, `vigencia` 0.38 — overlap
   permanece 0.94–1.00, ou seja, a região certa é achada, só não a fronteira
   exata). Essa é justamente a métrica que a atualização de 2026-06-06 da
   ADR-0012 definiu como gatilho formal para o fine-tune (não um caso
   isolado). Registrado aqui para quem decidir sobre M14.3; a reativação de
   2026-07-14 já tinha rodado o smoke test antes desse gatilho ser atingido
   — agora há evidência real de degradação para justificar tanto o smoke
   quanto um treino com pretensão de produção mais adiante.

**Não feito nesta sessão**: caminho 2/3 da Fase 2.5 (silver via XML parseado;
pré-filtro dirigido para `ali_marcador`/`vigencia`/`revogacao` escassos);
novo smoke-test do Colab sobre o gold v1 (M14.3 seguindo fora do alcance
headless); amostragem de `ro/assembleia` (zero itens raw publicados — nada a
amostrar até a fonte ter cobertura no IA).

### 2026-09-24 — Rotina de manutenção: M13 confirmado em produção; hang de teste corrigido; PRs #115/#116 atualizadas

**Sessão de rotina agendada.** Triagem das PRs abertas (mais antiga → mais nova):

**#115 e #116 (OPF, abertas desde 2026-07-16, LGTM do mantenedor, `mergeable_state:
behind`)** — 2+ meses sem CI porque nenhum push novo disparou um run desde então.
Nenhuma toca em código que mudou de forma incompatível: merge local de `main` em
ambas foi limpo (zero conflitos; `cli.py` de #116 fez auto-merge). Empurradas para
os branches das PRs para disparar CI fresco; PRs permanecem abertas aguardando
esse resultado (nunca auto-merge de PR de outra sessão sem CI verde confirmado no
GitHub, mesmo com LGTM prévio).

**Achado ao rodar a suíte completa nesse processo**: `uv run pytest -q` travava
por 10+ minutos num único teste, tanto nos branches mesclados quanto no `main`
puro (confirmado isolando a causa — não é regressão de #115/#116).
`cmd_parse_all` consulta `list_parsed_raw_ids()` (IA real) sempre que
`--skip-existing` está ativo (default), mas — ao contrário do `list_raw_ids()`
umas linhas abaixo — nunca ganhou o guard que detecta sessão de pytest e evita a
chamada de rede real quando o teste não mockou a função. A maioria dos testes de
`TestCmdParseAll` não mocka `list_parsed_raw_ids`, então cada um deles batia de
verdade no `archive.org` — violando a garantia do projeto de suíte 100% offline
(CLAUDE.md) e, neste sandbox de rede restrita, travando por vários minutos.
Corrigido em PR #171: guard simétrico ao de `list_raw_ids`, extraído para um
helper `_is_mocked()` compartilhado. Suíte completa: 91s → ~50s, 760 passed/13
skipped, determinística.

**M13 estava marcado errado**: a tabela dizia "(a) bloqueado pela ativação
RFC-0004". Verificação direta (sem credenciais, tudo público) mostra que não
está: `archive.org/advancedsearch.php?q=identifier:leizilla-dataset-ro*` retorna
`leizilla-dataset-ro-v0`; `franklinbaldo.github.io/leizilla/cobertura/` (produção,
HTTP 200) já linka esse item; `web/src/lib/db.ts` tem esse item como fallback
hardcoded do `PUBLIC_PARQUET_URL`; e `dataset_meta.json` do item mostra
`generated_at: 2026-09-24T11:11:31Z` com `git_sha` igual ao HEAD atual de `main` —
ou seja, o pipeline `parse-release.yml` publicou uma release **no mesmo dia**
desta sessão, com `row_count: 199` (contra 19 leis em 2026-07-14). RFC-0004 está
executada e os releases recorrentes (M9.4/M9.5) estão rodando de verdade em
produção, não só planejados. M13 fechado como done; "Próximos passos imediatos"
reescrito para apontar ao próximo marco real do roadmap (README.md, Q4/2026:
cobertura RO mais completa — a parte de "releases recorrentes" desse marco já
está em produção).

**#170 (draft, `steward/vigencia-data-ato-provenance`)** — o próprio corpo da PR
lista o que falta (reconciliar `SCHEMA.md`/`IMPLEMENTATION.md` e
`check_schema_consistency.py`, rodar todos os gates) e registra um bloqueio de
DNS numa sessão anterior. Não é desta rotina retomar um redesign de schema em
andamento de outra sessão sem esse contexto — deixado como está para a sessão que
o abriu (ou o mantenedor) continuar.

**#139 e #142 (Dependabot)** — autor externo, anotadas e puladas por regra da
rotina.

### 2026-07-15 — `claude-routine.yml` quebrado silenciosamente desde 2026-06-08

**Achado**: auditoria dos runs agendados (`event: schedule`) mostrou que a
sessão de manutenção automática (Mon/Thu, `docs/routines/maintenance-prompt.md`)
falhava em ~20s em **todas as execuções da amostra**, de 2026-06-08 a
2026-07-13 (11 runs consecutivos) — mais de um mês sem rodar de fato,
silenciosamente (só um `Notify on failure` — sem alarme visível fora do Actions
tab). Duas causas, ambas drift de versão da action `anthropics/claude-code-action@beta`:

1. `prompt_file: docs/routines/maintenance-prompt.md` não é mais um input
   válido da action (`##[warning]Unexpected input(s) 'prompt_file'`) — o
   prompt real nunca chegava a ser usado.
2. Sem `github_token` próprio no `with:`, a action tenta obter um token via
   GitHub OIDC (fluxo padrão do GitHub App gerenciado pela Anthropic), o que
   exige `permissions: id-token: write` — ausente no workflow, causando
   `Failed to setup GitHub token: Could not fetch an OIDC token`.

**Correção**: `permissions.id-token: write` adicionado; novo step carrega o
conteúdo de `maintenance-prompt.md` num output (`$GITHUB_OUTPUT` com heredoc)
e passa via `prompt: ${{ steps.load_prompt.outputs.text }}` (input atual da
action; `prompt` só aceita texto literal, não path).

Auditoria também cobriu `wayback-save.yml` (falhava por `--end` inexistente
na CLI — já corrigido em commit posterior ao da amostra de falha, nenhuma ação
necessária) e `rondonia_crawler.yml` (cancelamento por timeout do job
monolítico antigo — já dividido em 3 jobs com timeouts próprios, também sem
ação necessária). `discover-harvest.yml` teve um `decreto` cancelado por
timeout de 360min com Discover sozinho levando ~4h — o `max-parallel: 2` do
PR #112 deve ajudar, mas vale monitorar o próximo sábado; se `decreto`
continuar estourando, considerar separar Discover e Harvest em jobs com
timeout próprio.

### 2026-07-14 — Pacing de parse/harvest dentro de cotas + retry/backoff no upload IA

**Achado**: `parse-release.yml` rodava só às segundas, com 3 jobs paralelos
(assembleia + casacivil-lei + casacivil-lc) a `--limit 50` cada — até 150
tentativas de parse num único dia, contra um orçamento real de free tier de
**~20 requisições/dia por modelo** (confirmado em produção nesta mesma
sessão: `429 RESOURCE_EXHAUSTED`, `quotaId
GenerateRequestsPerDayPerProjectPerModel-FreeTier`, `quotaValue: 20`, tanto
para `gemini-2.5-flash` quanto `gemini-2.5-flash-lite`). As 3 fontes
competiam pelo mesmo orçamento diário compartilhado, e a maior parte das
150 tentativas terminava em 429 — desperdício, não distribuição. Achado
análogo em `discover-harvest.yml`: matrix de 7 tipos em paralelo (sem
`max-parallel`) faz até 7 processos de upload baterem no IA ao mesmo tempo;
uma rajada de ~15 uploads em ~10min já levou o IA a recusar como spam
("Please reduce your request rate...") na sessão de go-live desta mesma
data.

**Correção — `fix(ci): pace parsing and IA uploads within service quotas`**:

1. **`parse-release.yml`**: cron mudou de semanal (segunda) para **diário**,
   `--limit 50` → **`--limit 6`** por fonte (18/dia, margem sob o teto de
   20), e as 3 fontes agendadas passam a rodar **em série** via `needs`
   (não mais em paralelo) — evita que rodem simultaneamente disputando o
   mesmo orçamento de LLM. `if: always()` nas dependentes garante que uma
   fonte falhando não pule as seguintes. `concurrency: group: parse-release`
   impede que um dispatch manual sobreponha o cron.
2. **`discover-harvest.yml`**: `max-parallel: 2` na matrix de 7 tipos (era
   sem limite) + `concurrency: group: discover-harvest`.
3. **`publisher.py`**: novo método `InternetArchivePublisher._run_ia_upload`
   substitui as 7 chamadas diretas a `subprocess.run(["ia", "upload", ...])`
   — retry exponencial (até 5 tentativas, backoff 2s→60s + jitter) **só**
   para stderr que casa um padrão de erro transitório confirmado (rate
   limit do IA, 5xx, connection reset/timeout); erro de credencial, arquivo
   inválido ou conflito lógico propaga na primeira tentativa, sem retry.
   Espaça uploads sucessivos via `make_rate_limiter` (extraído de
   `scraper.py` para o novo módulo `leizilla/ratelimit.py`, reaproveitado
   sem duplicar — import cíclico impedia importar direto de `scraper.py`).
   **Limitação documentada**: como o upload é via subprocess do CLI `ia`
   (não a lib `internetarchive`), só há acesso ao stderr como texto, não
   aos headers HTTP reais — não há `Retry-After` de protocolo para honrar,
   o backoff é uma aproximação. 8 novos testes em
   `TestRunIaUploadRetry` (`tests/test_publisher.py`) com respostas
   simuladas (sucesso, retry-então-sucesso, erro não retryable, esgotamento
   de tentativas, crescimento exponencial do backoff, pacing entre uploads).

**Não feito nesta PR** (fora de escopo, mencionado para o futuro): seletor
que transfira orçamento não usado de uma fonte vazia para a fila seguinte;
troca do CLI `ia` pela biblioteca `internetarchive` (daria acesso a
`Retry-After` real); `max-parallel: 1` estrito no harvest (ficou em 2,
equilíbrio entre throughput e risco de throttle).

### 2026-07-14 — M14.3: manifesto do notebook OPF ganha proveniência completa (fast follow do PR #110)

A revisão do PR #110 (que corrigiu os 3 bugs de CLI do notebook) apontou uma ressalva
não-bloqueante: `run_manifest.json` registrava dados/seed/config, mas não o SHA do
`openai/privacy-filter` (código nem peso-base), nem versões de `opf`/`transformers`/
`torch`/`datasets`, nem o GPU/CUDA do runtime — a palavra "reproducibility" no
comentário da célula era mais forte do que o notebook de fato entregava.

Adicionado ao manifesto: `base_model_hf_sha` (revisão do Hub resolvida via `HfApi` e
**pinada** no `snapshot_download`, não só lida depois — evita race entre resolver e
baixar; persistida num sidecar `.base_model_sha.txt` ao lado do checkpoint no Drive,
lida de volta em runs que restauram do cache em vez de baixar de novo),
`privacy_filter_commit` (SHA completo do clone, capturado incondicionalmente — não só
no primeiro clone), `opf_version`/`transformers_version`/`torch_version`/
`datasets_version` (via `importlib.metadata`), `cuda_version` e `gpu_info`. Escopo
deliberadamente restrito ao notebook — nenhuma mudança na decisão de reativação em si
(ADR-0012 não muda).

### 2026-07-14 — M14.3: fine-tune OPF reativado (smoke test no gold v0), por decisão do mantenedor

Supersede a atualização de 2026-06-06 da ADR-0012 (fine-tune adiado até evidência de
OCR ruidoso/formatação irregular/outro ente). O mantenedor decidiu retomar a Fase 3
agora mesmo assim, como **smoke test explícito** — não porque o gatilho de evidência
foi atingido. O gold v0 segue com a limitação conhecida desde M14.2: fonte única
(Planalto federal), texto limpo (HTML oficial, não `_djvu.txt`), sem ruído de OCR.

A plumbing de dados não precisou mudar: `notebooks/opf_train_colab.ipynb` já aponta
`GOLD_GIT_URL`/`GOLD_GIT_REF` para `main`, e o gold v0 (`data/opf/gold/`) já está
commitado lá desde M14.2 (commit `d9fd0b0`, "feat(opf): gold v0 dataset via labeling +
evaluator-ensemble subagents"). O notebook em si, porém, tinha três bugs reais de
argumento de CLI — achados numa revisão desta reativação e corrigidos, verificados
contra uma instalação real do `openai/privacy-filter`: `--seed` não existe (flag real
`--shuffle-seed`); o modelo-base persistido no Drive nunca era passado a `opf train`
via `--checkpoint` (caía no default efêmero); `opf eval` não aceita
`--label-space-json`. Falta apenas executar o notebook corrigido — treino em GPU via
Colab está fora do alcance de sessões sem acesso a GPU/Drive interativo.

**Contexto da decisão**: na mesma sessão, o primeiro dataset real (`leizilla-dataset-ro-v0`,
19 leis de RO) foi publicado no IA (RFC-0004 passos 4-6), incluindo um caso de OCR
genuinamente ruidoso (`lei-00001-1983`, trecho de artigo corrompido) que ilustra — mas
não por si só configura o gatilho formal da ADR-0012 (que pede medição contra o
baseline 0.95/0.99, não um exemplo isolado) — o tipo de evidência que a atualização de
2026-06-06 previa.

**Recomendação registrada, não executada**: expandir o gold com OCR real e ruidoso de
RO (multi-fonte, via `opf-sample` sobre os raw items já publicados + o mesmo método de
anotação por subagentes de M14.2) antes de um treino com pretensão de produção. Ver
ADR-0012 "Atualização (2026-07-14)" e `docs/opf-finetune.md` para o detalhe completo.

### 2026-07-12 — issue #105: `discover-harvest.yml` agendado agora escopa `--fonte`

O risco em aberto anotado pelo PR de `discover --fonte` (entrada abaixo) e
detalhado na issue [#105](https://github.com/franklinbaldo/leizilla/issues/105)
está corrigido: o workflow agendado real (`.github/workflows/discover-harvest.yml`,
job `harvest-single` e `harvest-parallel`) chamava `leizilla discover --ente ro`
sem filtro — a próxima execução (cron de sábado ou `workflow_dispatch` manual)
travaria de novo por horas na `PlaywrightCrawlerDiscovery` da fonte `assembleia`,
o mesmo bug confirmado 2× em produção.

**Correção**: novo input `fonte` no `workflow_dispatch` (`type: choice`,
`options: [casacivil, assembleia]`, `default: casacivil`); ambos os steps de
Discover passam `--fonte` explicitamente (`inputs.fonte` no dispatch,
`inputs.fonte || 'casacivil'` no cron semanal, mesmo padrão já usado para
`ente`/`limit` nesse arquivo). `assembleia` só roda mediante escolha manual
explícita no dropdown do dispatch — nunca no cron. Teste estático novo
(`tests/test_workflow_hygiene.py`) varre todo `.github/workflows/*.yml` e falha
se algum step invocar `leizilla discover` sem `--fonte`, prevenindo regressão
(inclusive em workflows futuros).

### 2026-07-12 — RFC-0004 passo 3 (smoke batch) já concluído; `discover --fonte` adicionado

O smoke batch de RFC-0004 (passo 3) **já estava feito** antes desta sessão
(2026-07-11): 5 itens raw reais publicados no IA (`leizilla_ro_casacivil_lei_0001-1000`,
`_decreto_0001-1000`, `_decreto_1001-2000`, `_decreto_10001-11000`, `_fallback`
— confirmado via `archive.org/advancedsearch.php`, público, sem credenciais).
Uma repetição redundante do smoke batch nesta sessão (workflow temporário
push-triggered, já removido) confirmou de novo que `leizilla discover --ente ro`
sem filtro trava por horas na `PlaywrightCrawlerDiscovery` da fonte `assembleia`
(5000 páginas sequenciais) — a mesma causa que a sessão de 2026-07-11 já tinha
descoberto e contornado com uma chamada Python direta
(`discover_resources(fonte="casacivil")`). A execução de 2026-07-12 (run
29192792845) foi cancelada pelo timeout de 2h sem chegar ao harvest.

**Correção**: `leizilla discover` agora aceita `--fonte` (mesmo padrão de
`harvest`/`reconcile`), então `discover --ente ro --fonte casacivil` funciona
como comando de primeira classe — sem precisar do workaround em Python. Ver
RFC-0004 (runbook passo 3 atualizado) para o registro completo e o risco em
aberto: `discover-harvest.yml` (o workflow agendado real) ainda chama `discover`
sem `--fonte` e vai travar do mesmo jeito na próxima execução — precisa de
correção antes de destravar o passo 7 do runbook.

### 2026-07-12 — RFC-0004 passo 1 concluído: secrets configurados e IA autenticado

O gargalo descrito na RFC-0004 ("secrets nunca foram configurados") está
desatualizado. `IA_ACCESS_KEY`, `IA_SECRET_KEY` e `GEMINI_API_KEY` existem como
Repository secrets (`ANTHROPIC_API_KEY` segue ausente, irrelevante pela RFC-0006 —
uma chave LLM basta). Autenticação real no Internet Archive confirmada via log do
job `check-credentials` (PR #101, execução em push): o teste `curl
.../?check_auth=1` (que só roda quando os secrets estão presentes — não é o
caminho fail-open) retornou `{"authorized": true}` para a conta
`franklin_baldo`.

Passo 0 (merge de #93/#94) e passo 1 (secrets) do runbook RFC-0004 estão feitos.
Falta o preflight oficial (`check-credentials.yml` via `workflow_dispatch` manual
— agentes automatizados não conseguem disparar `workflow_dispatch` neste repo,
tentativa retornou 403 por falta de escopo `actions: write` na integração usada)
e, em seguida, os passos 3–6: smoke batch (`discover`+`harvest --limit 10`),
espera de OCR, parse-all, consolidate/release-dataset e apontar
`PUBLIC_PARQUET_URL`. Ver RFC-0004 atualizada para o detalhe.

### 2026-07-12 — M13: "frontend polish" → "M13 — Produto público v1" + critérios de aceite

**Renomeação**: o milestone M13 (nome antigo: "frontend polish") passa a se chamar
**M13 — Produto público v1**. "Polish" subestimava o escopo: o frontend deixa de ser
uma caixa de busca e vira a superfície de produto sobre o Parquet publicado — tudo
client-side, sem servidor (ADR-0001).

**O que está sendo implementado (branch de frontend em andamento, `web/`)**:
- **Página própria de cada lei** em `/lei/?id={lei_id}` com quatro áreas: **Texto**
  (árvore hierárquica de dispositivos com deep-link `#{path}`, copiar link e
  citação), **Versões** (linha do tempo por dispositivo, com aviso de consolidação
  temporal S5 pendente), **Evidências** (fontes `ia-id`, hash sha256, divergências,
  links para `law.xml`, `parsed_meta.json` e item IA) e **Dados** (download JSON/CSV
  da lei + link do dataset).
- **Busca agrupada por norma** (não linhas isoladas): trecho + caminho do dispositivo
  (breadcrumb), badge de estágio S4, contagem de dispositivos que casam, ação
  primária "Ver lei" (IA vira link secundário de evidência).
- **Home com manifesto** ("Leis públicas não deveriam desaparecer em PDFs."), painel
  de cobertura real (leis/dispositivos/versões/anos, por ente), leis
  recém-incorporadas e acesso ao dataset.
- **Página pública `/cobertura/`** com o funil S1→S5 (PRD §6), números medíveis (S4,
  derivados do Parquet), lacunas explícitas (S1–S3 sem contadores públicos ainda;
  cobertura restrita a RO), cadeia de auditoria e seção `#dados`.
- **Filtros honestos**: ente derivado do dataset (`SELECT DISTINCT ente`), não mais
  hardcoded RO/federal/SP.
- **Estado "dataset ainda não publicado"** amigável no lugar do erro genérico
  (aponta para `/cobertura/` e o roadmap).
- **Dark mode automático** (remoção do `data-theme="light"`); rótulos de dispositivo
  derivados do path em render-time (SCHEMA.md §0.1) no novo `web/src/lib/format.ts`.

**Critérios de aceite do M13**:
- (a) dataset real carregando em produção — **bloqueado pela ativação da RFC-0004**
  (secrets, não código; runbook passos 1–7);
- (b) página própria para cada lei;
- (c) dispositivo estruturado com URL estável (`/lei/?id=…#path`);
- (d) estágio e limites de cobertura visíveis;
- (e) acesso ao original e à evidência em até dois cliques;
- (f) painel público da coleção (`/cobertura/`);
- (g) download da release e identificação da sua versão.

(b)–(g) estão code-complete no branch de implementação; (a) não é código — depende
apenas da ativação de produção (secrets IA/LLM + `PUBLIC_PARQUET_URL`). Nada é
"done" até merge + primeiro dataset publicado.

### 2026-07-08 — RFC-0006: parser provider-agnóstico via LiteLLM

**Supersede a decisão de 2026-05-23** (fechamento da PR #59 "litellm migration" —
manter o SDK `anthropic` diretamente). O parse deixa de exigir `ANTHROPIC_API_KEY`
como único provider: `parse_law()` passa a chamar `litellm.completion`, com
precedência de modelo `--model` > `LLM_MODEL` > auto pela chave disponível
(`ANTHROPIC_API_KEY` → `claude-haiku-4-5`; `GEMINI_API_KEY`/`GOOGLE_API_KEY` →
`gemini/gemini-2.5-flash`) e validação fail-fast por provider. Motivos: diretiva
do mantenedor (a premissa "Claude-native" foi revogada), go-live da RFC-0004
destravável com a chave Gemini que o mantenedor já tem (free tier = rota
cost-zero), e o princípio load-bearing #3 ("Etapa 2 é pluggable") passa a ser
honrado pelo código. As objeções de 2026-05-23 (prompt caching, indireção sem
ganho) estão endereçadas ponto a ponto em
**[RFC-0006](docs/rfc/0006-llm-provider-agnostico-litellm.md)**.

### 2026-06-05 — M14.1: OPF fine-tune — fundação de prep de dados

**Contexto**: anotar a estrutura das normas com um **token-classifier** treinado (OPF,
`openai/privacy-filter`) em vez de só com o parser generativo do Claude. Segue o
`opf-finetune` skill (franklinbaldo/skills), Pattern B (structural tagging of statutes).
Decisão e enquadramento em **[ADR-0012](docs/adr/0012-opf-structural-span-tagging.md)**:
OPF é **complementar**, não substituto — marca *marcadores* curtos (`Art. 5º`, `§ 2º`,
`III -`, `a)`) + cues (ementa/vigência/revogação); o corpo do dispositivo é reconstruído
em pós-processamento (skill Warning 2: atenção em banda favorece âncoras curtas).

**Fase 1 de 4 (esta sessão — fundação committável)**:
- `data/opf/label_space.json` — ontologia `leizilla_normas_v1` (`O` + ementa + 4
  marcadores + vigencia + revogacao). Encaixa no token-map dispositivo→rótulo (SCHEMA §4.2).
- `src/leizilla/opf.py` — sampler **estratificado por fonte** (cada fonte é
  sub-distribuição; skill Warning 1: corpus PT-BR é out-of-distribution para OPF, eval
  PT-BR é obrigatório), alocação igual por fonte, seed fixo. Reusa `list_raw_ids` +
  `fetch_and_clean_ocr` (OCR raw já no IA, ADR-0010). Produz pool + `sample_manifest.json`.
  IO atrás de seams injetáveis (`list_fn`/`fetch_fn`) → testes offline.
- CLI `leizilla opf-sample --ente ro --fontes assembleia,casacivil --n 50 --seed 13`.
- `scripts/opf_annotate.py` — helper vendorado (validate/from-spans/preview): gate de CI
  sobre offsets de char do ouro.
- `.gitignore` — whitelist do ouro (`data/opf/label_space.json`, `data/opf/gold/`);
  pool fica ignorado. Corrigido `data/` → `data/*` (o `!data/.gitkeep` existente era
  inócuo — diretório com `/` no fim bloqueia re-inclusão de filhos).
- `docs/opf-finetune.md` — recipe Leizilla das 4 fases.
- 20 testes em `tests/test_opf.py` (sampler determinístico, estratificação, skip de OCR
  curto/ausente, manifest, label space, CLI, e smoke do helper vendorado).

**Fases seguintes**: F3 treino/eval em Colab GPU (`opf train`, eval PT-BR, ponto de
operação para precision); F4 inferência (reconstruir dispositivos dos marcadores).
Papel final no pipeline de produção decidido com métricas (ADR-0012, "fora de escopo").

### 2026-06-05 — M14.2: OPF gold v0 — anotação por subagentes (skill llm-work-via-subagents)

IA ainda sem itens raw publicados (rede OK; `list_raw_ids` retorna vazio). Decisão:
não bloquear o gold — montar o pool com **texto real** de normas direto da fonte
oficial (Planalto federal HTML, `fetch_html`/UA de browser; leis públicas, ADR-0009).
Pool de 6 leis federais curtas (texto inteiro, com a cláusula de vigência/revogação no
fim) em `data/opf/pool/` (gitignored).

**Anotação seguindo o skill `llm-work-via-subagents` (não script com API key)**:
- **Shape 1 (shard)**: 6 subagentes em paralelo, um por lei, retornando `finds`
  (categoria + surface exata) em ordem de documento. Offsets resolvidos
  deterministicamente pelo orquestrador (cursor sequencial → ordem + não-overlap;
  nenhum subagente conta caracteres).
- **Shape 2 (ensemble)**: 4 subagentes-avaliadores com enquadramentos decorrelacionados
  (strict-boundary, category-disambiguation, blind-relabel, adversarial) sobre o eval
  slice (val=lei-9455, test=lei-9296). Convergências aplicadas: (a) reparo
  length-preserving de bytes C1 do CP1252 mal-decodados como latin-1 (`\x96`→`–`, sem
  deslocar offsets); (b) marcador `III –` consistente com irmãos; (c) remoção de 2
  marcadores-fantasma de parágrafos **(VETADO)** — blind+adversarial concordaram que
  texto vetado não é dispositivo da lei.

**Gold v0 commitado** (`data/opf/gold/`, whitelist): train 4 docs/185 spans, val 1/24,
test 1/42; total 251 spans (art 100, par 77, inc 49, ali 7, ementa/vig/revog 6 cada).
`manifest.json` registra `test_verified_by` (o ensemble), `source_commit`, seed e
`known_limitations` (seed v0 pequeno; só fonte planalto; texto limpo, sem ruído de OCR
— caveat PT-BR do ADR-0012). Validado com `opf_annotate.py validate` (0 erros).

### 2026-05-25 — M12.1: DiscoveryStrategy base class + testes harvest pipeline

**Sessão de rotina horária.** Uma PR aberta encontrada (#63, M11 CI lint+test):

**#63 (M11)** — Codex P1 real: `cmd_pipeline --ente X` chamava `cmd_harvest(limit=N)` sem escopo de ente, processando recursos de qualquer ente. Fix em 3 camadas: `storage.get_pending_resources(ente=)` SQL filter; `scraper.harvest_pending_resources(ente=)` repassa; `cli.cmd_harvest(--ente)` expõe option + pipeline passa valor. Junto: dois `type: ignore[index]` indevidos removidos por M11 foram restaurados (necessários com `types-requests` instalado, pois mypy 1.19+ infere `fetchone()` retorna `tuple|None`); `types-requests` adicionado como dev dep (elimina `import-untyped` para requests em mypy 1.19+, mais robusto que `--ignore-missing-imports`). Mergeado em 06f13619.

**M12.1 — DiscoveryStrategy base class**:
- `discovery.py`: classes de estratégia não tinham base comum — M11 precisou de `# type: ignore[attr-defined]` em `runner.run()` e `# type: ignore[no-any-return]` em `json.load`. Fix próprio (sem ignores): `DiscoveryStrategy` como base class concreta com interface `__init__(config, ente, fonte)` + `run()`. As três classes herdam dela. `STRATEGIES: Dict[str, type[DiscoveryStrategy]]` completamente tipado.
- Fix adicional: `load_manifest` agora usa variável intermediária `data: Dict[str, Any] = json.load(f)` eliminando o `no-any-return`.

**17 novos testes em `tests/test_harvest_pipeline.py`**:
- `TestStorageResources` (7): `get_pending_resources` empty, insert+get, status filter, limit, duplicate ignore, update_status, update com wayback snapshot.
- `TestSequentialDiscovery` (3): URL range, campos, múltiplos templates.
- `TestRunDiscovery` (2): estratégia sequential end-to-end com mock de manifesto, estratégia desconhecida silenciada.
- `TestHarvestPendingResources` (5): queue vazia, robots bloqueado, fetch falho, sucesso com upload chamado, limit respeitado.

### 2026-05-24 — M11: CI lint+test + mypy fixes

**Problema**: `lint.yml` usava `astral-sh/setup-uv@v1` (desatualizado vs. `@v5` nos demais
workflows) e não aparecia nos check runs de PRs — CI estava silenciosamente quebrado.
Nenhum pytest rodava em PRs; mypy tinha 8 erros em 6 arquivos sem ninguém saber.

**`lint.yml` reescrito**:
- Remove `actions/setup-python@v5` (redundante — `setup-uv@v5` configura Python automaticamente).
- `setup-uv@v1` → `@v5` (alinha com todos os outros workflows do repo).
- Adiciona `uv run pytest -x -q` após mypy. Exit-on-first-failure (`-x`) fail-fast sem perder
  visibilidade de qual test quebrou.
- Renomeia job para `lint-test` (reflete o conteúdo real).

**Mypy errors corrigidos (8 erros, 6 arquivos)**:
- `storage.py:152`: `params = []` → `params: list[str | int] = []` (erro real de tipo).
- `parser.py:115,132`: `# type: ignore[no-any-return]` em `resp.read().decode()` — mypy trata `urlopen` context manager como `Any` internamente.
- `crawler.py:11`: `types-requests` adicionado como dev dep — elimina `import-untyped` para requests em mypy 1.19+.
- `discovery.py:195`: fix via variável intermediária tipada (M12.1 substituiu o type: ignore).
- `discovery.py:216`: fix via `DiscoveryStrategy` base class (M12.1 substituiu o type: ignore).
- `publisher.py:148`, `cli.py:478`: `# type: ignore[index]` necessários com types-requests instalado (fetchone() retorna tuple|None).

**Ruff**: `tests/test_fetch_all_parsed.py`: import `pytest` não utilizado removido + formatação.

### 2026-05-23 — M10.2: triagem de PRs + docs + manifest ranges + discover-harvest workflow

**Sessão de rotina horária.** Quatro PRs abertas encontradas:

**#42 (dependabot astro)** — Skip. Autor não é claude bot nem franklinbaldo.

**#58 (M10.1 fetch-all-parsed)** — Mergeada. CI verde; Kilo reviews eram outdated (contadores já separados na versão atual). Codex P1 (fail-open no listing) é trade-off intencional documentado no PR body: fallback para comportamento pré-M10.1, não pior que status quo. Squash com mensagem curada.

**#59 (litellm migration by Jules)** — Fechada. Migração Anthropic SDK → litellm não tem justificativa no PR body; quebra prompt caching (`cache_control` no root da mensagem em vez do content block — Codex P2 correto); adiciona indireção sem ganho para um projeto Claude-native. Decisão: manter SDK `anthropic` diretamente.

**#61 (OCR pipeline)** — Fix P1 antes de merge: `clean_ocr_text` com `[\x7f-\xff]` removia ç, ã, é e todos os chars Latin-1 — corromperia praticamente todo texto jurídico. Fix: `[\x7f]` apenas (DEL). Testes de regressão adicionados. Push feito; aguardando CI.

**M10.A e M10.B não estavam em IMPLEMENTATION.md** — duas sessões anteriores (PR #60 manifest-driven + commit a8fee2b torrent bundling) adicionaram features não rastreadas. Adicionadas ao log retrospectivamente. Não afetam nenhuma decisão ativa.

**Manifest ranges** (`manifests/ro.json`): `sequential.end` estava em 100 (placeholder), alinhado com ranges reais de `rondonia_crawler.yml`:
- casacivil lei: 1-6000 (separado do lc)
- casacivil lc: 1-1300 (separado do lei)
- assembleia: 1-5000

Templates de lei e lc separados em estratégias distintas (anteriormente misturados num único template list que gerava L e LC para o mesmo range).

**`discover-harvest.yml`**: workflow sábado 02:00 UTC. Complementa `rondonia_crawler.yml` (sequencial/incremental via scrape) com a pipeline manifest-driven (wayback-cdx pode encontrar arquivos fora do range sequencial). Os dois workflows são paralelos e aditivos — não há exclusão mútua, IA upload idempotente trata duplicatas.

### 2026-05-23 — M10.1: fetch-all-parsed + Parquet cumulativo

**Problema**: cada `parse-release.yml` run publica um Parquet com ≤150 leis (apenas os itens
parsed naquele run). O dataset não acumula — a cada semana substitui o anterior com uma fatia
pequena, nunca chegando a um Parquet browsable com todo o acervo do ente.

**`list_parsed_ia_ids(ente)`** adicionado a `publisher.py`: variante simplificada de
`list_parsed_raw_ids` — mesmo query IA scrape API (filtra raw/bundle/dataset), mas retorna
`list[str]` dos próprios identifiers parsed (sem fetch de `parsed_meta.json` por item).
Fail-open: erro de rede → lista vazia (não bloqueia pipeline).

**`fetch_parsed_xml(ia_id, output_path)`**: HTTP GET de `archive.org/download/{ia_id}/law.xml`
com timeout 30s. Salva bytes em `output_path`. Retorna `bool` (True = sucesso). Fail-open por item.

**`cmd_fetch_all_parsed --ente --output-dir`**: lista todos os IDs, skip se arquivo já existe
(idempotente), baixa em sequência, reporta `Baixados: N, Erros: M`. Exit 0 sempre (falhas
individuais não abortam pipeline — IA pode ter itens cujo upload está em andamento).

**Integração em `parse-release.yml`**: step `Fetch all parsed XMLs from IA` adicionado entre
os steps de parse e o `Consolidate`. Output dir `/tmp/leizilla-xmls` é compartilhado com o
parse-all step — novos XMLs gerados pelo parse ficam no dir, fetch-all-parsed adiciona os
históricos. Consolidate processa todos. Resultado: Parquet full-histórico acumulado.

**Trade-off de latência**: N requests HTTP (um por item parsed + N/10000 requests de paginação).
Para 500 items: ~501 requests × 1-2s = ~10min extra. Aceitável para run semanal noturno.
Otimização futura: cache local de IDs já baixados para pular confirmados (desnecessário agora).

12 testes em `tests/test_fetch_all_parsed.py`: 4 × `TestListParsedIaIds` (basic, paginate,
network_error, empty) + 3 × `TestFetchParsedXml` (success, error, url) + 5 × `TestCmdFetchAllParsed`
(basic, skip_existing_files, count_errors, no_items, create_dir).

### 2026-05-23 — M9.5: rondonia_crawler.yml idempotente + ranges reais

**Problema**: `rondonia_crawler.yml` nunca usou `--skip-existing` (disponível desde M9.3/#54).
Cada run semanal re-scrapeava os mesmos itens 1-100 (default) desde o início, desperdiçando
bandwidth e IA storage. Além disso, os inputs `casacivil_start`/`casacivil_end` eram
compartilhados para lei e lc — fontes com ranges bem distintos (~6000 vs ~1300 leis).

**Decisão — schedule/dispatch split** (mesmo padrão de parse-release.yml/#55):
- `schedule` (domingo meia-noite UTC): três steps fixos com ranges reais + `--skip-existing`.
  Alinhados com os mesmos limites de parse-release para não scrappear além do que o parser cobre.
- `dispatch`: inputs separados por fonte (`assembleia_start/end`, `casacivil_lei_start/end`,
  `casacivil_lc_start/end`) + `skip_existing` input (default `true`). Permite re-scrape forçado
  de um range específico sem impactar outras fontes.

**Ranges definidos** (mesmos que parse-release.yml para consistência):
- `assembleia`: coddocs 1-5000
- `casacivil lei`: números 1-6000
- `casacivil lc`: números 1-1300

**Sem `--limit`** no scraping: diferente do parse-all, scraping não tem custo LLM. O rate-limit
natural (Wayback + IA upload) limita o throughput. Com `--skip-existing`, runs subsequentes são
rápidos (itens já no IA → skip imediato sem chamada de rede de scraping).

**Não feito**: federal/planalto no schedule — o code suporta mas não há demanda imediata. Adiar
para M10+ quando iniciarmos indexação federal além dos stubs.

### 2026-05-23 — M9.4: parse-release multi-fonte + skip-existing

**Problema descoberto**: `parse-release.yml` não usava `--skip-existing` (M7.2 existe no CLI mas
estava ausente do workflow). Sem esse flag, cada run semanal reparseia os mesmos itens do início
do range — queimando budget LLM sem produzir novos dados. Com `--limit 50` e sem `--skip-existing`,
todo Monday re-parseia os coddocs 1-50, nunca chegando em 51-100.

**Segundo problema**: scheduled run cobria apenas uma fonte (casacivil-lei por default). assembleia
e casacivil-lc não eram parseadas automaticamente — teriam que ser disparadas manualmente.

**Fix**: dois modos no mesmo job.

**Schedule (Monday 06:00 UTC)**: três steps sequenciais, cada um com `--skip-existing --limit 50`.
- `ro/assembleia` coddocs 1-5000
- `ro/casacivil lei` coddocs 1-6000
- `ro/casacivil lc` coddocs 1-1300

Cada step parseia at most 50 novos itens (ainda não parseados em IA). Total: ~150 LLM calls/semana
até cobertura completa. Após cobertura completa: ~0 LLM calls (todos os itens são skipados).

**Dispatch**: mantém parametrização por fonte/tipo + adiciona input `skip_existing` (default `true`).
Útil para re-parse forçado de um range específico (`skip_existing=false`) ou dry-run de teste.

**Limitação conhecida (M10.1)**: o dataset liberado a cada run contém apenas os XMLs gerados naquele
run (≤150 itens). O Parquet não acumula com runs anteriores. Para o MVP isso é aceitável — o dataset
cresce semana a semana. Quando precisarmos de um Parquet full-histórico, adicionar `fetch-all-parsed`
que baixa todos os XMLs do IA antes do consolidate.

### 2026-05-23 — M9.3: scrape --skip-existing via list_raw_ids

**Problema**: `rondonia_crawler.yml` re-scraping todos os itens a cada execução CI mesmo
quando já estão no IA. Para um range de 5000 leis, isso desperdiça bandwidth + IA storage
e viola o princípio "Raw é imutável após upload" implicitamente (re-upload de item existente).

**`list_raw_ids(ente, fonte)`** adicionado a `publisher.py`: consulta IA scrape API com
prefix `leizilla-raw-{ente}-{fonte}-` e retorna `set[str]` de identifiers existentes.
Mais simples que `list_parsed_raw_ids` (M7.2): sem fetch de `parsed_meta.json` por item —
o prefix já identifica unicamente ente+fonte, basta listar identifiers.
Paginação via cursor. Fail-open: erro de rede → `set()` (nunca pula por falha de conectividade).

**`--skip-existing/--no-skip-existing`** (default False) em `cmd_scrape`:
- Chama `list_raw_ids(ente, fonte)` antes do loop e exibe count
- Para cada law, computa `ia_id = f"leizilla-raw-{ente}-{fonte}-{chave}"` e pula se em set
- Funciona para todos os tipos de fonte: assembleia (coddoc), casacivil (lei/lc), planalto (lei/lcp/decreto)
- Mensagem final inclui `N pulados (já existem)` quando flag ativo

**Simetria com M7.2**: `parse-all --skip-existing` usa `list_parsed_raw_ids` (fetch de meta);
`scrape --skip-existing` usa `list_raw_ids` (sem fetch extra — prefix já discrimina tudo).
Padrão idempotente por todo o pipeline.

5 novos testes em `TestListRawIds` (test_publisher.py) + 5 em `TestCmdScrapeSkipExisting`
(test_scrape_skip_existing.py).

### 2026-05-23 — M9.1: melhoria do maintenance-prompt — sessões paralelas + xsltproc

**Problema**: esta sessão encontrou um conflito de merge real entre #49 e #50 (duas sessões
que operaram no mesmo base SHA). O `maintenance-prompt.md` não tinha instrução para isso.

**Adições ao maintenance-prompt.md**:
- `Fase 1F` — protocolo de 5 passos para resolver conflito de sessões paralelas:
  (1) merge --no-commit para identificar, (2) IMPLEMENTATION.md: manter ambas as entradas,
  (3) testes: manter ambas as classes, (4) commit de resolução com push, (5) re-tentar merge.
- `Phase 2E`: adicionado loop `xsltproc` + `xmllint` para validar export LexML quando
  XSD ou fixtures mudam — estava descrito no prompt canônico da sessão mas ausente do arquivo.
- `Princípio 7` (reversibilidade): adicionado "deletar branches alheias" à lista NÃO-PODE.
  Era implícito; explicitado para sessões automáticas sem supervisão humana imediata.

**Não feito**: os comandos de validação de schema e XSLT não foram rodados nesta sessão
porque nenhuma fixture foi modificada (trabalho foi de merge + triagem). Comandos adicionados
como template para quando forem relevantes.

### 2026-05-23 — M8.2: observabilidade do pipeline — error-threshold + GitHub Step Summary

**Problema**: `parse-release.yml` pode completar com sucesso mesmo quando 80% das leis falharam
no LLM (confiança baixa, OCR ruim, etc.). Sem um gate, um batch ruim sobe para o IA sem
visibilidade. M8.1 adicionou contagens via IA API; M8.2 fecha o ciclo do lado do pipeline.

**`--error-threshold FLOAT`** em `parse-all`: se a taxa de falhas de parse exceder o percentual,
emite aviso e termina com exit 1. Default `0.0` (desabilitado) — retrocompatível. Workflow
`parse-release.yml` agora usa `--error-threshold 20` (20% de falhas indica problema real).

**Distinção com `upload_fail`**: o exit 1 de upload_fail (já existente) captura falhas de rede/IA.
O exit 1 de error_threshold captura degradação de qualidade do LLM/OCR. São condições independentes;
o threshold é verificado antes do upload_fail para que o Step Summary seja sempre escrito.

**GitHub Step Summary (`$GITHUB_STEP_SUMMARY`)**: quando rodando em CI, `_write_step_summary`
escreve Markdown com stats (parseados, falhos, taxa, uploaded) no arquivo apontado pela env var.
Fail-open: se a variável não está definida ou o arquivo não é gravável, segue sem erro.
Aparece na UI do workflow run do GitHub — visibilidade sem criar issues ou comentários.

**Threshold de 20%**: conservador para MVP. Com ~50 leis por batch (--limit 50), 20% = 10 falhas.
Falhas de OCR ruim tendem a ser estruturais (todas as leis de uma fonte), não aleatórias.
Se 10/50 falharem, algo está errado. Revisitar com dados reais quando pipeline for rodado.

5 novos testes em `TestCmdParseAllErrorThreshold`: threshold disabled, abaixo do limite,
acima do limite (exit 1 + aviso), step summary escrito, step summary com threshold no conteúdo.

### 2026-05-23 — M8.1: leizilla stats via IA + M5.3 bloqueado

**`count_ia_items(identifier_prefix)`** adicionado a `publisher.py`: conta itens no IA cujo identifier começa com o prefixo, paginando via cursor. Retorna `Optional[int]` — `None` em erro de rede (fail-open). Reutiliza a infraestrutura de paginação do `list_parsed_raw_ids` (M7.2), mas sem fetchar cada `parsed_meta.json` (só precisa do count).

**`cmd_stats --ente --ia`** reescrito: o comando anterior era um wrapper de `DuckDBStorage.get_stats()` (local), que não tem dados no pipeline atual (pipeline vai direto para IA, sem escrita local de dados). O novo comando mostra:
- Raw items (`leizilla-raw-{ente}-*`)
- Parsed items (`leizilla-{ente}-*` excluindo raw/bundle/dataset — net count)
- Dataset items (`leizilla-dataset-{ente}-*`)

O parsed_net usa 4 chamadas `count_ia_items` e subtrai raw+bundle+dataset do total `leizilla-{ente}-*`. Isso é necessário porque o prefixo `leizilla-ro-*` inclui itens raw (`leizilla-raw-ro-*` começa com `leizilla-` mas não com `leizilla-ro-`). Verificado: o prefix da query para parsed é `leizilla-{ente}-` (sem "raw"), então não há double-counting — mas mantemos a subtração explícita por segurança.

**M5.3 bloqueado**: sem dataset publicado em IA, o benchmark DuckDB-WASM não tem dados para medir. ILIKE columnar no DuckDB deve ser suficiente para ~300k rows estimados (RO). Revisitar quando: (a) first batch RO scraping/parsing completo, (b) search > 1s medido in-browser.

9 novos testes: `TestCountIaItems` (5) + `TestCmdStats` (4).

### 2026-05-23 — M7.2: parse-all --skip-existing via consulta IA

Problema: rotina automática rodando `parse-all --ente ro --fonte assembleia --start 1 --end 5000`
re-parseia todos os 5000 itens a cada execução, gastando ~$100 em LLM desnecessariamente.

**Abordagem escolhida — fetch de parsed_meta.json por item**:
`list_parsed_raw_ids(ente, fonte)` faz (1) uma IA scrape query para listar todos os parsed items do ente,
(2) faz N fetches de `parsed_meta.json` (um por item) para extrair `ia_id_raw`, (3) filtra pelo prefixo
`leizilla-raw-{ente}-{fonte}-`. Retorna `set[str]` de raw_ids já processados. Fail-open: erro de rede →
empty set (nunca pula item por falha de conectividade).

**Paginação via cursor**: o loop segue o `cursor` retornado pela IA scrape API até o esgotamento. Codex P1
apontou corretamente que a versão inicial não paginava; corrigido com commit de fix na mesma sessão.

**Por que não IA metadata search**: IA permite campos customizados mas indexação é assíncrona e busca por
campos arbitrários não é garantida. Alternativa confiável (adicionar `raw-id` ao campo `subject`) requer
modificar `upload_parsed` + re-fazer uploads existentes. Para MVP, N fetches HTTP de ~1KB é mais simples.

**Trade-off de latência**: ~101 requests para RO com 100 parseadas. Aceitável para rotina semanal.
Se virar gargalo → M7.3 otimiza com metadata IA indexada ou cache local.

9 novos testes (5 unitários `TestListParsedRawIds`, 4 de integração `TestCmdParseAllSkipExisting`).

### 2026-05-23 — M7.1: Claude Code routine infra — prompt canônico + workflow

M6 encerrado (M6.1 #40 + M6.2 em M5.1/#33 + M6.3 #41 todos merged). M7 desbloqueado.

**Decomposição de M7**: o log de M6.1 mencionava "incremental tracking é M7" — mas M7
também significa a infra de automação das sessões de rotina (que não existia formalmente).
Separados em M7.1 (infra) e M7.2 (incremental tracking) para manter PRs coerentes.

**`docs/routines/maintenance-prompt.md`**: prompt canônico extraído da sessão atual.
Motivo de versioná-lo: drift entre sessões sem fonte-da-verdade central era inevitável.
Com o arquivo no repo, o prompt evolui junto com o código (e o log aqui registra por quê).

**`claude-routine.yml`** — schedule segunda + quinta 10:00 UTC:
- Não diária — custo de sessão Opus + API GitHub tem overhead. 2×/semana é suficiente
  para um repo que faz 1-2 sessões de código por dia via web.
- `concurrency: cancel-in-progress: false` — sessões não devem se sobrepor; a segunda
  aguarda (não cancela) para garantir idempotência.
- `workflow_dispatch` sempre disponível para sessões ad-hoc e debugging.
- Usa `anthropics/claude-code-action@beta` — mesmo mecanismo das sessões manuais via web.

**M7.2 (incremental tracking)**: deferido para próxima PR. Requer consulta à API IA para
listar `ia_id_parsed` existentes — envolve HTTP e lógica nova em `publisher.py`. Mantém M7.1 focado.

### 2026-05-22 — M6.1: parse-all --output-dir + parse-release workflow

Pipeline parse→ETL→release estava funcionalmente completo mas sem orquestração
automática. O gap era: `parse-all` não salvava XMLs locais e `consolidate` só
lê de diretório local — não havia como encadear os dois em CI sem state intermediário.

**Decisão principal — `--output-dir` em vez de fetch-from-IA**: três opções
analisadas: (a) `parse-all --output-dir` salva localmente + faz upload; (b) novo
comando `fetch-parsed` baixa XMLs do IA depois; (c) `consolidate` aceita IA item IDs
diretamente. Escolha: (a). Motivo: menor fricção (sem novo comando, sem HTTP extra),
simétrico com `--output` do `parse`, e o CI job é efêmero (tmp_path entre steps).

**Custo LLM controlado por `--limit`**: produção deve rodar com `--limit 50-100` por
execução para controlar custo incremental. Re-parse de items já publicados é ineficiente
mas aceitável no MVP — incremental tracking (check IA antes de parsear) é M7.

**Workflow `parse-release.yml`**: job único `parse-release` (não matrix). Schedule
segunda 06:00 UTC (dia após o scraping dominical de `rondonia_crawler.yml`). Inputs
`dry_run=true` permite testar o pipeline sem upload. Secrets: `ANTHROPIC_API_KEY`
(obrigatório para parse), `IA_ACCESS_KEY`/`IA_SECRET_KEY` (upload IA).

**M6 decomposto**: M6.1 (parse+ETL+release), M6.2 (deploy-web — já em #33),
M6.3 (Planalto pós-2002 year-scoped URLs — independente, desbloqueado).

### 2026-05-22 — M6.3: Planalto year-scoped URLs + fix SCHEMA.md chave

**Problema descoberto**: SCHEMA.md §1.1 mostrava `chave = lei-{numero:05d}-{ano}` para
federal/planalto, mas o código gerava `lei-{num:05d}` (sem ano). Corrigi o SCHEMA.md:
chave planalto é `{tipo}-{num:05d}`, sem ano — lei federal number é globalmente único
no Brasil (não reseta por ano), então o ano é redundante na chave.

**Design de URL year-scoped**: `_camara_year_lookup(tipo, numero)` chama
`dadosabertos.camara.leg.br/api/v2/legislacoes?siglaTipo=LEI&numero=N` para obter o
ano. Resultado em `lru_cache(maxsize=2048)` — N chamadas por batch, uma por número
único. Fail-open: API indisponível → URL legada.

**Circuit breaker + 429 handling**: `_CamaraApiState` desativa lookups após primeira
falha de rede (limita stall a 1×3s). HTTP 429 (rate-limit) é tratado separadamente:
retorna None sem abrir o circuit (erro transiente, não estrutural).

**`year_lookup_fn` injetável**: `discover_planalto_laws(tipo, start, end, *, year_lookup_fn=...)`
aceita lambda para testes offline sem rede.

**Testes**: 47 em `TestCamaraYearLookupCircuitBreaker` + `TestPlanaltoYearScopedUrl` + `TestDiscoverPlanaltoLawsYearScoped`.
Testes existentes atualizados para passar `year_lookup_fn=lambda t, n: None` (determinismo).

### 2026-05-22 — M5.2: TanStack Query + paginação + filtros

**Entregável**: `LeiSearchUI.svelte` substitui a busca inline em `LeiSearch.svelte`.

**Arquitetura de componente**:
`LeiSearch.svelte` virou wrapper fino com `QueryClientProvider` (QueryClient configurado
com retry=2, staleTime=5min). `LeiSearchUI.svelte` contém toda a lógica de busca.
Essa separação é necessária porque `createQuery` deve ser chamado em filho do Provider.

**Bridge Svelte 5 runes → Svelte 4 stores**:
TanStack Svelte Query 5.90.2 usa a API de stores Svelte 4 (`derived`, `readable`, `subscribe`)
internamente — NÃO suporta runes Svelte 5 nativamente. O bridge é:
- Estado local em `$state` (Svelte 5 runes)
- `writable()` stores passadas para `createQuery` como options reativas
- `$effect()` para sincronizar state → store quando qualquer dependência muda
- Template acessa resultados via `$resultsQ.data`, `$resultsQ.isPending` (sintaxe de store)

**`db.ts` additions**:
- `searchLeisFiltered(query, {ente, year, page, pageSize})`: SQL dinâmico com WHERE
  clauses opcionais, LIMIT/OFFSET para paginação. Params parameterizados (sem injection).
- `countLeisFiltered(query, {ente, year})`: COUNT(*) para total de páginas.
- `runSql<T>()`: helper interno que abstrai prepare+query vs conn.query.
- `PAGE_SIZE = 20`: constante exportada usada pelo componente e queries.
- `YEAR(em)`: filtro por ano usa a coluna DATE `em` (inferred by DuckDB read_json_auto).
  YEAR(NULL) = NULL → rows sem data de início são excluídas quando filtro ativo (correto).

**Filtros implementados**:
- Ente: select dropdown (ro, federal, sp) — filtra por coluna `ente` no Parquet.
- Ano: input numérico → filtra por `YEAR(em)`. Representa o ano de início de vigência
  do dispositivo, não necessariamente o ano de publicação da lei (melhor que o que temos).

**Debounce**: 400ms no input de busca. `debouncedTerm` é o que vai para o queryKey;
page reset para 0 sempre que term/ente/year mudam. Debounce via `$effect` cleanup —
sem memory leak no unmount.

**Paginação**: Prev/Next com "Página N de M". Controles desabilitados durante fetch
(usando `$resultsQ.isFetching`). `totalPages()` calculado a partir de `$countQ.data`.

**Erro TypeScript pré-existente**: `pthreadWorker` em BUNDLES (db.ts:18) é de M5.1 —
não introduzido aqui. Build `astro build` passa sem erros; tsc reporta esse pré-existente.

### 2026-05-22 — M4.3: benchmark gatilhos §3.4 — local approximation é o deliverable M4

**Auditoria pós-M4.2**: o benchmark já estava implementado em `cmd_release_dataset`
(DuckDB Python local). O que faltava era cobertura de testes para os três gatilhos.

**6 testes em `TestReleaseDatasetBenchmark`** cobrem:
- `dry_run_reports_stats_line`: stats linha presente no output
- `no_gatilho_warning_for_small_dataset`: sem warning abaixo dos limites
- `row_count_threshold_warning`: 2_000_001 linhas → "rows > 2M" + "Gatilhos §3.4"
- `search_latency_threshold_warning`: 1.5s → "search > 1s"
- `file_size_threshold_warning`: 101 MB → "file > 100 MB"
- `two_gatilhos_triggers_rfc_message`: 2+ gatilhos → "RFC sobre split"

**"DuckDB-WASM real" em M5.2**: o benchmark in-browser requer frontend deployado
(M5.1) e dataset com dados reais. A aproximação Python-local é suficiente para M4 —
se thresholds forem excedidos, o CI em M5 sinalizará. Sem blocking para M5.1.

**M4.3 encerra como done.** Próximos: M5.1 (#33) → M5.2 → benchmark WASM real.

### 2026-05-22 — M2.8: parse-all --input-type html + chave federal

`cmd_parse_all` em `cli.py` extendido para suportar fontes HTML (Planalto federal).

**Mudanças em `cmd_parse_all`**:
- `--input-type ocr|html` (default `ocr`): controla qual fetch usar por item.
- Chave routing: `ente == "federal" and fonte == "planalto"` → `{tipo}-{N:05d}`; demais → `coddoc-{N:05d}`. Consistente com `discover_planalto_laws` (M2.7) que usa esse mesmo padrão.
- `fetch_ia_html(raw_id)` para `input_type == "html"`, `fetch_ocr(raw_id)` para `input_type == "ocr"`. Skip silencioso quando conteúdo ausente em ambos os casos.
- `parse_law(raw_text, raw_id, ente, model=model, input_type=input_type)` passa `input_type` adiante (M3.4 já suportava).
- Validação de `input_type` antes do loop; exit 1 imediato se inválido.
- Removido docstring duplicado (stale de M3.3) que ficou na refatoração M3.5.

**Testes**: 5 novos em `TestCmdParseAll` (html fetch, html skip, federal chave, non-planalto chave, invalid input_type). 319 total (todos passando).

### 2026-05-22 — M5.1: Frontend foundation — Astro 4 + Svelte 5 + DuckDB-WASM 1.32

**Stack efetiva** (vs. IMPLEMENTATION.md planning targets em parênteses):
- Astro **4.16.19** (planejado 6.3 — Astro 6.x não disponível; 4.x é latest stable)
- Svelte **5.55.9** (planejado 5.55 — exato match)
- @picocss/pico **2.x** via CDN classless (planejado 2.1 — compatível)
- DuckDB-WASM **1.32.0** (planejado 1.28 — versão mais recente, totalmente compatível)
- @tanstack/svelte-query **5.x** (planejado 6.1 — v6 não disponível; v5 é latest stable)

**Override `@sveltejs/vite-plugin-svelte@^4`**: Svelte 5.55 requer vite-plugin-svelte 4.x;
o `@astrojs/svelte@5` ainda depende da v3. Override em `package.json` resolve o warning
sem breaking change — `astro build` produz bundle limpo.

**Arquitetura DuckDB-WASM**: Worker inline via `URL.createObjectURL` (Blob com `importScripts`)
carrega o bundle do CDN jsDelivr em runtime. Evita bundling do WASM gigante (>20MB)
e problemas de CORS em GitHub Pages. `INSTALL httpfs; LOAD httpfs` foram removidos —
DuckDB-WASM não suporta INSTALL e usa path HTTP nativo para `read_parquet()`. VIEW
`versoes` aponta para IA — URL configurável via `PUBLIC_PARQUET_URL` (env var Astro/Vite).

**Busca full-text**: `ILIKE '%term%'` no DuckDB-WASM. Suficiente para M5; índice
FTS ou embeddings ficam para M5.2+.

**Decisão adiada**: `@tanstack/svelte-query` instalado mas não usado no componente
inicial — busca simples com `$state` é suficiente para MVP. Integrar TanStack Query
em M5.2 quando cache/invalidação/retry ficarem relevantes.

### 2026-05-22 — M2.7: Planalto federal HTML pipeline (desbloqueado pelo M3.4)

M3.4 (`fetch_html` + `parse_law(input_type="html")`) desbloqueou o scraping de
fontes que servem HTML em vez de PDF. Planalto é a fonte canônica federal (compilados
vigentes) — equivalente federal da casacivil RO.

**Decisão principal — raw HTML item no IA**: princípio #1 ("duas etapas no IA,
sempre separadas") exige raw e parsed como IA items distintos. Para fontes HTML
(sem PDF), o raw item armazena `{ia_id}.html` + `raw_meta.json` sidecar.
IA não faz OCR em HTML (princípio #2 não se aplica — HTML já é texto).
A Etapa 2 usa `fetch_html(fonte_url)` diretamente, não um `_djvu.txt` do IA.

**Identificadores sem mudança**: `leizilla-raw-{ente}-{fonte}-{chave}` idêntico
ao raw PDF. Tooling downstream não precisa saber o tipo de conteúdo.

**`raw_meta_html`**: campo `content_type: "html"` + `hash_html` (vs `hash_pdf`).

**URL patterns Planalto (leis pré-2002)**:
- Leis ordinárias: `https://www.planalto.gov.br/ccivil_03/leis/L{N}.htm`
- Leis complementares: `https://www.planalto.gov.br/ccivil_03/leis/lcp/Lcp{N}.htm`
- Decretos: `https://www.planalto.gov.br/ccivil_03/decreto/D{N}.htm`

Leis pós-2002 usam year-scoped paths (`_ato{Y}-{Y}/{ano}/lei/l{num}.htm`) —
M2.8 cobrirá via API Câmara. Fail-open em 404 garante sem crash no pipeline.

**CLI `scrape`**: ramo `ente=federal, fonte=planalto` usa `scrape_one_html` em vez
de `scrape_one`. Zero breaking change para ro/assembleia e ro/casacivil.

30 testes em `tests/test_planalto_pipeline.py`.

### 2026-05-22 — M4.2: release-dataset + upload_dataset (sem PyArrow)

`publisher.upload_dataset(parquet_path, ente, version, row_count, git_sha)` + CLI
`leizilla release-dataset <parquet> --ente ro --version 0 [--dry-run]`.

**Identifier**: `leizilla-dataset-{ente}-v{version}` (SCHEMA.md §3.5).

**Sidecar JSON em vez de KV footer no Parquet**: `dataset_meta.json` carrega as
colunas que §3.3 diz que deveriam ir no KV footer do Parquet (row_count, hash,
schema_version, git_sha). PyArrow não é dep explícita (decisão de M4.1); DuckDB
`COPY ... (KV_METADATA ...)` não existe na API pública até 1.3. Sidecar JSON tem
custo zero e dados equivalentes — se o KV footer se tornar relevante em M5, migra
com um script de reescrita.

**Validações**: `version >= 0` (ValueError se negativo); `ente` contra `^[a-z][a-z0-9-]*$`
(ValueError se inválido). CLI captura `ValueError` da API e produz erro controlado (exit 1).
`FileNotFoundError` capturado quando `ia` CLI não está instalado — retorna `{success: False}`
em vez de traceback.

**Benchmark gatilhos §3.4** embutido no CLI: mede file size, row_count e latência de
busca full-text local (DuckDB Python, não WASM). Canônico em M5.

18 testes em `tests/test_publisher_dataset.py`.

### 2026-05-22 — M3.5: CLI parse --input-type html + fetch_ia_html

`fetch_ia_html(ia_id)` adicionada em `parser.py` — thin wrapper sobre `fetch_html`
que constrói `https://archive.org/download/{ia_id}/{ia_id}.html`. Pattern simétrico
a `fetch_ocr` que usa `{ia_id}_djvu.txt`.

CLI `cmd_parse` recebe `--input-type` (valores: `ocr` | `html`; default: `ocr`).
- `ocr`: comportamento existente — `fetch_ocr(raw_id)` → `parse_law(..., input_type="ocr")`
- `html`: `fetch_ia_html(raw_id)` → `parse_law(..., input_type="html")`
- Valor inválido: exit 1 com mensagem clara.

**Por que agora**: M3.4 (parser.py) já aceitava `input_type="html"` mas a CLI continuava
hard-coded em `fetch_ocr`. M2.7 (#34) cria IA items com `.html` para Planalto federal.
Sem esta mudança, `parse` e o pipeline Etapa 2 são inutilizáveis para fontes HTML.

**Não feito aqui**: `parse-all --input-type html` fica para M2.8 — requer também
ajuste no padrão de chave (federal usa `lei-NNNNN`, não `coddoc-NNNNN`).

**Testes**: 3 novos em `TestFetchIaHtml` + 3 novos em `TestCmdParseUpload`. 314 total.

### 2026-05-22 — M3.4: parse_law aceita HTML além de OCR

`parse_law` recebe novo parâmetro `input_type: str = "ocr"` (padrão retrocompatível).
`fetch_html(url)` adicionado — análogo a `fetch_ocr`, mas recebe URL direta em vez de ia_id.

**Por que**: Planalto (fonte canônica federal) serve HTML, não PDF. Pipeline M3 existente
(`fetch_ocr` → IA `_djvu.txt`) não se aplica a HTML. Solução mínima: aceitar HTML como
texto de entrada em `parse_law` com prompt ligeiramente diferente e limite de caracteres maior.

**Mudanças em parser.py**:
- `_SYSTEM_INTRO_OCR` / `_SYSTEM_INTRO_HTML`: constantes de introdução de prompt distintas.
- `_HTML_CHAR_LIMIT = 32000` (vs `_OCR_CHAR_LIMIT = 8000`): HTML tem overhead de markup.
- `parse_method` em `parsed_meta` agora é `f"{model}+{input_type}"`.
- `ValueError` levantado para `input_type` desconhecido — evita `parse_method` corrompido
  por typo (ex: `'haiku+htlm'`). Fix post-review (P2 codex).
- `except Exception` → `(urllib.error.URLError, OSError)` em `fetch_html`. urllib levanta
  `HTTPError` (subclasse de `URLError`) para 4xx/5xx; check explícito de status é redundante.

**Testes**: 35 testes em `tests/test_parser.py` (33 iniciais + 2 do fix post-review).

**Não feito aqui**: integração na CLI `parse` com `--input-type html` fica quando federal
scraping for implementado (não há consumidor ainda).

### 2026-05-22 — M4.1: ETL XML→Parquet via DuckDB read_json_auto

`etl.py` implementa a transformação Leizilla XML v0.1 → tabela `versoes` (§3.1 SCHEMA.md).

**Decisões de design**:
- `xml_to_rows(xml_content, lei_id, ente)` é função pura (sem I/O). Parses Leizilla XML em
  lista de dicts prontos para Parquet. `lei_id` vem do caller (nome do arquivo ou IA item ID).
- `write_parquet` usa DuckDB `read_json_auto` via temp NDJSON file. PyArrow não é dependência
  explícita; DuckDB 1.3.1 não expõe `from_dict` na connection API. NDJSON é simples e correto.
- Datas serializam para ISO strings no JSON; DuckDB auto-infere `DATE` em `read_json_auto`.
- Token map duplicado de `check_schema_consistency.py` — ambos apontam para §4.2 SCHEMA.md.
  Candidato a extração futura para `leizilla.schema_tokens`, mas duplicação explícita é
  preferível a acoplamento implícito agora.
- `path_to_tipo` exportada públicamente — será usada por CLI `consolidate` e frontend.
- `consolidate` CLI aceita diretório de `{lei_id}.xml` — padrão de saída do `parse --output`.
- 76 testes cobrem todas as fixtures + fixes P1/P2 (lei revogada, cascata, xs:date, fallback ID).
### 2026-05-22 — M2 restante: fontes SP e federal — stubs com mapeamento de portais

### 2026-05-22 — M2.5: casacivil discovery via enumeração direta (sem Playwright)

**Auditoria do portal**: `www.casacivil.ro.gov.br/leis` → redireciona para
`ditel.casacivil.ro.gov.br/COTEL/Livros/listleiord.aspx?ano=YYYY`, que retorna
403 de ambientes externos. Porém, PDFs individuais são acessíveis diretamente:
`HEAD http://ditel.casacivil.ro.gov.br/COTEL/Livros/Files/L5120.pdf` → 200.

**Padrão de URL descoberto** via Google cache + HEAD requests:
- Leis ordinárias: `L{N}.pdf` (ex: `L5120.pdf`, `L3830 - COMPILADA.pdf`)
- Leis complementares: `LC{N}.pdf` (ex: `LC1209 - COMPILADO.pdf`, `LC748.pdf`)
- A versão `COMPILADA` (texto consolidado vigente) tem sufixo variável — não
  tentamos enumerar variações; o Wayback Machine frequentemente tem a base `L{N}.pdf`
  que é suficiente para OCR (compiladas são frequentemente scanned igualmente).

**Decisão de design**: `discover_casacivil_laws` é função standalone (não método
de `LeisCrawler`), pois não precisa de Playwright. Retorna URLs candidatas sem
verificar existência — `scrape_one` trata 404/timeout via Wayback fail-open.

**Chave**: `lei-{N:05d}` para ordinária, `lc-{N:05d}` para complementar.
`IA id`: `leizilla-raw-ro-casacivil-lei-{N:05d}` ou `lc-{N:05d}`.

**CLI**: `scrape --fonte casacivil --tipo lei|lc --start-coddoc N --end-coddoc M`
(reuso semântico de `--start-coddoc` como "número inicial", sem breaking change
para assembleia que continua usando coddoc).

**Descobertas notáveis**:
- Portal DITEL usa ASP.NET WebForms (`listleiord.aspx`) — script da década de 2000.
- Leis Rondônia chegam a L6000+ (ordinárias); LC chega a ~1300+.
- Alguns PDFs têm sufixos: `_compressed`, `- PL` (projetos), `- COMPILADA`.
  Para o pipeline v0 aceitamos o URL base e deixamos Wayback/IA lidar com
  disponibilidade.

### 2026-05-22 — M2.4: Rate-limit por host (supersede M2.2 global limiter)

`make_rate_limiter()` agora retorna `Callable[[str], None]` (recebe URL) em vez de
`Callable[[], None]`. Closure mantém `Dict[str, float]` com `last[host]` por netloc.

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
- `_xsd_gate` é fail-open apenas para ferramentas ausentes: `xmllint` não instalado
  ou schema não encontrado → retorna True (pipeline continua). Quando `xmllint`
  está presente e encontra erros → retorna False e o upload é **bloqueado** (exit 1 em
  `parse --upload`; skip + contagem de erro em `parse-all`).
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

- **2026-07-07 — Divergência de roadmaps entre README.md, CLAUDE.md e MASTERPLAN.** Os três
  documentos mantinham roadmaps mutuamente inconsistentes (README declarava o MVP RO
  "Implementado" sem dataset publicado; CLAUDE.md mantinha o cronograma Q3/2025–Q2/2026
  vencido; MASTERPLAN descrevia o repo como "Pre-MVP"). Detectado pela auditoria de
  2026-06-30 (`docs/audit-divergencias.md`) e resolvido via
  [RFC-0002](docs/rfc/0002-governanca-documental.md) (hierarquia de fontes de verdade;
  roadmap único no README; docs supersedidos em `docs/archive/`) e
  [RFC-0004](docs/rfc/0004-go-live-rondonia.md) (re-baseline 2026H2–2027 + runbook de go-live).

---

## Como rodar localmente

### Pipeline backend (Python)

```bash
# Setup
uv venv && source .venv/bin/activate
uv sync --extra dev          # (não `--dev` — linters/mypy vivem no extra `dev`)
uv run leizilla dev setup

# Pipeline atual (manifest-driven)
uv run leizilla discover --ente ro
uv run leizilla harvest --ente ro --limit 10

# Etapas separadas
uv run leizilla scrape --ente ro --fonte casacivil --tipo lei --start-coddoc 1 --end-coddoc 10
uv run leizilla parse --ente ro --raw-id leizilla-raw-ro-casacivil-lei-05120
uv run leizilla fetch-all-parsed --ente ro --output-dir data/parsed
uv run leizilla consolidate data/parsed --output out.parquet --ente ro
uv run leizilla release-dataset out.parquet --ente ro --version 0
```

Referência operacional completa: `docs/okf/pipeline/` e a tabela CLI do `CLAUDE.md`.

### Frontend (após M5)

```bash
cd web/
npm install
npm run dev    # http://localhost:4321
npm run build  # static build → dist/
```

### Testes

```bash
uv run leizilla dev check    # lint (ruff) + format-check + test (mypy roda separado no CI)
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

_(atualizado em 2026-09-24, sessão de rotina 5)_

**M0–M13, M14.4 e M15.1 concluídos** ✅. RFC-0004 (go-live) está executada:
`leizilla-dataset-ro-v0`/`-latest` publicado e crescendo, portal público em
produção. `docs/okf/project-dag.md` (PR #177) ainda não existe em `main` —
quando mergeado, passa a ser o ledger de estado executável (ver CLAUDE.md
dessa PR); até lá este arquivo + `docs/rfc/` + issues seguem reconstruíveis a
partir do repositório.

**Prioridade nº1 — causa raiz das falhas semanais do `rondonia_crawler.yml`**:
sessão 5 descobriu que os jobs `scrape-casacivil-lei`/`-lc` vêm cancelando por
timeout em praticamente toda execução semanal desde julho, com ~99% de falha
por item — e que a razão real ficava escondida atrás de um bug de relatório
(`Falha [?]` em vez do texto real do erro). Fix do relatório em PR própria
(#187); a **próxima execução semanal** (ou um `workflow_dispatch` manual) do
`rondonia_crawler.yml`, depois que essa PR mergear, vai finalmente imprimir o
`stderr` real do `ia upload` que falha. Próxima sessão deve ler esse log e
decidir a correção real (candidato mais provável: o throttle de rate-limit do
IA documentado em 2026-07-14 — "reduce your request rate... appears to be
spam" — batendo porque centenas de uploads sequenciais por hora miram o mesmo
IA item de range). Issues #136/#140 continuam abertas ligadas a este achado.

**Portfólio de PRs irmãs da sessão 5 — todas reconciliadas e mergeadas**:
#184 (log/docs), #181/#182/#183 (itens 1/2/4 da issue #151) e #179
(RFC-0003 Fase 1, issue #176 — fechada); #180 (releases imutáveis + ponteiro
`latest`, issue #175 — fechada); #185 (cobertura S1–S4, issue #174 —
fechada), com um bug real corrigido no processo (`upload_coverage` mirava um
identifier que #180 tornou inalcançável — ver log); #186 (itens 3/5 da
issue #151 — xsd-gate fail-closed + higiene de docs/scripts mortos — e
issue #102, testes de frontend). Issue #151 agora tem os 5 itens da sua
lista ordenada endereçados. Nenhuma PR de portfólio da sessão 5 segue aberta
exceto #178 (superseded) e #177 (DAG/OKR, aguardando review dedicada do
mantenedor) — ver abaixo. #178 ficou aberta com um
comentário explicando por que #179 foi preferida (conclusão contraditória
sobre RFC-0003 Fase 1); sua cobertura de teste adicional
(`test_wayback_html_response_triggers_fallback`, `test_direct_fallback_rejects_non_pdf`)
segue válida para uma PR própria. #177 (DAG/OKR) segue aberta, grande o
suficiente para preferir revisão dedicada do mantenedor antes do merge —
quando mergear, vira a fonte de verdade de estado executável (ver seu próprio
CLAUDE.md).

**M5.3 ainda bloqueado**: dataset real existe mas RO segue pequeno para um
benchmark WASM significativo. Revisitar quando a cobertura RO crescer (marco
Q4/2026 do README) ou o search in-browser medir > 1s.

**Marco de roadmap (README.md, Q4/2026)**: "Cobertura RO mais completa +
releases recorrentes". Releases recorrentes já rodam sozinhas; a
instrumentação S1–S4 (M15.1, mergeada) dá o primeiro número público para
medir esse marco assim que `coverage.json` for publicado pela primeira vez em
produção (próxima execução agendada de `parse-release.yml` — secrets já
existem, RFC-0004). Baseline conhecido no momento do merge: casacivil
S1=1196→S4=20; assembleia 0 em tudo (nenhum raw publicado ainda nessa fonte).

**Convergência scrape→harvest (RFC-0003)**: Fase 1 concluída (#173 + #179).
Falta, como dívida secundária, o `end: 5000` hardcoded do
`playwright-crawler` de `assembleia` (achado de #178, ainda sem PR própria).
Fases 2 (redirecionar workflows) e 3 (aposentar `cmd_scrape`) seguem não
iniciadas — dado o achado de causa raiz acima, a Fase 2 pode ganhar urgência
assim que a causa real das falhas do `rondonia_crawler.yml` for confirmada e
corrigida (ou se `discover-harvest.yml`, que não mostra o mesmo padrão de
cancelamento, provar-se suficiente sozinho).

**M14 (OPF fine-tune) segue em progresso** (M14.1–M14.2 done, M14.4 done;
M14.3 aguarda execução em GPU/Colab fora do alcance headless).

**Dívida técnica identificada, ainda aberta**: issue #127 (contrato de
`numero` com sufixo de letra — parser rejeita, ETL/URN aceitam; decisão de
design end-to-end, maior que "dívida pequena"); issue #167 (semântica de data
legada nos downloads públicos, depende de #170 — WIP de outra sessão).
