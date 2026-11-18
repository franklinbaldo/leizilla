# ADR-0016 — Colheita em lote: Wayback best-effort, upload em lote, derive único

**Status**: Aprovada (decisão do owner, 2026-11-15); implementada, **não verificada em
produção** (ver "Medido e suposto")
**Data**: 2026-11-15
**Contexto**: `ingestion-resilience` no DAG do projeto (`docs/okf/project-dag.md`) —
backfill dos ~30 mil decretos de Rondônia que faltam
**Emenda**: [ADR-0004](0004-wayback-fetch-path.md) (Wayback como caminho primário de fetch)
**Relaciona-se com**: [ADR-0008](0008-robots-rate-limit.md) (robots e limite por host),
[ADR-0010](0010-raw-content-addressed-parsed-urn.md) e
[ADR-0011](0011-raw-identity-keyed-range-items.md) (raw por conteúdo, itens de range e
`index.csv`), `src/leizilla/scraper.py`, `src/leizilla/publisher.py`,
`src/leizilla/wayback.py`

## Contexto

A colheita da fila (`leizilla harvest`) era estritamente serial e, por captura, fazia:
robots → `wayback.ensure_archived` (Save Page Now e fetch do snapshot) → um `ia upload`
com três arquivos (PDF, `_meta.json`, `index.csv` reescrito), com o derive padrão do IA
enfileirado a cada chamada.

Nesse ritmo o backfill dos decretos levaria meses, e o gargalo não é a fonte: é esperar
o Wayback e pagar um processo, uma reescrita de índice e um derive por documento.

## Decisão

Vale para `harvest_pending_resources` (a colheita da fila). `scrape_one`/`scrape_one_html`
(scrape por range e fontes HTML) continuam no ADR-0004.

1. **Wayback sai do caminho crítico.** Sem snapshot conhecido, a colheita baixa o PDF
   direto da fonte, no limite por host do ADR-0008 (~1 req/s), e **pede** o Save Page Now
   em segundo plano, sem esperar a resposta. Um snapshot que a descoberta já tinha no
   ledger continua sendo a origem preferida do fetch.
   - O pedido assíncrono é limitado (uma thread, fila de 200, 1 pedido a cada 5 s),
     fail-open, e consome o **mesmo** orçamento por host do fetch direto — o robô do
     Wayback também bate na fonte.
   - O que não couber na fila é descartado e contado; `wayback-save.yml` segue sendo o
     caminho que cobre o que ficou sem snapshot.
2. **Proveniência só afirma o que se sabe.** `provenance_wayback.fetched_from` passa a
   ter três valores: `wayback` (bytes vieram do snapshot), `source-fallback` (havia
   snapshot e ele falhou) e `source-direct` (nenhum snapshot era conhecido).
   `wayback_url`/`wayback_timestamp` só são preenchidos quando os bytes vieram de um
   snapshot. Um snapshot que o Save Page Now devolver depois vai para a coluna
   `wayback_snapshot` do ledger local, nunca para o `_meta.json` já montado.
3. **Upload em lote por item.** As capturas ficam num buffer por item do IA e sobem a
   cada 25 (`HARVEST_BATCH_SIZE`) num único `ia upload --no-derive --checksum`. O
   `index.csv` é mesclado com todas as linhas do lote e enviado **uma vez, por último**.
   O status no DuckDB só muda depois do flush que contém o arquivo; flush que falha
   deixa os recursos `pending`.
4. **Um derive por item por execução.** Ao fim, um `ia tasks <item> --cmd derive.php`
   para cada item que recebeu arquivos.
5. **PDF recusado pelo IA é terminal.** "error checking pdf file" marca o recurso como
   `ia-rejected` (não é retentado) e o restante do lote é reenviado sem ele. Os bytes
   **não** são preservados por outra via: renomear a extensão para driblar a checagem
   mudaria o contrato do `index.csv` sem que se saiba se o IA aceitaria. A contagem sai
   no resumo da CLI.
6. **Mais recentes primeiro.** Dentro do mesmo degrau de justiça (`ultima_tentativa`
   nula antes das demais, depois a mais antiga), a fila ordena pelo maior número.
