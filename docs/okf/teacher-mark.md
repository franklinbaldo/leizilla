---
type: Avaliacao
title: Teacher batch — modo mark (o professor devolve só onde as marcas vão)
description: Terceiro modo do professor LLM: leitura completa e independente da norma, resposta só com posições (duas âncoras por marca), documento marcado montado e verificado por código; formato da resposta, política das âncoras, estados, piloto de 60 normas, pontuação.
tags: [avaliacao, teacher, mark, documento-marcado, ancoras]
timestamp: 2026-11-18T00:00:00Z
---

No modo `label` o professor rotula cada linha; no `review` audita a leitura do leitor.
No modo `mark` ele faz a **leitura completa**, sem ver a leitura do leitor (nenhuma
etiqueta), e responde **só onde as marcas vão**: nunca devolve o texto. O código monta o
[documento marcado](documento-marcado.md) com `marcacao.build` e o confere com
`marcacao.verify`. Código: `src/leizilla/teacher_mark.py`; pontuação:
`scripts/score_mark.py`; simulação sem API: `scripts/simulate_mark.py`.

Prompt `teacher-mark-v2` (`MARK_PROMPT_VERSION`; o v1 rodou o piloto, ver abaixo). O texto
completo está em
`teacher_mark.MARK_SYSTEM_PROMPT` (o exemplo dele é gerado de dados, então as colunas
estão certas por construção, e um teste o passa pelo conversor).

## Entrada

Cada requisição traz uma a quatro normas (ou uma parte de norma longa), com linhas
`NÚMERO<TAB>TEXTO` e a numeração global do texto (linhas em branco omitidas, o número
conserva os saltos). O TEXTO é a linha sem espaços nas pontas: **a coluna conta a
partir do primeiro caractere depois do TAB**, base 1, em caracteres (um acento conta 1).
Empacotamento por tamanho (16 000 caracteres, no máximo 4 normas, semente
`--shuffle-seed`); norma maior que 150 linhas ou 14 000 caracteres é partida com
`tb.chunk_document` (contexto e cabeçalho somente leitura), uma requisição por parte.

## A resposta

`{"norms": [{"id": "N01", "marks": [...]}]}`, uma entrada por id, exatamente uma vez.
Cada marca tem sempre os dez campos (o esquema estrito exige todos; o que não vale vai
`null`/`false`):

| campo | significado |
|---|---|
| `l` | linha onde a marca começa |
| `k` | tipo: `art par inc ali item`, `parte liv tit cap sec subsec`, `epigrafe ementa preambulo fecho assinatura anexo ruido alteracao` |
| `c` | **âncora A, a que vale**: coluna (1-based) do primeiro caractere do marcador impresso (em bloco, a aspa de abertura inclusive) |
| `t` | **âncora B, a que confere A**: o marcador como impresso (`Art. 5º`, `§ 2º`, `III -`, `a)`), copiado; é também o span do `<m>`. Em bloco, no máximo os ~15 primeiros caracteres da PRIMEIRA linha. Sem marcador: as primeiras palavras da frase |
| `n` | número **interpretado**: arábico (`art par item`), valor do romano (`inc`, organizacionais), letra (`ali`), `"unico"`; `null` em bloco. O impresso nunca é alterado |
| `s` | sufixo do "5º-A" |
| `le` | linha final do bloco; `null` em dispositivo. Para `anexo` vale só como limite inferior: o conversor termina o anexo na marca seguinte |
| `x` | `true`: dispositivo sem marcador legível (número deduzido pela sequência); não gera `<m>` |
| `e` | `"vetado"` ou `null` |
| `nota` | observação curta nossa (vira `<nota por="modelo" tipo="teacher-mark">`), usar pouco |

Dispositivos e títulos dão só o início: o fim é derivado (início do próximo irmão ou
ancestral, fim do pai). Blocos dão início e `le`; o fim é o fim dessa linha. Exemplo
(o do prompt, norma de 16 linhas; uma marca por linha só para ler):

```
{"norms":[{"id":"N01","marks":[
 {"l":3,"k":"ruido","c":1,"t":"GOVERNO DO ESTADO","n":null,"s":null,"le":3,"x":false,"e":null,"nota":null},
 {"l":4,"k":"epigrafe","c":1,"t":"LEI Nº 7","n":null,"s":null,"le":4,"x":false,"e":null,"nota":null},
 {"l":6,"k":"ementa","c":1,"t":"Dispõe sobre a coisa","n":null,"s":null,"le":6,"x":false,"e":null,"nota":null},
 {"l":8,"k":"preambulo","c":1,"t":"O GOVERNADOR DO ESTADO","n":null,"s":null,"le":8,"x":false,"e":null,"nota":null},
 {"l":10,"k":"art","c":1,"t":"Art. 1º","n":"1","s":null,"le":null,"x":false,"e":null,"nota":null},
 {"l":11,"k":"par","c":1,"t":"§ 1º","n":"1","s":null,"le":null,"x":false,"e":null,"nota":null},
 {"l":12,"k":"inc","c":1,"t":"I -","n":"1","s":null,"le":null,"x":false,"e":null,"nota":null},
 {"l":13,"k":"ali","c":1,"t":"a)","n":"a","s":null,"le":null,"x":false,"e":null,"nota":null},
 {"l":14,"k":"inc","c":1,"t":"Il -","n":"2","s":null,"le":null,"x":false,"e":null,"nota":"impresso Il, lido II"},
 {"l":15,"k":"art","c":1,"t":"Art. 2º","n":"2","s":null,"le":null,"x":false,"e":null,"nota":null},
 {"l":16,"k":"alteracao","c":1,"t":"\"Art. 5º - Fica","n":null,"s":null,"le":17,"x":false,"e":null,"nota":null},
 {"l":16,"k":"art","c":2,"t":"Art. 5º","n":"5","s":null,"le":null,"x":false,"e":null,"nota":null},
 {"l":17,"k":"par","c":1,"t":"Parágrafo único","n":"unico","s":null,"le":null,"x":false,"e":null,"nota":null},
 {"l":18,"k":"art","c":1,"t":"Esta Lei entra em vigor","n":"3","s":null,"le":null,"x":true,"e":null,"nota":"marcador perdido"},
 {"l":20,"k":"fecho","c":1,"t":"Porto Velho","n":null,"s":null,"le":20,"x":false,"e":null,"nota":null},
 {"l":21,"k":"assinatura","c":1,"t":"OSWALDO FILHO","n":null,"s":null,"le":21,"x":false,"e":null,"nota":null}
]}]}
```

