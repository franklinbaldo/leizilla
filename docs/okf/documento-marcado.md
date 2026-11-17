---
type: Contrato
title: Documento marcado — o texto preservado com tags inseridas
description: Segunda camada XML (v0) ao lado do Leizilla XML v0.1. O texto cru de uma norma, intocado, com tags inseridas; invariante do strip, elementos, convenções de span e o que ainda está em aberto.
tags: [documento-marcado, xml, leitor, invariante, marcacao]
timestamp: 2026-11-17T00:00:00Z
---

## A ideia

O **documento marcado** é o texto preservado de uma norma (o arquivo como o IA o guarda,
ou a linha `textos.texto`) com tags **inseridas** nos lugares certos. Nada é reescrito,
copiado ou normalizado: só entram tags. O aninhamento expressa a hierarquia em qualquer
profundidade (a lei tem artigos; artigos têm parágrafos e incisos; incisos têm
alíneas...).

É um tipo de documento **novo**, ao lado do Leizilla XML v0.1
([SCHEMA.md §4](../SCHEMA.md)), que descreve a norma no tempo (versões, vigência,
revogação, fontes) e **não muda**. O marcado descreve onde as partes estão no texto
preservado; o v0.1 diz o que a norma foi ao longo do tempo.

Código: `src/leizilla/marcacao.py`. Gramática: `docs/schemas/leizilla-doc-v0.xsd`.
CLI: `leizilla marcar` e `leizilla marcar-verificar`.

## A invariante

> Remover todas as tags (e o conteúdo dos elementos de anotação) devolve o texto
> original, caractere por caractere. O sha256 do texto está na raiz.

`verify(xml, texto)` confere as duas coisas. A invariante vale sobre o **dado de
caracteres já interpretado** (depois de decodificar entidades), não sobre os bytes
serializados. Consequências, todas decididas em v0:

- `&`, `<`, `>` saem como `&amp;`, `&lt;`, `&gt;`.
- O que XML 1.0 não carrega (C0 exceto tab e LF: form feed `\f`, NUL..., U+FFFE/U+FFFF,
  surrogates soltos) e o que o parser reescreveria (`\r`: `\r\n` viraria `\n`) vira o
  elemento vazio `<c v="0C"/>` (code point em hexadecimal, maiúsculas, 2 a 6 dígitos). O
  `strip` o restaura. Reversível e exato; terminações de linha preservadas.
- U+007F e U+0080..U+009F são válidos em XML 1.0 e ficam como estão.
- Um texto com `\r\n` vira muitos `<c v="0D"/>`: correto, só barulhento. Se isso
  incomodar, normalizar terminações de linha é decisão do **texto preservado**, não da
  marcação.

## Elementos

Raiz: `<documento versao="0" sha256-texto="…" texto-id="…">` (`texto-id` opcional;
`versao` é acrescentada por segurança de evolução). Dentro, um ou mais `<lei tipo numero>`
(normalmente um); texto fora de qualquer `<lei>` é permitido (assinatura, rodapé de
página depois do corpo).

| Grupo | Elementos | Atributos |
|---|---|---|
| Dispositivos | `art`, `par`, `inc`, `ali`, `item` | `n`, `sufixo`, `lido-por`, `corrigido`, `estado` |
| Organizacionais (declarados; o leitor ainda não os emite) | `parte`, `liv`, `tit`, `cap`, `sec`, `subsec` | idem |
| Partes (declaradas; o leitor ainda não as delimita) | `epigrafe`, `ementa`, `preambulo`, `fecho`, `assinatura`, `anexo` | `anexo`: `n` |
| Texto de outra norma | `alteracao` | `alvo`, `acao` (opcionais, ainda não emitidos) |
| Citação / não-norma | `ref` (`alvo`), `ruido` | declarados; ainda não emitidos |
| Anotação nossa | `nota` (`por`, `tipo`) | o **único** cujo conteúdo é nosso; o `strip` o remove com o conteúdo |
| Marcador | `m` | o marcador como impresso ("Art. 5º", "§ 2º", "III -", "a)") |
| Caractere | `c` (`v`) | code point que XML não carrega |

