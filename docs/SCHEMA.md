# SCHEMA.md — Design de dados do Leizilla

> Decisões load-bearing sobre granularidade de IA items, modelo XML dispositivo-cêntrico, schema Parquet, naming, e export LexML. Editado quando uma decisão muda — coluna **Status** indica `proposta`, `aprovada`, ou `superseded-by-#PR`.

**Histórico**: a v0 deste documento esboçava um formato "LeiML" como fork de LexML, com a lei como unidade primária. Reescrito após review do PR #6: (a) **dispositivo é a unidade primária**, não a lei; (b) formato próprio escrito do zero ("Leizilla XML"), com export LexML apenas como gate de CI — não como constraint estrutural; (c) timeline temporal nativa de dispositivos para tratar alterações legislativas; (d) parsed item = "vigente compilado" como objeto principal, histórico exposto via timeline. Ver §0.

Companion docs:
- `IMPLEMENTATION.md` (raiz) — status geral e log de decisões cronológico
- `docs/adr/0005-ia-identifiers.md` (a criar em M1) — formalização normativa
- `docs/schemas/leizilla-v0.1.xsd` (a criar em M0.2) — schema XML

---

## 0. Princípios de modelagem (reescrita pós-review #6)

### 0.1 Dispositivo é a unidade primária

A unidade básica de dado **não é a lei** — é o **dispositivo** (artigo, parágrafo, inciso, alínea, item). Justificativa:

- Lawyers citam dispositivos, não leis inteiras ("art. 5º, §2º, II, alínea b da CF/88").
- Alterações legislativas operam sobre dispositivos individuais, não sobre a lei toda.
- Revogações são parciais com frequência (revoga art. 3º mantém o resto).
- Cross-references naturais ("Lei 14.133/2021 art. 3 alterou Lei 1.234/2003 art. 5 §2").
- DuckDB-WASM consegue indexar e buscar dispositivos com SQL trivial; a lei é apenas o agregador.

Isso difere de LexML/Akoma Ntoso, que centram em document/work. Para nosso uso (busca jurídica + timeline temporal), dispositivo-cêntrico é mais expressivo.

### 0.2 Vigente compilado é o objeto canônico; histórico é timeline

O parsed item canônico representa a lei **como ela deve estar vigente hoje** (best-effort compilation). Versões anteriores são **acessíveis** mas não são objetos primários — são snapshots indexados na timeline de cada dispositivo (date picker → "como era em 2010-01-01?").

A "hierarquia de autoridade DO > Casa Civil > Assembleia" do esboço anterior foi descartada. As fontes não competem por canonicidade — elas cross-verificam a compilação vigente:

- Casa Civil/COTEL geralmente mantém o consolidado vigente — fonte primária para texto atual.
- Diário Oficial dá fé da publicação original — fonte primária para snapshots históricos.
- Assembleia Legislativa dá o texto legislativo original (pode diferir de DO por retificações tardias).
- Divergências entre fontes indicam **possível erro de consolidação ou retificação não-aplicada**, não ranking. Frontend mostra como "verificar".

### 0.3 Formato próprio (não fork), com export LexML como gate de CI

O esboço anterior propunha "LeiML" como fork de LexML. Descartado: dispositivo-cêntrico + timeline + divergencias multi-fonte + parse-LLM-metadata + bloco-livre não cabem confortavelmente em LexML, e a regra de round-trip ficaria perdendo dados em todo PR.

Em vez disso: **Leizilla XML v0.1 é escrito do zero**, otimizado para nossos casos de uso. Mantemos a **disciplina** de LexML/Akoma Ntoso (URN LEX para identificar dispositivos, semântica jurídica) e um **gate de CI**: a cada PR, rodar `scripts/lexml_export.py` que produz um LexML válido a partir do nosso XML para casos representativos. O LexML resultante é uma **representação reduzida** (perde divergencias, parse meta, bloco-livre quality) — isso é OK; o gate só garante que conseguimos exportar para gov interop quando preciso, sem amarrar nosso design.

### 0.4 Granularidade na renderização — SSR híbrido

