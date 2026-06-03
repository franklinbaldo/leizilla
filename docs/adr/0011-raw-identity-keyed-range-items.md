# ADR-0011 — Raw é capturado por contexto (content-addressed); o catálogo navegável é identity-keyed por (ente, fonte, tipo, número); identidade é evidência refinada a jusante, não catraca de ingestão

**Status**: Aprovada (revisada 2026-06-02 — ver "Revisão" abaixo)
**Data**: 2026-06-02
**Contexto**: M4 — Internet Archive, revisão do esquema raw (decisão do owner)
**Supersede**: a camada **Raw** de [ADR-0010](0010-raw-content-addressed-parsed-urn.md)
(itens bucketizados por prefixo de hash). Mantém intacta a parte **Parsed é
URN-keyed** de ADR-0010/[ADR-0005](0005-ia-identifiers.md).

## Revisão (2026-06-02) — identidade é evidência, não catraca

A primeira versão desta ADR tinha um **gate de ingestão "identidade ou nada"**:
recursos sem `(tipo, número)` extraível na descoberta eram **descartados**. Isso
foi revertido por confundir duas perguntas distintas e por contrariar o ethos de
preservação de [ADR-0001](0001-projeto-estatico-duckdb-torrent.md) (arquivar tudo:
storage do IA é grátis e permanente, fontes gov.br são frágeis):

1. **"Devemos capturar?"** é respondido pelo **contexto da descoberta**, não pela
   leitura do documento. Um recurso só aparece porque uma estratégia ciente de
   legislação apontou para ele — logo já há **evidência positiva de que é norma**
   antes de abrir o PDF.
2. **"Que norma é esta (tipo, número)?"** é extraído do **contexto da descoberta**
   (metadados / páginas que levam ao PDF) na grande maioria dos casos (>90%). Não é
   pré-condição de captura — e *não pode* ser no resíduo, já que aí o **próprio OCR
   do IA** é o que revela o número (galinha-e-ovo: sem upload não há OCR).

A decisão revisada (§1) preserva tudo o que se descobre e usa identidade para
**promover** ao catálogo navegável, não para barrar a entrada. As seções §2–§5
(itens navegáveis, arquivos content-addressed, `index.csv`, sem `-rN`) seguem
válidas — passam a ser a camada de **saída classificada**, não a catraca.

## Contexto

ADR-0010 tornou a camada raw **content-addressed**: o endereço de um arquivo era
o SHA-256 dos seus bytes, os itens IA eram bucketizados por prefixo de hash
(`leizilla-raw-ro-casacivil-3f`), e um `index.csv` mapeava a chave de colheita →
hash. Isso entregou agnosticismo de fonte e deduplicação por construção, mas a um
custo: **o catálogo ficou ilegível** (não dá para saber o que é `…-3f` sem abrir
metadados) e **toda leitura exige o índice**.

Para uma coleção de **legislação**, a unidade natural é a **norma**, e a tese do
owner é: *o mínimo para uma norma entrar na coleção é sabermos seu **tipo** e seu
**número**. Se sabemos, usamos como identidade; se não sabemos, não adicionamos.*

Isso é coerente com o resto do sistema, que já é identity-keyed:
`discovered_resources` guarda `tipo_documento`/`chave`; `discovery.parse_filename`
extrai `(tipo, número)` de nomes como `L5120.pdf → ("lei","lei-05120")`; a camada
parsed usa URN-LEX; a política de re-scrape do SCHEMA versiona por `{chave}-rN`.
A camada raw content-addressed era o ponto fora da curva.

**Reversão consciente de ADR-0010.** ADR-0010 argumentou que o número de
`casacivil` (`L{N}.pdf`) é o `coddoc` do CMS da Ditel — uma idiossincrasia de
fonte, pré-parse — e que promovê-lo a fronteira de range "não significa nada para
o Planalto". Aceitamos a premissa e mesmo assim escolhemos identity-keying,
porque **cada item é namespaced por `(ente, fonte, tipo)`**: `5001-6000` só
precisa significar algo dentro de `ro/casacivil/lei`; o Planalto recebe
`federal/planalto/lei_*`, com a sua própria numeração. Não há pretensão de uma
coordenada nacional uniforme na camada raw — essa é a função da camada **parsed
(URN-LEX)**, que permanece a identidade jurídica pan-Brasil.

