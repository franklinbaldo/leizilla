# ADR-0011 — Raw é identity-keyed por (ente, fonte, tipo, número); arquivos content-addressed dentro do item; só se admite o que sabemos identificar

**Status**: Aprovada
**Data**: 2026-06-02
**Contexto**: M4 — Internet Archive, revisão do esquema raw (decisão do owner)
**Supersede**: a camada **Raw** de [ADR-0010](0010-raw-content-addressed-parsed-urn.md)
(itens bucketizados por prefixo de hash). Mantém intacta a parte **Parsed é
URN-keyed** de ADR-0010/[ADR-0005](0005-ia-identifiers.md).

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

### 1. Gate de ingestão — identidade ou nada

A identidade de ingestão é `(ente, fonte, tipo, número)`, extraída na descoberta.
**Reject-until-identified**: recursos sem `(tipo, número)` — p.ex. o browse por
`coddoc` puro da ALRO assembleia — **não** são adicionados; são descartados e
logados até que a descoberta produza tipo+número. Isso **elimina os fallbacks de
lixo** atuais (`("documento","fallback-…")`, `("lei","seq-NNNNN")`).

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
- **ALRO assembleia (coddoc puro) fica deferida** até a descoberta extrair
  tipo+número (ou até mapearmos coddoc→norma via parse).
- **Requer** um classificador de rendição por fonte (rótulos do portal → vocab) e
  reescrita de `ia_utils`, `publisher` (identificadores + index com rendição),
  `parser` (resolução via index), `discovery` (gate + remoção dos fallbacks), e a
  suíte de testes.

## Em aberto

- Confirmar empiricamente se o número de `casacivil` (`L{N}.pdf`) coincide com o
  número da lei ou é o `coddoc` do CMS. Não bloqueia esta decisão (o item é
  namespaced por fonte), mas afeta a legibilidade dos ranges.
- Vocabulário canônico de rendições e o mapa rótulo-da-fonte → vocab.