O esboço anterior cravou "HTML renderizado no browser via XSLT/JS, nunca server-side". Suavizado: páginas de detalhe de lei (`/lei/{id}`) renderizam server-side via Astro (acessibilidade WCAG, SEO, no-JS funciona, LBI 13.146/2015). Busca/timeline interativa fica client-side com Svelte+DuckDB-WASM. XSLT in-browser é fallback opcional para quem abre `law.xml` diretamente.

### 0.5 Genericidade real, não só de slug

O esboço anterior afirmou "genérico por ente desde dia 1" mas o vocabulário era estadual. Realidade: cada nível federativo tem fontes diferentes (Federal: Câmara, Senado, Planalto, DOU; Municípios: ~5.570 estruturas distintas). O modelo Leizilla XML **não** assume estrutura de fonte — apenas que cada dispositivo tem `<fonte ia-id="..."/>` apontando para um raw item. O catálogo `src/leizilla/fontes/{ente}.py` declara fontes válidas por ente; o resto do código consome a lista sem hardcode.

---

## 1. Granularidade dos IA items

### 1.1 Raw items — individual por PDF (aprovada)

**Pattern**: `leizilla-raw-{ente}-{fonte}-{chave}`

| ente | fonte | chave | Exemplo |
|---|---|---|---|
| `ro` | `casacivil` | `coddoc-{N:05d}` | `leizilla-raw-ro-casacivil-coddoc-00042` |
| `ro` | `assembleia` | `coddoc-{N:05d}` | `leizilla-raw-ro-assembleia-coddoc-00042` |
| `ro` | `diario` | `{YYYY-MM-DD}-p{pagina:04d}` | `leizilla-raw-ro-diario-2003-06-15-p0012` |
| `federal` | `planalto` | `lei-{numero:05d}-{ano}` | `leizilla-raw-federal-planalto-lei-12345-2024` |

**Justificativa**: IA faz OCR **apenas** em PDFs individuais (não em PDFs dentro de ZIP). Permalink por PDF facilita citação e debugging. Manifest CSV escala para milhares de items.

### 1.2 Raw items — bundle ZIP semanal (aprovada, redundância)

**Pattern**: `leizilla-bundle-{ente}-{fonte}-{periodo}` onde `{periodo}` = ISO week (`YYYY-Www`).

Exemplo: `leizilla-bundle-ro-casacivil-2026-W20`

**Layout interno**:
```
manifest.csv         columns: coddoc, ia_id, fonte_url, hash_pdf, data_captura
pdfs/{chave}.pdf
meta/{chave}.json
```

Forensics + download em lote. Mirror histórico das fontes.

### 1.3 Parsed items — 1 lei = 1 IA item (aprovada)

**Pattern canônico**: `leizilla-{ente}-{tipo}-{numero:05d}-{ano}`

| Exemplo | Notas |
|---|---|
| `leizilla-ro-lei-01234-2003` | caso normal |
| `leizilla-ro-decreto-00056-2024` | tipo=decreto |
| `leizilla-federal-lc-00141-2012` | LC = lei complementar |

**Pattern fallback** (lei antiga sem numeração formal): `leizilla-{ente}-{tipo}-fallback-{fonte}-{chave}`

Exemplo: `leizilla-ro-lei-fallback-casacivil-coddoc-00099`