## As duas âncoras e por quê

O dono quer medir se o modelo sabe apontar o caractere exato dentro de uma linha. Cada
marca traz, na mesma resposta, a coluna (A) e o trecho (B). O conversor resolve as duas
**independentemente** e registra, por marca, na tabela `anchors.jsonl`: o offset de A, o de
B, o método de B (`exact`, `tolerant`, `ambiguous`, `none`), se concordam e `|A−B|`.

- B exato: o trecho aparece uma única vez na linha. B tolerante: não há exato e há
  exatamente um casamento com acento, caixa, espaços e pontuação dobrados (`º`, `°` e `o`
  se encontram: "5º" e "5o" do OCR). **As aspas nunca são dobradas para fora**: um
  casamento tolerante não pode pular o caractere de aspa (no piloto, um bloco em `lc-00074`
  linha 51 saiu uma coluna adiante assim); aspas curvas e retas se encontram. Várias
  ocorrências: `ambiguous`.
- **Política (v2): A é primária.** A coluna vale quando os 4 primeiros caracteres de `t`
  (sem espaços, aspas dobradas) são os que estão nessa coluna (`a_confirm` na tabela de
  âncoras; um `t` copiado através de uma quebra de linha confirma até o fim da linha).
  Se A não confirma: B quando resolve de modo único na linha (exato ou tolerante). Se
  nenhum dos dois: a marca é descartada (`no_anchor`). Os dois continuam sendo resolvidos
  e pontuados independentemente (`score_mark` mostra A contra B).
- Por quê: no piloto a coluna `c` foi exata em 1 494 de 1 494 marcas em que o trecho
  resolveu e certa nas 20 em que não resolveu; o trecho falhou 17 vezes porque o modelo
  copiou o `t` de um bloco através de uma quebra de linha, e uma vez resolveu errado
  (casamento tolerante pulou a aspa). Em dispositivo o `t` fica: dá o span do `<m>`.
- Com A usado, o `<m>` tem o tamanho de `t` cortado no fim da linha; marcador quebrado
  entre linhas ("Art. \n29") é dado pela primeira linha.

## Montagem

1. Cada marca vira um offset; número, sufixo e `vetado` são validados (`bad_number`,
   `bad_suffix`); blocos precisam de `le` válido (`bad_end_line`, `empty_block`).
2. Ordem por posição; aninhamento por pilha de níveis: um dispositivo fecha os de nível
   igual ou inferior, um título fecha tudo abaixo dele, `epigrafe`/`ementa`/`preambulo`/
   `fecho`/`assinatura` fecham todos os dispositivos. `alteracao` e `anexo` são
   barreiras: dentro delas os dispositivos aninham à parte (citados por construção) e
   acabam no fim do bloco. O fim de um dispositivo é o início do que o fecha, sem espaços
   finais; o último vai até o fim do texto.
   **Anexo (v2)**: o fim vem da marca seguinte (a próxima que não é `ruido`), ou do fim
   do texto; o `le` do modelo é só limite inferior (no piloto 7 de 24 vieram cedo demais;
   marcas dentro do intervalo do `le` continuam dentro do anexo). Um anexo seguido de
   dispositivo do corpo (tabela entre dois parágrafos de um artigo) fica DENTRO do
   dispositivo aberto, que continua depois dele (a gramática aceita `anexo` em
   dispositivo desde o v2; o leitor não o emite); o anexo depois do último dispositivo
   fecha tudo e fica fora do `<lei>`.
3. `<lei>` (v2): uma por ato. Termina depois do último dispositivo do corpo; `anexo`,
   `fecho` e `assinatura` entre dispositivos ficam dentro dela. Um arquivo com várias
   normas (a lei e, depois da assinatura, cópias do projeto de lei) tem um `<lei>` por
   ato: começa um ato novo na primeira marca de corpo depois de `fecho`/`assinatura` quando
   é `epigrafe`/`ementa`/`preambulo`, ou um `art` cujo número não sobe (recomeça em 1).
   Sem nenhuma marca de norma, não há `<lei>`. (No v1 o `<lei>` fechava no primeiro
   `fecho`/`assinatura`/`anexo` e os dispositivos depois dele, sem recipiente, eram
   descartados: as 42 marcas do piloto.)
4. `build`. Em erro de aninhamento ou gramática, **a marca culpada é descartada e
   registrada** (`conflict`; entre as duas nomeadas cai a de menor prioridade: `nota`,
   `ruido`, `alteracao`, partes, títulos, dispositivos; empate, a segunda) e o documento é
   derivado de novo; a norma não falha. `strip(xml) == texto` é afirmado em todo documento
   (não pode falhar por construção); `verify` precisa passar, senão `build_failed`.

## Suspeitas (v2): sinalizar, e uma segunda leitura ao lado

`convert_response` devolve `suspects` por norma (vai em `records/*.json` e em
`summary.json`: `suspects_by_type`, `norms_with_suspects`; `score_mark` as conta):