7. **Recuar é parar.** IA limitando a taxa: o flush recua (60 s, 120 s) e, se não
   passar, a colheita encerra e tudo volta a `pending`. Dez falhas transitórias seguidas
   no fetch direto também encerram — a fonte caiu ou está nos barrando.
   `HARVEST_MAX_SECONDS` encerra com flush e derive antes do teto do job.

O paralelismo do workflow **não muda** (`max-parallel: 1`): o limite que estourou é da
conta, não do item.

## Medido e suposto

**Medido** (produção, 2026-11-14 e 2026-11-15):

- `harvest --tipo lei --limit 200`: 190 capturas em 1h43, ~33 s por captura.
- O IA respondeu `Please reduce your request rate. - total_tasks_queued exceeds
  global_limit` com a fila da conta saturada por uploads repetidos.
- O IA derivando um arquivo a cada 5–10 minutos num item de 1000 arquivos.
- O IA recusando alguns PDFs com `Uploaded content is unacceptable. - error checking
  pdf file`.

**Verificado no código da biblioteca instalada** (`internetarchive` 5.8.0), não em
produção:

- `ia upload --no-derive` envia `x-archive-queue-derive: 0`; sem a flag, a biblioteca só
  pede derive no último arquivo de cada invocação.
- Num `ia upload` de vários arquivos, o primeiro erro HTTP aborta os seguintes e o CLI
  sai com código 1, imprimindo ` error uploading {arquivo}: {mensagem}`. Por isso o
  `index.csv` vai por último e o arquivo recusado é identificável.
- `--checksum` pula arquivo já presente no item com o mesmo MD5.
- `ia tasks <item> --cmd derive.php` chama a Tasks API; sai com código 1 também para
  "already queued/running".

**Suposto** — precisa de uma execução de produção para confirmar:

- ~6 s por captura no fluxo novo (estimativa; o que domina é a latência de PUT do IA).
- Que a fila saturava por causa de um derive por upload, e que sem eles ~20 PUTs por
  minuto não esbarram no limite da conta.
- Que PUTs num item não ficam presos atrás de um derive longo do mesmo item.
- Que um derive pedido depois de uploads `--no-derive` processa todos os PDFs novos, e
  que "already queued/running" cobre os arquivos recém-enviados.
- Que o Save Page Now autenticado responde rápido o bastante para a maior parte dos
  pedidos caber na fila.

## Trade-offs aceitos

- A testemunha independente do Wayback deixa de ser garantida no momento da captura;
  passa a ser pedida e pode faltar. O hash do PDF e a URL de origem continuam no
  `_meta.json`.
- A fonte recebe até duas batidas por documento (a nossa e a do robô do Wayback) em vez
  de uma, dentro do mesmo teto de ~1 req/s por host.
- Uma execução morta antes do fim deixa arquivos no item sem derive pedido; o próximo
  derive do item os cobre, e a diferença S2/S3 de `leizilla coverage` os mostra.
- Um flush que falha a meio deixa PDFs no item sem linha no índice. São bytes
  endereçados por conteúdo: a recaptura reusa o mesmo nome.
- O OCR de um item passa a chegar em rajada, ao fim da execução, não documento a
  documento.

## Adendo 2026-11-16 — o que a produção mediu e duas regras novas

**Medido** (execuções agendadas de 2026-11-15 e 2026-11-16, run 43837226213):

- Cada captura levou **12–13 s** (lei: 560 capturas em 7300 s, parada pelo orçamento
  de 2 h), não os ~6 s estimados.
- O IA limita também **por item**: `Please reduce your request rate. -
  bucket_tasks_queued exceeds rationed amount` (27 vezes em decreto), distinto do
  limite da conta (`total_tasks_queued`, visto em 2026-11-14). Como a fila é ordenada
  do número mais novo para o mais antigo, todos os uploads iam para um único item,
  `decreto_32001-33000`, e a colheita parou depois de 125 capturas.
- Esse item tinha o derive pedido no dia anterior ainda na fila (`queued`, 219 PDFs, 0
  `_djvu.txt`) mais de 20 horas depois. Novos uploads se empilham atrás dele: era o
  risco do dia 2 (suposição 2 acima).