> Codex P1 fix (PR #6): fallback **inclui obrigatoriamente** o segmento `{fonte}` para evitar colisão quando diferentes fontes compartilham a mesma chave.

**Conteúdo do parsed item** (vigente compilado + histórico em timeline):
```
leizilla-ro-lei-01234-2003/
├── law.xml             ← Leizilla XML v0.1 (dispositivo-cêntrico, com timeline)
├── parsed_meta.json    ← metadados estruturados de produção
├── provenance.json     ← rastreabilidade raw items + parse method
└── alteracoes.json     ← relações computadas (alteradoPor, altera, revogadoPor)
```

Não inclui HTML pré-gerado (renderização SSR via Astro a partir de `law.xml`). Não inclui `law.lexml` (export sob demanda; ver §6).

### 1.4 Dataset items — versionados (aprovada)

**Pattern**: `leizilla-dataset-{ente}-v{N}`

Conteúdo: `leis-{ente}-v{N}.parquet`, `dispositivos-{ente}-v{N}.parquet`, `versoes-{ente}-v{N}.parquet`, `manifest-{ente}.csv`, `README.md`.

Bump de `N` apenas em **breaking schema change** (coluna removida, tipo alterado de forma incompatível).

---

## 2. Layout dos JSON sidecars

### 2.1 `raw_meta.json` (sidecar do raw item)

```json
{
  "leizilla_meta_version": "0.1",
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
  "leizilla_meta_version": "0.1",
  "schema_xml_version": "0.1",
  "urn_lex": "urn:lex:br;estado:rondonia:lei:2003-06-15;1234",
  "ente": "ro",
  "tipo": "lei",
  "numero": "1234",
  "ano": 2003,
  "data_publicacao": "2003-06-15",
  "ementa": "Dispõe sobre...",
  "vigente_em": "2026-05-20",
  "num_dispositivos": 27,
  "num_versoes_total": 31,
  "fontes_consultadas": [
    "leizilla-raw-ro-casacivil-coddoc-00042",
    "leizilla-raw-ro-diario-2003-06-15-p0012"
  ],
  "tem_divergencia": true,
  "num_divergencias": 1,
  "parse_method": "llm-haiku",
  "parse_model": "claude-haiku-4-5-20251001",
  "parse_timestamp": "2026-05-20T18:45:00Z",
  "confianca_parse": 0.92,
  "validacao_xsd": "passed"
}
```

### 2.3 `provenance.json`

Audit trail mínimo separado para facilitar verificação sem carregar `parsed_meta.json` completo.

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
    "git_sha": "abc1234def5678901234567890abcdef12345678"
  }
}
```

### 2.4 `alteracoes.json` (novo)

Relações computadas com outras leis. Permite ao frontend mostrar "esta lei foi alterada por X" sem ter que escanear o `law.xml` inteiro.

```json
{
  "leizilla_meta_version": "0.1",
  "alterada_por": [
    {
      "urn_lex": "urn:lex:br;estado:rondonia:lei:2024-06-30;5678",
      "ia_id": "leizilla-ro-lei-05678-2024",
      "dispositivos_afetados": ["art-3-par-2", "art-5"],
      "data_efeito": "2024-07-30"
    }
  ],
  "altera": [],
  "revogada_por": null,
  "revoga": []
}
```

---

## 3. Schema Parquet v1 — três tabelas

Dispositivo-cêntrico exige três tabelas relacionadas. Cada uma vira um Parquet separado no dataset item.

### 3.1 Tabela `leis` — header por lei

| coluna | tipo | nullable | nota |
|---|---|---|---|
| `id` | VARCHAR | NO | identifier IA do parsed item, **zero-padded** (e.g. `leizilla-ro-lei-01234-2003`) |
| `ente` | VARCHAR | NO | `ro`, `sp`, `federal`, `ro-porto-velho`... |
| `tipo` | VARCHAR | NO | `lei`, `decreto`, `lc`, `resolucao`... |
| `numero` | VARCHAR | YES | nullable porque fallback existe |
| `ano` | INTEGER | NO | |
| `data_publicacao` | DATE | YES | |
| `urn_lex` | VARCHAR | YES | nullable se `data_publicacao` desconhecida (URN LEX requer data) — ver §5.4 |
| `titulo` | VARCHAR | YES | |
| `ementa` | VARCHAR | YES | |
| `url_law_xml_ia` | VARCHAR | NO | URL do `law.xml` no IA |
| `vigente_em` | DATE | NO | data da compilação vigente |
| `tem_divergencia` | BOOLEAN | NO | flag rápido frontend |
| `num_divergencias` | INTEGER | NO | |
| `num_dispositivos` | INTEGER | NO | |
| `num_versoes_total` | INTEGER | NO | soma de versoes em todos os dispositivos |
| `revogada` | BOOLEAN | NO | |
| `parse_status` | VARCHAR | NO | `raw_only`/`parsed`/`failed` |
| `parse_method` | VARCHAR | YES | `llm-haiku`/`llm-opus`/`manual`/`deterministic` |
| `confianca_parse` | FLOAT | YES | 0.0–1.0 |
| `created_at` | TIMESTAMP | NO | |
| `updated_at` | TIMESTAMP | NO | |

### 3.2 Tabela `dispositivos` — uma linha por dispositivo

| coluna | tipo | nullable | nota |
|---|---|---|---|
| `dispositivo_id` | VARCHAR | NO | composto: `{lei_id}#{path}` (e.g. `leizilla-ro-lei-01234-2003#art-3-par-2`) |
| `lei_id` | VARCHAR | NO | FK para `leis.id` |
| `urn_dispositivo` | VARCHAR | YES | `urn:lex:...;1234!art-3!par-2` (LexML dialect, ver §5.4) |
| `tipo` | VARCHAR | NO | `artigo`/`paragrafo`/`inciso`/`alinea`/`item`/`caput` |
| `rotulo` | VARCHAR | NO | "Art. 1º", "§ 2º", "II", "a)" |
| `path` | VARCHAR | NO | hierárquico: `art-3` / `art-3-par-2` / `art-3-par-2-inc-1` / `art-3-par-2-inc-1-ali-a` |
| `parent_path` | VARCHAR | YES | NULL para raiz; senão path do dispositivo pai |
| `ordem` | INTEGER | NO | ordem dentro do parent (1, 2, 3...) |
| `texto_vigente` | VARCHAR | YES | texto da versão atualmente vigente (denormalizado para query rápida) |
| `vigente_desde` | DATE | YES | data efeito da versão vigente |
| `revogado` | BOOLEAN | NO | |
| `revogado_em` | DATE | YES | |

