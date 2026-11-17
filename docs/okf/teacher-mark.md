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

Prompt `teacher-mark-v1` (`MARK_PROMPT_VERSION`). O texto completo está em
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
| `c` | **âncora A**: coluna (1-based) do primeiro caractere do marcador impresso |
| `t` | **âncora B**: o marcador como impresso (`Art. 5º`, `§ 2º`, `III -`, `a)`), copiado; é também o span do `<m>`. Em bloco, os primeiros ~15 caracteres. Sem marcador: as primeiras palavras da frase |
| `n` | número **interpretado**: arábico (`art par item`), valor do romano (`inc`, organizacionais), letra (`ali`), `"unico"`; `null` em bloco. O impresso nunca é alterado |
| `s` | sufixo do "5º-A" |
| `le` | linha final do bloco; `null` em dispositivo |
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
  se encontram: "5º" e "5o" do OCR). Várias ocorrências: `ambiguous`.
- **Política**: usar B quando resolve de modo único na linha (exato ou tolerante); senão A
  (coluna dentro da linha); senão a marca é descartada (`no_anchor`).
- Com A usado, o `<m>` tem o tamanho de `t` cortado no fim da linha; marcador quebrado
  entre linhas ("Art. \n29") é dado pela primeira linha.

## Montagem

1. Cada marca vira um offset; número, sufixo e `vetado` são validados (`bad_number`,
   `bad_suffix`); blocos precisam de `le` válido (`bad_end_line`, `empty_block`).
2. Ordem por posição; aninhamento por pilha de níveis: um dispositivo fecha os de nível
   igual ou inferior, um título fecha tudo abaixo dele, `epigrafe`/`ementa`/`preambulo`/
   `fecho`/`assinatura`/`anexo` fecham todos os dispositivos. `alteracao` e `anexo` são
   barreiras: dentro delas os dispositivos aninham à parte (citados por construção) e
   acabam no fim do bloco. O fim de um dispositivo é o início do que o fecha, sem espaços
   finais; o último vai até o fim do texto.
3. `<lei>`: do primeiro caractere não branco até o fim do corpo (antes do primeiro
   `fecho`/`assinatura`/`anexo`); sem nenhuma marca de norma, não há `<lei>`.
4. `build`. Em erro de aninhamento ou gramática, **a marca culpada é descartada e
   registrada** (`conflict`; entre as duas nomeadas cai a de menor prioridade: `nota`,
   `ruido`, `alteracao`, partes, títulos, dispositivos; empate, a segunda) e o documento é
   derivado de novo; a norma não falha. `strip(xml) == texto` é afirmado em todo documento
   (não pode falhar por construção); `verify` precisa passar, senão `build_failed`.

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
conjunto `main` rotulado (2 065 com texto igual ao da camada publicada): 30
`agree_closed` por terços de comprimento (10 curtas ≤ 34 linhas, 10 médias ≤ 85, 10
longas), 15 em que leitor ≠ professor (10 `disagree_open`, 5 `teacher_inconsistent`), 10
`agree_closed` com bloco citado, e 5 longas a mais (o OCR próprio não está no conjunto
rotulado: os rótulos foram feitos sobre o texto do IA). Excluídas as normas com mais de 4
partes. Estimativa do `plan` (claude-haiku-5-5, effort medium; 63 requisições): US$ 0,07,
teto US$ 0,29; o modo `label` para as mesmas normas: US$ 0,09 / 0,16.

Rodar (workflow `teacher-batch.yml`):

1. `step=plan`, `mode=mark`, `ids_file=mark-pilot-2026-11`, `shuffle_seed=20261118`,
   `model=claude-haiku-5-5`, `effort=medium`;
2. `step=submit`, os mesmos insumos, `max_usd=0.5`, `guard=ceiling`;
3. `step=collect` com `manifest_run_id` do submit (`upload_ia` opcional).

Plano local sem API: `uv run python -m leizilla.teacher_batch plan --mode mark
--text-source textos --textos textos.parquet --ids-file
docs/okf/review-samples/mark-pilot-2026-11.txt --shuffle-seed 20261118 --count-sample 0`.

## Ler a pontuação

```bash
uv run scripts/score_mark.py --run COLLECT_DIR --out OUT_DIR
```

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

## Simulação seca (sem API)

`scripts/simulate_mark.py` gera a resposta de um modelo perfeito a partir do leitor para
as 60 normas do piloto, perturba âncoras (coluna ±1 em 5% das marcas; trecho sem acento
em 3%) e roda o pipeline de verdade (plano, manifesto, `collect_mark` com um cliente de
mentira, `score_mark`). Em 2026-11-18: 808 marcas, 60 de 60 `ok`; foram injetados 40
deslocamentos (4,95%) e 24 acentos retirados (2,97%); a pontuação devolveu A exato em
94,89% das 783 marcas de referência (os 40 são todos +1, mesmo delta, 100% depois da
correção) e 24 marcas com B tolerante; a conferência de 4 caracteres pegou 40 de 40 A
errados sem rejeitar nenhum A certo.

## Em aberto

- Marcador quebrado entre linhas e bloco que termina no meio de uma linha não têm
  convenção melhor que "primeira linha" e "fim da linha"; o piloto conta quanto isso custa.
- `estado="ausente"` (largura zero) não é pedido: não há âncora.
- Alteração cortada na fronteira de duas partes vira dois blocos adjacentes.
- Calibrar a estimativa: não há medição de saída do modo `mark`; usa a do `review`
  (2 070 tokens por requisição) até o `summary.json` do piloto.