- Um tipo (lc) gastou as 1000 tentativas em 404 de URLs adivinhadas que uma estratégia
  de descoberta já removida deixara na fila. Custo único, mas esgotou o limite.

**Regras novas**

1. *Item com fila cheia não para a colheita.* A mensagem do IA é classificada
   (`ia_throttle_scope`): `bucket_tasks_queued` é da ração do item; `total_tasks_queued`
   ou mensagem sem marcador é da conta. No caso do item, ele é marcado como adiado
   nesta execução, suas capturas em buffer voltam a `pending`, e os recursos seguintes
   que mapeiam para ele não são baixados da fonte nem contam como tentativa ou falha
   (contador `adiados`); os demais itens seguem. Limite da conta continua encerrando.
2. *Derive só com o item terminado.* Ao fim da execução, o derive de um item que
   recebeu arquivos só é pedido se nenhum recurso `pending` da fila mapear para ele
   (`count_pending_in_range`); senão fica "derive adiado". Item que a execução tocou
   sem subir nada (já preservado, 404 confirmado) e ficou sem pendências também recebe
   o derive. Item adiado por fila cheia nunca recebe. `HARVEST_DERIVE=0` desliga tudo.
3. *Sequência de inexistentes.* 50 resultados 404/410 confirmados seguidos, sem nenhuma
   captura na execução, encerram a colheita. Não há coluna de proveniência em
   `discovered_resources`, então isto limita o desperdício a 50 por execução em vez de
   removê-lo; cada 404 já é terminal e a próxima execução segue adiante.

4. *Rodízio entre itens.* A fila pendente (`get_pending_resources`) passa a intercalar
   os buckets de 1000 números: dentro do degrau "nunca tentado antes de retentado", pega
   o mais novo de cada bucket em turnos, do bucket mais alto ao mais baixo, em vez de
   esgotar um item antes do próximo. Isso espalha os uploads (e a ração por item).
   Bucket adiado por throttle simplesmente é pulado no rodízio.
5. *Mais tempo por dia.* `HARVEST_MAX_SECONDS` 7200 → 16200 (4,5 h) por tipo, limite
   1000 → 3000 e quatro execuções por dia (02:00, 08:00, 14:00, 20:00 UTC). Conta do
   teto de 360 min: ~5 min de setup, ~10 de descoberta, 270 de colheita e ~20-30 de
   encerramento (fetch em voo, flush, derive) ≈ 315 min no pior caso, ~45 de folga. O
   grupo de concorrência enfileira, não cancela, mas guarda uma única execução
   pendente (uma terceira substitui a pendente mais velha); `max-parallel: 1` vale por
   execução e execuções não se sobrepõem. O OCR do IA pode esperar (decisão do dono): o
   derive só sai com o item terminado.

**Ainda suposto**: que o derive pedido ao fim de um item completo termina em tempo
razoável e libera os uploads seguintes; que a ração por item se esvazia quando o derive
do item termina; que o derive adiado é pedido numa execução posterior (depende de a
fila do item esvaziar, não de um agendamento).

## Adendo 2026-11-16 (2) — recusa por conteúdo, item cheio sem espera, tipos em paralelo

**Medido** (execução 43893315937): o IA recusou 4 PDFs válidos (`%PDF-1.4`, 250–500 KB;
lei-05995, 04977, 05942, 04971) com `Uploaded content is unacceptable. - pdf file looks
like spam`. A regex de recusa só reconhecia `error checking pdf file`, então cada recusa
virou `upload-failed`: o lote inteiro (25) falhou, o culpado voltou a `pending` (e
envenenou a execução seguinte) e dois flushes falhos seguidos abortaram a colheita de lei
(`ia-upload-failing`) com 275 sucessos. Cada captura custava ~25–32 s, dominadas pelo
upload, e os 7 tipos em série passavam de um dia, de modo que o grupo de concorrência
engolia os disparos do cron.