- **`n` é o número interpretado**: arábico em `art`/`par`/`item`, o valor do numeral
  romano em `inc` (o romano impresso fica no texto: `III -` é `n="3"`), a letra em `ali`,
  `n="unico"` para parágrafo único. O texto impresso nunca é alterado: "Art. 42" fica no
  texto e o elemento diz `n="4"`. `sufixo` é a letra do artigo "5º-A".
- **`<m>`**: ausente quando o marcador não era legível (número deduzido). O elemento sem
  `<m>` começa onde o leitor diz que o dispositivo começa.
- **Evidência** (opcional): `lido-por` é o `read_by` do leitor (`literal`, `confusion`,
  `gap`); `corrigido="true"` quando o número interpretado difere do literal.
- **Ausência declarada**: elemento vazio `<art n="4" estado="ausente"/>` (largura zero) ou
  `estado="vetado"` num elemento com conteúdo.
- **O caminho não é escrito**: `art-5-par-2-inc-3` (token map, SCHEMA.md §4.2) deriva do
  aninhamento e de `n`. `to_rows` o devolve (visão tabular "dispositivos").
- **`alteracao`**: envolve um bloco transcrito de OUTRA norma. Os dispositivos dentro dele
  são citados por construção; não existe atributo próprio/citado. Cabe dentro de qualquer
  dispositivo (art, par, inc, ali, item); contém qualquer dispositivo.

### Gramática de níveis

`art ⊃ par | inc | ali | item`; `par ⊃ inc | ali | item`; `inc ⊃ ali | item`;
`ali ⊃ item`. Organizacionais aninham de fora para dentro (parte, liv, tit, cap, sec,
subsec) e contêm artigos. `ruido`, `ref` e `nota` cabem em qualquer lugar; `anexo`
cabe também dentro de um dispositivo (tabela entre dois parágrafos de um artigo, o
caso do documento que o modo mark do professor monta; o leitor não o emite). A fonte da
verdade é `marcacao.children_allowed`; `tests/test_marcacao.py` compara o XSD com ela.

### Sobreposição

XML não sobrepõe. Os spans do leitor formam uma árvore, e `build` recusa marcas que se
cruzam, nomeando as duas (`OverlapError`). Fechar e reabrir **não** é permitido (muda a
semântica). Para um bloco citado que cruze limites de dispositivos, o adaptador
`from_hierarchy_ex` omite aquele `<alteracao>` **e os dispositivos citados dentro dele**,
e registra o conflito em `Adaptation.dropped`. No corpus local isso não ocorreu nenhuma
vez (ver abaixo).

## Convenções de span (v0)

Offsets são code points Unicode sobre o texto, a mesma unidade das `ancoras`.

- Marcador `<m>` = `[start, start + len(raw))` do nó do leitor.
- Elemento = `[start, end)` do leitor **sem os espaços finais**: o espaço entre dois
  dispositivos pertence ao pai.
- Artigo recuperado de uma frase de encerramento (marcador perdido, `raw == ""`): sem
  `<m>`; o elemento começa no início da frase, onde o leitor põe `start`.
- `<lei>`: do primeiro caractere não branco até o fim do corpo (`body_end` do leitor, ou
  o fim do último dispositivo). O que vem depois (data, assinatura, rodapé) fica fora da
  `<lei>`, dentro de `<documento>`. Texto sem artigo próprio não ganha `<lei>`.
- `<alteracao>` fica sob o dispositivo mais profundo que contém seu início (o mesmo pai que
  o leitor dá ao bloco citado); inclui as aspas que o abrem.
- Elemento de largura zero fora de qualquer fronteira estrita: vai para o elemento aberto
  mais interno cuja gramática o admite (uma ausência `art` entre o fim do art. 1 e o
  início do art. 3 cai dentro de `<lei>`).

## Exemplo real: lei 369 de Rondônia