- `suspect_alteracao`: dentro de um ato, os artigos próprios deixam de crescer (o número
  repete ou volta: 9, 10, 2, 3, o bloco citado cortado cedo, cujos artigos seguintes
  viraram "próprios"). Culpa o último `alteracao` que termina antes do artigo
  ofensor; `closing_quote` diz se a última linha dele tem aspa de fechamento (`false`:
  cortado; `null`: nem abre com aspa).
- `suspect_sequence`: a mesma quebra sem `alteracao` antes dela.
- `suspect_number`: número próprio bem acima do anterior que, sem o último dígito, é o
  anterior ou o anterior + 1 (o sinal ordinal lido como dígito: `Art. 92`, `Art. 102` por
  9 e 10). O número fica como o modelo deu; a sequência seguinte é conferida com o valor suposto (`n // 10`).

O score ainda compara cada `alteracao` do modelo com os blocos citados do leitor
(`same`, `longer_in_reader`, `shorter_in_reader`, `only_model`, `only_reader`).

### Segunda leitura (`repair`): uma variante verificada, nunca no lugar

O prompt não corrigiu as duas falhas de artigo (bloco `alteracao` terminado antes da aspa
que fecha; sinal ordinal lido como dígito), então o conversor oferece uma **segunda leitura
determinística, ao lado**: o documento do modelo continua como veio (`marked/`), a variante
reparada vai para `marked-repaired/` (só para normas em que algo mudou) e o `records/*.json`
traz `repairs` (o que mudou, com a evidência), `repairs_rejected`, `repaired_suspects` e
`closure: {model, repaired}` (fecho dos artigos próprios de cada um). O `summary.json` tem
`norms_repaired`, `repairs_by_kind` e `own_article_closure`. Nada altera o texto (a
invariante do strip vale para a variante) nem a resposta do modelo. Passes, nesta ordem:

1. `duplicate_marker`: o mesmo dispositivo (tipo, número, sufixo) marcado duas vezes, a no
   máximo 3 linhas, sem outra marca entre elas, quando o marcador está partido entre linhas
   (o primeiro termina a linha, ou o segundo não tem marcador): fica o primeiro
   (`lei-00380`, "Art. " / "3Q" / "- Esta Lei...", linhas 314 e 316).
2. `ordinal_digit`: artigo próprio (nunca citado, nunca com sufixo) com número `n >= 10`
   acima do anterior + 1 cujo último dígito retirado dá o anterior + 1 (`49` depois de 3,
   `102` depois de 9), e o artigo próprio seguinte continua dali (ou não há seguinte).
   Variante `sequence-pair`: retirado o dígito dá o próprio anterior e o seguinte lê
   anterior + 1 do mesmo jeito (`92`, `102` depois de um 9: lê 9 e 10). **Não** se aplica se
   a sequência é consistente como impressa (3, 49, 50, 51: o seguinte é `n + 1`), nem a
   números citados (`lei-00765`: 52, 60, 79, 80 ficam).
3. `alteracao_end`: o bloco apontado por `suspect_alteracao` (ou, para `suspect_number`, o
   último bloco que termina antes do artigo marcado) é estendido até a linha mais próxima
   com aspa de fechamento ou `(NR)` que faz a suspeita sumir e o número de quebras cair. A
   segunda testemunha é o bloco citado do leitor (`witness: sequence+reader` quando ele
   termina na mesma linha; só `sequence` quando não). **Só vale se os artigos próprios da
   variante fecham (1..N)**; senão a extensão vai para `repairs_rejected` e a variante não
   a leva (a extensão é a reparação mais arriscada: vira citados artigos que eram próprios).

Repetição offline sobre as respostas reais do piloto (`scripts/replay_mark.py`; v2, 60
normas, os mesmos 1 551 marcas; comparação com `scripts/compare_mark_reader.py --labels`):

| | modelo como veio | variante reparada |
|---|---:|---:|
| normas com os artigos próprios fechando | 53/60 | 56/60 |
| artigos próprios iguais aos do professor (50 normas com o mesmo texto) | 44 | 46 |
| artigos próprios iguais aos do leitor | 41 | 44 |
| norma que ficou pior (contra o professor ou o leitor) | | 0 |

Por norma: `lei-00002` (49/59): 4 e 5, fecha, igual ao professor e ao leitor;
`lei-00380`: duplicata das linhas 314/316 fundida e bloco 77-246 estendido a 285 (o fim que
o leitor também dá), fecha, igual ao professor e ao leitor; `lei-01335`: bloco 33-234
estendido a 543 (igual ao leitor), fecha, igual ao leitor mas **não** ao professor (o
professor tem um artigo próprio `1` na linha 541, dentro do bloco do leitor);
`lei-00765`: a única extensão que apaga a suspeita termina na linha 750 e engole o artigo
próprio da linha 749, os artigos próprios continuam sem fechar: **recusada**, a norma
segue sinalizada (o bloco verdadeiro, do professor, vai da linha 44 até a 748 sem aspa
de fechamento no OCR; nenhuma regra de aspa o acha). Sobre as respostas do v1 do piloto: a
`lei-00216` (92 e 102) lê 9 e 10 (iguais ao professor nas linhas 479 e 486) mas continua
sinalizada (`suspect_sequence`: o modelo deu 9 duas vezes porque numerou a mais um artigo
ilegível na linha 357); `lei-00380` e `lei-01335` como acima.

## Estados por norma e truncamento

`ok` (sem marca descartada), `degraded` (construído, com marcas descartadas, motivo por
marca em `records/`), `partial` (norma partida com partes truncadas/inválidas),
`truncated` (resposta cortada em `max_tokens` ou sem texto), `invalid` (id faltando ou
repetido, entrada malformada), `build_failed`. Truncada vai para `truncated_requests` do
`manifest.json`; `--retry-truncated` (no workflow, `manifest_run_id`) reenvia uma norma
(ou parte) por requisição com 1,5x o orçamento, mesmos insumos exigidos. `max_tokens` =
8 192 + por norma (1 024 de pensamento + 50 por linha mostrada), no máximo 32 000; o teto
de custo é a soma. O manifesto leva os textos comprimidos (o `collect` não depende de
baixar o `textos.parquet` de novo).

