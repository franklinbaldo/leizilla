# ADR-0020 — Estrutura como anotação sobre o texto preservado

**Status**: Aceito (pelo proprietário, 2026-11-18)
**Data**: 2026-11-18
**Contexto**: nó `mark-reference-reader-tournament` e folhas `reader-compiled-texts` e `compiled-renditions-preservation` do DAG (`docs/okf/project-dag.md`)
**Relaciona-se com**: [ADR-0010](0010-raw-content-addressed-parsed-urn.md) (raw por conteúdo), [ADR-0011](0011-raw-identity-keyed-range-items.md) (identidade), [ADR-0015](0015-camada-de-texto-desacoplada.md) (camada de texto e adendo de 2026-11-18), [ADR-0017](0017-catalogo-oficial-como-produto.md) (catálogo), [ADR-0019](0019-targeted-reocr-via-kreuzberg.md) (re-OCR), `docs/SCHEMA.md`, `docs/okf/documento-marcado.md`, `docs/okf/textos-compilados.md`, `src/leizilla/marcacao.py`, `docs/schemas/leizilla-doc-v0.xsd`

## Status e contexto

Aceito pelo proprietário em 2026-11-18. O dono aprovou a estrutura deste ADR e decidiu em 2026-11-18 três pontos, marcados abaixo como "decidido": a estrutura (Decisões 1 a 7), as versões dos compilados alimentarem `versoes` (Decisão 3) e o texto de leitura ser o da compilada (Decisão 3).

O modelo atual (`docs/SCHEMA.md`, XML v0.1, tabela `versoes`) descreve **a norma no tempo**: dispositivos, versões de redação, vigência, revogação, fontes. Ele não guarda três coisas.

1. **O texto como foi preservado.** O `<texto>` de uma versão é texto canônico, normalizado. Nada liga um dispositivo ao trecho exato do arquivo que o IA guarda.
2. **A evidência da leitura.** Quando o leitor corrige um número ou deduz um artigo cujo marcador o OCR perdeu, o v0.1 não registra que isso aconteceu. A lei 369 de Rondônia perdeu os marcadores dos arts. 4º e 5º no OCR: o v0.1 não tem onde registrar que o artigo foi deduzido.
3. **As partes que não são artigo:** epígrafe, ementa, preâmbulo, fecho, assinatura, anexo, ruído de página. O v0.1 não tem onde pô-las.

Por isso o v0.1 não pode ser a primeira camada. Ele supõe que a leitura já aconteceu. A primeira camada precisa ser a própria leitura, verificável contra o texto.

A ideia dessa camada é do dono: **um XML que só insere tags no texto bruto**, aninhando em qualquer profundidade. Entre 2026-11-17 e 2026-11-18 ela foi implementada (PRs 380 a 393) e medida contra o acervo.

## Decisão 1 — o documento marcado é a fonte

O **documento marcado** é o texto preservado de uma norma com tags inseridas. Ele é a fonte da estrutura. Contrato completo em `docs/okf/documento-marcado.md`.

**Invariante do strip.** Remover todas as tags e o conteúdo dos elementos de anotação devolve o texto original, caractere por caractere. O sha256 do texto fica na raiz (`sha256-texto`). `marcacao.verify` confere as duas coisas, e `leizilla marcar` não emite documento que falhe.

**O que é permitido:**

- inserir elementos de estrutura: dispositivos (`art`, `par`, `inc`, `ali`, `item`), organizacionais, partes (`epigrafe`, `ementa`, `preambulo`, `fecho`, `assinatura`, `anexo`), `alteracao`, `ref`, `ruido`;
- marcar o marcador impresso com `<m>` ("Art. 5º", "§ 2º", "III -");
- codificar com `<c v="0C"/>` o caractere que XML 1.0 não carrega (o `strip` o restaura);
- deixar texto sem elemento dono (padrão reversível, ver "Fora do escopo");
- `<nota>`, o **único** elemento cujo conteúdo é nosso; o `strip` o remove com o conteúdo.

**O que não é permitido:** reescrever, copiar, normalizar, reordenar ou corrigir o texto; marcas que se cruzam (`OverlapError`); fechar e reabrir um elemento. Normalizar terminação de linha, se for desejado, é decisão do texto preservado, não da marcação.

Exemplo: na lei 369, os arts. 4º e 5º aparecem como `<art n="4" lido-por="gap" corrigido="true">- Esta Lei entra em vigor…</art>`, sem `<m>`, com as quebras de palavra do OCR intactas. O texto continua sendo o do arquivo; a leitura é uma camada sobre ele.

