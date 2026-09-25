# ADR-0013 — Proxy CORS para leitura direta do Parquet publicado pelo navegador

**Status**: Aprovada — implementação bloqueada em credencial (ver "Bloqueios" abaixo). O
gap de CORS em si foi corrigido por outra via em [ADR-0014](0014-same-origin-dataset-mirror.md)
(espelho same-origin, sem dependência de credencial), que não revoga esta decisão — o Worker
continua uma opção válida, só deixou de ser a única.
**Data**: 2026-09-25
**Contexto**: `browser-read-cors-integrity` no DAG do projeto; issue #223; PR #224 (mitigação de
classificação, já mergeada)
**Relaciona-se com**: [ADR-0001](0001-projeto-estatico-duckdb-torrent.md) (IA como pilar
central — nenhum servidor próprio), [ADR-0010](0010-raw-content-addressed-parsed-urn.md)/
[ADR-0011](0011-raw-identity-keyed-range-items.md) (publicação no IA), `web/src/lib/db.ts`
(DuckDB-WASM lê o Parquet publicado)

## Contexto

A premissa central da ADR-0001 é que o navegador lê o dataset publicado **direto do
Internet Archive** via DuckDB-WASM (`read_parquet()` sobre HTTP range requests) — sem
nenhum servidor próprio. Issue #223 encontrou que isso está quebrado para **qualquer**
navegador real, não só nesta sessão:

`archive.org` (e os nós de armazenamento `iaNNNNNN.us.archive.org` para onde ele
redireciona) não envia `Access-Control-Allow-Origin` para arquivos servidos como
`application/octet-stream` — confirmado para `.parquet` — mas **envia** para `.json` do
mesmo item, no mesmo nó. Reconfirmado ao vivo nesta sessão (2026-09-25) contra o ponteiro
`-latest` que o site publicado realmente usa, não só contra archive.org genericamente:

```
curl -L "https://archive.org/download/leizilla-dataset-ro-v0-latest/versoes.parquet" \
  -H "Origin: https://franklinbaldo.github.io" -H "Range: bytes=0-0"
# → HTTP/2 206, content-type: application/octet-stream, SEM access-control-allow-origin

curl -L "https://archive.org/download/leizilla-dataset-ro-v0-latest/dataset_meta.json" \
  -H "Origin: https://franklinbaldo.github.io"
# → HTTP/2 200, access-control-allow-origin: *, access-control-allow-credentials: true
```

Sem CORS, `XMLHttpRequest`/`fetch` do DuckDB-WASM não conseguem ler o `.parquet` a partir
de `https://franklinbaldo.github.io` — nenhum navegador real, produção incluída. A rota
`/lei/?id=...` nunca renderiza uma norma; cai no estado `DatasetUnavailable`. PR #224 (já
mergeada) apenas **classifica** essa falha como permanente/externa em vez de mostrar "tente
de novo" para algo que nunca vai resolver sozinho — não é uma correção.

