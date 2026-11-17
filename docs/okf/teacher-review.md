---
type: Avaliacao
title: Teacher batch — modo review (professor como auditor do leitor)
description: O professor LLM audita a leitura do leitor por regras e devolve só os ajustes; contrato (v2), orçamento de resposta, reenvio de requisições truncadas, canários de atenção, amostra de avaliação, pontuação offline e como rodar.
tags: [avaliacao, leitor, teacher, review, canarios]
timestamp: 2026-11-17T00:00:00Z
---

No modo `label` (padrão, inalterado) o professor rotula cada linha estrutural de cada
norma; ~75% do custo é saída. No modo `review` o leitor (`read_hierarchy`) lê primeiro e
o modelo recebe várias normas com a leitura embutida em etiquetas (`[art 5]`,
`[art 5 Q]`, `[§ 2]`, `[inc III]`, `[ali a]`, `[item 1]`) e devolve **uma entrada por
norma**: `ok` ou `ajuste` com operações (`add_own_article`, `remove_article`,
`set_number`, `set_quoted`, `add_node`, `remove_node`), cada uma com linha, evidência
(a linha, até 80 caracteres) e motivo. Código: `src/leizilla/teacher_review.py`.

Prompt `teacher-review-v2` (`REVIEW_PROMPT_VERSION`); a v1 é a da primeira execução
(2026-11, ver "Primeira execução" abaixo).

## Contrato

- Ids curtos por requisição (`N01`..); o manifesto mapeia para `texto_id` e sha256.
  O cabeçalho de cada norma mostra só o identificador, tipo/número e a contagem de
  artigos próprios do leitor: não mostra `closes` nem o último artigo (com um erro
  plantado eles denunciariam o canário).
- Linha sem etiqueta que abre com marcador de artigo (o mesmo candidato solto do
  leitor, `_ART_WILD`) vem marcada `[?art]`: o leitor viu e não tomou. Vale para
  canários e normas reais igualmente: um canário que apagou uma etiqueta aparece
  exatamente como um artigo perdido de verdade.
- **Estrutura inválida** invalida a norma inteira (`failures.jsonl`), nunca aceita:
  id faltando, repetido ou inventado; entrada malformada; `ok` com ajuste; `ajuste`
  sem ajuste; operação desconhecida; linha inexistente ou não listada; operação
  repetida; conflito entre `remove_article` e outro ajuste na mesma linha.
  Silêncio não é aprovação.
- **Ajuste fora do encaixe é descartado, não invalida**: evidência que não está na
  linha, operação que não cabe nas etiquetas mostradas (inclusive `add_node` em nível
  já presente), nenhuma mudança (`set_number` igual à etiqueta) ou número que não lê
  como numeral. Cada descarte vai para `dropped` no registro da norma, com o motivo.
  Uma norma cujo `ajuste` ficou sem nenhum ajuste válido vira `ok` com
  `downgraded: true` e `dropped` não vazio.
- Evidência lenient (`_evidence_matches`): espaços em sequência, aspas e travessões
  normalizados; prefixo de etiqueta copiado (`[art 4 Q] …`) descartado; evidência que
  continua para a linha seguinte é aceita quando a linha inteira é o seu início.
- **Truncado**: a requisição que terminou em `max_tokens` (ou sem bloco de texto) não
  é inválida. Cada norma dela recebe `verdict: truncated` e entra em
  `truncated_requests` do `manifest.json` gravado pelo `collect`.
- **Parte faltando**: norma partida (`> --max-chars`) com partes válidas e partes
  truncadas ou inválidas vira `verdict: partial` (ou `ajuste`, se as partes válidas
  trazem ajuste), com `partial: true` e `missing_parts`. Só é `ok` quando todas as
  partes são `ok`. `score_review.py` a conta em balde próprio.
- Empacotamento por tamanho (24 000 caracteres de texto, no máximo 8 normas, semente
  `--shuffle-seed`); norma maior que o orçamento vai sozinha; maior que `--max-chars`
  (20 000) é partida com a lógica do modo `label`, uma requisição por parte, com nota
  do último artigo próprio e de bloco citado aberto.
- Orçamento de resposta (`review_max_tokens`): 8 192 + (2 048 de pensamento + 465 de
  ajuste) por norma da requisição, no máximo 16 000. Medição de uma execução (240
  requisições, `claude-haiku-5-5`, effort medium): 2 070 tokens de saída por
  requisição, ~95% pensamento; o teto antigo (3 072 + 465 por norma) truncou 61 de
  240. O teto de custo (`ceiling`) é a soma dos `max_tokens`, um limite superior
  honesto; a estimativa usa 2 070 por requisição mais o esperado por norma, limitado a
  cada `max_tokens`. A estimativa mede só effort medium; para os outros, usa o maior
  entre 2 070 e a tabela de pensamento. O `ModelSpec` não tem campo de limite de saída;
  16 000 fica bem abaixo do que o modelo aceita, mas isso não é verificado aqui.
