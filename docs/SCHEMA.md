# SCHEMA.md — Design de dados do Leizilla

> Decisões load-bearing sobre granularidade de IA items, layout de bundles, schema Parquet v1, schema LeiML v0.1, e naming. Este documento é editado quando uma decisão muda — a coluna **Status** indica se está `proposta`, `aprovada`, ou `superseded-by-#PR`.

Companion docs:
- `IMPLEMENTATION.md` (raiz) — status geral e log de decisões cronológico
- `docs/adr/0005-ia-identifiers.md` (a criar em M1) — formalização normativa
- `docs/schemas/leiml-v0.1.xsd` (a criar em M0) — schema XML

---

## 1. Granularidade dos IA items

### 1.1 Raw items — individual por PDF (decisão primária)

**Decisão (aprovada)**: cada PDF é um IA item separado.

**Pattern**: `leizilla-raw-{ente}-{fonte}-{chave}`

| ente | fonte | chave | Exemplo |
|---|---|---|---|
| `ro` | `casacivil` | `coddoc-{N:05d}` | `leizilla-raw-ro-casacivil-coddoc-00042` |
| `ro` | `assembleia` | `coddoc-{N:05d}` | `leizilla-raw-ro-assembleia-coddoc-00042` |
| `ro` | `diario` | `{YYYY-MM-DD}-p{pagina:04d}` | `leizilla-raw-ro-diario-2003-06-15-p0012` |
| `federal` | `planalto` | `lei-{numero}-{ano}` | `leizilla-raw-federal-planalto-lei-12345-2024` |

**Justificativa**:
- Internet Archive faz OCR automático **apenas** em PDFs uploadados como item; PDFs dentro de ZIP não recebem OCR.
- Permalink estável por PDF facilita citação e debugging.
- Manifest CSV rastreia milhares de itens sem dificuldade (padrão causaganha).

**Trade-off aceito**: muitos itens (~5.000 só para Rondônia). Acceptable — IA não cobra por número de itens.

### 1.2 Raw items — bundle ZIP periódico (decisão secundária, redundância)

**Decisão (aprovada)**: além dos PDFs individuais, gerar ZIPs semanais com o lote scrapeado, para arquivamento defensivo (padrão ficha).

**Pattern**: `leizilla-bundle-{ente}-{fonte}-{periodo}` onde `{periodo}` segue ISO week: `YYYY-Www`.

Exemplo: `leizilla-bundle-ro-casacivil-2026-W20`

**Layout interno do ZIP**:
```
leizilla-bundle-ro-casacivil-2026-W20.zip
├── manifest.csv
│   columns: coddoc, ia_id, fonte_url, hash_pdf, data_captura
├── pdfs/
│   ├── 00042.pdf
│   ├── 00043.pdf
│   └── ...
└── meta/
    ├── 00042.json    ← cópia do raw_meta.json do item individual
    ├── 00043.json
    └── ...
```

**Justificativa**:
- Redundância contra perda acidental de items individuais.
- Permite download em lote (1 ZIP de N MB > N requests).
- Mirror histórico das fontes (snapshot semanal).

### 1.3 Parsed items — 1 lei = 1 item

**Decisão (aprovada)**: cada lei canônica é um IA item permanente.

**Pattern**: `leizilla-{ente}-{tipo}-{numero:05d}-{ano}`

| Exemplo | Notas |
|---|---|
| `leizilla-ro-lei-01234-2003` | caso normal |
| `leizilla-ro-decreto-00056-2024` | tipo = decreto |
| `leizilla-federal-lc-00141-2012` | LC = lei complementar |

**Fallback se `numero` ausente** (algumas leis antigas perderam numeração formal):
- Pattern: `leizilla-{ente}-{tipo}-fallback-{chave}` onde `{chave}` é o coddoc da fonte primária.
- Exemplo: `leizilla-ro-lei-fallback-casacivil-coddoc-00099`

**Conteúdo do parsed item**:
```
leizilla-ro-lei-01234-2003/
├── law.leiml          ← formato canônico (XML LeiML v0.1)
├── parsed_meta.json   ← metadados estruturados
└── provenance.json    ← rastreabilidade
```