O mesmo problema, com a mesma causa raiz, já foi encontrado e corrigido no projeto irmão
`causaganha` (issue #1482 / PR #1521 lá): um Cloudflare Worker que re-serve o Parquet do IA
adicionando `Access-Control-Allow-Origin`, preservando `Range`/`Content-Range` para que o
DuckDB-WASM continue fazendo leitura parcial em vez de baixar o arquivo inteiro.

## Opções consideradas

1. **Proxy serverless (Cloudflare Worker, portado de `causaganha`)** — re-serve
   `archive.org/download/{item}/*.parquet` com CORS adicionado. Free tier do Cloudflare
   Workers é zero-custo e serverless/edge (sem servidor próprio para operar/atualizar/cair).
   Implementação já existe e está validada em produção no projeto irmão — risco de
   engenharia é baixo, é port, não design novo.
2. **Reportar o gap para o Internet Archive** — é uma limitação da própria plataforma
   (`.json` do mesmo item/nó já tem CORS; `.parquet` não), então pode ser corrigível
   upstream sem proxy nenhum. Não exclui a opção 1 — são complementares, não alternativas:
   reportar tem custo baixo e o teto é alto (resolve para todo mundo que usa IA + CORS),
   mas está fora do controle do projeto e sem prazo previsível.
3. **Não corrigir; manter apenas a mitigação de classificação (PR #224)** — o portal
   continua funcionalmente quebrado para `/lei/?id=...` em produção. Rejeitada: contraria
   a proposta central do produto (legislação pesquisável de verdade, não só um portal que
   explica educadamente por que não funciona).
4. **Mudar o formato de distribuição** (ex.: publicar `.json`/`.csv` em vez de `.parquet`
   para leitura pelo navegador) — perderia leitura colunar eficiente e forçaria manter dois
   formatos ou baixar o dataset inteiro sem range requests. Rejeitada: o Parquet + DuckDB-WASM
   é a arquitetura assumida desde M5 (ADR-0001) e o problema é CORS, não o formato.

## Decisão

**Adotar a opção 1 (Cloudflare Worker, free tier) como correção principal, e perseguir a
opção 2 (reportar ao IA) em paralelo, sem prazo de bloqueio mútuo.**

- O Worker é a única opção que corrige o problema **sem** esperar por terceiros e sem
  mudar o formato de distribuição assumido pelo resto do pipeline.
- Cloudflare Workers free tier é serverless, sem custo e sem servidor para operar — o mais
  próximo do princípio infrastructure-minimal do CLAUDE.md que uma correção real permite.
  Ainda assim **é** uma peça de infraestrutura própria nova (hoje o projeto não tem
  nenhuma) — por isso esta decisão está registrada em ADR antes de implementar, como o
  próprio CLAUDE.md pede para decisões arquiteturais.
- Reportar ao Internet Archive é barato e não compete por esforço de implementação (é um
  reporte, não um projeto) — deve ser feito por quem tem canal apropriado com o IA
  (mantenedor/owner do projeto), não bloqueia nem é bloqueado pelo Worker.

## Bloqueios

- **Credencial Cloudflare** (conta + API token do Workers free tier) — nenhuma sessão até
  agora teve acesso a essa credencial. Sem ela, o Worker não pode ser implantado.
  O código-fonte já existe em `deployment/archive-cors-proxy/` (port de `causaganha`
  issue #1482/PR #1521, escrito e testado nesta sessão — 8 testes cobrindo path
  allowlist, preflight, forwarding de `Range` e erro de upstream, `node --test`), então a
  implementação em si não é mais o gargalo, só o `wrangler deploy` propriamente dito.
  `web/src/lib/db.ts`'s `DATASET_IA_ITEM` também já deriva a identidade do item pelo
  pathname `/download/{item}/...` em vez de exigir o host `archive.org` literal, então
  apontar `PUBLIC_PARQUET_URL` para o domínio do Worker depois do deploy não quebra
  `dataset_meta.json`/`coverage.json` (que continuam servidos direto do IA, já têm CORS).
- **Canal de reporte ao Internet Archive** — não há uma conta de suporte configurada para
  este projeto; melhor feito manualmente pelo mantenedor.

## Consequências

- **Enquanto bloqueado**: o site publicado continua sem conseguir ler o Parquet em
  produção real; PR #224 evita que o usuário receba uma mensagem enganosa ("tente de
  novo"), mas não restaura a funcionalidade. `kr-public-semantic-legibility` (issue #167)
  também continua sem poder validar a seção Dados contra dado real publicado, por
  depender do mesmo caminho de leitura.
- **Quando desbloqueado**: portar o Worker de `causaganha` (issue #1482/PR #1521),
  apontar `PUBLIC_PARQUET_URL`/`DATASET_META_URL`/`COVERAGE_JSON_URL` (ou só o parquet,
  a decidir na implementação) para o domínio do Worker, e então a visual-capture real de
  `/lei/?id=...` finalmente se torna possível — desbloqueando `kr-public-semantic-legibility`.
- **Reversível**: se o Internet Archive corrigir o CORS upstream, o Worker vira redundante
  e pode ser removido sem afetar o resto do pipeline (nenhuma camada abaixo do navegador
  depende dele).

## Fora de escopo desta ADR

O código do Worker em si (é port de `causaganha`, não design novo), o domínio/DNS exato
usado para servir o proxy, e se `dataset_meta.json`/`coverage.json` também passam a ser
servidos pelo Worker ou continuam direto do IA (já têm CORS, não precisam do proxy) —
decisões de implementação para quando a credencial existir.
