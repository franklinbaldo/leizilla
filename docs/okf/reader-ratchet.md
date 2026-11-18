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

## Gate por nível (art par inc ali item)

O gate acima só cobre o nível `art`, contra o professor do modo `label`. Abaixo do artigo
o leitor tem defeitos conhecidos e a referência é o **documento marcado do modo `mark`**
([teacher-mark.md](teacher-mark.md)) de 3161 normas: as 300 de
`review-samples/mark-reference-2026-11.txt` mais as duas partes (A: coleta
`44228356004`, B: coleta `44227337585`) da camada de texto inteira. A referência pode ter erros: a catraca só
trava o que **já concorda**; o que discorda fica de fora até ser resolvido, e uma regra
que discorda da referência e está certa vira uma errata, não uma rejeição.

`scripts/reader_ratchet_levels.py` (job `levels` de `reader-ratchet.yml`, ~10 s depois de
ter o `textos.parquet`):

```bash
# textos.parquet = a revisão FIXADA em reference.json (source.textos_revision)
curl -sSL -o textos.parquet \
  https://archive.org/download/leizilla-textos-ro-v0-20261118t003626z/textos.parquet
uv run scripts/reader_ratchet_levels.py check --textos textos.parquet [--splits]
uv run scripts/reader_ratchet_levels.py update --textos textos.parquet [--force --reason "texto"]
# raro: acrescenta normas de uma ou mais coletas mark à referência
uv run scripts/reader_ratchet_levels.py build-reference --run COLLECT_DIR [--run ...] \
    --textos textos.parquet --textos-revision ITEM_ID
# sem --textos: só as 300 normas com texto no repositório (caminho rápido, testes)
uv run scripts/reader_ratchet_levels.py check
```

- **Textos fora do repositório.** `reference.json` guarda só as linhas dos dispositivos e o
  `text_sha256` de cada norma. O texto vem do `textos.parquet` da revisão fixada no
  cabeçalho (`source.textos_revision`; o ponteiro `-latest` anda, a revisão não): o
  `check` recalcula o sha256 de cada `texto` e casa por ele. Norma sem texto ou com sha256
  diferente é **não comparável**: aparece na contagem e **não** falha o gate (as unidades
  dela não contam como perdidas); mais de 2% da referência não comparável
  (`--max-not-comparable`) falha. Sem `--textos`, só as 300 normas de `texts.json.gz` são
  checadas e a contagem não é imposta. `update` exige `--textos` e recusa se houver norma
  não comparável (senão ela sairia da linha de base), salvo `--force --reason`.
- **Cache no CI.** O job baixa a revisão fixada uma vez e a guarda com `actions/cache`
  pela chave `reader-ratchet-textos-<revisão>`.
- **Divisão de teste.** `--splits` imprime também as tabelas dos 80% `train` e dos 20%
  `test` (`split_of`: sha256 de `semente:texto_id`, semente `SPLIT_SEED`). O gate e a linha
  de base cobrem 100%; o torneio de regras só projeta e julga regras no `train` e usa o
  `test` para medir fora da amostra.

- **Referência** (`docs/okf/mark-reference/`, `reference.json` 1,7 MB + `texts.json.gz`
  317 KB): `reference.json` (por norma, as linhas `[tipo, número, sufixo, citado, offset]` do documento marcado, a variante usada
  --- a reparada quando o conversor fez uma ---, as suspeitas que sobram e o sha256 do
  texto) e `texts.json.gz` (`sha256 -> texto` das 300 normas originais, do manifesto da coleta
  `44200532103`; legislação pública; caminho rápido offline dos testes). Os documentos XML completos estão só no artifact
  `teacher-batch-labels` dessa coleta (expira em 90 dias); as linhas bastam para o gate.
- **Unidade** = (norma, nível). `agree` quando os dispositivos do leitor no nível (próprios e
  citados) pareiam um a um com os da referência, com mesmo número, sufixo e estado
  (`compare_mark_reader.pair_devices`). Normas com suspeita e níveis que a referência não
  tem na norma ficam **fora** do gate.
- **Regra**: FAIL se uma unidade da linha de base (`docs/okf/mark-ratchet-baseline.json`,
  lista `agree` por nível) deixou de ser `agree` (ou a norma não é mais comparável: sha256
  do texto diferente) ou se há errata stale. PASS imprime a tabela (unidades e dispositivos
  `agree`/`misses`/`extra`/`number`/`status`/`kind`) e as unidades que entraram.
  `update` recusa quando o `check` falharia, salvo `--force --reason`; errata stale
  nunca é forçável.
- **Errata da referência** (`docs/okf/mark-reference-errata.json`, mesmo molde de
  `teacher-label-errata.json`): `{"schema_version": 1, "corrections": [...]}`; cada uma tem
  `norm` (`texto_id`), `text_sha256`, `op` (`add_device`: `kind`, `n`, `sufixo`, `quoted`;
  `remove_device`; `set_device`: `set` com `n`/`sufixo`/`quoted`; as duas últimas acham o
  dispositivo por `kind` + `line` (+ `n` se houver mais de um)), `line` (1-based),
  `evidence` (trecho literal da linha; no `add_device` é o marcador e dá o offset),
  `reason`, `verified_by`, `date`. Vale só com o sha256 e a evidência batendo; senão é
  stale e o `check` falha. Só depois de ler o texto e ver que a referência errou; nunca
  para fazer uma regra passar.