1. *Recusa por arquivo, duas mensagens.* `error checking pdf file` e `pdf file looks like
   spam` seguem o mesmo caminho: o arquivo culpado é identificado pela linha
   `error uploading {arquivo}`, vira `ia-rejected` (terminal), o restante é reenviado no
   mesmo flush (`--checksum` pula o que já subiu antes do culpado) e o `index.csv` sai
   nesse reenvio, com as linhas de todos que subiram. Recusa por arquivo **não** conta
   para `_MAX_CONSECUTIVE_FLUSH_FAILURES`. O motivo fica distinto: coluna `motivo` em
   `discovered_resources` (`spam` | `pdf-check`; migração `ADD COLUMN IF NOT EXISTS` para
   bancos em cache), `reason` `ia-rejected: spam` nos itens do resumo, e a CLI imprime
   `Recusados pelo IA ...: N (spam: M)`. A URL fica no banco para uma estratégia especial
   futura (ADR-0011); nada é apagado do IA e os bytes não são preservados por outra via
   (mesmo trade-off da regra 5).
2. *Ração por item não espera.* `bucket_tasks_queued exceeds rationed amount` num flush da
   colheita propaga na hora (sem os recuos de 60 s + 120 s + terceira tentativa, ~10 min):
   o item é adiado (regra 1 do adendo anterior), as capturas em buffer voltam a `pending`
   e a colheita segue com os outros itens. Só a colheita pede isso
   (`fail_fast_item_ration`); uploads de dataset, textos e reocr mantêm seus recuos. O
   limite da conta (`total_tasks_queued`) mantém os recuos curtos (60 s, 120 s) e, esgotados,
   encerra a colheita: é uma espera única, depois da qual a execução acaba.
3. *Tipos em paralelo, ritmo dividido.* `max-parallel: 3` (lei, lc, decreto primeiro).
   Cada tipo grava em itens próprios do IA, então não disputam a ração por item. A
   cortesia da ADR-0008 é preservada dividindo o ritmo: `HARVEST_HOST_INTERVAL_S` (padrão
   1,0 s) vale 3,0 s em cada job, ~1 req/s somado. `HARVEST_MAX_SECONDS` cai para 4500 s
   (75 min) e `timeout-minutes` para 120; pior caso do workflow: 7 jobs em 3 vagas = 3
   ondas x ~115 min = ~5,75 h, menos que os 6 h entre disparos. O que um tipo não colhe
   em 75 min fica `pending` para a execução seguinte (4 por dia). O grupo de concorrência
   continua enfileirando sem cancelar a execução em curso e guardando uma só pendente.


## Adendo 2026-11-17 — recusa geral, descoberta redundante, prazo do job

**Medido** (execução 44002214612, três tipos em paralelo; lei 160 capturas, lc 162,
decreto morto pelo `timeout-minutes` sem resumo):

- **Recusa com outra mensagem.** O IA respondeu `Uploaded content is unacceptable. -
  Syntax error detected in pdf data...` a `decreto-27996`. A regex só conhecia as duas
  mensagens anteriores, então o lote de 11 falhou inteiro (`upload-failed`), voltou a
  `pending` e o culpado nunca foi isolado.
- **Descoberta de decreto: 42 min** (02:20 a 03:02): índice anual 2 min (46 páginas,
  ~2,6 s cada com o ritmo de 1 s), `casacivil-index` 2 s, CDX 73 s, `DEC{num}.pdf`
  **36 min** (2000 HEAD a ~1,1 s cada, 19 achados) e a inserção linha a linha no DuckDB
  ~2,5 min.
- **Teto do job.** O orçamento de colheita contava do início da colheita. Com a
  descoberta de 42 min, o `HARVEST_MAX_SECONDS` de 4500 s terminava às 04:17 e o flush
  final às 04:20 bateu no `timeout-minutes: 120`. Lei estourou o orçamento em ~630 s no
  flush final (fim 03:51, parada da busca 03:39).
- **Banco de descoberta trocado.** O `restore-keys` `discover-db-decreto-` também casa
  com `discover-db-decreto-lei-`; o decreto restaurou o banco do decreto-lei.

**Regras novas**

