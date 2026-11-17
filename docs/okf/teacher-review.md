---
type: Avaliacao
title: Teacher batch — modo review (professor como auditor do leitor)
description: O professor LLM audita a leitura do leitor por regras e devolve só os ajustes; contrato, canários de atenção, amostra de avaliação, pontuação offline e como rodar.
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

## Contrato

- Ids curtos por requisição (`N01`..); o manifesto mapeia para `texto_id` e sha256.
- Id faltando, repetido, linha inexistente, evidência que não está na linha, operação
  incompatível com as etiquetas mostradas, ou `ok` com ajuste: o resultado **da norma**
  é inválido (`failures.jsonl`), nunca aceito. Silêncio não é aprovação.
- Empacotamento por tamanho (24 000 caracteres de texto, no máximo 8 normas, semente
  `--shuffle-seed`); norma maior que o orçamento vai sozinha; maior que `--max-chars`
  (20 000) é partida com a lógica do modo `label`, uma requisição por parte, com nota
  do último artigo próprio e de bloco citado aberto.
- Canários: cópias de normas que o leitor fecha, com **um erro plantado nas etiquetas**
  (nunca no texto): `drop_last`, `drop_middle`, `renumber`, `flip_quoted`, `spurious`.
  No máximo um por requisição. `collect` pontua `caught` / `partly` / `missed` /
  `invalid`; um canário `missed` ou `invalid` marca os `ok` das outras normas da
  requisição como `unverified`.
- `collect` grava `reviews/` (um JSON por norma), `summary.json`, `failures.jsonl` e
  `review-adjustments.json` (ajustes candidatos de normas reais, **não aplicados**);
  com `upload_ia` publica em `leizilla-teacher-labels-ro-review-<revisão>`.
- O conjunto `main` é recusado no modo review (o padrão é `review`).

## Amostra de avaliação

`docs/okf/review-samples/eval-2026-11.txt` (200 `texto_id`, semente 20261117) e
`eval-2026-11-canaries.txt` (100 fontes de canário). Saem do conjunto `main`
rotulado, só normas cujo texto na camada publicada tem o mesmo sha256 do rótulo. Os
cabeçalhos dos arquivos dizem a composição. Não ajuste o leitor olhando para ela.

## Rodar

Workflow `teacher-batch.yml`, `mode=review`. Avaliação: `step=plan` (sem custo),
depois `step=submit` com `ids_file=eval-2026-11`, `canary_ids_file=eval-2026-11-canaries`,
`shuffle_seed=20261117`, `model=claude-haiku-5-5`, `effort=medium` e um `max_usd`; depois
`step=collect` com `manifest_run_id`. Pontuação offline:

```bash
uv run scripts/score_review.py --reviews COLLECT_DIR --labels LABELS_DIR \
    --texts TEXTS_DIR --textos-parquet textos.parquet --out OUT_DIR
```

Mede: (i) nas normas em que o leitor discorda do professor, se o revisor disse `ajuste`
e se leitor + ajustes igualam o professor; (ii) taxa de falso alarme nas normas em que
leitor e professor concordam (e a lista delas: algumas podem ser erro real dos dois);
(iii) recall de canários por tipo; (iv) custo por norma contra US$ 0,00063 do modo label.
