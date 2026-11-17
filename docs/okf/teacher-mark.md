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

## Suspeitas (v2): sinalizar, nunca consertar

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

`marked/<item>/<tipo>-NNNNN_<uuid5>.xml` (um documento por norma), `records/…json`
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
norma-base (não as poucas linhas).

`score_mark` (bloco "Stress set"): a verdade é o offset do marcador do leitor lido sobre
o texto original e levado à variante, para os dispositivos casados por linha, tipo e
número; taxa de A exato, de B exato e do offset usado, por coluna do marcador na linha
(0-10, 11-40, 41-100, 101-200, 201-400, 401+) e por haver ou não não-ASCII antes. Seco
(`simulate_mark.py` com este arquivo, A deslocado em 5%): ver abaixo.

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
