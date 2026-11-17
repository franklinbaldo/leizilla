---
type: Avaliacao
title: Reader ratchet — leitor por regras vs. rótulos do professor
description: Gate que impede regressão do leitor de artigos (article_sequence, hierarchy_sequence) medido contra os rótulos do professor LLM; linha de base, fonte dos dados e procedimento de atualização.
tags: [avaliacao, leitor, teacher, ratchet, ci]
timestamp: 2026-11-17T00:00:00Z
---

O placar `scripts/compare_teacher_reader.py` compara `read_hierarchy` com os rótulos
do professor e classifica cada norma em cinco grupos. O gate
`scripts/reader_ratchet.py` transforma a convenção "agree_closed não encolhe,
disagree_closed não cresce" em uma verificação registrada.

## Regras

- **FAIL** se uma norma de `agree_closed` na linha de base deixou de ser
  `agree_closed` (ou deixou de ser comparada: texto ausente ou sha256 divergente).
  O gate imprime cada id e o grupo atual.
- **FAIL** se uma norma está hoje em `disagree_closed` e não estava na linha de base.
- Caso contrário **PASS**, com a tabela antes → depois por grupo e as normas que
  entraram em `agree_closed`.

Identificador de norma: `item/uuid5`. O `item` sozinho é compartilhado por muitas
normas (faixas de 1000), então o `uuid5` completa a chave.

## Linha de base

`docs/okf/reader-ratchet-baseline.json`: commit do leitor, data, identificador
dos rótulos (batch `msgbatch_01VYBeV9AWA7A2QeNaYfJZAC`, 2086 normas), as cinco
contagens, as listas ordenadas de `agree_closed` e `disagree_closed`, e o
histórico de atualizações (data, commit, forçado ou não, motivo, normas que
entraram ou saíram dos dois grupos desde a linha de base anterior).

Linha de base inicial (2026-11-17): `agree_closed` 1782, `agree_open` 95,
`disagree_closed` 1, `disagree_open` 201, `teacher_inconsistent` 7.

## Uso

```bash
# verificação (sem rede se o cache de textos estiver completo)
uv run scripts/reader_ratchet.py check --labels LABELS_DIR --texts TEXTS_DIR \
    [--textos-parquet PATH]

# reescrever a linha de base depois de uma melhoria aceita
uv run scripts/reader_ratchet.py update --labels LABELS_DIR --texts TEXTS_DIR

# aceitar uma regressão conscientemente (motivo obrigatório, fica no histórico)
uv run scripts/reader_ratchet.py update --labels ... --texts ... \
    --force --reason "texto do motivo"
```

`LABELS_DIR` é a raiz de saída do `teacher-batch collect` (contém `labels/` e
`summary.json`). As errata são aplicadas por padrão (`--errata PATH` troca o arquivo;
`--no-errata` desliga). `update` recusa quando o `check` falharia, a não ser com
`--force --reason`. Com `GITHUB_STEP_SUMMARY` definido, o resumo em Markdown vai
para o resumo do job.

## Onde o CI obtém os dados

Workflow `.github/workflows/reader-ratchet.yml`, disparado em PR que muda
`article_sequence.py`, `hierarchy_sequence.py`, `compare_teacher_reader.py`,
`reader_ratchet.py` ou a linha de base, e manualmente.

- **Rótulos**: artifact `teacher-batch-labels` da execução `43937274430`
  (`actions/download-artifact` com `run-id`). **Fonte temporária**: o artifact
  expira em **2027-02-14T19:14:38Z** (retenção de 90 dias).
- **Textos**: `textos.parquet` publicado (`leizilla-textos-ro-v0-latest`, 2065 das
  2086 normas por sha256); as 21 restantes vão ao IA com pausa de 1 s.
- **Cache dos textos**: `actions/cache` com chave que inclui o identificador dos
  rótulos. O `_missing.txt` é apagado antes de cada execução, para que uma falha
  de rede não fique gravada.

### O que `upload_ia` do `teacher-batch collect` publica

Com `upload_ia=true`, `upload_to_ia` (`src/leizilla/teacher_batch.py`) envia **um
item por execução**, com identificador `leizilla-teacher-labels-ro-<timestamp>`
(imutável; o timestamp é gerado na hora). Arquivos: `labels.tar.gz` (diretório
`labels/`, um JSONL por norma), `failures.jsonl`, `summary.json` e
`manifest.json`. Para este lote **nenhum item existe**: a busca no IA por
`leizilla-teacher-labels*` retorna zero, e o artifact de `43937274430` não tem
`ia_upload.json` (o upload não foi executado). Como o nome inclui o timestamp, o
workflow não consegue localizar um item sem um identificador fixado. O formato
serviria para o gate depois que um `collect` com `upload_ia=true` for executado e o
identificador for gravado na linha de base e no workflow.