1. *Recusa por conteúdo é geral.* Qualquer `Uploaded content is unacceptable` numa linha
   de arquivo é recusa daquele arquivo (terminal, `ia-rejected`, o restante do lote segue
   no mesmo flush). O motivo vai para `discovered_resources.motivo`: `spam` |
   `pdf-syntax` | `pdf-check` | `other: {texto do IA, até 120 caracteres}`. O resumo
   mantém `(spam: M)` e lista os outros motivos.
2. *Varredura redundante não roda quando o índice anual está completo.* A estratégia
   `sequential` com `skip_if_year_index_complete: true` (hoje só `DEC{num}.pdf` de
   decreto) é pulada quando o `casacivil-year-index` do mesmo tipo leu todos os anos
   (sem ano com falha, sem bloqueio do robots) **e** a descoberta é operacional (com
   `storage`). A reconciliação (`storage=None`) segue varrendo. O índice já lista o nome
   real de cada arquivo `DEC…` (ex.: `DEC31990 - RETIFICADO.pdf`), e o commit 89b4ccc
   tirou pelo mesmo motivo as varreduras de L, LC e D. Efeito estimado para decreto:
   ~2050 requisições e ~38 min por execução para ~50 requisições e ~6 min.
   **Risco aberto**: os 19 achados da varredura `DEC` não foram conferidos um a um contra
   o índice anual (o banco de produção não está acessível daqui). Se algum número não
   estiver no índice, ele deixa de ser descoberto; a regra é reversível retirando a flag.
   Não foi alterado o pacing da descoberta: `_HEAD_RATE_LIMIT_S` (0,5 s) e o índice anual
   (1 s) não leem `HARVEST_HOST_INTERVAL_S`, então três jobs na descoberta podem somar
   ~3 req/s no mesmo host. Decidir isso junto com o ADR-0008.
3. *Prazo do job, não só do teto.* O primeiro passo do job grava
   `JOB_DEADLINE_EPOCH` (agora + 120 min); a colheita recebe `--job-deadline` e para de
   buscar 20 min antes do fim (`HARVEST_TAIL_RESERVE_S`), o que cobre o flush final, o
   derive e o resumo. Com menos de 5 min úteis (`HARVEST_MIN_USEFUL_S`) a colheita nem
   começa e o resumo sai com `Colheita interrompida cedo: no-time-left`. `HARVEST_MAX_SECONDS`
   (4500 s) segue como teto. `harvest-single` não muda.
4. *O resumo sai mesmo se a colheita levantar.* `harvest_pending_resources` preenche
   o `stats` passado pela CLI no lugar; a CLI imprime `Colheita parcial` no `except`.
   Um flush que falha já não levanta (é capturado e vira `pending`), então o caso real
   de perda do resumo foi o `timeout-minutes`, que a regra 3 resolve.
5. *Banco de descoberta por tipo de verdade.* A chave de cache e o `restore-keys` de
   `discover-harvest.yml` terminam em `--` (`discover-db-{tipo}--`). Efeito de uma vez
   só: a primeira execução depois da mudança não acha o banco antigo e refaz a descoberta
   (os 404 marcados e os `ia-rejected` locais se perdem; `_already_preserved` impede
   reenvio ao IA). O workflow `discover-harvest-federal.yml` tem o mesmo padrão e não foi
   alterado.

**Medido, sem mudar código: o que cada captura custa** (logs sem tempo por captura; a
conta é estimativa). Lei: 160 capturas em 5130 s (~32 s cada), 12 flushes, 38 falhas
das quais 25 são um flush inteiro perdido (`upload-failed` sem culpado identificado,
depois de dois `ReadTimeout` do S3 e esperas de 60–150 s), ou seja ~25 capturas já
baixadas voltaram para `pending`. Lc: 162 em 4635 s (~29 s), 8 flushes, 10 falhas de
busca, 3 recusas `pdf-check`.

- O piso do limitador por host é ~6 s por captura, não 28: a busca e o Save Page Now
  dividem o mesmo horário de 3 s por requisição, então cada captura ocupa ~2 slots.
  A busca espera o slot; o Save Page Now não bloqueia a colheita.