## Decisão 2 — a tabela de dispositivos é derivada

A tabela de dispositivos nunca é editada à mão. Ela sai do documento por `marcacao.to_rows`, uma linha por dispositivo e bloco organizacional, em ordem de documento.

- **O caminho não é escrito.** `art-5-par-2-inc-3` deriva do aninhamento e de `n`, pelo token map de `SCHEMA.md` §4.2. Dentro de `alteracao` o escopo recomeça; um `art-3` citado se distingue do próprio pela coluna `quoted`.
- **Colunas:** `path`, `kind`, `n`, `sufixo`, `parent_path`, `ordem`, `start`, `text_start`, `text_end`, `end` (deslocamentos em code points), `quoted`, `read_by`, `corrected`, `estado`, `marker`.
- **Visão "só o texto vigente":** `estado != 'superado'` (Decisão 6).
- **Correção** entra como marca nova, regra do leitor ou errata com evidência, nunca como edição da linha. A linha é função do documento; o documento é função do texto e das marcas.

## Decisão 3 — a lei compilada (XML v0.1 / `versoes`) é a segunda camada

O v0.1 e a tabela `versoes` continuam como o formato da norma no tempo e **não mudam de forma**. Passam a ser alimentados pelo documento marcado. O marcado diz onde as partes estão no texto preservado; o v0.1 diz o que a norma foi ao longo do tempo.

**Decidido (2026-11-18): as versões impressas dos textos compilados alimentam o histórico de redações da norma (`versoes`).** A Casa Civil já consolidou; ler essa consolidação é o caminho mais barato para ter as redações de uma norma emendada. Forma:

- cada impressão superada vira uma redação do mesmo dispositivo; a vigente é a última impressa (Decisão 6);
- a lei alteradora vem da nota oficial (`<ref rel="redacao" alvo="…">`); para virar `alterado_por` o `alvo`, hoje vazio, precisa ser resolvido para a norma citada;
- a compilada é consolidação da Casa Civil, não nossa. O portal já avisa isso (ADR-0015, adendo 2026-11-18), e `versoes` deve carregar a origem compilada como fonte da redação.

Este ADR não fixa o `inicio_tipo` dessas linhas nem a data `em` de cada redação; isso fica para a etapa de implementação.

**Também decidido (2026-11-18):** o texto de leitura exibido é o da rendição compilada quando existe; o original continua alcançável (ADR-0015, adendo 2026-11-18).

## Decisão 4 — número interpretado separado do impresso

O texto impresso nunca é alterado. O atributo `n` é a **interpretação**; o marcador como impresso fica dentro de `<m>`.

- "Art. 42" impresso entre o art. 3º e o art. 5º é o artigo 4: o texto mantém "42", o elemento diz `n="4"`. O mesmo vale para o ordinal lido como dígito ("Art. 92" por 9º; o piloto v1 leu 11 de 437 artigos próprios assim).
- Numeral romano: `III -` é `n="3"`; o romano fica no texto.
- Sufixo: `Art. 49-A` da LC 1174 é `n="49" sufixo="A"`. O professor do modo de rotulagem leu `4A`; o leitor, a referência e a revisão do Sonnet leram 49-A, pelo texto da linha 129.
- Parágrafo único: `n="unico"`.

**Evidência de quem leu:** `lido-por` recebe o `read_by` do leitor (`literal`, `confusion`, `gap`, `implicit-single`); `corrigido="true"` marca o número que difere do literal. Quem consome pode filtrar o que foi deduzido. Se `lido-por` fica em produção ou só em diagnóstico é pergunta em aberto.

## Decisão 5 — bloco transcrito por aninhamento

O trecho de outra norma que uma norma transcreve ("Fica acrescentado o parágrafo único ao art. 5º da Lei nº 891, com a seguinte redação: …") é envolvido por `<alteracao>`. **Não existe atributo "próprio" ou "citado"**: os dispositivos dentro do elemento são citados por construção, e `to_rows` deriva `quoted` da posição.

- `alteracao` cabe dentro de qualquer dispositivo e contém qualquer dispositivo; inclui a aspa que o abre; fica sob o dispositivo mais profundo que contém seu início.
- Um bloco que cruza fronteira de dispositivo não pode ser aninhado. O adaptador omite o `alteracao` e os dispositivos citados dentro dele, e registra o conflito. No acervo local isso não ocorreu: 684 blocos em 487 normas, 0 omitidos.
- `alvo` e `acao` existem no XSD como opcionais; o leitor ainda não os extrai.