## Errata dos rótulos do professor

`docs/okf/teacher-label-errata.json` registra correções aos rótulos do professor
LLM, para os casos em que a leitura do texto mostra que o professor errou e o leitor
acertou. Sem elas, o gate fica preso num acordo errado: leitor e professor concordam
numa resposta errada, ou o leitor passa a discordar de um rótulo incompleto.

Formato: `{"schema_version": 1, "corrections": [...]}`. Cada correção tem:

- `norm`: id `item/uuid5`, como aparece no placar e na linha de base;
- `text_sha256`: sha256 do texto que o professor viu. A correção vale só para esse
  texto;
- `op`: `add_own_article` (`line`, `number`, `suffix` opcional), `set_number`
  (mesmos campos, troca o número do artigo que já está na linha) ou `set_quoted`
  (`line`, `quoted`). `remove_label` está reservado; op desconhecida é erro;
- `line`: linha 1-based de `text.split("\n")`, a mesma convenção do placar;
- `evidence`: a linha crua do texto, citada textualmente (basta conter a evidência);
- `reason`: uma frase;
- `verified_by`: `leitura do texto`;
- `date`: `AAAA-MM-DD`.

Aplicação (`compare_teacher_reader.py`, usada também pelo gate):

- A correção é aplicada aos rótulos da norma antes da comparação **somente** se o
  `text_sha256` bate com o texto e a `evidence` está na `line`.
- Caso contrário a correção é **stale**: não é aplicada, é contada e listada (`id`,
  `op`, `line`, motivo). O `check` falha com exit 1 e `update` recusa, **mesmo com
  `--force`**. A entrada precisa ser corrigida ou removida, não ignorada.
- `--no-errata` compara os rótulos como estão, sem correções.
- O resumo (`summary.json`, chave `errata`, e `summary.md`) diz quantas foram
  aplicadas, em quais normas, e quantas estão stale. A linha de base grava
  `labels.errata_applied`, `labels.errata_sha256` e o mesmo número no histórico.

Quando acrescentar uma correção:

- Só depois de ler o texto e confirmar que o professor errou. A linha de evidência
  é citada no próprio registro.
- Nunca para fazer uma regra passar. Se o leitor erra, a correção não é o remédio:
  a norma continua no gate, e o leitor é que se corrige.
- Uma entrada por erro observado, com motivo.

O errata é um **registro de erros do professor**. Cada padrão recorrente deve voltar
ao prompt do professor (`prompt_version` `teacher-labels-v1`): um exemplo ou uma
regra nova, com nova versão de prompt num novo lote de rótulos. Os rótulos antigos
não são reescritos.

## Conjunto de avaliação (held-out)

Um conjunto de rótulos separado, com `label_set` diferente de `main`
(ex. `holdout-2026-11`), existe para **medir** o leitor. Regras:

- As regras do leitor **nunca** são ajustadas olhando para esse conjunto. Se o
  leitor erra nele, a correção é uma regra geral, validada no conjunto `main`, e só
  depois se mede de novo.
- O gate e a linha de base continuam usando somente o conjunto `main`. O conjunto
  held-out não entra no `check` nem no `update`.
- Para medir, compare com o diretório de rótulos do conjunto e grave numa pasta de
  saída própria, para não misturar com o placar do `main`:

  ```bash
  uv run scripts/compare_teacher_reader.py --labels <diretório held-out> \
      --texts <cache de textos> --out <pasta de saída própria> \
      --textos-parquet <textos.parquet>
  ```

- Os rótulos do held-out excluem as normas já rotuladas no `main` (`--exclude-labelled`),
  então os dois conjuntos não se sobrepõem. O nome do conjunto fica no manifesto,
  no `summary.json`, em cada cabeçalho de norma e no identificador do item do IA.

## Limites

- Uma norma que deixa de ser comparada conta como saída de `agree_closed`. É a
  escolha conservadora: se o texto some, o gate não pode dizer que a norma continua
  correta.
- O gate mede concordância com um professor LLM, não com um ouro humano. Os dois
  grupos de "disagree" são a fila de revisão, não prova de erro do leitor.