`leizilla-raw-ro-casacivil-lei-00369` (item IA com `68257596` no nome). Os dois últimos
artigos tiveram o marcador perdido no OCR; o leitor os recupera pela sequência (1, 2, 3 e
depois exatamente dois enunciados de encerramento), então eles não têm `<m>` e levam
`lido-por="gap" corrigido="true"`. O texto abaixo é o do arquivo, intocado (inclusive as
quebras no meio das palavras do OCR). Fixture:
`tests/fixtures/documento_marcado/lei-00369.xml`.

```xml
<documento versao="0" sha256-texto="3df95810381a6f3e4c6cae5ee1093c9eca403c812f77c3a1fc9ff1819d20d1c6" texto-id="leizilla-raw-ro-casacivil-lei-00369"><lei tipo="lei" numero="369">GOVERNO DO ESTADO DE RONDÔNIA 
GOVERNADORIA 


369 DE 13 DE FEVEREIRO DE 1992. 


Cria o município de Mirante da Serra, 
desmembrado do município de Ouro Pre 
to D'Oeste. 


O GOVERNADOR DO ESTADO DE RONDÔNIA , faço 
saber que a Assembléia Legislativa decreta e eu sanciono a seguin 
te Lei: 


<art n="1" lido-por="literal"><m>Art. 1º</m> - Fica criado o município de Mi 
rante da Serra, com sede na cidade do mesmo nome, desmembrado da 


área territorial do município de Ouro Preto D'Oeste.</art> 


<art n="2" lido-por="literal"><m>Art. 2º</m> - O municipio de Mirante da Serra, 
tem seus limites assim definidos: partindo do cruzamento da 1i 
nha 172 com o rio Urupá, sobe por este rio até suas nascentes na 
chapada da serra dos Pacaás-Novos, divisor de águas Guaporé / Ji- 
-Paranã ou Machado; prossegue pela chapada da serra dos Pacaás- 
-Novos até a cumeada da serra do Mirante; segue por esta cumea 
da no divisor de águas Jaru/Urupá até a cabeceira do Ribeirão 
Trincheiras; desce por este até encontrar o prolongamento da Ee 
ta que, partindo da cabeceira do igarapé Esmeril, atinge o igara 
pé Paraiso, no ponto de encontro com o paralelo 10221'16";dai pe 
la citada reta até encontrar o prolongamento da linha 50; segue 
a linha 50 até a linha 172; por esta linha até o rio Urupá, pon 
to de partida.</art> 


<art n="3" lido-por="literal"><m>Art. 3º</m> - A instalação do município ora 
criado, dar-se-ã com a posse do Prefeito, Vice-Prefeito e Verea 
dores eleitos na forma da Lei, nos termos do art. 108, da Consti 


tuição Estadual.</art> 


<art n="4" lido-por="gap" corrigido="true">- Esta Lei entra em vigor na data 


de sua publi</art> 


<art n="5" lido-por="gap" corrigido="true">- Revogam-se as disposições em con 


trário. 


GOVERNO DO ESTADO DE RONDÔNIA 
GOVERNADORIA 


02.</art></lei> 


Palácio do Governo do Estado de Rondônia, 
em 13 de fevereiro de 1992, 104º da República. 


OSWALDO| P A FILHO 


Governador 


</documento>
```

Observações sobre o exemplo: o cabeçalho e o preâmbulo ("Cria o município...", "O
GOVERNADOR...") estão dentro de `<lei>` e fora de qualquer dispositivo (texto sem dono,
v0 o tolera e o conta); o rodapé repetido do OCR ("GOVERNO DO ESTADO DE RONDÔNIA...")
ficou dentro do art. 5 porque o leitor só delimita o corpo até `body_end`; a data e a
assinatura estão fora de `<lei>`.

## O que o XSD verifica e o que o `verify` verifica

O XSD (`docs/schemas/leizilla-doc-v0.xsd`, sem namespace em v0, conteúdo misto) verifica
a gramática de níveis, os atributos (forma de `n`, `estado`, `sufixo`, `sha256-texto`,
`v` de `<c>`) e a obrigatoriedade de `n` nos dispositivos. Ele **não** consegue verificar:

