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