### Torneio de regras no subnível

Cada mudança candidata ao leitor é julgada **sozinha**: passa o gate de artigo (2086
normas), passa o gate por nível, ganha pelo menos uma unidade (norma, nível) para `agree`,
não perde nenhuma e, nos dispositivos que passa a ler, acerta pelo menos 90% contra a
referência (um dispositivo que só troca de número conta contra o que lia antes). Uma regra
que falha é tentada uma vez com guarda mais estreita. Uma rodada é um lote de candidatas; o
torneio para quando duas rodadas seguidas não promovem nada. Quando uma regra acerta e a
referência erra, a saída é uma errata da referência, não a rejeição da regra.

**Divisão de teste.** Com a referência em escala total (3161 normas), 20% das normas
(`split_of`, semente `SPLIT_SEED`: 636 normas) são o conjunto de **teste**: as candidatas
são projetadas e julgadas só nos outros 80% (`train`; as listas de defeitos, os exemplos e
a leitura "a olho" do dispositivo novo vêm só dele). O gate e a linha de base cobrem 100%,
então uma candidata que perde uma unidade do teste é rejeitada sem ler o motivo. O teste
mede o resultado: `check --splits` imprime as três tabelas.

Rodadas de 2026-11-18 em escala total (rodada anterior, nas 300 normas: 12 regras e 13
errata): **16 regras promovidas em 5 rodadas** (8, 3, 2, 1 e 2) e 5 errata novas.
Resultado em unidades (norma, nível) que concordam, antes -> depois: art 2961 -> 2995 de
3113, par 1509 -> 1534 de 1676, inc 721 -> 747 de 970, ali 228 -> 232 de 312, item 13 -> 13
de 58; no teste: art 598 -> 602, par 296 -> 298, inc 151 -> 153, ali 48 -> 49, item 4 -> 4.
Rejeitadas (e porquê): sufixo colado à ordinal para toda letra (perde unidades onde o
artigo "Art. 1°-C" já é próprio), "m" sozinho como III (perde uma unidade do teste),
reinício de inciso em bloco citado (precisão 3/9), troca do artigo duplicado que fecha a
norma (0 unidades), `ao/aos` como citação de parágrafo (0), `T = ...` como fórmula (0),
5/6 como sinal ordinal em artigo (perde unidades), troca por aspas de fechamento (falha o
gate de artigo). O que não cede a regras (ver o relatório): tabelas e anexos lidos como
incisos, blocos citados sem aspas nem `(NR)`, `Art. T` de primeiro artigo citado (1 ou 7:
50% dos casos), "Art. 22" por 2º em bloco citado (19% dos casos), cópias repetidas do mesmo
texto, marcadores perdidos que o modelo infere.

Rodada 6 (continuação, mesma escala): 4 regras promovidas (`s lo -` com `s` minúsculo como
`§`: treino +9 / teste +6, 18 de 18 dispositivos novos certos; `Parágrafo 1º -` por extenso
no início de linha: +2 / +1; sinal de parágrafo seguido de `.` ou `:` e glifo duplo `S$`:
+2 / +1; algarismo romano depois de palavra capitalizada no meio da linha, `Assessor IV -
CDS-04`, não é inciso: +1 / 0) e 16 errata `add_device` (dispositivos que o conversor
omitiu e o leitor lê, com a evidência citada: 6 de lista própria, 10 de bloco citado).
Rejeitadas: numeral romano sozinho na linha antes de prosa minúscula (precisão 2/3), `a)`
sozinho como detrito (perde 5 unidades), lista de itens que começa depois de 1 (precisão
0,58, 0 unidades), glifo parecido e número na mesma linha (0 unidades, perde 1).

Rodada 7: 4 regras promovidas. Numeral romano puro sem o traço antes de palavra
capitalizada (`III Cabo da Polícia`), só dentro de uma cadeia: treino +10 / teste +2, 11 de 11
dispositivos. Bloco citado recomeça a cadeia depois de linha só de pontos (`I`, `.....`, `VII`,
`.....`, `XXIII`): +6 / 0. Parágrafo e inciso citados podem pular números (`§ 1º`, `§ 6º`,
`§ 7º`) quando o candidato é um `§` ou romano puro que abre a linha, com a penalidade de salto
limitada a 0,5 (`best_chain(gap_cap, capped)`): +8 / +2 em incisos e +9 / +2 em parágrafos, 14
de 14 em parágrafos e 30 de 34 em incisos (dois dos quatro erros são lacunas da referência).
`Paraâgrafo único` com vogal dobrada: +1 / 0. Rejeitadas: `t` minúsculo como traço de `I`
(precisão 0,8), romano seguido de título em maiúsculas não é inciso (perde 5 unidades e uma do
teste), mesma regra de salto para alíneas (3 de 7 errados), elisão entre colchetes
(`[...]`, precisão 0,53), `Paraágrato` (0,875).

**Erros sistemáticos da referência.** Nenhuma classe de erro do conversor apareceu em
número que pedisse reconstruir a referência: as 18 errata (13 + 5) são pontuais
(13 `add_device`: dispositivo que o modelo deixou de marcar; 5 `set_device`: status
citado/próprio ou sufixo de parágrafo). As suspeitas do conversor (`suspect_*`, 38 normas) continuam
fora do gate.

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