## Saídas do collect

`marked/<item>/<tipo>-NNNNN_<uuid5>.xml` (um documento por norma),
`marked-repaired/…` (a variante reparada, só onde algo mudou), `records/…json`
(estado, descartes com motivo), **`anchors.jsonl`** (uma linha por marca respondida),
`failures.jsonl`, `summary.json`, `manifest.json`, `raw/`. Com `upload_ia`, o item do IA
`leizilla-teacher-labels-ro-mark-<revisão>`. Nada é aplicado a rótulo, errata ou leitor.

## Piloto

`docs/okf/review-samples/mark-pilot-2026-11.txt`: 60 normas, semente 20261118, do
conjunto `main` rotulado: 30 `agree_closed` por terços de comprimento (10 curtas ≤ 34
linhas, 10 médias ≤ 85, 10 longas), 15 em que leitor ≠ professor (10 `disagree_open`, 5
`teacher_inconsistent`), 10 `agree_closed` com bloco citado, e 5 longas a mais. Excluídas as
normas com mais de 4 partes. **Os textos não são todos os que o professor do modo `label`
viu**: 50 têm o texto da camada publicada igual ao dele, mas 10 são o texto do re-OCR da
camada nova (posições 8, 25, 32, 45, 46, 48, 49, 51, 54, 55 do arquivo), cujos rótulos foram
feitos sobre o texto do IA. Estimativa do `plan` do v1 (claude-haiku-5-5, effort medium;
60 requisições): US$ 0,063, teto US$ 0,279; do v2: US$ 0,0655 / 0,2835 (o prompt cresceu
816 tokens); o modo `label` para as mesmas normas: US$ 0,09 / 0,16.

### Resultado medido (prompt v1, Haiku, 2026-11-18)

60 de 60 normas construídas (57 `ok`, 3 `degraded`), 1 514 marcas, 1 472 usadas (42
descartadas, todas `conflict`), custo medido US$ 0,0724 (US$ 0,0012 por norma, 1,9x o modo
`label`; a estimativa deu 0,0631: 13% abaixo). Âncoras: a coluna `c` foi exata em 1 494 de
1 494 marcas em que o trecho resolveu, e certa nas 20 em que não resolveu; o trecho falhou
17 vezes (o modelo copiou o `t` de um bloco através de uma quebra de linha) e resolveu uma
vez errado (casamento tolerante pulou a aspa, `lc-00074` linha 51). Só 22 de 1 494 marcas
não estavam na coluna 1 (18 delas o padrão aspa-antes-do-artigo que o próprio exemplo do
prompt ensina): o piloto **não testou posições no meio da linha**; é o que o conjunto de
estresse abaixo faz. Três tipos de falha, todas do conversor ou do prompt, não de âncora:

1. **`<lei>` fechado no primeiro fecho/assinatura/anexo** (as 42 descartadas: `lei-00767`
   28 dispositivos com anexos de tabela entre artigos, `lei-00131` 13 artigos de cópias do
   projeto depois da assinatura, `lei-01660` 1 artigo depois de um anexo) e o "fecha" do
   modelo ficava trivialmente verdadeiro (`lei-00767` fechava com 4 de 17 artigos).
2. **Limites de `alteracao`**: `lei-00380` terminou o bloco na linha 240 (a aspa que fecha
   está na 285), os artigos 9 e 10 citados viraram próprios; `lei-01335` marcou o bloco numa
   linha só (o leitor tem 33-543); `lei-00765` cortou o bloco em pedaços (~100 dispositivos
   com estado próprio/citado errado).
3. **Ordinal lido como dígito** (11 de 437 artigos próprios: `Art. 92`, `Art. 102` por 9 e
   10; 52, 60, 79, 80) e **fim de anexo cedo demais** (7 de 24).

### Repetição offline com o conversor do v2

Sobre as respostas reais do piloto (sem API, `replay`: as mesmas respostas passam pelo
conversor novo): marcas descartadas 42 → 0; normas `ok`/`degraded` 57/3 → 60/0; artigos
próprios do modelo em `lei-00767` 4 → 17 (fecha de verdade) e em `lei-00131` 5 → 18 em 4
atos; âncoras usadas A/B 19/1 453 → 1 514/0; `lei-00074` linha 51: offset 775 → 774 (a
aspa). Suspeitas: `lei-00380`, `lei-00765`, `lei-01335` (`suspect_alteracao`) e `lei-00216`
(`suspect_number`, 92 e 102); entre as 45 `agree_closed`, só a `00380` (erro real, o bloco
cortado); nenhum alarme falso. Os erros de dígito ordinal em `lei-00765` (52, 60, 79, 80)
não são pegos por `suspect_number` (o número vizinho já estava errado); a norma é
sinalizada pelo `suspect_alteracao`.

Rodar (workflow `teacher-batch.yml`):

1. `step=plan`, `mode=mark`, `ids_file=mark-pilot-2026-11`, `shuffle_seed=20261118`,
   `model=claude-haiku-5-5`, `effort=medium`;
2. `step=submit`, os mesmos insumos, `max_usd=0.5`, `guard=ceiling`;
3. `step=collect` com `manifest_run_id` do submit (`upload_ia` opcional).

Estresse (v2, sintético): `ids_file=mark-stress-reflow-2026-11`, mesmos demais insumos;
ver "Conjunto de estresse". O prompt v2 dos mesmos 60 do piloto roda com os mesmos
insumos do piloto.