## Decisão 6 — versões impressas de um mesmo dispositivo

Em um texto compilado, várias impressões do mesmo dispositivo são **versões dele**, não duplicatas nem texto citado. A Casa Civil imprime a redação superada de novo, sem marca, e a nova depois dela, encerrada por "(Redação dada pela Lei …)". O risco do PDF se perde na extração; sobram a posição e a nota.

- **Elemento:** a impressão anterior é o mesmo elemento (`n` igual) com `estado="superado"`, e também todos os dispositivos dentro dela. A vigente não leva `estado`.
- **Nota oficial:** `<ref rel="redacao|acrescimo|revogacao|veto|vide|outra">` em volta do parêntese impresso. É texto impresso e permanece no strip.
- **Sinal exigido:** impressões do mesmo número e sufixo no mesmo escopo, e ao menos uma impressão posterior com nota de alteração no próprio texto. "Acrescido" ou "revogado" sozinhos não bastam: não há texto anterior. Dispositivo revogado continua impresso e tem uma só versão. Renumeração não é versão (decreto-lei 9, art. 140).
- **Exemplo:** lei 5970, art. 1º, o texto original e quatro redações (18/2, 27/8, 2/9 e 1º/10/2025). O leitor conta o artigo uma vez; quem filtra `estado != 'superado'` vê uma só linha.
- **A convenção e seu limite:** "a vigente é a última impressa" é uma convenção da Casa Civil observada no gênero, **não uma garantia**. Foi observada nos 99 compilados do corpus; ainda não foi confirmada com o próprio documento oficial.

## Decisão 7 — referência e catraca

A leitura é conferida contra uma referência independente, e nada que a melhore pode piorar o que já concorda.

- **Modo `mark` (professor):** o modelo (Haiku) faz o parse completo e devolve **só as posições das marcas**, nunca o texto. O código resolve as posições, monta o documento com `marcacao.build` e confere o strip. Duas âncoras por marca: **coluna** (exata em linhas curtas do OCR) e **trecho citado** (a única que funciona em linha longa).
- **Referência:** 3.213 normas com parse completo (3.161 mais 52 gigantes, PRs 384, 386, 387, 392), com errata em `docs/okf/mark-reference-errata.json` (135 entradas hoje; 133 no PR 390). Cada errata traz evidência literal e o sha do texto; errata obsoleta falha.
- **Catraca por nível** (`scripts/reader_ratchet_levels.py`): a unidade é o par (norma, nível). Nenhum par que concorda pode sair. Nível vazio na referência e no leitor conta como concordância, em norma cuja referência tem artigos; leitor sem nenhum artigo na norma é `reader_blind`, nunca concordância (PR 392). Os textos vêm de uma revisão fixa de `textos.parquet`, casados por sha256.
- **Torneio de regras:** cada regra é julgada sozinha: catraca de artigos passa, catraca por nível sem perda, ao menos uma unidade ganha, precisão de 0,90 nos dispositivos novos. 53 regras promovidas: 46 até a rodada 16, quando saturou, mais 1 (rodada 17, artigo implícito), 3 (rodadas 18 a 20, resíduo do Sonnet) e 3 (rodada 21).
- **Divisão de teste:** 20% das normas (636 das 3.161), que o torneio não olha. O ganho em teste é menor que o de treino.
- **Revisão do resíduo (Sonnet):** nos ajustes que ele devolveu, 42 de 42 lidos estavam certos. Os silêncios não valem: em 16 de 16 omissões do leitor amostradas, o leitor calou e a referência estava certa.

## Evidência medida