## Decisão

### 1. Ingestão — capturar é dirigido por contexto; identidade é evidência, não catraca

Dois fatos distintos, que a versão original confundia num só "gate":

- **"Devemos capturar este recurso?"** — respondido na **descoberta, pelo
  contexto**. Um recurso só aparece porque uma estratégia ciente de legislação
  apontou para ele: um padrão de URL do manifesto, um template sequencial, um
  prefixo CDX, ou uma página de listagem cuja seção/âncora diz "Leis Ordinárias /
  Lei nº 5120". **Por construção, a estratégia já afirma "isto é uma norma"** —
  antes de abrir o PDF. Logo **capturamos os bytes** (content-addressed) e o
  **contexto de descoberta** como proveniência. A captura **nunca** é condicionada
  a extrair um número de uma chave.
- **"Que norma é esta — tipo, número?"** — extraído do **mesmo contexto**: nome de
  arquivo → número em casacivil; título da página → número na ALRO; caminho de URL
  → número no Planalto; linha/metadado da listagem → número. É *isto* que **promove**
  o recurso ao catálogo navegável identity-keyed (§2).

**Extrair a identidade do contexto é a tarefa primária da descoberta — e resolve a
grande maioria dos casos (>90%).** O número está nos **metadados ou nas páginas que
levam ao PDF**; a estratégia de descoberta **deve ler esse contexto** — não é um
sweep cego de URLs. Quando o contexto rende `(tipo, número)`, o recurso vai **direto
ao catálogo**. **"Sem número" não deveria acontecer na rota normal**; se acontece com
frequência numa fonte, é sinal de que a estratégia de descoberta daquela fonte
precisa ser **reforçada**, não de que devemos relaxar o catálogo.

O resíduo (<10%) — fontes cujo número **não** está no contexto — exige uma
**estratégia especial** por fonte (p.ex. baixar → OCR do IA → parse para ler o
número, ou heurística específica). Até resolver, esses bytes ficam **preservados**
numa área de espera content-addressed (`leizilla_{ente}_{fonte}_unidentified`),
onde o IA faz OCR; um passo de **reconciliação** os promove ao item de range. A
área de espera é a **exceção** (rede de segurança), não um depósito de rotina —
nunca há descarte. Os antigos fallbacks de lixo (`("documento","fallback-…")`,
`("lei","seq-NNNNN")`) somem: ou a identidade é extraída do contexto, ou o recurso
fica preservado aguardando reconciliação.

### 2. Item IA — range bucket por identidade

| | Pattern | Exemplo |
|---|---|---|
| Item raw | `leizilla_{ente}_{fonte}_{tipo}_{start:04d}-{end:04d}` | `leizilla_ro_casacivil_lei_5001-6000` |

Faixas de 1.000 por `(ente, fonte, tipo)`. `_` separa as seções; `-` é livre
dentro de uma seção (ex.: `lei-complementar`). O item é **navegável** — o nome
diz ente, fonte, tipo e faixa de números.

### 3. Arquivo — content-addressed por UUIDv5 truncado

Dentro do item, cada arquivo é nomeado por um hash determinístico do conteúdo:

```
uuid5_8 = str(uuid.uuid5(uuid.NAMESPACE_DNS, sha256_hex(bytes)))[:8]
```

| | Pattern | Exemplo |
|---|---|---|
| Arquivo bruto | `{uuid5_8}.{ext}` | `a1b2c3d4.pdf` |
| OCR derivado (IA) | `{uuid5_8}_djvu.txt` | `a1b2c3d4_djvu.txt` |
| Metadados | `{uuid5_8}_meta.json` | `a1b2c3d4_meta.json` |

Colisão só importa **dentro de um item** (escopo de ≤1.000 leis × poucas
rendições/capturas), onde a probabilidade é < 1%. O `index.csv` guarda o
**SHA-256 completo**, então uma colisão real (mesmo nome curto, bytes diferentes)
é **detectada na escrita** e tratada (estende o comprimento ou adiciona
discriminador) — nunca um overwrite silencioso.