Plano local sem API: `uv run python -m leizilla.teacher_batch plan --mode mark
--text-source textos --textos textos.parquet --ids-file
docs/okf/review-samples/mark-pilot-2026-11.txt --shuffle-seed 20261118 --count-sample 0`.

## Ler a pontuação

```bash
uv run scripts/score_mark.py --run COLLECT_DIR --out OUT_DIR
```

0. **Política e blocos (v2)**: âncoras usadas A/B; suspeitas por tipo e por norma;
   cada `alteracao` contra o bloco citado do leitor; fim dos anexos contra o `le`; fecho
   dos artigos próprios por ato e contando os descartados; bloco "Stress set" quando há
   variantes `~reflow`.
1. **Precisão de coluna**: referência = marcas cujo B resolve de modo exato e A está na
   linha. Taxa de A exato; distribuição de A−B (−3..+3 e além); por tamanho da linha,
   coluna (0–10, 11–40, 41+), não ASCII antes da coluna e tipo; se o erro é um deslocamento
   constante (delta mais comum, e a precisão de A depois da melhor correção constante);
   quantas vezes conferir A com os 3–4 primeiros caracteres de `t` bastaria (precisão
   quando confirmado, fração dos A errados que a conferência pega); custo em tokens de `c`
   contra `t` (2 caracteres por token). Também contra o offset do marcador do leitor,
   para os dispositivos que ele achou na mesma linha e tipo.
2. **Concordância com o leitor** por nível (`art par inc ali item`), próprio e citado:
   casados, só modelo, só leitor (por caminho, `to_rows` dos dois documentos); fecho dos
   artigos próprios do modelo (`chain_intact`) contra `article_closes` do leitor.
3. **Cobertura**: parcela de caracteres não brancos dentro de `<lei>` fora de qualquer
   elemento, contra a do leitor na mesma norma; contagem por tipo de bloco; parcela de
   `ruido`.
4. **Resultados**: estados, descartes por motivo, truncamentos, custo medido, custo por
   norma contra US$ 0,00063 do modo `label`.

## Conjunto de estresse (`--ids-file` com `ID~reflow`)

O piloto quase não teve marcador fora da coluna 1. O conjunto
`docs/okf/review-samples/mark-stress-reflow-2026-11.txt` lista 40 normas do piloto
(≥ 3 dispositivos do leitor, ≤ 40 000 caracteres; as 40 primeiras por
`sha256("20261118|stress|" + id)`) como `ID~reflow`. `prepare_mark` troca cada uma por uma
**variante sintética**: `teacher_mark.reflow_text` junta as linhas (e as linhas em branco
entre elas) em linhas de 200 a 400 caracteres (`REFLOW_MIN_CHARS`/`REFLOW_MAX_CHARS`,
meta sorteada por linha, semente = o `texto_id`), trocando cada quebra por UM espaço. O
texto tem o mesmo tamanho (os offsets, inclusive os do leitor, valem nos dois) mas o seu
próprio sha256, `texto_id` (`BASE~reflow`) e `uuid5` (`…-reflow`); o manifesto e o
`records/*.json` levam `reflow` (`base_texto_id`, `base_text_sha256`, `joined`: os offsets
das quebras trocadas, de onde sai o texto original, `synthetic: true`). Os marcadores caem
em colunas arbitrárias, depois de acentos e pontuação. Nada disso se parece com o texto
real; serve só para medir a âncora. O orçamento de saída conta as marcas esperadas da
norma-base (não as poucas linhas). A
primeira rodada (2026-11-17, haiku-5-5, effort medium, 15 requisições) truncou em 15 de 15:
todas as respostas só têm bloco de raciocínio (`thinking_tokens` = `output_tokens` =
`max_tokens`, 10 166 a 15 988 por requisição), nenhum texto, nenhuma marca; é comportamento
do modelo (raciocínio sem fim com marcadores em colunas de 100-400), não de âncora. O
orçamento tinha um defeito menor, corrigido: a parte da norma-base que cabe a uma
requisição era dividida por todas as linhas (as em branco entre as linhas do OCR
incluídas), metade do certo.

`score_mark` (bloco "Stress set"): a verdade é o offset do marcador do leitor lido sobre
o texto original e levado à variante, para os dispositivos casados por linha, tipo e
número; taxa de A exato, de B exato e do offset usado, por coluna do marcador na linha
(0-10, 11-40, 41-100, 101-200, 201-400, 401+) e por haver ou não não-ASCII antes. Seco
(`simulate_mark.py` com este arquivo, A deslocado em 5%): ver abaixo.

## Modo de âncora `snippet` (`--anchors snippet`, prompt `teacher-mark-v2s`)

O estresse truncou 40/40 (effort medium) e 8/8 (effort low): cada requisição gastou o
`max_tokens` inteiro raciocinando e não escreveu nada. A hipótese (não verificada) é que o
modelo gasta o raciocínio **contando colunas** em linhas de 200 a 400 caracteres. Para
separar essa causa das demais existe uma opção de modo de âncora:

- `--anchors col+snippet` (padrão, o contrato v2 acima, sem mudança de byte no prompt);
- `--anchors snippet`: o prompt, o esquema, o exemplo e as instruções **não pedem `c`**. O
  campo `c` sai e entra `o` (inteiro pequeno ou `null`): qual ocorrência de `t` na linha é a
  marca, contando da esquerda, a partir de 1. Os dez campos continuam obrigatórios
  (`l k t o n s le x e nota`).