Não inclui `law.html` (renderizado no browser via XSLT) nem `law.lexml` (export sob demanda; ver §6).

### 1.4 Dataset items — versionados por schema

**Decisão (aprovada)**: 1 IA item por `{ente}` × `{schema_version}`.

**Pattern**: `leizilla-dataset-{ente}-v{N}`

Exemplo: `leizilla-dataset-ro-v1` contém `leis-ro-v1.parquet` + `manifest-ro.csv` + `README.md`.

Bump de `N` apenas em **breaking schema change** (coluna removida, tipo alterado de forma incompatível). Adicionar coluna nullable não bumpa.

---

## 2. Layout dentro dos JSON sidecars

### 2.1 `raw_meta.json` (sidecar do raw item)

```json
{
  "leiml_meta_version": "0.1",
  "ente": "ro",
  "fonte": "casacivil",
  "fonte_url": "https://ditel.casacivil.ro.gov.br/cotel/livros/Folder.aspx?coddoc=42",
  "chave": "coddoc-00042",
  "data_captura": "2026-05-20T14:30:00Z",
  "hash_pdf": "sha256:abc123...",
  "user_agent": "leizilla-crawler/1.0",
  "ia_id_bundle": "leizilla-bundle-ro-casacivil-2026-W20"
}
```

### 2.2 `parsed_meta.json` (sidecar do parsed item)

```json
{
  "leiml_meta_version": "0.1",
  "urn_lex": "urn:lex:br;estado:rondonia:lei:2003-06-15;1234",
  "ente": "ro",
  "tipo": "lei",
  "numero": "1234",
  "ano": 2003,
  "data_publicacao": "2003-06-15",
  "ementa": "Dispõe sobre...",
  "fontes": [
    "leizilla-raw-ro-casacivil-coddoc-00042",
    "leizilla-raw-ro-diario-2003-06-15-p0012"
  ],
  "divergencias": [
    {
      "campo": "articulacao/artigo[@id='art-3']/caput",
      "fonte_a": "leizilla-raw-ro-casacivil-coddoc-00042",
      "fonte_b": "leizilla-raw-ro-diario-2003-06-15-p0012",
      "diff_summary": "§2º ausente em casacivil; texto idêntico no resto",
      "resolvido_por": "diario_oficial"
    }
  ],
  "fonte_canonica": "diario_oficial",
  "parse_method": "llm-haiku",
  "parse_model": "claude-haiku-4-5-20251001",
  "parse_timestamp": "2026-05-20T18:45:00Z",
  "confianca_parse": 0.92,
  "validacao_xsd": "passed"
}
```

### 2.3 `provenance.json` (sidecar do parsed item)

Audit trail mínimo separado para facilitar auditoria sem carregar `parsed_meta.json` completo.

```json
{
  "fontes_raw": [
    {
      "ia_id": "leizilla-raw-ro-casacivil-coddoc-00042",
      "ocr_url": "https://archive.org/download/leizilla-raw-ro-casacivil-coddoc-00042/law_djvu.txt",
      "hash_pdf": "sha256:abc123...",
      "consumed_at": "2026-05-20T18:45:00Z"
    }
  ],
  "produced_by": {
    "tool": "leizilla.etl.llm_parse",
    "version": "0.1.0",
    "git_sha": "abc1234"
  }
}
```

---

## 3. Schema Parquet v1

Tabela canônica `leis` no DuckDB e Parquet espelho.

