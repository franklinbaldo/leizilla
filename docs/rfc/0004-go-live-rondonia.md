# RFC-0004: Go-live Rondônia — ativação de produção e re-baseline do roadmap

**Status**: aceito — `leizilla doctor` e re-baseline implementados no PR desta RFC.
**Atualização 2026-07-12**: `IA_ACCESS_KEY`, `IA_SECRET_KEY` e `GEMINI_API_KEY` já
estão configurados como Repository secrets e autenticação real no Internet Archive
foi confirmada (`check-credentials.yml`, execuções em push/PR — ver log do job
"check-credentials" no PR #101: resposta `{"authorized": true}` do endpoint
`check_auth` do IA). Falta apenas uma execução manual de `check-credentials.yml`
via `workflow_dispatch` (ver "passo 1" abaixo) para o preflight oficial, depois o
runbook segue direto para o smoke batch (passos 3–6) — **secrets não é mais o
gargalo**.
**Data**: 2026-07-07
**Relacionados**: M5.3 (bloqueado), IMPLEMENTATION.md "Ação manual necessária"
(2026-05), PRs #93/#94 (primeiras execuções reais de scraping, 06/2026)

## Problema

**O gargalo do projeto não é código — é ativação.** O estado em 2026-07:

- Pipeline completo implementado e testado (M0–M12.2 done, ~660 testes verdes).
- Frontend pronto (M5.1/M5.2) apontando para uma URL de Parquet que **não existe**:
  nenhum dataset foi publicado no IA. `list_raw_ids` retornava vazio em 06/2026.
- M5.3 (benchmark WASM + FTS) bloqueado há 14 meses de trabalho esperando esse dataset.
- A causa raiz está registrada desde 05/2026: `IA_ACCESS_KEY`, `IA_SECRET_KEY` e
  uma chave LLM nunca foram configurados nos secrets do GitHub Actions. **Isso já
  foi corrigido** (2026-07-12): `IA_ACCESS_KEY`, `IA_SECRET_KEY` e `GEMINI_API_KEY`
  existem como Repository secrets (`ANTHROPIC_API_KEY` segue ausente, mas a
  RFC-0006 torna isso irrelevante — uma chave LLM basta). Os 4 workflows agendados
  (discover-harvest, crawler, parse-release, claude-routine) rodaram semanalmente
  por mais de um ano produzindo zero dados por essa causa; com os secrets
  presentes, os próximos disparos devem produzir dados reais.
- As primeiras execuções reais (locais) só aconteceram em 06/2026 e imediatamente
  acharam bugs de produção (#93: Wayback devolvendo HTML; #94: navegação impossível
  nos buckets) — evidência de que cada semana sem rodar em produção esconde uma fila
  de bugs desse tipo.
- Enquanto isso, o roadmap público venceu inteiro (Q3/2025–Q2/2026) e o README
  declara entregue o que não foi (ver RFC-0002).

## Decisão

### 1. Runbook de go-live (ordem estrita)

| # | Passo | Dono | Verificação |
|---|---|---|---|
| 0 | Mergear #93 e #94 (fixes de produção já prontos) | mantenedor | ✅ feito — CI verde em main |
| 1 | Configurar `IA_ACCESS_KEY`/`IA_SECRET_KEY` + **uma** chave LLM (ex.: `GEMINI_API_KEY`) + opcional `LLM_MODEL` nos Actions secrets/vars *(atualizado pela RFC-0006)* | mantenedor (manual) | ✅ feito — secrets presentes; `check-credentials.yml` via dispatch ainda pendente para o preflight oficial (ver nota abaixo) |
| 2 | Rodar `leizilla doctor` localmente e no CI | qualquer um | ⚠️ parcial — auth real confirmada em execuções via push/PR (log do job, `"authorized":true`); falta rodar `check-credentials.yml` por `workflow_dispatch` (o caminho que falha de verdade em vez de fail-open) para o preflight oficial |
| 3 | Smoke batch: `discover --ente ro` + `harvest --ente ro --limit 10` via dispatch | CI | 10 itens raw no IA (`stats --ia`) |
| 4 | Esperar OCR do IA (~horas) e parsear o smoke batch: `parse-all … --limit 10 --upload` | CI | 10 itens parsed no IA |
| 5 | `fetch-all-parsed` + `consolidate` + `release-dataset … --version 0` | CI | `leizilla-dataset-ro-v0` existe; Parquet baixável |
| 6 | Apontar `PUBLIC_PARQUET_URL` do frontend para o dataset e fazer deploy | CI | busca no GH Pages retorna resultados |
| 7 | Destravar os schedules com ranges completos (workflows já existem) | mantenedor | crescimento semanal em `stats --ia` |
| 8 | **Desbloquear M5.3**: benchmark in-browser com dados reais | sessão de rotina | métricas registradas no IMPLEMENTATION.md |