O conversor resolve só por `t`: único na linha (exato ou tolerante) vale (`used="B"`); se
ocorre mais de uma vez (inclusive `I -` dentro de `II -`) vale o `o` (`used="O"`); sem `o`
a marca é descartada (`ambiguous_snippet`), com `o` fora das ocorrências, ou `o` > 1 para
um `t` único, também (`bad_occurrence`); `t` que não está na linha: `no_anchor`. Uma única
tolerância: um `t` copiado através de uma quebra de linha ("Art. \n6º") que não ocorre na
linha resolve pelo maior prefixo de palavras (3 ou mais caracteres) que ocorre uma vez e
**termina no fim da linha** (`b_method="prefix"`). O manifesto, os `records/*.json` e o
`summary.json` carregam `anchors`; o `collect` lê o modo do manifesto; `--retry-truncated`
exige o mesmo modo.

`score_mark`: no modo `snippet` não há âncora A. O bloco `snippet_resolution` conta marcas
resolvidas (B/O), descartes por motivo, empates na linha (com e sem `o`); o bloco de
estresse e a referência contra o leitor passam a pontuar o **offset usado** (por coluna
verdadeira do marcador, por haver não-ASCII antes, por número de ocorrências de `t` na
linha), e `a_exact_rate` fica `null`. Simulação seca (`simulate_mark.py --anchors snippet`
sobre o conjunto de estresse, acentos retirados em 3%): 575 de 576 marcas resolvidas, 26
empates todos resolvidos por `o`, offset usado igual ao do leitor em 99,1%.

Sonda de 8 normas do conjunto de estresse (workflow `teacher-batch.yml`):

1. `step=plan`, `mode=mark`, `anchors=snippet`, `ids_file=mark-stress-reflow-2026-11`,
   `limit=8`, `model=claude-haiku-5-5`, `effort=medium`, `text_source=textos`;
2. `step=submit`, os mesmos insumos, `max_usd=0.05`, `guard=ceiling`;
3. `step=collect` com o `manifest_run_id` do submit.

O `plan` local dá 8 normas em 2 requisições, estimativa US$ 0,0034, teto US$ 0,0101. Ler:
se as 2 requisições escreverem marcas (não truncarem), o custo de contar colunas era a
causa; compare as âncoras usadas e o offset usado contra o leitor por coluna.

## Conjunto de referência (300 normas, depois 3161) e o placar por nível

`docs/okf/review-samples/mark-reference-2026-11.txt`: 300 normas, semente 20261119,
montadas por `scripts/select_mark_reference.py` (determinístico) do conjunto rotulado pelo
modo `label` (2086) cruzado com a camada de textos atual (pool de 1 994: 730 sem rótulo e 91
com mais de 4 partes ficaram de fora). Entram as 60 do piloto; o resto é estratificado por
tipo e por terço de comprimento do pool (linhas não brancas), em proporção ao pool; mais
(com piso, escolhendo a célula mais abaixo da cota) 70 normas com dispositivos de
subnível (`par inc ali item`) em que o leitor e o professor do modo `label` **discordam**
(só valem normas cujo texto é o que o professor viu) e 64 com bloco citado (o leitor acha
um). Resultado: `lei` 215, `decreto` 44, `lc` 38, `decreto-lei` 3; curtas 101, médias 99,
longas 100; 54 normas partidas em até 4 partes.

Rodar (`teacher-batch.yml`; plano local: 202 requisições, estimativa **US$ 0,25**, teto
US$ 1,01, o modo `label` para as mesmas normas US$ 0,36; o piloto mediu 15% acima da
estimativa, então espera-se US$ 0,3 a 0,4):

1. `step=plan`, `mode=mark`, `ids_file=mark-reference-2026-11`, `shuffle_seed=20261119`,
   `model=claude-haiku-5-5`, `effort=medium`, `text_source=textos`;
2. `step=submit`, os mesmos insumos, `max_usd=1.2`, `guard=ceiling`;
3. `step=collect` com o `manifest_run_id` do submit (`upload_ia` opcional).

## Camada inteira (`mark-full-2026-11`)

`scripts/select_mark_full.py` (offline, determinístico) perfila o `textos.parquet`
publicado (3 228 normas) e escreve as seleções de uma rodada do modo `mark` sobre a
camada inteira. Fora, nesta ordem (cada norma entra no primeiro motivo):

1. **referência** (300): as normas de `mark-reference-2026-11` cujo sha256 do texto é o de
   `docs/okf/mark-reference/reference.json` (já medidas); uma norma da referência cujo
   texto mudou entraria (o cabeçalho do arquivo as lista; hoje nenhuma mudou);
2. **mais de 8 partes** (57; a maior com 122): um tratamento à parte, depois; custam
   centenas de requisições seguidas e o teto delas é o que mais pesa;
3. **linhas longas** (10): alguma linha acima de 200 caracteres ou p95 das linhas não
   brancas acima de 150. Medido: o piloto (mediana 36, máximo 128) funcionou, o
   estresse (toda linha de 200 a 400) truncou 48 de 48. A camada não tem texto
   reflowed (nenhuma norma com mediana acima de 120), então o limite é pelo que sobra
   fora do medido: uma linha na faixa que falhou (acima de 200) ou mais de 5% das linhas
   acima de 150 (o piloto não passou de 128). Vão para `mark-full-longlines-2026-11` (`anchors=snippet`, rodada à
   parte).

Sobram 2 861 normas, partidas em dois arquivos de custo parecido
(`mark-full-2026-11-a`/`-b`: ordenadas por (caracteres, id) e distribuídas
alternadamente), porque o teto do arquivo único (US$ 11,43) passa de US$ 8.

Plano local (claude-haiku-5-5, effort medium, `--shuffle-seed 20261119`):

| arquivo | normas | requisições | estimativa | teto | pior realista (+15%) |
|---|---:|---:|---:|---:|---:|
| `mark-full-2026-11` (junto) | 2 861 | 2 244 | US$ 2,75 | US$ 11,43 | US$ 3,17 |
| `mark-full-2026-11-a` | 1 431 | 1 133 | US$ 1,38 | US$ 5,77 | US$ 1,59 |
| `mark-full-2026-11-b` | 1 430 | 1 112 | US$ 1,37 | US$ 5,66 | US$ 1,58 |
| `mark-full-longlines-2026-11` (`--anchors snippet`) | 10 | 19 | US$ 0,02 | US$ 0,09 | US$ 0,03 |