| Medida | Resultado | Fonte |
|---|---|---|
| Strip + sha256 da raiz | 2.970 de 2.970 textos; repetido nos 99 compilados | PRs 380, 393 |
| Válidos no XSD (xmllint) | 2.970 de 2.970 | PR 380 |
| Ida e volta `parse(build(marcas)) == marcas` | 2.970 de 2.970 | PR 380 |
| Variante hostil (CRLF, `\f`, NUL, U+FFFE…) | 2.970 de 2.970 | PR 380 |
| Tamanho do marcado | 1,24× o texto (mediana); p90 1,41× | `documento-marcado.md` |
| Piloto Haiku, 60 normas, coluna + trecho | v1: 1.514 marcas, coluna exata em 1.494 de 1.494, US$ 0,0724. v2: coluna exata em 1.545 de 1.546, US$ 0,0748. Quase todas as marcas estão nas colunas 0 a 10: a coluna nunca foi testada no meio de linha longa | `teacher-mark.md` |
| Estresse (variante sintética, linhas de 200 a 400), coluna + trecho | 48 de 48 truncadas (40 com esforço médio, 8 com baixo) | `teacher-mark.md` |
| Sonda só com trecho, as mesmas 8 normas | nenhuma truncada: 113 marcas, 84 usadas, 29 descartadas como conflito (não investigadas), 8 `degraded`. É uma rodada de 8, sem repetição nem controle: indica, não prova, que contar colunas é a causa | `teacher-mark.md` |
| Gigantes com linha longa, só trecho | 3 de 3 marcadas | `teacher-mark.md` |
| Etiquetador aprendido contra o leitor, 418 normas retidas, F1 de todos os níveis | leitor 0,938; MLP 0,819; melhor modelo (BiGRU fatorado) 0,835. Em citação (`status`): leitor 0,789, MLP 0,378 | `reader-ratchet.md` |
| Híbrido leitor + modelo, precisão / revocação | leitor 0,970 / 0,909; filtro 0,974 / 0,885; acréscimo 0,970 / 0,911 | `reader-ratchet.md` |
| Bisseção de linhas longas | em linha, F1 0,911 com 9,8× as linhas de trabalho; em caractere, revocação 0,576 contra 0,919 do passe único, com 17,7× as chamadas | `reader-ratchet.md` |
| Revisão Sonnet do resíduo | 79 normas + 16 canários; US$ 0,80 medidos (2,03 estimados) | PR 390 |
| Artigo implícito (decreto de dispositivo único) | 8 normas, 8 de 8 certas por leitura | PR 389 |
| Compilados: artigos fecham, desenho | 29 → 67 de 72 | PR 393 |
| Compilados: artigos fecham, retidas | 11 → 23 de 27 | PR 393 |
| Camada publicada: artigos fecham | 3.481 → 3.500 de 3.616 | PR 393 |
| Custo medido da API do professor | US$ 5,7561 em 14 coletas; é um piso (coleta que falha antes de imprimir custo não entra) | `medicoes-2026-11.md` |

Unidades (norma, nível) que concordam com a referência de 3.161 normas, depois do PR 390 (antes da mudança de critério do PR 392):

| Nível | Concordam |
|---|---|
| art | 3.021 de 3.126 |
| par | 1.581 de 1.685 |
| inc | 794 de 973 |
| ali | 250 de 317 |
| item | 13 de 58 |

**Testado e descartado, com números na tabela acima** (registrado em `reader-ratchet.md` e `medicoes-2026-11.md`; o material bruto não foi preservado e não se reproduz a partir do repositório): etiquetador de linhas aprendido, bisseção de linhas longas, híbrido aprendido + regras, e âncora de coluna em linha longa (substituída por trecho).

## Consequências

**Fica mais fácil.** A estrutura é verificável: qualquer documento prova que o texto não foi tocado. O leitor por regras tem uma régua por nível, e uma regra nova se aceita ou se recusa por medida. O histórico de redações de uma norma emendada tem fonte barata: a consolidação já impressa. A leitura mostra o que foi deduzido (`lido-por`).

**Fica mais difícil.**

- Há duas camadas a manter coerentes; a conversão do marcado para o v0.1 (e para `versoes`) precisa de regras próprias.
- O documento está preso à revisão do texto: o sha256 na raiz muda se o texto muda (novo re-OCR, outra rendição). O marcado se regenera; não se remenda.
- Para alimentar `versoes` é preciso resolver `ref@alvo` até a norma alteradora.
- Nenhuma das 3.213 normas da referência é compilada; as leituras de compilados não estão travadas pela catraca por nível.
- Norma que não fecha por defeito do arquivo oficial (lei 1296: o escaneado oficial salta do art. 2º para o art. 6º) é registrada com evidência em `docs/okf/defeitos-da-fonte.json` e continua sem fechar; o re-OCR não tem o que ganhar.

**O que muda em `docs/SCHEMA.md` e no XSD com a aceitação** (feito no PR que traz este ADR, exceto o que fica como decidido e não implementado):

