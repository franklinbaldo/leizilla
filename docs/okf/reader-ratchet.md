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
  dispositivo por `kind` + `line` (+ `n` se houver mais de um); `clear_suspect`: `flags`, sem
  `kind`, fecha as suspeitas do conversor da norma, ver "Suspeitas fechadas"), `line` (1-based),
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

Rodada 7: 5 regras promovidas. Numeral romano puro sem o traço antes de palavra
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

Rodada 8: 1 regra promovida e 4 errata. Um artigo com sufixo (`Art.49-A`) não é lido como
`N-A` antes do `Art. N` simples que vem depois (`best_chain(suffix_repeats)`): treino +4
(uma norma, quatro níveis), teste 0, 12 de 12 dispositivos; o professor do modo `label` lê
`4A` ali, então 17 dispositivos dessa norma deixam de casar com ele. Rejeitadas: item
isolado em bloco citado (precisão 0,5), salto de parágrafo também para o glifo `$` (0,33),
item seguido de dígito com sinal ordinal (`1) 1º Ten`, 0 unidades, 5 de 5 certos).

Rodada 9: 1 regra promovida e 1 errata. Dois ou três marcadores ilegíveis seguidos entre
dois vizinhos da cadeia preenchem os números que faltam (`XQ -`, `ym -` entre XI e XIV), a
generalização de `_fill_single_gaps`: treino +1, teste 0, 10 de 10 dispositivos. Rejeitadas:
`II -` repetido lido como III só se nenhum `III -` vem depois (perde 4 unidades do treino e 2
do teste), `e os artigos` como citação à direita do `§` (0 unidades).

Rodada 10: 2 regras promovidas. `1)` ou `|)` abrindo a linha é a alínea `l` quando um `k)`
vem antes (700 caracteres): treino +2, teste 0, 2 de 2 (sem a guarda do `k)`, precisão 0,71).
O artigo de fecho com ordinal impresso claro mantém o número quando a cadeia está curta
(`Art. 6º Esta Lei entra em vigor` depois de `Art. 2º`): treino +1, teste 0; a norma
`lei-01296` deixa de fechar, correto, porque os artigos 3 a 5 não estão no texto.

Rodada 11: 1 regra promovida e 1 errata. `£)` é a alínea `f` (glifo de OCR): treino +2, teste
+2, 5 de 5 no treino (3 de 4 no teste). Rejeitadas: `9)` como alínea `g` (0 unidades), "seguinte
parágrafo/inciso/alínea:" como sinal de bloco citado (sem efeito). Errata `set_device` em
`lei-06520`: `Art. 4ºA concessão` é o artigo 4º e a frase "A concessão", não o sufixo `A`.

Rodada 12: 1 regra promovida e 1 errata. Alíneas de bloco citado podem pular até duas letras
(`a)`, `d)`, `e)`): treino +2, teste 0, 3 de 3 (sem limite, 3 de 7 errados). Rejeitadas: preencher
um marcador isolado no fim da cadeia também para alíneas e parágrafos (0,67 / 0 unidades), `.-`
como separador de inciso (0 unidades), item seguido de título em maiúsculas (0 unidades, perde
3 dispositivos certos), `(` antes de `Art.` como citação (reprova o gate de artigo). Errata
`set_device` em `decreto-10227`: o terceiro marcador (`II —` depois de `H —`) é III pela cadeia.

Rodada 13: 2 regras promovidas, as duas de glifo de numeral romano: `Q` vale `II` (`XQ -`,
`VQ -`; treino +1, teste 0, 2 de 2) e `ü`, `Ü`, `Í`, `Ì`, `Î` valem `II` ou `I` (`ü - manter`;
+1 / 0, 2 de 2). Rejeitadas: `E` como `I` (precisão 0,5), alínea `a)` isolada sem prosa em 120
caracteres (0 unidades).

Rodada 14: 1 regra promovida: a letra de alínea impressa duas vezes no começo da linha
(`Cc) Quadro de Oficiais`): treino +1, teste 0, 1 de 1. Rodadas 15 e 16: nenhuma regra
promovida. Rejeitadas na 15: janela do `1.` isolado de 400 para 1500 caracteres, `(NR)` como
quebra de cadeia, cadeia de inciso citado recomeça depois de linha terminada em `:` (precisão
0,3), parágrafo no começo da linha depois de vírgula é citação (perde unidade do teste). Na 16:
lista de itens citada que começa depois de 1 (precisão 0,4), `1º.` sem o `§` ao lado de uma
cadeia (0 unidades). **Duas rodadas seguidas sem promoção: o torneio satura na rodada 16.**