| coluna | tipo | nullable | nota |
|---|---|---|---|
| `id` | VARCHAR | NO | identifier IA do parsed item (`leizilla-{ente}-{tipo}-{numero}-{ano}`) |
| `ente` | VARCHAR | NO | `ro`, `sp`, `federal`, `ro-porto-velho`... |
| `tipo` | VARCHAR | NO | `lei`, `decreto`, `lc`, `resolucao`... |
| `numero` | VARCHAR | YES | nullable porque fallback existe |
| `ano` | INTEGER | NO | |
| `data_publicacao` | DATE | YES | nullable se não extraível |
| `urn_lex` | VARCHAR | NO | URN LEX canônico |
| `titulo` | VARCHAR | YES | título informal se houver |
| `ementa` | TEXT | YES | resumo oficial |
| `texto_completo` | TEXT | YES | denormalizado: OCR concatenado da fonte canônica |
| `texto_normalizado` | TEXT | YES | NFC + whitespace cleanup, busca client-side |
| `url_raw_ia` | VARCHAR (JSON array) | NO | lista de raw IA ids consumidos |
| `url_leiml_ia` | VARCHAR | NO | URL do `law.leiml` |
| `url_ocr_ia` | VARCHAR (JSON array) | NO | lista de URLs `_djvu.txt` por fonte |
| `url_pdf_ia` | VARCHAR (JSON array) | NO | lista de URLs PDF por fonte |
| `fonte_canonica` | VARCHAR | NO | `diario_oficial`/`casacivil`/`assembleia` |
| `num_fontes` | INTEGER | NO | quantidade de fontes capturadas |
| `tem_divergencia` | BOOLEAN | NO | flag rápido frontend |
| `divergencias` | TEXT (JSON) | YES | diff summary estruturado |
| `parse_status` | VARCHAR | NO | `raw_only`/`parsed`/`failed` |
| `parse_method` | VARCHAR | YES | `llm-haiku`/`llm-opus`/`manual`/`deterministic` |
| `confianca_parse` | FLOAT | YES | 0.0–1.0 |
| `hash_conteudo` | VARCHAR | YES | sha256 do `texto_completo` |
| `created_at` | TIMESTAMP | NO | |
| `updated_at` | TIMESTAMP | NO | |

### 3.1 Representação de arrays

**Decisão (aprovada)**: usar `VARCHAR` com JSON serializado, **não** Parquet LIST nativo.

**Justificativa**:
- DuckDB-WASM 1.28 lê LISTs nativos, mas TanStack Query + Svelte components ficam mais simples com JSON strings.
- JSON é universal (compatível com qualquer ferramenta downstream).
- Custo: ~5–10% maior em storage, irrelevante para Parquet (compressão SNAPPY).

### 3.2 Representação de divergências

**Decisão (aprovada)**: `divergencias` é JSON string única, não colunas separadas.

**Justificativa**:
- Cardinalidade variável (0–N divergências por lei).
- Frontend renderiza apenas se `tem_divergencia=true` (flag rápido).
- Drill-down é uso minoritário; full-table scan é tolerável.

### 3.3 Footer KV metadata (PyArrow)

```python
{
  "leizilla.schema_version": "1",
  "leizilla.ente": "ro",
  "leizilla.generated_at": "2026-05-20T19:00:00Z",
  "leizilla.row_count": "4827",
  "leizilla.git_sha": "abc1234",
  "leizilla.leiml_version": "0.1"
}
```

Escrita via `pyarrow.parquet.write_table` (não DuckDB `COPY` — esse não embute KV custom).

### 3.4 Versioning

- `schema_version` semver-ish: major bump apenas em break.
- CI valida que o `v{N}` no caminho do arquivo bate com o footer KV.
- Zod schema em `web/src/schemas/v1/lei.ts` deve ser bumped junto.

---

## 4. Schema LeiML v0.1

Definição mínima v0.1. Schema XSD formal em `docs/schemas/leiml-v0.1.xsd` (a criar).

### 4.1 Elementos raiz

```xml
<lei xmlns="https://leizilla.org/leiml/0.1" version="0.1">
  <header>...</header>
  <articulacao>...</articulacao>
  <anotacoes>...</anotacoes>
</lei>
```

### 4.2 `<header>` — metadados obrigatórios

| Elemento | Obrigatório | Tipo | Nota |
|---|---|---|---|
| `<ente>` | sim | enum | slug do ente (`ro`, `federal`, `ro-porto-velho`) |
| `<tipo>` | sim | enum | `lei`, `decreto`, `lc`, `resolucao`, `portaria` |
| `<numero>` | não | string | nullable se fallback |
| `<ano>` | sim | int | |
| `<data-publicacao>` | não | date ISO | |
| `<ementa>` | não | string | |
| `<urn-lex>` | sim | string | `urn:lex:br;...` canônico |