### 4. `index.csv` por item — o mapa identidade → arquivo

Mapeia `(tipo, número, rendição, formato) → {uuid5_8, sha256, captured_at, source}`,
append-only, **newest-wins**. Rendição (`original`, `compilada`, `atual`, …) e
formato (`pdf`, `docx`, `html`) são **metadados no índice, não no nome do
arquivo**. Quando a rendição não puder ser classificada pela fonte, fica vazia
(`unclassified`) — o arquivo ainda é admitido (já é content-addressed).

A coluna **`source`** guarda a chave de colheita / URL de origem (ADR-0010): é
o que mapeia cada arquivo de volta à sua fonte. É justamente por o índice
preservar a proveniência que a **identidade pode descartar o `coddoc`** — o
índice de navegação da ALRO vira metadado em `source`, nunca a chave de identidade.

### 5. Sem `-rN`

Versionamento e dedup **caem de graça** do content-addressing dos arquivos:
bytes diferentes → hash diferente → arquivo novo coexistindo; bytes idênticos →
mesmo hash → no-op (dedup). "Versão corrente" = `captured_at` mais recente por
`(identidade, rendição, formato)` no índice. Não há sufixo de versão.

### 6. Parsed — inalterado

A camada parsed permanece **URN-keyed** (URN-LEX), conforme ADR-0010/ADR-0005.

## Consequências

- **Catálogo navegável** no nível do item; arquivos seguem opacos (hash), mas o
  `index.csv` os descreve por tipo/número/rendição.
- **Mantém os ganhos de ADR-0010 que importam**: dedup e imutabilidade, via
  content-addressing dos arquivos.
- **Numeração é por fonte**, namespaced por `(ente, fonte, tipo)`. Para
  `casacivil` o número é o do arquivo `L{N}.pdf` (que ADR-0010 nota ser o `coddoc`
  da Ditel); aceitamos isso porque não há colisão entre fontes e a identidade
  normativa nacional vive no parsed (URN-LEX).
- **Nada com evidência de descoberta é perdido.** Recursos sem número resolvido
  são preservados na área de espera `_unidentified` (content-addressed + OCR do
  IA), não descartados — alinhado ao ethos de arquivo da ADR-0001.
- **ALRO assembleia** entra normalmente: o título da página rende tipo+número na
  descoberta, então vai direto ao catálogo; títulos não-parseáveis ficam na área
  de espera até a reconciliação.
- **Requer** um classificador de rendição por fonte (rótulos do portal → vocab) e
  reescrita de `ia_utils`, `publisher` (identificadores + index com rendição),
  `parser` (resolução via index), `discovery` (captura por contexto, sem descarte),
  e a suíte de testes.

## Implementado

- **Passo de reconciliação** (`_unidentified` → item de range): o comando
  `leizilla reconcile` re-roda a descoberta com os extratores atuais (re-derivação
  **por contexto**), monta o mapa `source-URL → (tipo, número)` e promove os
  arquivos preservados agora identificáveis. Os bytes vêm do **IA** (item de
  espera), nunca do portal de origem (ADR-0004); a linha promovida sai do índice de
  espera via `remove_index_rows`.

## Em aberto

- **Reconciliação por OCR+parse** para o resíduo cujo número só existe no corpo do
  documento (o `<10%` que a re-derivação por contexto não cobre). A re-derivação
  por contexto já está implementada; falta a variante que lê o `_djvu.txt`.
- Capturar o **contexto de descoberta** como proveniência rica (estratégia/página
  que encontrou o recurso, âncora, seção) — hoje `source` guarda só a URL.
- Confirmar empiricamente se o número de `casacivil` (`L{N}.pdf`) coincide com o
  número da lei ou é o `coddoc` do CMS. Não bloqueia esta decisão (o item é
  namespaced por fonte), mas afeta a legibilidade dos ranges.
- Vocabulário canônico de rendições e o mapa rótulo-da-fonte → vocab.
