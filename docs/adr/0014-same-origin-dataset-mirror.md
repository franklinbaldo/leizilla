# ADR-0014 — Espelho same-origin do Parquet como correção do gap de CORS do IA

**Status**: Aprovada e implementada
**Data**: 2026-09-25
**Contexto**: `browser-read-cors-integrity` no DAG do projeto; issue #223; ADR-0013 (Cloudflare
Worker, aprovada mas bloqueada em credencial desde 2026-09-25)
**Relaciona-se com**: [ADR-0001](0001-projeto-estatico-duckdb-torrent.md) (IA como pilar
central), [ADR-0013](0013-cors-proxy-parquet-browser-read.md) (opção de proxy, mantida como
alternativa dormente), `web/src/lib/db.ts`, `.github/workflows/deploy-web.yml`

## Contexto

ADR-0013 já registrou o problema: `archive.org` não envia `Access-Control-Allow-Origin`
para arquivos `.parquet` (mas envia para `.json` do mesmo item), então nenhum navegador
real consegue ler o Parquet publicado via DuckDB-WASM a partir de `franklinbaldo.github.io`.
ADR-0013 decidiu corrigir isso com um Cloudflare Worker (proxy CORS), já implementado e
testado em `deployment/archive-cors-proxy/`, mas bloqueado desde então: nenhuma sessão teve
(ou tem previsão de ter) a credencial Cloudflare necessária para `wrangler deploy`. Múltiplas
sessões re-confirmaram o mesmo bloqueio sem progresso nesse eixo.

Nova constatação desta sessão, verificada ao vivo: o dataset publicado é pequeno (143KB,
472 linhas em 2026-09-25) e o próprio `web/` já é publicado como site estático no GitHub
Pages. `raw.githubusercontent.com` confirmadamente envia `access-control-allow-origin: *`
para arquivos de repositórios públicos, mas isso nem é necessário — se o Parquet for
publicado **junto com o próprio site** (mesma origem), a leitura deixa de precisar de CORS
por definição: CORS só se aplica a requisições cross-origin.

## Opções consideradas

1. **Cloudflare Worker (ADR-0013)** — já decidida, implementada, mas bloqueada
   indefinidamente numa credencial que nenhuma sessão autônoma consegue prover a si mesma.
2. **Espelho same-origin** — publicar uma cópia do Parquet corrente dentro de
   `web/public/data/{ente}/`, servida pelo GitHub Pages junto com o resto do site.
   DuckDB-WASM passa a ler esse caminho relativo em vez do item do IA diretamente. Não
   precisa de nenhuma credencial nova, nenhuma infraestrutura própria adicional (GitHub
   Pages já é usado para o site), e o arquivo é pequeno o bastante (dezenas/poucas
   centenas de KB no volume atual) para não pesar no build/deploy.
3. **Reportar o gap ao Internet Archive** — mantido de ADR-0013, complementar, sem prazo.
4. **Não corrigir** — rejeitada pelas mesmas razões de ADR-0013.

## Decisão

**Adotar a opção 2 (espelho same-origin) como correção ativa por padrão, sem revogar
ADR-0013.** O Worker continua sendo uma opção arquiteturalmente válida (útil se algum dia
o dataset crescer demais para viver confortavelmente dentro do repositório/build do site,
ou se o projeto preferir centralizar tudo atrás de um domínio próprio) — seu código
permanece em `deployment/archive-cors-proxy/`, testado, dormente. Mas ela deixa de ser a
**única** via de correção: como a opção 2 não depende de nenhuma credencial externa, uma
sessão autônoma consegue implementá-la e verificá-la de ponta a ponta na mesma sessão,
sem esperar por um mantenedor.

Mecânica (ver `web/src/lib/db.ts` e `.github/workflows/deploy-web.yml`):

- `DATASET_PARQUET_URL`/`PARQUET_URL` (citação, download, exemplo de SQL, derivação de
  identidade `DATASET_IA_ITEM`) **não mudam** — continuam apontando para o item canônico
  do Internet Archive. Clicar num link `<a href>` é navegação de página inteira, não passa
  pela checagem de CORS, então isso já funcionava e continua funcionando; provenance e
  citação continuam corretas.
- Uma nova função `getDuckdbSourceUrl()` resolve o caminho que o DuckDB-WASM efetivamente
  lê: por padrão, `${BASE_URL}data/ro/versoes.parquet` resolvido contra a origem corrente
  do navegador — o espelho same-origin. Overridável via `PUBLIC_DUCKDB_SOURCE_URL` (ex.:
  apontar para o domínio do Worker da ADR-0013 se/quando ele for implantado).
  `_init()`/`probeDatasetAccess()` usam essa função, não `PARQUET_URL`.
- `.github/workflows/deploy-web.yml` sincroniza `web/public/data/ro/versoes.parquet` a
  partir do item `-latest` do IA a cada build (push em `web/**`, PR, dispatch manual, e um
  novo `schedule` diário ~30min depois do cron de `parse-release.yml`) — fail-open: se o
  IA estiver instável, mantém a cópia já commitada em vez de falhar o deploy.
- `DatasetAccessProbe`'s `'cors-blocked'` foi renomeado para `'mirror-unreachable'`: a
  causa mais provável de uma falha isolada no espelho deixou de ser CORS (impossível
  same-origin, por definição) e passou a ser "o espelho ainda não sincronizou" ou uma
  falha pontual de rede específica a esse arquivo.

## Consequências

- **Resolve o bloqueio de `kr-public-semantic-legibility`/issue #167**: a rota `/lei/` (e
  o resto do site) volta a poder carregar o Parquet num navegador real publicado, sem
  esperar por nenhuma credencial de terceiro. A captura visual já existente em
  `deploy-web.yml` (Playwright contra a página publicada) passa a rodar contra um site que
  de fato consegue ler o dataset.
- **Freshness**: o espelho só atualiza quando `deploy-web.yml` builda de novo — o novo
  gatilho `schedule` cobre o caso em que nenhum código de `web/` mudou, mas um dataset novo
  foi publicado. Pior caso (o IA está fora do ar bem na hora do sync), o site serve a
  release anterior até o próximo build bem-sucedido — never pior que o estado atual (site
  sem conseguir ler nenhum dado).
- **Escala futura**: se o dataset crescer a ponto de pesar no repositório/build (a decidir
  com um limiar concreto, não preventivamente), revisitar — nesse ponto o Worker da
  ADR-0013 (ou outro CDN) volta a ser a opção natural, e a troca é só mudar
  `PUBLIC_DUCKDB_SOURCE_URL`, sem tocar no resto do pipeline.
- **Reversível**: remover o espelho e voltar a `PARQUET_URL` como fonte de leitura é uma
  mudança de uma linha se algum dia deixar de fazer sentido.