### 4.3 `<articulacao>` — corpo da lei

Hierarquia (do mais externo para o mais interno):
- `<artigo id="art-N">` ← rotulo + caput + paragrafos
  - `<rotulo>` ← "Art. 1º"
  - `<caput>` ← `<p>` com texto principal
  - `<paragrafo id="art-N-par-M">` ← rotulo + p
    - `<rotulo>` ← "§ 1º"
    - `<p>` ← texto
  - `<inciso id="art-N-inc-M">` ← rotulo + p (Roman: I, II, III...)
  - `<alinea id="art-N-inc-M-ali-L">` ← rotulo + p (a, b, c...)

Fallback se texto não puder ser estruturado:
```xml
<articulacao>
  <bloco-livre quality="low"><p>...texto OCR cru...</p></bloco-livre>
</articulacao>
```

### 4.4 `<anotacoes>` — metadados de processamento

```xml
<anotacoes>
  <fontes>
    <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00042" tipo="casa-civil"/>
    <fonte ia-id="leizilla-raw-ro-diario-2003-06-15-p0012" tipo="diario-oficial"/>
  </fontes>
  <divergencia campo="articulacao/artigo[@id='art-3']/caput"
               entre="casa-civil,diario-oficial"
               resolvido-por="diario-oficial">
    §2º ausente em casacivil
  </divergencia>
  <parse method="llm-haiku"
         model="claude-haiku-4-5-20251001"
         confianca="0.92"
         timestamp="2026-05-20T18:45:00Z"/>
</anotacoes>
```

### 4.5 Stylesheet processing instruction