- a invariante do strip (texto idêntico, sha256 da raiz);
- a numeração: `n="unico"` só em `par`, letras só em `ali`, no máximo um `<m>` por
  elemento, elemento vazio só com `estado`, `estado="ausente"` só em elemento vazio.

`marcacao.verify(xml, texto)` verifica tudo isso e devolve a lista de problemas (com o
primeiro offset divergente e 40 caracteres de contexto). `leizilla marcar` não emite um
documento que falhe em `verify`. O workflow `schema-validate.yml` valida as fixtures em
`tests/fixtures/documento_marcado/` contra o XSD.

## Prova no corpus local (2026-11-17)

Leitor → marcas → `build` → `verify` em todo texto local: os 2.086 do cache do professor
mais as linhas do `textos.parquet` do holdout, sem duplicar sha256 (2.970 textos, 15,5 MB).

- strip: 2.970 de 2.970 (100%); sha256 da raiz confere em todos; 0 falhas.
- XSD (xmllint): 2.970 de 2.970 válidos.
- `parse(build(marcas)) == marcas`: 2.970 de 2.970. Conjunto de artigos próprios de
  `to_rows` igual a `own_articles(report)`: 2.970 de 2.970; caminhos de `to_rows` iguais
  aos do leitor (próprios e citados): 2.970 de 2.970.
- `alteracao`: 684 blocos em 487 normas; 0 omitidos por sobreposição.
- 46.793 marcas; 2.947 normas com `<lei>` (23 sem artigo próprio, sem `<lei>`).
- texto sem dono dentro de `<lei>` (caracteres não brancos fora de qualquer artigo): média
  30%; mediana 29%; p10 7%; p25 16%; p75 42%; p90 55%; p99 71%. É sobretudo cabeçalho,
  ementa e preâmbulo (v0 não os delimita).
- tamanho: o documento marcado tem em mediana 1,24x os bytes do texto (p90 1,41x);
  sobrecarga mediana de 424 bytes por norma.
- caracteres que precisaram de codificação no corpus: `&` (1.521 em 378 textos), `<` (569
  em 310), `>` (1.245 em 463). Nenhum controle C0, form feed ou `\r` apareceu no corpus.
  Para exercitar o caminho, a prova repete os 2.970 textos em variante hostil (CRLF, um
  form feed a cada 2.500 caracteres, NUL, U+0001, U+FFFE, U+007F, U+0085): 2.970 de 2.970
  passam, com 922.227 `\r` e 4.553 `\f` codificados.
- tempo total: 4,8 s com 4 processos.

## O que é v0 e o que não está decidido

Decidido em v0 (código e testes): invariante, `<c>`, gramática de níveis, convenções de
span acima, `lei`/`alteracao`/dispositivos emitidos pelo leitor.

Ainda não decidido (escolhas do dono; o texto e o código foram escritos para mudar
depois sem dor):

1. **Nomes das tags.** Curtos (`art`, `par`, `inc`, `ali`, `m`, `c`). Trocar é mudar
   `KINDS`/`children_allowed` e regenerar o XSD; nada mais conhece os nomes.
2. **Texto sem dono é permitido?** Em v0 sim, tolerado e contado (conteúdo misto em todo
   lugar). Proibi-lo exigiria `epigrafe`, `ementa`, `preambulo` e `ruido` emitidos pelo
   leitor, que ainda não os delimita.
3. **Notas inline ou em bloco.** Em v0 `<nota>` fica inline em qualquer elemento. Um bloco
   `<notas>` no fim do documento (com offsets) teria o `strip` mais simples e evitaria
   marcação no meio do texto.

Outros pontos em aberto: namespace do XSD (v0 sem); `alteracao` com `alvo`/`acao` (o
leitor ainda não os extrai); atributo `lido-por` ser mantido em dispositivos de
produção ou só em diagnóstico; se `<lei>` deve cobrir o cabeçalho (hoje cobre); onde
termina o corpo quando há anexos (hoje em `body_end`).