- Canários: cópias de normas que o leitor fecha, com **um erro plantado nas etiquetas**
  (nunca no texto): `drop_last`, `drop_middle`, `renumber`, `flip_quoted`, `spurious`.
  No máximo um por requisição. `collect` pontua `caught` / `partly` / `missed` /
  `invalid` / `truncated`; um canário `missed`, `invalid` ou `truncated` marca os `ok`
  das outras normas da requisição como `unverified`. O recall sai em dois números:
  `canary_recall_chain_intact` (a sequência de artigos próprios do canário continua sem
  lacuna, então a lacuna não se vê lendo) e `canary_recall_chain_broken`.
- `collect` grava `reviews/` (um JSON por norma, com `verdict`, `adjustments`,
  `dropped`, `downgraded`, `partial`, `missing_parts`), `summary.json`, `failures.jsonl`,
  `manifest.json` (com `truncated_requests`) e `review-adjustments.json` (ajustes
  candidatos de normas reais, **não aplicados**); com `upload_ia` publica em
  `leizilla-teacher-labels-ro-review-<revisão>`.
- O conjunto `main` é recusado no modo review (o padrão é `review`).

## Reenvio de requisições truncadas

`submit --mode review --retry-truncated PATH` (no workflow: `manifest_run_id` do
submit, com a execução de um `collect` anterior) reenvia **só** as requisições
truncadas do `manifest.json` desse collect, uma norma (ou parte) por requisição, com
o orçamento de resposta acima. Exige **os mesmos insumos** do submit original (mode,
select, ids_file, canary_ids_file, shuffle_seed, label_set): cada slot é casado por
`(entry, parte)` e a sha256 do texto é conferida; se algo mudou, o reenvio é recusado.
O manifesto novo carrega o original em `base`; `collect` funde os dois: as
requisições truncadas do original são substituídas pelas do reenvio, e as demais
seguem como estão. Um reenvio pode ser reenviado (o `retry_depth` sobe). Custo: o
mesmo guarda de custo do submit (`max_usd`, `guard`), sobre o reenvio.

## Amostra de avaliação

`docs/okf/review-samples/eval-2026-11.txt` (200 `texto_id`, semente 20261117) e
`eval-2026-11-canaries.txt` (100 fontes de canário). Saem do conjunto `main`
rotulado, só normas cujo texto na camada publicada tem o mesmo sha256 do rótulo. Os
cabeçalhos dos arquivos dizem a composição. Não ajuste o leitor olhando para ela.

## Primeira execução (v1, 2026-11) e reavaliação offline

Com o prompt v1 e o teto antigo: 61 de 240 requisições terminaram em `max_tokens`
(55 sem texto); 55 de 200 normas reais e 18 de 100 canários ficaram sem resposta
válida. Nas respostas completas, 98,7% dos slots validaram e os 82 canários válidos
foram todos pegos. Quatro respostas falharam por outros motivos (evidência que
atravessa a linha, evidência com a etiqueta, `add_node` em nível já marcado, `set_number`
sem mudança).

Reavaliação das mesmas respostas com o validador v2 (`collect` sobre o manifesto e os
resultados brutos da execução, sem API): as 4 falhas viram 2 válidas (evidência lenient)
e 2 descartadas (1 com `downgraded`); as 61 requisições truncadas viram `truncated`
(60 normas, 97 partes); `invalid` cai de 56 para 0; canários: 82 pegos, 18 truncados,
0 inválidos. Partes: 6 normas parciais.

## Rodar

Workflow `teacher-batch.yml`, `mode=review`. Avaliação: `step=plan` (sem custo),
depois `step=submit` com `ids_file=eval-2026-11`, `canary_ids_file=eval-2026-11-canaries`,
`shuffle_seed=20261117`, `model=claude-haiku-5-5`, `effort=medium` e um `max_usd`; depois
`step=collect` com `manifest_run_id`. Pontuação offline:

```bash
uv run scripts/score_review.py --reviews COLLECT_DIR --labels LABELS_DIR \
    --texts TEXTS_DIR --textos-parquet textos.parquet --out OUT_DIR
```

Se houver truncadas: `step=submit` de novo com os mesmos insumos e
`manifest_run_id` = a execução do `collect`; depois `step=collect` com o id dessa nova
execução de submit. Plano local, sem API:

```bash
uv run python -m leizilla.teacher_batch plan --mode review --label-set review \
    --text-source textos --textos textos.parquet \
    --ids-file docs/okf/review-samples/eval-2026-11.txt \
    --canary-ids-file docs/okf/review-samples/eval-2026-11-canaries.txt \
    --count-sample 0 --out plan.json
```

Mede: (i) nas normas em que o leitor discorda do professor, se o revisor disse `ajuste`
e se leitor + ajustes igualam o professor; (ii) taxa de falso alarme nas normas em que
leitor e professor concordam (e a lista delas: algumas podem ser erro real dos dois);
(iii) recall de canários por tipo e separado por cadeia intacta ou quebrada; (iv) custo
por norma contra US$ 0,00063 do modo label. Normas `truncated` e `partial` ficam em
baldes próprios e não contam como concordância nem como correção.