Todo `law.leiml` deve começar com:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<?xml-stylesheet type="text/xsl" href="https://leizilla.org/leiml.xsl"?>
```

Permite abrir `law.leiml` diretamente no browser e ver HTML renderizado (XSLT nativo).

---

## 5. Naming completo — regex formal

### Raw individual
```
^leizilla-raw-(?P<ente>[a-z][a-z0-9-]*)-(?P<fonte>[a-z]+)-(?P<chave>[a-z0-9-]+)$
```

### Raw bundle ZIP
```
^leizilla-bundle-(?P<ente>[a-z][a-z0-9-]*)-(?P<fonte>[a-z]+)-(?P<periodo>\d{4}-W\d{2})$
```

### Parsed canônico
```
^leizilla-(?P<ente>[a-z][a-z0-9-]*)-(?P<tipo>[a-z]+)-(?P<numero>\d{5})-(?P<ano>\d{4})$
```

### Parsed fallback (sem numero)
```
^leizilla-(?P<ente>[a-z][a-z0-9-]*)-(?P<tipo>[a-z]+)-fallback-(?P<fonte>[a-z]+)-(?P<chave>[a-z0-9-]+)$
```

### Dataset
```
^leizilla-dataset-(?P<ente>[a-z][a-z0-9-]*)-v(?P<version>\d+)$
```

### Slug `{ente}` — produção controlada

- União: `federal`
- Estados: ISO 3166-2:BR sem o prefixo `BR-`, lowercase: `ro`, `sp`, `mg`, `rj`...
- Municípios: `{uf}-{slug-kebab}` — exemplo: `ro-porto-velho`, `sp-sao-paulo`
- DF: `df`

**Validação**: lista canônica em `src/leizilla/entes.py` (M1) com nome oficial, UF pai, e código IBGE.

### Slug `{fonte}` — enum por ente

Cada ente declara suas fontes oficiais em `src/leizilla/fontes/{ente}.py`. Exemplo:

```python
# src/leizilla/fontes/ro.py
FONTES = {
    "casacivil": "https://ditel.casacivil.ro.gov.br/cotel/",
    "assembleia": "https://sapl.al.ro.leg.br/",
    "diario": "https://www.diof.ro.gov.br/",
}
```

---

## 6. Export LexML

**Decisão (aprovada)**: LeiML é canônico; LexML é export sob demanda.

**Estratégia**:
- XSLT `etl/leiml-to-lexml.xsl` realiza a conversão.
- CLI `uv run leizilla export-lexml --ia-id leizilla-ro-lei-01234-2003` gera `law.lexml` localmente.
- **Não** uploadamos `law.lexml` ao IA por padrão. Geração on-demand evita duplicação e mantém LexML sempre derivado de LeiML.
- Quando um release oficial for solicitado (e.g., entrega para Senado/Câmara), gerar batch em ZIP separado: `leizilla-lexml-export-{ente}-{date}.zip`.

**CI round-trip**:
- A cada PR, rodar `pytest tests/test_leiml_export.py` que:
  1. Pega 3 fixtures LeiML em `tests/fixtures/leiml/`.
  2. Aplica `leiml-to-lexml.xsl`.
  3. Valida XML resultante contra XSD oficial LexML em `tests/fixtures/lexml.xsd`.

---

## 7. Versionamento — regras de bump

| Coisa | Versão atual | Quando bumpar major |
|---|---|---|
| LeiML | `0.1` | mudança incompatível no schema XSD |
| Parquet schema | `1` | coluna removida ou tipo alterado de forma breaking |
| LeiML meta JSON | `0.1` | campo obrigatório adicionado ou removido |
| `leizilla` CLI | `1.0` (após M5) | breaking change em subcomandos |

**Constraint CI**: ao bumpar major, `web/src/schemas/v{N}/` precisa existir e ser referenciado em `web/src/lib/queries.ts`. Build quebra se faltar.

---

## 8. Inspirações dos sister projects

Onde nossa decisão foi influenciada por código existente em ficha/baliza/causaganha:

### Da ficha
- **ZIP de raw bulk** (§1.2): ficha mirror dos 37 ZIPs RFB. Adotamos pattern análogo (ZIP semanal por ente+fonte).
- **Parquet como camada canônica**: ficha tem `cnpjs.parquet`, `socios.parquet` etc. Nossa `leis-{ente}-v{N}.parquet` segue mesma filosofia.
- **Footer KV `schema_version`**: ficha embute no Parquet; replicamos em §3.3.

### Da baliza
- **Manifest CSV no IA como source of truth**: baliza usa `baliza-pncp-manifest/manifest.csv` com `parquet_url`, `parquet_uploaded_at`, `parquet_schema_version`, `sha256`. Nossa `manifest-{ente}.csv` segue mesma estrutura adaptada.
- **`raw-YYYY-MM.zip` para forensics**: baliza guarda JSON cru opcionalmente. Nossa `leizilla-bundle-...zip` cumpre função similar.

### Da causaganha
- **Sync manifest por `(tribunal, date)`**: causaganha rastreia status de coleta granularmente. Nossa manifest rastreia `(ente, fonte, chave)` similarmente.
- **Tribunais como subunit**: análogo aos nossos entes federativos.

---

## 9. Decisões pendentes (a fechar antes de M0 close)

- [ ] **Compressão Parquet**: SNAPPY (atual) vs ZSTD? ZSTD pode reduzir 20–30% mas DuckDB-WASM precisa suportar. Verificar em M0.
- [ ] **Granularidade do bundle ZIP**: semanal (`YYYY-Www`) vs mensal (`YYYY-MM`)? Semanal melhor para frequência de scrape, mensal melhor para tamanho de download. **Provável**: semanal por enquanto, revisitar se tamanho ficar trivial.
- [ ] **Onde armazenar `lexml.xsd` (validação CI)**: bundle no repo (~200KB) vs download em runtime do site oficial? **Provável**: bundle no repo para reprodutibilidade e isolamento de quebra do site gov.
- [ ] **`leiml-meta-version` separado de `leiml-version`?**: meta JSON pode evoluir independente do XML. **Provável**: sim, separados.

---

## 10. Open questions (não bloqueiam M0)

- Como lidar com **revogações e alterações** entre leis? LeiML v0.1 não captura essa relação. v0.2 poderia ter `<relacoes><revoga ref="urn:lex:..."/></relacoes>`.
- Como **versionar a própria lei** quando o texto consolidado muda? Versão `latest` vs versão temporal? Adiar para v0.2.
- **Multilíngua**: LexML cobre só pt-br oficial. Não precisa em v0.1.