### 3.3 Tabela `versoes` — uma linha por versão histórica de cada dispositivo

| coluna | tipo | nullable | nota |
|---|---|---|---|
| `versao_id` | VARCHAR | NO | `{dispositivo_id}#v{N}` |
| `dispositivo_id` | VARCHAR | NO | FK para `dispositivos.dispositivo_id` |
| `lei_id` | VARCHAR | NO | denormalizado p/ join-free queries |
| `numero_versao` | INTEGER | NO | 1, 2, 3... cronológico |
| `vigente_de` | DATE | NO | |
| `vigente_ate` | DATE | YES | NULL = ainda vigente |
| `texto` | VARCHAR | NO | |
| `texto_normalizado` | VARCHAR | YES | NFC + cleanup, p/ busca |
| `alterado_por_lei_id` | VARCHAR | YES | NULL na versão original; senão FK para `leis.id` da lei alteradora |
| `fonte_canonica` | VARCHAR | NO | slug curto da fonte usada (`casacivil`, `diario`, `assembleia`...) |
| `fontes_consultadas` | VARCHAR (JSON array) | NO | lista de raw IA ids usados |
| `tem_divergencia` | BOOLEAN | NO | |
| `divergencias` | VARCHAR (JSON) | YES | diff summary entre fontes |
| `hash_texto` | VARCHAR | NO | sha256 |
| `bloco_livre_quality` | VARCHAR | YES | `null` (parsing OK) / `low` / `medium` / `high` se `<bloco-livre>` foi usado |

### 3.4 Representação de arrays e JSON

**Decisão (aprovada)**: arrays como `VARCHAR` com JSON serializado, **não** Parquet LIST nativo. Justificativa: simplifica TanStack Query + Svelte components; JSON universal; custo storage irrelevante com SNAPPY.

### 3.5 Footer KV metadata (PyArrow)

```python
{
  "leizilla.schema_version": "1",
  "leizilla.xml_schema_version": "0.1",
  "leizilla.ente": "ro",
  "leizilla.table": "dispositivos",  # ou leis / versoes
  "leizilla.generated_at": "2026-05-20T19:00:00Z",
  "leizilla.row_count": "12483",
  "leizilla.git_sha": "abc1234def5678901234567890abcdef12345678"
}
```

Escrita via `pyarrow.parquet.write_table` (não DuckDB `COPY` — esse não embute KV custom).