- Uma busca que falha custa até 3 tentativas de 60 s com backoff (`fetch_bytes_detailed`):
  ~3 min por falha. As falhas de busca somam talvez 20–30% do tempo de cada tipo.
- O flush roda **na mesma thread** (`_RawBatcher.add` → `flush`): a colheita fica parada
  enquanto 25 PDFs, 25 `_meta.json` e o `index.csv` sobem (~51 PUTs). Não dá para
  separar o tempo de flush do de busca só com estes logs; a estimativa é de 20–40% do
  tempo total, com as esperas de retry do S3 como a parte visível.
- Conclusão: o que mais aumentaria a vazão é **subir em segundo plano** (uma thread de
  upload com fila limitada, enquanto a busca continua). Mudar o pacing não ajuda: a
  busca já espera o limitador só ~6 s em ~28. Um arquivo por captura aumenta os PUTs
  (ADR-0016 existe para reduzi-los). Antes de implementar, convém que a colheita
  registre o tempo de busca, de flush e de espera no resumo, para medir a fatia.

## Adendo 2026-11-17 (2) — ração da conta, prazo do flush, um PUT por captura, 2 em paralelo

**Medido** (logs de 2026-11-17): o IA passou a recusar com `Please reduce your request
rate. - accesskey_tasks_queued exceeds rationed amount`, uma ração por **chave de acesso**
(a conta inteira), distinta de `bucket_tasks_queued` (item) e `total_tasks_queued exceeds
global_limit`. A colheita de `lei` ficou ~30 min dentro de um upload (11:51 a 12:21) e foi
morta pelo `timeout-minutes: 120` sem resumo: o prazo do job só era checado entre
capturas, e o `ia upload` repetia por conta própria (`--retries 5 --sleep 30`, ~150 s por
arquivo, vezes 3 tentativas com recuos de 60/120 s). A de `decreto` encerrou com
`ia-throttled` após 71 capturas. O upload do reocr não esperou: a regex só conhecia duas
mensagens. Com 3 colheitas em paralelo, 2 PUTs por captura e os uploads de dataset dos
outros workflows, a ração da conta é o que se esgota.

1. *Uma classificação, por escopo.* `ia_utils.classify_ia_throttle`: `item` só se todo
   marcador `*_tasks_queued` for `bucket`; `account` para `accesskey_`, `total_` e qualquer
   `*_tasks_queued` desconhecido (lado conservador) e para um aviso de taxa sem marcador;
   `None` se não for taxa. `is_ia_queue_full` = há marcador `*_tasks_queued`. Substitui as
   três regex do publisher e `ia_throttle_scope` do scraper (que agora a chama).
2. *Na colheita.* Fila cheia, qualquer escopo, propaga na hora do `_run_ia_upload`
   (`fail_fast_queue`, sem os recuos de 60/120 s; antes só a ração por item). Escopo item:
   adia o item (igual). Escopo conta: a colheita para de buscar, as capturas em buffer
   voltam a `pending` **sem** contar como falha (`stats["requeued"]`, linha própria no
   resumo; antes entravam em "Falhas"), o derive final é pulado (os itens com arquivos
   novos saem em `derive-failed` com o comando manual) e a colheita termina com
   `aborted = ia-account-throttled` (antes `ia-throttled`). Código de saída: 0 se ao menos
   uma captura foi preservada; 1 se nenhuma (mesma convenção de antes para throttle sem
   captura, agora explícita). Um aviso de taxa sem marcador mantém os recuos curtos e,
   esgotados, também sai como conta. Uploads de dataset com espera (`IaQueueWait`) esperam
   qualquer escopo; passaram a esperar 30 min (`_DATASET_QUEUE_WAIT_MIN`): textos,
   cobertura, catálogo/completude e rótulos do teacher, além do reocr (45 min).
3. *O flush não sobrevive ao job.* O prazo (`--job-deadline` menos 3 min para o resumo e o
   cache) vira `timeout_s` do flush e do derive: o `subprocess.run` recebe o que resta, um
   recuo que não cabe não é esperado, e estourar dá `TimeoutExpired`. Resultado do lote:
   `flush-timeout` (capturas a `pending`, sem falha, `aborted = flush-timeout`, resumo
   impresso). Sem prazo nada muda. A CLI `ia` passou de `--retries 5 --sleep 30` para
   `--retries 2 --sleep 15`: o Python vê o throttle em cerca de um minuto.