O teto (toda requisição gasta o `max_tokens`) é 4x a estimativa: o piso de 8 192 tokens de
saída por requisição domina. Os 5% maiores pedidos (por `max_tokens`) pesam 8% do teto
(US$ 0,92 de 11,43); se esses estourassem o teto e o resto custasse +15%, o total seria
US$ 3,86 (a e b somadas dão o mesmo). As listas das excluídas por partes e por linhas longas (id, partes, caracteres; id,
máximo, p95, mediana) estão em `docs/okf/review-samples/mark-full-excluded-2026-11.tsv`.
Rodar com `guard=estimate`, `max_usd=2` em cada metade e `0.05`
nas linhas longas: a trava recusa só se a estimativa passar disso.

### As 57 normas com mais de 8 partes

Em três listas (`docs/okf/review-samples/`), todas fora da referência e da camada já marcada:
`mark-full-giants-2026-11` (50 normas, 756 requisições, máx. 36 partes; `claude-haiku-5-5`,
effort medium: estimativa US$ 0,81, teto US$ 3,62; `anchors=col+snippet`),
`mark-full-giants-longlines-2026-11` (3 normas com uma linha acima de 200 caracteres, 224/213/231,
`anchors=snippet`: 61 requisições, estimativa US$ 0,07, teto US$ 0,30) e
`mark-full-giants-annex-2026-11` (4 normas com mais de 40 partes: `decreto-29991` 122,
`lei-01297` 89, `lei-00254` 70, `lei-01306` 51; 332 requisições, estimativa US$ 0,33, teto
US$ 1,62). Nas quatro o corpo (artigos e fecho, `read_hierarchy` `body_end`) termina nos
primeiros 1,5% a 5% do texto e o resto é anexo de tabelas (orçamento, PPA, listas de
processos, sem marcador `Art.`, até 41% dos caracteres são dígitos): marcar as tabelas vale
pouco. Cortar o corpo exigiria um modo de marca "só o corpo" (o documento marcado precisa do
texto inteiro); não está implementado, então as quatro **não** entram em nenhuma rodada. As
outras 53 passam pelo plano abaixo (`shuffle_seed=20261119`, `text_source=textos`):
`mark-full-giants-2026-11` com `max_usd=1.5`, `guard=estimate`; `mark-full-giants-longlines-2026-11`
com `anchors=snippet`, `max_usd=0.15`, `guard=estimate`.

`scripts/compare_mark_reader.py` (offline) compara, **por nível** (`art par inc ali item`,
próprio e citado), o leitor por regras com os documentos do modo `mark` de uma coleta, via
`marcacao.to_rows` dos dois (o documento do modo `mark` é a referência; no subnível ele é
melhor que o leitor). Os dispositivos são pareados por tipo (mesmo offset do marcador, depois
na ordem da mesma linha, depois mesmo número a até 2 linhas) e cada um cai em: `agree`,
`reader_misses`, `reader_extra`, `number_differs`, `status_differs` (próprio x citado) ou
`kind_differs` (uma falta e um excesso na mesma linha, de tipos diferentes). Por norma e
nível, o grupo é `agree`, um dos cinco defeitos ou `mixed`. Normas com suspeita
(`suspect_alteracao/sequence/number`) são tabuladas à parte e ficam fora da tabela
"limpa"; `--variant repaired` usa a variante reparada (e as suspeitas que sobram nela).
`--labels` acrescenta, por nível, a igualdade por norma do documento do modo `mark` e do
leitor com o professor (nas normas cujo texto ele viu; errata aplicada). O fim da saída é a
lista ordenada dos defeitos do leitor nos subníveis, por forma do marcador impresso
(dígitos viram `9`, romano válido `R`, parecido com romano `R~`, `§` lido como letra `§~`)
e por onde o dispositivo está (`line start`, `mid-line`, `in anexo/table`, `in ruido`), cada
um com exemplos: é a entrada de um torneio de regras no subnível.

Primeira medição, as 60 normas do piloto (respostas v2 repetidas; 56 limpas, 4 com
suspeita; leitor contra o modo `mark`, normas limpas):

| nível/estado | dispositivos (modo mark) | iguais | leitor não acha | leitor a mais | número difere | estado difere | tipo difere |
|---|---:|---:|---:|---:|---:|---:|---:|
| art/próprio | 372 | 356 | 14 | 0 | 2 | 0 | 0 |
| art/citado | 25 | 21 | 1 | 0 | 0 | 3 | 0 |
| par/próprio | 137 | 129 | 8 | 1 | 0 | 0 | 0 |
| par/citado | 16 | 12 | 3 | 0 | 0 | 1 | 0 |
| inc/próprio | 114 | 108 | 6 | 3 | 0 | 0 | 0 |
| inc/citado | 31 | 29 | 0 | 0 | 0 | 2 | 0 |
| ali/próprio | 18 | 18 | 0 | 0 | 0 | 0 | 0 |
| ali/citado | 2 | 2 | 0 | 0 | 0 | 0 | 0 |
| item/próprio | 1 | 0 | 0 | 0 | 0 | 0 | 1 |