> Reviewer #6 ponto 8 fix: `git_sha` é o SHA completo (40 chars), não truncado.

### 3.6 Versioning

- `schema_version` semver-ish na coluna `leizilla.schema_version`: major bump apenas em break.
- CI valida que o `v{N}` no caminho do arquivo bate com o footer KV.
- Zod schema em `web/src/schemas/v1/lei.ts` + `dispositivo.ts` + `versao.ts` bumped junto.
- v1 só é cravado depois do MVP rodar (reviewer #6 ponto 13). Durante M0–M4 o schema é **v0.1**; promove para v1 no fechamento de M5.

---

## 4. Leizilla XML v0.1 — formato canônico

Esboço. Definição XSD formal em `docs/schemas/leizilla-v0.1.xsd` (M0.2).

### 4.1 Estrutura raiz

```xml
<?xml version="1.0" encoding="UTF-8"?>
<?xml-stylesheet type="text/xsl" href="https://leizilla.org/render/0.1/lei.xsl"?>
<lei xmlns="https://leizilla.org/lei/0.1"
     schema-version="0.1"
     urn-lex="urn:lex:br;estado:rondonia:lei:2003-06-15;1234">
  <header>...</header>
  <dispositivos>...</dispositivos>
  <anotacoes>...</anotacoes>
</lei>
```

### 4.2 `<header>` — metadados da lei

```xml
<header>
  <ente>ro</ente>
  <tipo>lei</tipo>
  <numero>1234</numero>
  <ano>2003</ano>
  <data-publicacao>2003-06-15</data-publicacao>
  <ementa>Dispõe sobre...</ementa>
  <vigente-em>2026-05-20</vigente-em>
  <revogada>false</revogada>
</header>
```

### 4.3 `<dispositivos>` — corpo dispositivo-cêntrico

Cada dispositivo carrega sua própria **timeline de versões**. Nested para hierarquia.

```xml
<dispositivos>
  <dispositivo tipo="artigo" path="art-1" urn="urn:lex:...;1234!art-1">
    <rotulo>Art. 1º</rotulo>
    <versoes>
      <versao numero="1" vigente-de="2003-06-15" vigente-ate="2024-07-30"
              alterado-por="urn:lex:br;estado:rondonia:lei:2024-06-30;5678">
        <texto>Esta Lei dispõe sobre...</texto>
        <fonte-canonica>casacivil</fonte-canonica>
        <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00042"/>
        <fonte ia-id="leizilla-raw-ro-diario-2003-06-15-p0012"/>
      </versao>
      <versao numero="2" vigente-de="2024-07-30">
        <texto>Esta Lei dispõe sobre (redação dada pela Lei 5.678/2024)...</texto>
        <fonte-canonica>casacivil</fonte-canonica>
        <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00187"/>
      </versao>
    </versoes>
    <dispositivo tipo="paragrafo" path="art-1-par-1" urn="urn:lex:...;1234!art-1!par-1">
      <rotulo>§ 1º</rotulo>
      <versoes>
        <versao numero="1" vigente-de="2003-06-15">
          <texto>...</texto>
          <fonte-canonica>casacivil</fonte-canonica>
          <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00042"/>
        </versao>
      </versoes>
    </dispositivo>
  </dispositivo>
</dispositivos>
```

Regras:
- Cada `<dispositivo>` tem **no mínimo 1** `<versao>` (a original).
- `vigente-ate` ausente = ainda vigente.
- `alterado-por` aponta para URN da lei alteradora (não para versão específica).
- Hierarquia via nesting; `path` é a chave determinística (gerada do nesting).

### 4.4 Fallback: `<bloco-livre>` para OCR ruim

Se o LLM não conseguir estruturar dispositivos:

```xml
<dispositivos>
  <bloco-livre quality="low">
    <p>...texto OCR cru, possivelmente fragmentado...</p>
  </bloco-livre>
</dispositivos>
```

Atributo `quality` é extensível: `low` / `medium` / `high` / `raw` (reviewer #6 ponto 🟢). Frontend renderiza com banner "texto não estruturado".

### 4.5 `<anotacoes>` — metadados de processamento

```xml
<anotacoes>
  <divergencia
      dispositivo-path="art-3-par-2"
      versao-numero="1"
      entre="casacivil,diario"
      diff-xpath="/dispositivo/versoes/versao[@numero='1']/texto">
    §2º está ausente em casacivil; presente em diario. Texto vigente
    adotado de casacivil (consolidado oficial); inconsistência marcada
    para verificação manual.
  </divergencia>
  <parse
      method="llm-haiku"
      model="claude-haiku-4-5-20251001"
      confianca="0.92"
      timestamp="2026-05-20T18:45:00Z"/>
</anotacoes>
```

> **Confiança baixa exibida explicitamente**: reviewer #6 ponto 5. Frontend mostra banner no card de detalhe da lei se `confianca_parse < 0.8` ou `parse_method = "llm-*"`: "Este texto foi compilado por LLM a partir de OCR — para texto oficial, consulte: [links das fontes raw]".

### 4.6 Stylesheet processing instruction

Todo `law.xml` começa com:
```xml
<?xml-stylesheet type="text/xsl" href="https://leizilla.org/render/0.1/lei.xsl"?>
```

Abrir o XML direto no browser exibe HTML (XSLT in-browser). **Não** é o caminho de renderização primário (esse é Astro SSR — reviewer #6 ponto 12). É fallback opcional.

---

## 5. Naming completo — regex formal

### 5.1 Raw individual
```
^leizilla-raw-(?P<ente>[a-z][a-z0-9-]*)-(?P<fonte>[a-z]+)-(?P<chave>[a-z0-9-]+)$
```

### 5.2 Raw bundle ZIP
```
^leizilla-bundle-(?P<ente>[a-z][a-z0-9-]*)-(?P<fonte>[a-z]+)-(?P<periodo>\d{4}-W\d{2})$
```

### 5.3 Parsed
**Canônico**:
```
^leizilla-(?P<ente>[a-z][a-z0-9-]*)-(?P<tipo>[a-z]+)-(?P<numero>\d{5,})-(?P<ano>\d{4})$
```

> Reviewer #6 ponto 4 fix: `\d{5,}` em vez de `\d{5}` — leis federais já passam de 5 dígitos por extenso; zero-pad mínimo de 5 mantém ordenação lexicográfica para a maioria.

> Codex P2 fix: o `id` no Parquet (§3.1) **sempre** usa o `numero` zero-padded para bater com o IA identifier. Lookup `id → IA item` é literal, sem normalização extra.

**Fallback**:
```
^leizilla-(?P<ente>[a-z][a-z0-9-]*)-(?P<tipo>[a-z]+)-fallback-(?P<fonte>[a-z]+)-(?P<chave>[a-z0-9-]+)$
```

> Codex P1 fix: `{fonte}` é obrigatório no fallback, evitando colisão quando fontes diferentes compartilham `chave`.

### 5.4 Dataset
```
^leizilla-dataset-(?P<ente>[a-z][a-z0-9-]*)-v(?P<version>\d+)$
```

### 5.5 URN LEX

**Lei**: `urn:lex:br;{jurisdicao};lei:{YYYY-MM-DD};{numero}`
- `{jurisdicao}` para estados: `estado:rondonia` / `estado:sao-paulo`
- `{jurisdicao}` para federal: `federal`
- `{jurisdicao}` para municípios: `municipio:rondonia;porto-velho`

**Dispositivo**: `{urn-lei}!art-N` ou `{urn-lei}!art-N!par-M!inc-K!ali-L` (separador `!` cf. extensão LexML para sub-document addressing).

**Fallback URN quando `data_publicacao` desconhecida** (reviewer #6 ponto 3): `urn_lex` na coluna Parquet é nullable. Quando data não é extraível, gravar `NULL` (não falsificar). Identifier IA usa fallback `{ente}-{tipo}-fallback-{fonte}-{chave}` que não depende de URN.

> **Pendente M0.2**: verificar contra a especificação oficial CGPID se o separador interno é `;`, `,` ou `:` em casos como `urn:lex:br;rondonia:estadual:lei,2003-06-15;1234`. Reviewer #6 sugeriu que CGPID usa vírgulas em alguns campos. Validar antes de cravar o exemplo.

### 5.6 Slug `{ente}`

- União: `federal`
- Estados: ISO 3166-2:BR sem `BR-`, lowercase: `ro`, `sp`, `mg`, `rj`...
- Municípios: `{uf}-{slug-kebab}`: `ro-porto-velho`, `sp-sao-paulo`
- DF: `df`

Lista canônica em `src/leizilla/entes.py` (M1) com nome oficial, UF pai, código IBGE.

### 5.7 Slug `{fonte}` — regra load-bearing

`{fonte}` é token único `[a-z]+` — **sem hífens nem underscores**. Toda referência (IA identifier, `raw_meta.json.fonte`, `parsed_meta.json.fonte_consultadas`, atributo `<fonte-canonica>` em XML, coluna Parquet `fonte_canonica`, enum `FONTES` Python) usa **exatamente o mesmo slug**.

Hífens quebrariam parsing de `leizilla-raw-{ente}-{fonte}-{chave}` (sem fronteira reconhecível). Nomes longos (`diário oficial`, `casa civil`) ficam em campos `display_name` / metadata IA legível.

Slugs canônicos lockados: `casacivil`, `diario`, `assembleia`, `planalto`, `camara`, `senado`.

---

## 6. Export LexML — gate de CI, não constraint estrutural

**Decisão (aprovada, pós-review #6)**: Leizilla XML é o formato canônico. LexML é gerado sob demanda como **representação reduzida** para gov interop.

**Perdas conhecidas no export** (documentadas no XSLT):
- `<bloco-livre quality="low">` → vira `<Texto>` cru sem marcação.
- `<anotacoes><divergencia>` e `<parse>` → descartados (não têm equivalente LexML).
- Timeline `<versoes>` colapsa para `<TextoArticulado>` da versão vigente apenas; histórico vira `<Alteracao>` LexML quando possível.

**Estratégia**:
- XSLT `scripts/leizilla-to-lexml.xsl` realiza conversão.
- CLI `uv run leizilla export-lexml --ia-id leizilla-ro-lei-01234-2003` gera `law.lexml` localmente.
- **Não** uploadamos `law.lexml` ao IA por padrão. Sob demanda para release oficial: ZIP separado `leizilla-lexml-export-{ente}-{date}.zip`.

**CI gate**:
- A cada PR, `pytest tests/test_lexml_export.py`:
  1. Pega 3 fixtures `tests/fixtures/leizilla_xml/`.
  2. Aplica `leizilla-to-lexml.xsl`.
  3. Valida XML contra XSD oficial LexML em `tests/fixtures/lexml.xsd` (bundle no repo — reviewer #6 ponto 6 + §9 resolvida: **bundle aprovada**).
  4. Falha se LexML resultante não validar.

CI **não** valida round-trip (LexML → Leizilla XML não é objetivo).

---

## 7. Versionamento — regras de bump

| Coisa | Versão atual | Bump major em |
|---|---|---|
| Leizilla XML | `0.1` | mudança incompatível no schema XSD |
| Parquet schema | `0.1` (vira `1` em M5) | coluna removida ou tipo breaking |
| Sidecar JSON | `0.1` | campo obrigatório add/remove |
| `leizilla` CLI | `1.0` (após M5) | breaking em subcomandos |

CI: ao bumpar major, `web/src/schemas/v{N}/` precisa existir + ser referenciado em `web/src/lib/queries.ts`. Build quebra se faltar.

---

## 8. Inspirações dos sister projects

### Da ficha
- ZIP de raw bulk (§1.2) ← ficha mirror dos 37 ZIPs RFB.
- Parquet como camada canônica ← ficha tem `cnpjs.parquet`, `socios.parquet`. Nossa `leis-{ente}-v{N}.parquet` + `dispositivos-{ente}-v{N}.parquet` + `versoes-{ente}-v{N}.parquet` seguem mesma filosofia, normalizada em 3 tabelas.
- Footer KV `schema_version` ← ficha embute; replicamos em §3.5.

### Da baliza
- Manifest CSV no IA como source of truth ← baliza usa `baliza-pncp-manifest/manifest.csv`. Nossa `manifest-{ente}.csv` segue mesma estrutura.

### Da causaganha
- Sync manifest por `(tribunal, date)` ← rastreio granular. Nossa rastreia `(ente, fonte, chave)`.

---

## 9. Decisões resolvidas em M0 (rastreio)

- ✅ **Granularidade IA raw**: individual por PDF (§1.1) + bundle ZIP semanal redundante (§1.2).
- ✅ **Slug fonte é `[a-z]+` único** (§5.7).
- ✅ **Bundle `lexml.xsd` no repo** (§6) — reprodutibilidade.
- ✅ **`git_sha` SHA completo (40 chars)** (§3.5).
- ✅ **Regex parsed aceita `\d{5,}`** (§5.3).
- ✅ **Tipo Parquet usa `VARCHAR`** (§3.1–3.3), não `TEXT`.
- ✅ **Fallback parsed inclui `{fonte}`** (§5.3).
- ✅ **`id` Parquet sempre zero-padded** (§3.1).
- ✅ **Dispositivo é unidade primária** (§0.1).
- ✅ **Vigente compilado é canônico, histórico via timeline** (§0.2).
- ✅ **Formato próprio (Leizilla XML), não fork LexML** (§0.3).
- ✅ **SSR híbrido via Astro** (§0.4), softening do princípio 6 anterior.
- ✅ **`urn_lex` Parquet é nullable** (§5.5).
- ✅ **Schema Parquet é v0.1 durante M0–M4; promove a v1 em M5** (§3.6, §7).

## 10. Decisões pendentes (resolver em M0.2)

- [ ] **Verificar URN LEX dialect** (§5.5) — separadores `;`/`,`/`:` contra spec CGPID atual.
- [ ] **Compressão Parquet**: SNAPPY vs ZSTD. Verificar DuckDB-WASM 1.28 (ou versão atual) suporta ZSTD via teste real em M0.2.
- [ ] **Granularidade bundle ZIP**: semanal (`YYYY-Www`) atual; revisitar se tamanho ficar trivial.
- [ ] **XPath dialect em `diff-xpath`** (§4.5) — declarar "XPath 1.0 subset, atributos com aspas simples" (reviewer #6 ponto 9).
- [ ] **Política de re-scrape**: PDF re-publicado pela fonte (hash diferente do anterior) vira novo raw item `{chave}-v2`? Ou substitui? (reviewer #6 ponto 11) — decidir antes de M2.
- [ ] **Robots.txt + rate limiting** como princípio explícito no crawler (reviewer #6 ponto 12) — adicionar em ADR-0008 (pipeline) e `src/leizilla/crawler.py`.
- [ ] **LGPD em leis antigas com nomes** (reviewer #6 ponto 8 da parecer) — triagem necessária? Política de redação? Adiar para v0.2 ou decidir agora?
- [ ] **XSLT in-browser deprecation** (reviewer #6 ponto 4) — confirmar que primário é Astro SSR, XSLT é fallback opcional. Atualizar §4.6 se Astro SSR cobrir 100%.
- [ ] **Estimativa custo LLM realista** (reviewer #6 ponto 6) — recalcular: 5.000 leis × 10k tokens × Haiku ≈ $40–100/ente. Atualizar IMPLEMENTATION.md se diferir muito.

## 11. Open questions (v0.2 ou posterior)

- **Catálogo de fontes federais** (Câmara, Senado, Planalto, DOU) — modelagem em §0.5 acomoda, mas vocabulário concreto fica para quando atacarmos `ente=federal`.
- **Catálogo de fontes municipais** — ~5.570 estruturas distintas; modelo `src/leizilla/fontes/{ente}.py` escala, mas curadoria é desafio próprio.
- **Versionamento de raw quando fonte republica** (overlap com §10) — política mais fina depois.
- **Acessibilidade WCAG completa** — Astro SSR resolve maior parte; auditoria formal em M5.
- **Multilíngua** — fora de escopo Leizilla.
