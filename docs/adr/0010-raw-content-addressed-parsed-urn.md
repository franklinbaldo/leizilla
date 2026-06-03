# ADR-0010 — Raw é content-addressed, Parsed é URN-keyed, chaves de fonte são metadados

**Status**: Parcialmente superada (camada Raw) — ver [ADR-0011](0011-raw-identity-keyed-range-items.md)
**Data**: 2026-05-30
**Contexto**: M4 — Internet Archive consolidation (pós PR #74)
**Supersede**: linha "Raw (individual)" e "Raw (bundle ZIP)" de [ADR-0005](0005-ia-identifiers.md)
**Superada por**: a camada **Raw** desta ADR (content-addressed, itens
bucketizados por hash) foi substituída por
[ADR-0011](0011-raw-identity-keyed-range-items.md) — raw identity-keyed por
`(ente, fonte, tipo, número)`, arquivos content-addressed dentro do item. A parte
**Parsed é URN-keyed** permanece vigente.

## Contexto

PR #74 consolidou os uploads no Internet Archive (IA) de "1 item por lei" para
"1 item por range de 1.000", o que resolveu a fragmentação do catálogo. Porém a
implementação ancorou o **range** e o **nome de arquivo** no número de `coddoc`
(ex: `leizilla_ro_casacivil_5001-6000` / `005120.pdf`).

`coddoc` é a **chave primária do CMS da Ditel** — o sistema que serve a Casa
Civil de Rondônia. Não é um conceito de Rondônia, nem do Brasil: é idiossincrasia
de **uma fonte**. Planalto (federal) endereça por caminho de URL
(`/ccivil_03/leis/L8112.htm`); a Alesp (SP) tem outro esquema; algumas fontes não
têm índice sequencial nenhum. Promover `coddoc` a parâmetro de range/arquivo
hard-codifica o quirk de um scraper no catálogo nacional — no momento em que
Planalto entrar, `5001-6000` não significa nada.

A causa raiz é a confusão entre **dois sistemas de coordenadas distintos**:

- `coddoc` (e congêneres) — **chave de colheita**, existe no momento do crawl,
  é específica da fonte, **pré-parse**.
- norma (Lei 5.120/1999) — **identidade jurídica**, existe só **após o parse**,
  é pan-Brasil.

A camada *raw* vive no espaço de colheita; a camada *parsed* vive no espaço de
norma. O mapa entre os dois é **dado**, não fórmula. PR #74 tentou ser uma
fórmula determinística cruzando os dois espaços — daí o defeito.

## Decisão

### 1. Camada Raw → content-addressed

O endereço de um arquivo bruto é o **hash SHA-256 do seu conteúdo**, agnóstico de
fonte por construção. Quaisquer bytes de qualquer `fonte` recebem um hash; o
arquivo *é* o seu hash. A chave de colheita da fonte (`coddoc`, caminho do
Planalto, etc.) **nunca** aparece em path ou em fronteira de range — vira coluna
`source_key` no manifesto.

Benefícios que caem de graça: deduplicação (bytes idênticos → mesmo hash → mesmo
arquivo → no-op), imutabilidade e **código idêntico para toda fonte do país**.

| Item | Pattern | Exemplo |
|---|---|---|
| Raw range item | `leizilla-raw-{ente}-{fonte}-{bucket}` | `leizilla-raw-ro-casacivil-3f` |
| Raw file (dentro do item) | `{sha256}.{ext}` | `3f8a…d21c.pdf` |
| OCR derivado (IA) | `{sha256}_djvu.txt` | `3f8a…d21c_djvu.txt` |

`{bucket}` agrupa por prefixo de hash para manter contagem/tamanho de itens
limitados. A granularidade exata é a **única decisão em aberto** (ver abaixo).

### 2. Camada Parsed → URN-keyed (URN-LEX)

O Brasil já tem o padrão universal de identidade jurídica: **URN-LEX**
(`urn:lex:br;rondonia:estadual:lei:1999;5120`). Toda norma — federal, 26 estados,
DF, 5.570 municípios — tem uma. Esse é o sistema de coordenadas e o agrupamento
humano-legível da camada parsed, com **zero dependência** de como o documento foi
colhido. Mantém o padrão já definido em ADR-0005:

| Item | Pattern | Exemplo |
|---|---|---|
| Parsed range item | `leizilla-{ente}-{tipo}-{numero_range}` | `leizilla-ro-lei-05001-06000` |
| Parsed file | `{ente}-{tipo}-{numero:05d}-{ano}.xml` | `ro-lei-05120-1999.xml` |

O range parsed é bucketizado pelo **número da norma por tipo** — universal,
independente do `coddoc`.

### 3. A ponte é dado

O manifesto (e a linha correspondente no DuckDB) materializa as setas:

```
source_key (coddoc-05120) ──┐
                            ├─→ content_hash (3f8a…d21c) ──→ URN (urn:lex:…;5120)
captured_at (2026-05-30) ───┘        [raw]                       [parsed]
```

O crawler escreve `source_key → content_hash`. O parser escreve
`content_hash → URN`. Nenhuma das setas é computável; ambas são gravadas.

### 4. Cardinalidade

- **Uma norma → muitos arquivos raw.** Re-capturas ao longo do tempo (versões) e
  componentes do mesmo documento (PDF + DOCX + anexos). O hash diferencia bytes,
  **não** distingue versão de componente — quem distingue são `captured_at`
  (versão) e `content_type` (componente), ambos no manifesto.
- **`raw_id` identifica a chave de colheita** (uma `(ente, fonte, source_key)`),
  não uma norma e não uma captura. Uma captura é `(source_key, content_hash)`.
  Uma norma é construção pós-parse.

## Schema do manifesto

`filename,url` (estado atual pós-#74) é insuficiente — não é "proveniência", é o
**índice que torna a camada raw endereçável**. Colunas mínimas:

| Coluna | Descrição |
|---|---|
| `content_hash` | SHA-256 — endereço primário do arquivo raw |
| `filename` | `{hash}.{ext}` dentro do item de range |
| `source_key` | chave idiossincrática da fonte (ex: `coddoc-05120`) |
| `source_url` | URL original (Ditel/Planalto/Wayback) |
| `captured_at` | timestamp da captura — ordena versões |
| `content_type` | distingue componentes (PDF vs DOCX vs anexo) |

`fetch_ocr(source_key)` resolve via **lookup no manifesto** (fetch único por
range, cacheável — 1.000 chaves é um CSV trivial), seleciona a **captura corrente
no formato primário**, e retorna o `_djvu.txt` correspondente. Contrato continua
single-string; só a resolução deixa de ser fórmula e passa a ser consulta.

## Decisão em aberto (requer escolha)

Granularidade de bucket da camada raw:

- **Prefixo de hash** — content-addressing puro, generalidade perfeita,
  localização imprevisível sem o hash. Ex: 1 hex (`3`) = 16 buckets, 2 hex (`3f`)
  = 256 buckets por `(ente, fonte)`.
- **Contador de ingestão monotônico** do próprio Leizilla por fonte — ranges
  ordenados e limpos, agnóstico de fonte, mas adiciona um passo de atribuição de
  ID no ingest.

Esta ADR fixa o **princípio** (raw = content-addressed); a granularidade fica
para a issue de follow-up.

## Consequências

### Positivas
- Generaliza para qualquer fonte do Brasil sem código por-fonte na nomenclatura.
- Dedup e imutabilidade nativos via content-addressing.
- Camada parsed alinhada ao padrão nacional (URN-LEX) e a ADR-0005.
- Histórico de capturas imutável e auditável (missão de arquivo, não vazamento).

### Negativas
- Nomes de arquivo raw não são human-readable (hash). Mitigado: legibilidade é
  responsabilidade da camada parsed; o manifesto traduz hash ↔ source_key ↔ URN.
- Exige reescrever as partes coddoc-shaped de #74
  (`get_range_identifier`, `get_ia_filename`, `resolve_ia_id_to_url`) — todas
  recebem números derivados de `coddoc` como entrada.

## Implementação

Ver issue de follow-up: desfazer a nomenclatura coddoc-shaped de #74 e introduzir
manifesto content-addressed. Nenhum upload de produção foi feito sob o esquema de
#74, então não há migração de itens IA existentes.