Defeitos do leitor nos subníveis, normas limpas (16 padrões; os primeiros): (1) 4x
`par` não achado, `§2o.` (sem espaço, OCR "o" no lugar do ordinal; as 4 em `lei-01043`);
(2) 3x `inc` a mais, `II` / `-` partidos em duas linhas (`decreto-01013`, linhas 288-298,
tabela lida como incisos); (3) 3x `inc` não achado, `II -oprojeto` (sem espaço depois do
hífen, `lei-01043`); (4) 2x estado difere, `inc` próprio no modelo e citado no leitor
(`lc-00386`, linhas 36-40); (5) 2x `par` não achado, `s 2o` (o `§` lido como `s`,
`lei-00392`); (6) 2x `inc` não achado, `I-aação` (hífen colado); depois 1x cada: `s lo -`
(`§ 1º` com `§` lido como `s` e `1` como `l`), `Parágrafo único.` (estado), `§ 1°`,
`§ 45` (`§ 4º` com o ordinal como `5`), `§ Io.` (o `1` como `I`), parágrafo sem marcador
legível (`A/% /llS`), `Parágrafo único` no meio de uma frase (`lei-00884`, uma menção, o
leitor a mais), item `1 –` lido como inciso (`kind_differs`, `lei-01113`), `II` sem hífen.
Por onde: 10x `par` não achado no começo da linha, 6x `inc` não achado, 3x `inc` a mais e 1
`kind_differs`, 2 no meio da linha (a menção `Parágrafo único` que o leitor leu como
dispositivo e um parágrafo sem marcador legível). Os números têm pouco sinal (137 `par`, 114 `inc`, 18 `ali`): as
300 normas são para isso.

### Esboço: catraca por nível (implementada: ver `reader-ratchet.md`, "Gate por nível")

O esboço original (o gate real difere: referência commitada em forma compacta, unidade
(norma, nível), errata da referência em `docs/okf/mark-reference-errata.json`; a linha de
base é `docs/okf/mark-ratchet-baseline.json`). Esboço:

- **Referência**: os documentos do modo `mark` das 300 normas de
  `mark-reference-2026-11`, depois que uma **amostra** (por exemplo 60, todas as com
  discordância de subnível mais um terço do resto) for conferida por uma leitura do Sonnet
  (`mode=mark`, `model` mais forte, `effort=high`) e o que o Sonnet e o Haiku discordam
  for decidido por errata (como `teacher-label-errata.json`: correção presa ao sha256 do
  texto, evidência na linha). Documentos de normas com suspeita entram pela variante
  reparada ou ficam de fora da linha de base, explicitamente.
- **Linha de base**: `docs/okf/mark-ratchet-baseline.json` com, por nível
  (`art par inc ali item`) e por norma, o grupo de `compare_mark_reader` (`agree`, um
  defeito, `mixed`), a identidade do batch/texto da referência e o commit do leitor.
- **O portão, por nível**: FAIL se uma norma que concordava num nível (`agree` na
  linha de base) deixou de concordar nesse nível (ou deixou de ser comparada: texto
  ausente, sha256 divergente), com o nível e o grupo atual impressos; FAIL se uma norma
  tem num nível um defeito que não tinha. PASS com a tabela antes -> depois por nível e as
  normas que entraram em `agree`. `update` só sem regressão, ou `--force --reason`. Um
  nível pode melhorar enquanto outro piora só se o motivo ficar no histórico.
- **Insumos no CI**: o `reader-ratchet.yml` baixa os rótulos do IA; este baixaria o item do
  IA de `upload_ia` da execução de referência (documentos marcados, `records/`), sem
  chamar API. Mudar a referência (novo prompt, novo modelo, nova errata) é uma atualização
  da linha de base com motivo, nunca implícita.

## Simulação seca (sem API)

`scripts/simulate_mark.py` gera a resposta de um modelo perfeito a partir do leitor (de
uma variante `~reflow`, do texto-base), perturba âncoras (coluna ±1 em 5% das marcas; trecho
sem acento em 3%) e roda o pipeline de verdade (plano, manifesto, `collect_mark` com um
cliente de mentira, `score_mark`). Em 2026-11-18, com o v2 (A primária, confirmada por 4
caracteres):

- piloto (60 normas): 834 marcas, 60 de 60 `ok`; injetados 42 deslocamentos (5,0%) e 25
  acentos retirados (3,0%); A exato em 94,8% das 808 marcas de referência (os 42 são todos
  +1); a conferência de 4 caracteres pegou 42 de 42 A errados sem rejeitar nenhum A certo;
  âncoras usadas A/B 780/54; offset usado igual ao do leitor em 99,6%;
- estresse (40 normas `~reflow`): 576 marcas, 39 `ok` e 1 `degraded`; 29 deslocamentos e 17
  acentos retirados; offset usado igual ao do leitor em 97,0% (A 94,7%, B 99,2% das que
  resolvem), por coluna: 0-10 100%, 11-40 94%, 41-100 99%, 101-200 96%, 201-400 97%. Os
  erros que sobram são A deslocado em linha longa com o mesmo marcador várias vezes
  (`I -`, `a)`), onde o trecho é ambíguo e a conferência de 4 caracteres cai em letras
  iguais: é o que o modelo de verdade vai ou não repetir.

## Em aberto

- Marcador quebrado entre linhas e bloco que termina no meio de uma linha não têm
  convenção melhor que "primeira linha" e "fim da linha"; o piloto conta quanto isso custa.
- `estado="ausente"` (largura zero) não é pedido: não há âncora.
- Alteração cortada na fronteira de duas partes vira dois blocos adjacentes.
- Calibrar a estimativa: o piloto mediu US$ 0,0012 por norma (252 481 tokens de saída em
  60 requisições, 4 208 por requisição) contra 0,00105 estimado; a estimativa do `plan`
  continua usando os 2 070 tokens do `review` como base por requisição.
- Ato novo só por `epigrafe`/`ementa`/`preambulo` ou numeração que recomeça depois de
  `fecho`/`assinatura`; um arquivo de várias normas sem nada disso fica como um ato.
- `suspect_number` pega o ordinal lido como dígito só quando a sequência vizinha está
  certa (2 de 8 casos do piloto; os outros 6 estão num bloco já sinalizado).