- `SCHEMA.md` §0.1 e §4: situar o documento marcado como primeira camada e o v0.1 como segunda; §0.1 hoje diz que a lei é uma árvore de dispositivos com versões e não menciona o texto preservado.
- `SCHEMA.md`: contrato da tabela derivada de dispositivos (as colunas de `to_rows`) e a ligação com `textos` por `texto_id` e sha256.
- `SCHEMA.md` §3.1 e §4: como redações vindas de compilados entram em `versoes` (`alterado_por`, `inicio_tipo`, fonte compilada).
- `SCHEMA.md` §8: registrar as decisões e as perguntas em aberto abaixo.
- XSD: `estado="superado"` e `ref@rel` já constam em `leizilla-doc-v0.xsd` (PR 393); falta decidir se o atributo `versao` da raiz sobe de 0 para 1 e se `alvo` de `ref` ganha regra de forma.
- `documento-marcado.md` e `textos-compilados.md`: trocar "aguarda o ADR-0020" por referência a este ADR (feito).

## Fora do escopo e perguntas em aberto

- **Item pontuado ("2.1")**: o XSD não o suporta. No nível `item`, 13 de 58 unidades concordam; decisão de esquema antes de qualquer trabalho do leitor.
- **Tabelas lidas como dispositivos** e anexos orçamentários. As quatro normas com mais de 40 partes (corpo de 1,5% a 5% do texto) ficam fora de rodada.
- **Vários atos num só arquivo** (lei-00131, decreto-01004, lc-01164, lei-06284) e cópias repetidas.
- **Decisões judiciais que transcrevem leis** (lei-04989, lei-04984, lei-01635).
- **Dispositivo sem marcador impresso** (artigo implícito de decreto de dispositivo único) como pergunta de modelagem: hoje é `<art n="1" lido-por="implicit-single">` sem `<m>`. Seis decretos sem fórmula de promulgação seguem abertos de propósito.
- **"A última impressão é a vigente"**: precisa de sobrescrita por norma? Hoje é só convenção.
- **Fonte-texto nascida digital: SEI.** Para leis e decretos assinados no SEI, obter o HTML original como texto-fonte em vez de PDF/OCR; o documento marcado partiria de texto limpo. RFC-0008 (proposto): os identificadores do SEI já estão guardados como proveniência em `textos` (1.074 de 3.616 linhas). O acesso ao HTML original ficaria no repositório `ies` (ler documento público do SEI sem autenticação); o Leizilla o consumiria e preservaria o HTML como mais uma rendição. Das rotas públicas sondadas na instância de Rondônia, a conferência e a pesquisa pública têm captcha; Publicações Eletrônicas não tem na página do formulário (o que ela devolve não foi verificado). Captcha nunca é resolvido nem contornado.
- **Padrões reversíveis** (escolhas de v0, trocáveis sem dor): nomes curtos das tags, texto sem dono tolerado, `<nota>` inline em vez de bloco no fim.

## Plano em etapas

**Já integrado:**

1. PRs 378 e 379: modo de revisão do professor.
2. PR 380: documento marcado v0, XSD, `marcar` e `marcar-verificar`.
3. PRs 381 a 384: modo `mark`, montador v2, âncora por trecho, segunda leitura conferida.
4. PR 385: catraca por nível e primeiras 12 regras.
5. PRs 386 a 388: camada inteira, referência de 3.161 normas, torneio (rodadas 1 a 16).
6. PR 389: artigo implícito; frente registrada no DAG.
7. PR 390: revisão do resíduo com o Sonnet, erratas, rodadas 18 a 20.
8. PR 392: compilada como texto de leitura, gigantes na referência, níveis vazios na catraca.
9. PR 393: versões impressas de um dispositivo; fila `sem-texto` olha a rendição de leitura.
10. Aceitação deste ADR (2026-11-18): arquivo em `docs/adr/`, `SCHEMA.md` e os dois documentos operacionais atualizados.

**Em seguida, nesta ordem:**

1. Resolver `ref@alvo` até a norma alteradora.
2. Alimentar `versoes` com as redações dos compilados (decisão 3).
3. Delimitar no leitor as partes que o marcado já declara (epígrafe, ementa, preâmbulo, fecho, assinatura, anexo, ruído) para reduzir o texto sem dono.
4. Pôr normas compiladas na referência, para a catraca por nível travar essas leituras.
5. Folhas abertas do DAG: o resíduo (a1 a a5), as 57 normas com mais de 8 partes (rodada paga, a disparar pelo dono) e fixar os rótulos do professor num item durável do IA antes de 2027-02-14.
6. Frente do HTML do SEI: decidir a RFC-0008 (issue no `ies`, rota sem captcha) e depois consumir o HTML como rendição.