O runbook é deliberadamente incremental: um lote de 10 antes de qualquer range de
milhares, porque as execuções de 06/2026 mostraram que os bugs aparecem nos 10
primeiros itens.

**Nota sobre o passo 2 (preflight)**: `check-credentials.yml` roda em todo push/PR,
mas é fail-open nesses eventos (`exit 0` mesmo faltando secret ou falhando a auth) —
só o disparo manual via `workflow_dispatch` falha de verdade (`exit 1`) se algo
estiver errado. As execuções em push/PR já mostraram o teste de auth real
(`curl .../?check_auth=1`) rodando e retornando `{"authorized": true}` — isso não é
o caminho fail-open (que só age quando falta secret ou a auth falha), então é
evidência real, não um bypass. Ainda assim, o preflight **oficial** deve ser um
disparo manual de `check-credentials.yml` via `workflow_dispatch` (Actions → Check
Pipeline Credentials → Run workflow → branch `main`), porque só esse caminho
bloqueia (`exit 1`) em caso de regressão. Agentes automatizados não conseguem
disparar `workflow_dispatch` neste repositório (a integração usada não tem escopo
`actions: write` — tentativa em 2026-07-12 retornou 403); é uma ação manual do
mantenedor.

### 2. `leizilla doctor` (implementado neste PR)

Novo comando que verifica os pré-requisitos de produção e imprime um checklist:

- variáveis de ambiente presentes (`IA_ACCESS_KEY`, `IA_SECRET_KEY`, chave LLM
  presente para o modelo configurado — ex. `GEMINI_API_KEY` ou
  `ANTHROPIC_API_KEY`; *atualizado pela RFC-0006*) — sem vazar valores;
- diretório de dados/DuckDB acessível e gravável;
- conectividade com IA e Wayback (HEAD requests, fail-open: rede ausente vira aviso,
  não erro — consistente com a filosofia do projeto);
- resumo com exit code 0 (tudo essencial OK) / 1 (falta pré-requisito essencial),
  para uso em CI antes de steps que gastam LLM/upload.

### 3. Re-baseline do roadmap (implementado neste PR, no README)

| Período | Entregável | Critério objetivo |
|---|---|---|
| **Q3/2026** | Go-live: dataset RO v0 publicado no IA + frontend apontando para ele | passos 1–6 do runbook |
| **Q4/2026** | Cobertura RO completa (assembleia + casacivil lei/lc) + releases semanais estáveis | `stats --ia` ≥ ranges dos manifestos; M5.3 done |
| **Q1/2027** | Federal (Planalto 1988–presente) em produção | dataset federal v0 no IA |
| **Q2/2027** | Busca semântica (embeddings no DuckDB) + novo ente (SP) | protótipo em produção |

Regra da RFC-0002: esta tabela vive só no README; CLAUDE.md aponta para ela.

## Alternativas consideradas

- **Rodar o pipeline completo direto (ranges de milhares)**: rejeitado — queima budget
  LLM e horas de IA-OCR antes de validar o caminho; o histórico de #93/#94 mostra que
  o primeiro lote encontra bugs.
- **Publicar um dataset sintético para desbloquear M5.3**: rejeitado — viola
  "evidência antes de inferência" (PRD §3.1); o benchmark precisa da distribuição real.