**Balanço das rodadas 6 a 16** (2026-11-18, mesma referência de 3161 normas): 18 regras
promovidas, 33 rejeitadas, 23 errata novas (41 no total). Unidades (norma, nível) que
concordam, antes -> depois, tudo / treino / teste: art 2995 -> 3002 / 2393 -> 2400 / 602 -> 602,
par 1534 -> 1571 / 1236 -> 1265 / 298 -> 306, inc 747 -> 786 / 594 -> 628 / 153 -> 158, ali 232
-> 244 / 183 -> 192 / 49 -> 52, item 13 -> 13 / 9 -> 9 / 4 -> 4. O teste ganhou bem menos que o
treino em quase toda regra; ganhou nas regras `s lo -` (+6), `Parágrafo 1º -` (+1), `§` com `.` ou
`:` (+1), romano sem traço (+2), salto de parágrafo e inciso em bloco citado (+2 e +2) e `£)` (+2);
as outras regras ganharam só no treino.

**Rodada 17: artigo único implícito** (`hierarchy_sequence.implicit_single_article`, feita
por decisão do dono). Um ato de uma só disposição que não traz marcador `Art.` (decretos de
pessoal de 1982-83: "O GOVERNADOR ..., no uso de suas atribuições legais, RESOLVE: Conceder
afastamento ao servidor ...") não tinha artigo próprio lido. A regra lê **um** artigo próprio,
n=1, sem marcador (`read_by="implicit-single"`, `raw` vazio, como o artigo recuperado de uma
frase de encerramento), da primeira frase depois da fórmula (`RESOLVE`/`DECRETA`, ou a linha
solta de letras que o OCR deixou no lugar dela depois da vírgula do preâmbulo: `RES OB VE`,
`RA BES ON aV E:`) até o fecho. Só vale quando **todas** estas guardas passam: nenhum marcador
de artigo no texto inteiro (próprio ou citado, legível ou borrado: `ARTICLE_CANDIDATE` e
`_ART_WILD`); fórmula depois de um preâmbulo (`governador`/`atribui...`); fecho que existe
(`Porto Velho, <dia>`, `Palácio do Governo`, `Brasília, <dia>` ou linha `Governador`); trecho
de 40 a 12 000 caracteres que começa por letra; sem "nova redação"/`(NR)`; nenhuma linha que
abra como disposição numerada (`1º -`, `29 -`, ou um travessão); nenhuma frase de
vigência/revogação (seria um segundo artigo de marcador perdido). Linhas curtas de resíduo
(nome do signatário, rabiscos do OCR) no fim do trecho ficam fora do artigo. Um ato de vários
artigos com todos os marcadores destruídos **não** fecha por esta regra: `decreto-01019` e
`decreto-01007` (itens `1º -`, `29 -`) e `decreto-01000` (a frase "Revogam-se as disposições
em contrário" depois da disposição) continuam abertos; `decreto-01001` não tem fecho; seis
decretos sem fórmula (`01010`, `01011`, `01012`, `01015`, `01032`, `01002`: "concede
afastamento ..." direto depois do preâmbulo) ficam abertos de propósito.

Resultado (camada `-latest` de 2026-11-18, 3616 normas): **8 normas** mudam, todas de "não
fecha, 0 artigos" para "fecha, 1 artigo" (`artigos_fecham` e `artigos_total` da camada
publicada): `decreto-00100`, `00101`, `00102`, `00103`, `01016`, `01017`, `01018`, `01031`. Lidas
uma a uma contra o texto: 8 de 8 são decretos de uma só disposição (designar, conceder
afastamento, remover, colocar à disposição, promover), precisão a olho 8/8; nenhuma outra
norma da camada muda de `closes` nem de artigos. Gate por nível: passa, **nenhuma unidade
perdida no treino nem no teste**; as 6 normas em que a referência (modo `mark`) já deduzia o
artigo (`x: true`) ganham a unidade `art` (treino +4 / teste +2) e `decreto-00100` e
`decreto-01018`, em que o modelo não deduziu, entram como `reader_extra` até duas errata
`add_device` da referência (lidas no texto, mesma forma dos artigos de bloco que o conversor
omitiu), que as levam a `agree`: art 3002 -> 3010 de 3115 unidades (nível `art` 3113 -> 3115
unidades; par/inc/ali/item sem mudança). Dispositivos novos: 8, 6 certos contra a referência
original e 8 de 8 depois das errata. Gate de artigo (rótulos do modo `label`): o professor
(`teacher-labels-v1`) rotula só marcadores impressos e não deu artigo a 6 destas 8 normas
(as outras 2 não estão nos 2086 rotulados), então elas viriam como `disagree_closed` e
reprovariam o gate; 6 errata `add_own_article` em `teacher-label-errata.json` (mesmo caso das 3
anteriores: a linha abre o artigo e o professor só tem o marcador) as levam a `agree_closed`
(1930 -> 1936, `disagree_closed` 1 -> 1). `marcar` emite `<art n="1"
lido-por="implicit-single">` sem `<m>` e `marcar-verificar` confirma strip, sha256 e gramática;
as âncoras do `textos` usam a regra do artigo de largura zero (`ini` na frase, `fim` cobre a
primeira palavra).

**Erros sistemáticos da referência.** Nenhuma classe de erro do conversor apareceu em
número que pedisse reconstruir a referência: as 41 errata (13 + 5 + 23) são pontuais
(13 `add_device`: dispositivo que o modelo deixou de marcar; 5 `set_device`: status
citado/próprio ou sufixo de parágrafo). As 23 das rodadas 6 a 12: 21 `add_device` (omissões do
modelo: 15 de dispositivos citados, entre eles 5 artigos de bloco com elisão `..`, e 6 de lista própria) e 2 `set_device` (sufixo `A` que é a primeira palavra da frase; `II` que é III pela cadeia). As suspeitas do conversor (`suspect_*`, 38 normas) continuam
fora do gate.

### Suspeitas fechadas (`clear_suspect`)

Uma norma com suspeita do conversor (`suspect_sequence`, `suspect_alteracao`, `suspect_number`:
os artigos próprios deixam de crescer, ou um número próprio salta) fica fora do gate. A errata
`clear_suspect` (`flags`: as que ela fecha; `line` + `evidence`: a linha da quebra; `reason`:
o que a resolve) a traz de volta, **depois** das errata de `remove_device`/`set_device` que
corrigem a cadeia: só se fecha uma suspeita quando a cadeia própria da referência, já
corrigida, é a do leitor por regras e foi lida no texto. É stale (falha o `check`, não é
forçável) se a norma não traz a flag que ela nomeia. `open_flags(rec, applied)` diz as flags
que sobram; `review_to_errata.py` e `select_residue_review.py` usam o mesmo critério
(`review_to_errata.py --include-flagged` classifica também as normas ainda suspeitas).

## Revisão do resíduo com o Sonnet (2026-11-18)

Rodada única de `teacher_batch --mode review` com `claude-sonnet-5-5` (effort medium, camada
`-latest` de 3616 textos, leitor no commit d73f5dc) sobre `residue-review-2026-11`: 79 normas
(as 38 com suspeita, 9 nomeadas, amostras semeadas das classes do resíduo) + 16 canários;
coleta 44288579553, manifesto 44288243796, custo medido **US$ 0,80** (estimativa 2,03). O modelo
vê a leitura do **leitor** como etiquetas e só devolve ajustes; `review_to_errata.py` compara
cada ponto leitor x referência com o que ele fez. Números e leitura a olho:

- **Validador.** 123 ajustes válidos e 48 descartados. Dos 48, **45 são o modelo repetindo a
  etiqueta ou escrevendo lixo** ("placeholder", "x", "sem erro", "etiqueta já correta": 29 ``set_number`` /
  ``set_node_number`` para o número que a etiqueta já tem, 3 `set_quoted` com o valor que já tem,
  o resto sem etiqueta na linha); 3 (6%) são ajuste de verdade com a operação errada
  (`set_number`/`set_node_number` em linha sem etiqueta do nível, `add_node` em linha que já tem
  a etiqueta). O validador está certo; não houve correção a fazer (converter a operação
  recuperaria 3 de 171).
- **Canários**: 15 de 16 pegos; o perdido é um `flip_quoted` (decreto-10221, artigo 8 posto como
  próprio): o modelo respondeu `ok` e um ajuste-lixo. As 2 normas `unverified` (lei-00022, lc-01107)
  são as `ok` da mesma requisição.
- **Custo.** Entrada 641 804 tokens a preço cheio + 431 085 lidos do cache (o prompt de 4,5 mil
  tokens x 88 requisições), saída 25 220 tokens (mediana 155 por requisição; **pensamento: 1 786
  tokens em 3 de 88 requisições, 7% da saída**). A estimativa supunha 187 mil tokens de saída (o
  piso de 2 070 por requisição) e todo o prompt a preço cheio: saída US$ 0,13 (estimado 0,94),
  entrada US$ 0,64 + cache 0,02 (estimado 1,10). Em `medium` o Sonnet quase não pensa.

**O que o Sonnet decidiu, por classe (319 pontos leitor x referência nas 41 normas fora do
gate; "a olho" = lido por mim contra o texto):**

| desfecho do modelo | pontos | certo a olho |
|---|---|---|
| ajustou até a referência (`confirms_reference`: defeito do leitor) | 42 | 42 de 42 lidos (lc-01211 12/12, lei-04989 6/6, lei-00131 5/5, lei-05972 6/6, ...) |
| não ajustou onde o leitor tem a mais (`reader_extra`) | 65 | ~2/3: o leitor está certo e a referência omitiu (lc-01251, lei-04989, lei-00476, lei-00756, lei-01591); errado em tabelas/ruído (`T =`, `[=`, `1.` de título), citação no meio de frase |
| não ajustou onde o leitor perde um dispositivo (`reader_misses`) | 113 | **0 de 16** na amostra: a referência está certa (romano sozinho na linha, `g)`, `h)`, artigos de cópia repetida) |
| não ajustou onde o `status` difere | 59 | **a referência está certa** (6 normas: bloco citado inteiro lido como próprio) |
| terceira opinião (nem leitor nem referência) | 15 | 10 certos, 4 errados, 1 em aberto (lei-01296) |

Leitura: o revisor só enxerga o que a etiqueta mostra; **omissão em subnível e a cascata de
`status` de um bloco citado ele não vê** (não há `[?inc]`, e quando corrige o artigo hospedeiro não
leva os filhos). Silêncio dele vale como "o leitor está certo" só onde o leitor **tem** o
dispositivo; onde falta, o silêncio não prova nada.

**Casos nomeados.** `lc-01174`: `Art. 49-A` é 49-A (linha 129, "Art. 49-A. Compõem o Sistema
Estadual dos Juizados Especiais", seguido de 49-B...; leitor e referência certos; o `4A` do
professor do modo label estava errado; Sonnet `ok`). `lei-01296`: o texto salta do 2 para
"Art. 6º Esta Lei entra em vigor" (depois de um "4" solto de rodapé); Sonnet lê 3 (erro de OCR),
leitor e referência leem 6; ficou **em aberto**, a leitura impressa é o 6. `lei-04989`: é um
acórdão de ADI (PJe) que transcreve leis; os artigos próprios são só os 4 do fim (linhas 2177
a 2229); todo o resto é citado: Sonnet certo em 9 de 9 ajustes (3 deles contra leitor **e**
referência), mais 15 dispositivos citados que a referência omitiu e o leitor lê certo.
`lei-00262`/`lei-00432`/`lei-00452`, `lc-01211`: lei que reescreve um regulamento inteiro entre
aspas. `lc-01211`: Sonnet certo 12 de 12; `lei-00432` e `lei-00262`: Sonnet ficou do lado do
leitor e errou (o bloco vai das aspas de abertura até `".`; os próprios são os do fim);
`lei-00452`: nem leitor nem referência estão certos (o regulamento inteiro, artigos 1 a 33, é
citado; a referência só o fez nos 3 primeiros). `lei-00131`: o arquivo reúne 4 atos; Sonnet
acrescentou os 5 artigos do primeiro (certo) e não viu os dos outros dois. `decreto-01004`: o mesmo decreto
impresso duas vezes; leitor lê uma. **Tabelas lidas como incisos**: `II - TRIMESTRE CR$
11.000.000,00` (decreto-01027) e `Assessor IV - CDS-04` não são dispositivos (Sonnet: "linha de
tabela"); a pista estrutural é o valor em moeda na mesma linha e não haver `I` antes, mas remover
o inciso não faz nenhuma unidade entrar (o nível some da norma), então não passa o torneio.
**Romano sozinho na linha**: a referência está certa (16 de 16), o Sonnet não adicionou nenhum;
uma regra só pela cadeia perde 8 unidades (títulos `CAPÍTULO`/`TÍTULO` + romano). **Listas de
itens** (`1.` sozinho, títulos de orçamento, teses de ementa): ambíguas, a referência é incoerente
entre as listas; deixadas.

**Aplicado.** (a) 90 errata novas (133 no total): 36 `add_device` (omissões do conversor lidas
pelo leitor e aceitas pelo Sonnet, lidas a olho; 15 só em lei-04989), 37 `set_device` (números
de OCR, citado/próprio em decisões que transcrevem a lei, o bloco citado inteiro de lei-00262),
6 `remove_device` (marcador contado duas vezes: `Art.` e o número em linhas separadas, ou citação no
meio de frase), 11 `clear_suspect`. (b) Suspeitas: **38 -> 27**; as 11 fechadas são 11 normas em
que a cadeia própria da referência tinha um defeito que o texto mostra (marcador contado duas vezes:
lc-00090, decreto-lei-00054, lei-00225, lei-00471, lei-00551; º lido como dígito: lei-00022,
lei-00468, lei-00089, lei-00217, lc-01347; artigo 1 citado posto como próprio: lei-00694) e em que o
leitor por regras já lia a cadeia certa; **29 unidades entram na linha de base** (art +11, par +9,
inc +5, ali +4). As 27 restantes continuam fora: cópias repetidas (lei-06271, lei-06284,
lei-01293, lei-05970, lei-06150), blocos citados sem fecho, tabelas. (c) Regras (rodadas 18 a
20; as mensagens de commit dizem 17 e 18 nas duas primeiras, mas a 17 é a do artigo implícito):
bloco citado longo fecha na marca seguida de ponto e com o número do artigo da cadeia (lei-00432:
+3 unidades no treino, 27 de 27 dispositivos certos); marca de fechamento perdida no fim da linha
anterior (decreto-lei-00072: +1, 14 de 15); numeral e traço depois de marcador de alínea não é
inciso (lei-05972: +2, 5 de 5). Teste +0 nas três. Rejeitadas: romano sozinho na linha (perde 8
unidades), `is_reference` dentro de bloco citado (efeito 0), remover o inciso de tabela com valor
em moeda (0 unidades).

**Placar por nível, antes -> depois** (unidades que concordam / unidades; teste entre parênteses):
art 3010/3115 -> 3021/3126 (604 -> 606), par 1571/1676 -> 1581/1685 (306 -> 307), inc 786/967
-> 794/973 (158 -> 159), ali 244/312 -> 250/317 (52 -> 53), item 13/58 -> 13/58. Gate de artigo:
agree_closed 1936 -> 1937.

**Vale a revisão em escala?** Medido: US$ 0,0101 por norma (US$ 0,80 / 79 normas reais e 16
canários; as mais difíceis, 40% partidas em várias requisições). Inferido: as 357 normas do gate
com alguma unidade fora de `agree` custariam ~US$ 4 a 8 (com canários), então o dinheiro não é o
limite; **a conferência a olho é**: de cada 100 pontos, o Sonnet decidiu certo ~30 (42 ajustes
certos + 10 terceiras opiniões certas + ~43 silêncios certos em 319), e dois terços do que ele
deixa passar (omissões e cascata de `status`) só se vê lendo. O que esta rodada rendeu foi 35
unidades (29 de errata/suspeitas, 6 de regras) em 79 normas; uma passada em todas renderia
algumas dezenas a mais, quase todas de errata `add_device` de dispositivo citado e de suspeitas
com cadeia corrigível, não de regras novas. Só vale com `effort` mais alto (em `medium` o modelo
não pensa) e com `[?inc]`/`[?ali]` nas linhas sem etiqueta, que o revisor hoje não recebe.
Terceira opinião (o ajuste não é nem do leitor nem da referência): 15 de 319 pontos (4,7%) nas 41
normas fora do gate; 10 certos a olho, 4 errados (decreto-lei-00072 x2, lc-01271, lei-00452), 1
em aberto.

**O que continua aberto**: arquivos com vários atos ou cópias do mesmo ato (lei-00131,
decreto-01004, lc-01164, lei-06284: reiniciar a cadeia na fórmula de promulgação é o candidato
natural); bloco citado sem aspas de fechamento ou com marcas soltas (lei-00262, lei-00452);
decisões judiciais que transcrevem leis (lei-04989, lei-04984, lei-01635: o tipo de documento é
a pista); romano/alínea soltos em coluna; lei-01296 (2 -> 6); 27 normas suspeitas.

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