4. *Um PUT por captura.* O lote não grava mais `_meta.json`; o `index.csv` ganhou as colunas
   `fetched_from`, `wayback_url`, `wayback_timestamp`, `wayback_blocked_robots`,
   `user_agent` (anexadas depois de `source`; linhas antigas leem vazio = desconhecido).
   De `2N+1` PUTs por flush para `N+1`. O resto do sidecar é redundante (`hash_pdf` =
   `sha256`, `fonte_url` = `source`, `data_captura` ~ `captured_at`, `ente`/`fonte`/`chave`
   = item + identidade) ou derivável (`ia_id_bundle`, `leizilla_meta_version`). O Save Page
   Now responde depois do flush: o que se sabe na captura (snapshot que a descoberta já
   tinha) vai ao índice; o snapshot devolvido depois segue só em `wayback_snapshot` do
   ledger (como antes no sidecar). Os uploaders unitários (`upload_raw`, `upload_raw_html`)
   mantêm o sidecar e também preenchem as colunas. Nada é apagado do IA; `reconcile` copia
   as colunas e o sidecar se existir; `refile` não depende dele.
   *Compatibilidade:* código novo lê índice antigo sem problema (`row.get`). Código **antigo**
   lendo índice novo ignora as colunas novas; se o código antigo **reescrever** o índice
   (merge/promoção), grava só as 8 colunas antigas e perde as de proveniência de todas as
   linhas (identidade, sha256 e source ficam).
5. *Em paralelo: 2.* `max-parallel: 2`, `HARVEST_HOST_INTERVAL_S: "2.0"` na descoberta e na
   colheita (~1 req/s). Pior caso: 7 tipos em 2 vagas = 4 jobs em sequência; job = 5 setup +
   10 descoberta + 45 colheita (`HARVEST_MAX_SECONDS` 2700) + 25 encerramento = 85 min
   (`timeout-minutes: 85`, prazo `85 * 60`); 4 x 85 = 340 min < 360 min entre disparos.
   Custo: a colheita por tipo cai de 75 para 45 min.

## Adendo 2026-11-18 — ordem da fila por rendição e a rendição no `index.csv`

**Medido** (catálogo publicado de 2026-11-18, `index.csv` dos itens de range e logs do
`discover-harvest`): leis e LCs com só o arquivo original listado estavam 49% preservadas;
só compilada, 30%; só revogado, 29%; "outra", 13% (exemplo: LC 68/1992, só `LC68 -
COMPILADA.pdf`). Não é filtro: arquivos com sufixo são enfileirados, buscados e aceitos pelo
IA (cerca de 120 já capturados, todos depois de 2026-11-15, com `%20` na `source`). O
original das décadas antigas tinha 87-100% por causa da varredura por nome canônico
(`L{n}.pdf`) anterior à descoberta pela lista anual; dentro da mesma década a diferença some
ou inverte. A fila não tinha preferência por rendição, e a colheita faz ~100-270 capturas
por execução.

1. *Prioridade por norma* (`storage.get_pending_resources`), depois do degrau de justiça
   (nunca tentado primeiro, #297) e antes do rodízio por bucket: 0 = a norma não lista
   original; 1 = a norma tem rendição compilada (o original que a acompanha também); 2 =
   outras rendições não originais; 3 = originais. O agregado por norma olha todos os status.
   O rodízio por bucket, o limite por host, o lote e o derive não mudam.
2. *Rendição gravada.* `discovered_resources.rendicao` (derivada do nome do arquivo, preenchida
   também em bancos antigos do cache) e a coluna `rendicao` do `index.csv`, que o lote passa
   a gravar para as não originais; vazia continua sendo o original, para a recaptura dos
   mesmos bytes seguir sendo no-op. `year_index_rendicao` passou para `leizilla.rendicao`:
   `L{n}_compressed.pdf` (257 dos 466 "outra") é o original recomprimido, e `- COMP.pdf` é
   compilada.
