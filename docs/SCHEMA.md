# SCHEMA.md — Design de dados do Leizilla

> **v2 — redesign a partir de first principles.** Esta versão reescreve a v1 (PR #6) do zero, partindo do princípio "dispositivo é a unidade básica" e derivando o resto. PR #7 (XSD + fixtures sobre o desenho v1) fica como referência histórica do que aprendemos. Ver §0 para o pivô e §9 para a tabela de migração.

Decisões load-bearing — coluna **Status** indica se é `aprovada` ou `superseded-by-#PR`. Documento editado quando uma decisão muda.

Companion docs:
- `IMPLEMENTATION.md` (raiz) — status geral e log de decisões cronológico.
- `docs/schemas/leizilla-v0.1.xsd` — schema XML formal.
- `tests/fixtures/leizilla_xml/` — fixtures cobrindo todos os cenários.

---

## 0. Princípio e o que mudou

### 0.1 Dispositivo é a unidade. Tudo o mais é derivado ou herda.

Lei = árvore de dispositivos. Dispositivo = árvore de dispositivos + linha do tempo de redações. Redação = texto + lista de testemunhos (fontes). Esse é o modelo inteiro.

Tudo o que não cabe nessa frase **não pertence ao XML**:

- **Rótulo** ("Art. 1º", "§ 2º", "I", "a)") é uma função pura de `(tipo, path)` aplicada em render-time. Token map (§4.2) é o contrato público. Sem `<rotulo>` armazenado, sem override por versão.
- **Tipo do dispositivo** (`artigo`, `paragrafo`, `inciso`, `capitulo`...) é derivado do `path` via token map. Não há atributo `tipo` no XML.
- **Parent estrutural** é o nesting XML. Sem atributo `parent` duplicado.
- **URN do dispositivo** é `lei.urn-lex + "!" + path`. Consumer compõe. Sem atributo `urn` no dispositivo.
- **Bloco organizacional** (livro/capítulo/seção) não é categoria separada — é um dispositivo cujo `path` começa com token organizacional. Token map define semântica.
- **OCR ruim** não é elemento separado (`<bloco-livre>`); é um dispositivo com `path="ocr-ruim"` e atributo `quality`. Render decide formato.
- **Texto é texto.** Não há distinção entre "texto normativo" e "nome de capítulo". Capítulo tem texto — o nome dele.

### 0.2 Vigência herda; proveniência é declarada quando importa

Caso default: dispositivo vigora junto com a lei. Não declara nada — herda. Cadeia: `<versao>.em` → ancestral `<dispositivo>` mais próximo que declara → `data-publicacao` extraída da URN da `<lei>`.

Quando um dispositivo tem múltiplas versões (foi alterado), cada `<versao em="X">` declara explicitamente. `vigente-ate` **não é armazenado** — é inferido (próxima versão, ou `<revogacao>` do dispositivo, ou `<revogacao>` da lei, cascateando).

A informação "esta vigência veio de onde" tem qualidade variável:

| `tipo` | Quando aplica |
|---|---|
| `data-publicacao` | Vigência = data da lei (regra default LINDB). |
| `texto-lei-alteradora` | Declarado na lei que alterou (caso comum em alterações). |
| `vacatio-legis` | Texto especifica prazo ("entrará em vigor 90 dias após publicação"); calculada. |
| `consolidacao` | Casa Civil/COTEL adotou sem prova textual no ato original. |
| `inferencia-llm` | Parser inferiu sem evidência textual direta. |
| `decisao-judicial` | STF/STJ modulou efeitos. |

Quando `tipo` é não-óbvio, `<versao>` carrega sub-elemento `<inicio tipo="...">` com `<fonte>` filha apontando para o IA item que materializa a prova. Caso óbvio (ato original ou alteração explícita), `<inicio>` é omitido — `tipo` deriva por default: `data-publicacao` se primeira versão sem `alterado-por`, `texto-lei-alteradora` se há `alterado-por`.

### 0.3 Revogação é evento estruturado

`<revogada>true|false</revogada>` é insuficiente. Revogação tem 4 dimensões: **quem** (URN), **quando** (data de efeito), **tipo jurídico**, **escopo** (parcial vs total).

Elemento `<revogacao em="..." por="..." tipo="...">` com `<fonte>` filha. Posição estrutural indica escopo:
- No root da `<lei>` → revogação total da lei.
- Dentro de `<dispositivo>` → revogação parcial daquele dispositivo (e descendentes via cascata implícita).

Tipos jurídicos:

| `tipo` | `por` | Notas |
|---|---|---|
| `expressa` | URN da lei revogadora | "Fica revogado o art. X". |
| `tacita` | URN da lei posterior | Incompatibilidade material; relação inferida. |
| `caducidade` | (ausente) | Decurso de tempo, leis temporárias. |
| `inconstitucionalidade` | URN da ADI/ADC/ADPF | STF/STJ declarou; tecnicamente não é revogação mas efeito equivalente. |
| `nao-recepcao` | URN da CF | Norma pré-1988 não recepcionada. |

### 0.4 Fonte é uma só; processo vai para sidecar

`<fonte ia-id="...">` é a tag única usada em 4 contextos: testemunho do texto da `<versao>`, prova do `<inicio>` de vigência, prova da `<revogacao>`, e prova da `<revogacao>` total da lei. Sempre aponta para um IA item.

Não existe "fonte canônica" — o texto canônico está no `<texto>` da `<versao>` (compilação best-effort do ETL). Fontes são testemunhos que corroboram (default) ou divergem (`diverge="true"`, carregam `<texto>` próprio inline).

O **processo** que produziu o texto canônico (parse method, modelo LLM, confiança, regras de desempate, timestamp) **não pertence ao XML**. Vai para `parsed_meta.json` (sidecar do parsed item). XML carrega só estrutura normativa.

### 0.5 Auditoria por embeddings (plano paralelo)

Drift entre OCR raw e texto compilado é detectado por comparação de embeddings (`embedding(raw_djvu_txt)` × `embedding(versao.texto)` por dispositivo). Baixa similaridade dispara auditoria humana. Roda em batch periódico, fora do XML.

Implica: **não há flag manual** tipo `revisao-pendente` no XML. LLM não sabe quando errou — pedir auto-flag é contraditório. Auditoria é externa, sistemática, e não polui o conteúdo.

Plano detalhado em arquivo separado (M3+).

---

## 1. Internet Archive — granularidade dos items

(Carregado da v1 — esta parte funciona inalterada.)

### 1.1 Raw items — individual por PDF

**Pattern**: `leizilla-raw-{ente}-{fonte}-{chave}`

| ente | fonte | chave | Exemplo |
|---|---|---|---|
| `ro` | `casacivil` | `coddoc-{N:05d}` | `leizilla-raw-ro-casacivil-coddoc-00042` |
| `ro` | `assembleia` | `coddoc-{N:05d}` | `leizilla-raw-ro-assembleia-coddoc-00042` |
| `ro` | `diario` | `{YYYY-MM-DD}-p{pagina:04d}` | `leizilla-raw-ro-diario-2003-06-15-p0012` |
| `federal` | `planalto` | `lei-{numero:05d}-{ano}` | `leizilla-raw-federal-planalto-lei-12345-2024` |

**Justificativa**: IA faz OCR **apenas** em PDFs individuais (não em PDFs dentro de ZIP). Permalink por PDF facilita citação. Manifest CSV escala para milhares de items.

### 1.2 Raw items — bundle ZIP semanal (redundância)

**Pattern**: `leizilla-bundle-{ente}-{fonte}-{periodo}` onde `{periodo}` = ISO week (`YYYY-Www`).

Layout interno: `manifest.csv` + `pdfs/{chave}.pdf` + `meta/{chave}.json`. Forensics + download em lote.

### 1.3 Parsed items — 1 lei = 1 IA item

**Pattern canônico**: `leizilla-{ente}-{tipo}-{numero:05d}-{ano}`

| Exemplo | Notas |
|---|---|
| `leizilla-ro-lei-01234-2003` | caso normal |
| `leizilla-ro-decreto-00056-2024` | tipo=decreto |
| `leizilla-federal-lc-00141-2012` | LC = lei complementar |

**Pattern fallback** (lei antiga sem numeração formal): `leizilla-{ente}-{tipo}-fallback-{fonte}-{chave}`

**Conteúdo do parsed item**:
```
leizilla-ro-lei-01234-2003/
├── law.xml             ← Leizilla XML v0.1 (canônico)
├── parsed_meta.json    ← processo de parse (método, confiança, divergências)
├── provenance.json     ← rastreabilidade raw items
└── alteracoes.json     ← relações computadas (alterada_por, altera, revogada_por, revoga)
```

Sem HTML pré-gerado (Astro SSR renderiza a partir do `law.xml`). Sem `law.lexml` (export sob demanda; ver §6).

### 1.4 Dataset items — versionados

**Pattern**: `leizilla-dataset-{ente}-v{N}` onde `N = int(major(schema_version))`.

Pre-M5: `schema_version = "0.1"` → `v0`. Post-M5: `schema_version = "1"` → `v1`. `v0` é versão **válida e citável**, não draft/empty.

Conteúdo: `versoes-{ente}-v{N}.parquet` + `manifest-{ente}.csv` + `README.md`.

---

## 2. JSON sidecars

### 2.1 `raw_meta.json`

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
  "ia_id_bundle": "leizilla-bundle-ro-casacivil-2026-W20",
  "provenance_wayback": {
    "fetched_from": "wayback",
    "wayback_url": "https://web.archive.org/web/20260520143000/https://ditel.casacivil.ro.gov.br/cotel/...",
    "wayback_blocked_robots": false
  }
}
```

### 2.2 `parsed_meta.json` — agora carrega o processo

```json
{
  "leizilla_meta_version": "0.1",
  "schema_xml_version": "0.1",
  "urn_lex": "urn:lex:br;estado:rondonia;lei:2003-06-15;1234",
  "ente": "ro",
  "tipo": "lei",
  "numero": "1234",
  "ano": 2003,
  "data_publicacao": "2003-06-15",
  "vigente_em": "2026-05-20",

  "fontes_consultadas": [
    "leizilla-raw-ro-casacivil-coddoc-01234",
    "leizilla-raw-ro-diario-2003-06-15-p0012"
  ],

  "num_dispositivos": 27,
  "num_versoes_total": 31,
  "tem_divergencia": true,
  "num_divergencias": 1,

  "parse_method": "llm-haiku",
  "parse_model": "claude-haiku-4-5-20251001",
  "parse_timestamp": "2026-05-20T18:45:00Z",
  "confianca_parse_global": 0.92,
  "regras_desempate": ["voto-majoritario", "ocr-confianca"],
  "validacao_xsd": "passed",

  "auditoria_embeddings": {
    "ultimo_check": "2026-05-21T03:00:00Z",
    "min_similarity": 0.94,
    "dispositivos_flagged": []
  }
}
```

### 2.3 `provenance.json`

Audit trail mínimo:

```json
{
  "fontes_raw": [
    {
      "ia_id": "leizilla-raw-ro-casacivil-coddoc-01234",
      "ocr_url": "https://archive.org/download/leizilla-raw-ro-casacivil-coddoc-01234/law_djvu.txt",
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

### 2.4 `alteracoes.json` (relações pré-computadas)

Derivado do `law.xml`; regenerado a cada update. Conflito = `law.xml` é fonte de verdade.

```json
{
  "leizilla_meta_version": "0.1",
  "alterada_por": [
    {
      "urn_lex": "urn:lex:br;estado:rondonia;lei:2024-06-30;5678",
      "ia_id": "leizilla-ro-lei-05678-2024",
      "dispositivos_afetados": ["art-3", "art-3-par-1"],
      "data_efeito": "2024-07-30"
    }
  ],
  "altera": [],
  "revogada_por": null,
  "revoga": []
}
```

---

## 3. Schema Parquet v0.1 — tabela única `versoes`

Tabela única denormalizada, grão `lei × dispositivo × versão`. Zero JOIN em DuckDB-WASM, dictionary encoding + SNAPPY compactam redundância. Decisão transicional com gatilhos concretos de revert em M5 (§3.4).

### 3.1 Colunas

Agrupadas por origem (lei / dispositivo / versão). Toda metadata de lei e dispositivo repete por row; emerge via `SELECT DISTINCT`.

**Lei** (repete por linha):

| coluna | tipo | nullable | nota |
|---|---|---|---|
| `lei_id` | VARCHAR | NO | identifier IA do parsed item, zero-padded |
| `ente` | VARCHAR | NO | `ro`, `sp`, `federal`, `ro-porto-velho`... |
| `tipo_lei` | VARCHAR | NO | `lei`, `decreto`, `lc`, `constituicao`... |
| `numero_lei` | VARCHAR | YES | nullable em fallbacks |
| `ano_lei` | INTEGER | NO | |
| `data_publicacao` | DATE | YES | extraída da URN; nullable em fallbacks |
| `urn_lex_lei` | VARCHAR | YES | nullable se `data_publicacao` desconhecida |
| `vigente_em` | DATE | NO | data de referência da compilação |
| `lei_revogada` | BOOLEAN | NO | true se `<revogacao>` na raiz |
| `lei_revogada_em` | DATE | YES | data efeito |
| `lei_revogada_por` | VARCHAR | YES | URN da revogadora |
| `lei_revogada_tipo` | VARCHAR | YES | enum de revogação |

**Dispositivo** (repete por versão):

| coluna | tipo | nullable | nota |
|---|---|---|---|
| `dispositivo_path` | VARCHAR | NO | global p/ normativos, namespaceado p/ organizacionais |
| `dispositivo_tipo` | VARCHAR | NO | derivado do path via token map |
| `dispositivo_ordem` | INTEGER | NO | ordem dentro do parent estrutural |
| `dispositivo_parent_path` | VARCHAR | YES | NULL para top-level |
| `dispositivo_revogado` | BOOLEAN | NO | |
| `dispositivo_revogado_em` | DATE | YES | |
| `dispositivo_revogado_por` | VARCHAR | YES | |
| `dispositivo_revogado_tipo` | VARCHAR | YES | |
| `urn_dispositivo` | VARCHAR | YES | `urn_lex_lei + "!" + path`; NULL se `urn_lex_lei` é NULL |

**Versão** (unique por row):

| coluna | tipo | nullable | nota |
|---|---|---|---|
| `versao_id` | VARCHAR | NO | `{dispositivo_path}#{em}` |
| `em` | DATE | NO | data de início da versão (chave natural) |
| `ate` | DATE | YES | inferido; NULL = ainda vigente |
| `alterado_por` | VARCHAR | YES | URN da lei alteradora |
| `inicio_tipo` | VARCHAR | NO | enum: `data-publicacao` (default) / `texto-lei-alteradora` / `vacatio-legis` / `consolidacao` / `inferencia-llm` / `decisao-judicial` |
| `texto` | VARCHAR | YES | texto canônico estabelecido |
| `texto_normalizado` | VARCHAR | YES | NFC + cleanup; NOT NULL quando `texto` NOT NULL |
| `fontes` | VARCHAR (JSON) | NO | array de `{ia_id, diverge?, texto_divergente?}` |
| `num_fontes` | INTEGER | NO | |
| `tem_divergencia` | BOOLEAN | NO | true se alguma fonte tem `diverge=true` |
| `hash_texto` | VARCHAR | YES | sha256 |
| `quality` | VARCHAR | YES | NULL (parse OK) / `low` / `medium` / `high` / `raw` (OCR ruim) |

### 3.2 Padrões de query

Vigente em data X:
```sql
SELECT * FROM versoes
WHERE lei_id = ?
  AND em <= '2020-01-01'
  AND (ate IS NULL OR ate > '2020-01-01')
  AND NOT dispositivo_revogado
ORDER BY dispositivo_path;
```

TOC (estrutura da lei):
```sql
-- token_map(dispositivo_tipo, dispositivo_path) → rotulo deriva em código,
-- não em SQL (rotulo não é armazenado).
SELECT DISTINCT dispositivo_path, dispositivo_tipo, dispositivo_parent_path, dispositivo_ordem
FROM versoes
WHERE lei_id = ?
ORDER BY dispositivo_ordem;
```

Busca full-text:
```sql
SELECT lei_id, dispositivo_path, em
FROM versoes
WHERE texto_normalizado LIKE '%transparência%'
  AND ate IS NULL;
```

### 3.3 Footer KV metadata (PyArrow ou DuckDB COPY)

```python
{
  "leizilla.schema_version": "0.1",
  "leizilla.xml_schema_version": "0.1",
  "leizilla.ente": "ro",
  "leizilla.table": "versoes",
  "leizilla.generated_at": "2026-05-20T19:00:00Z",
  "leizilla.row_count": "12483",
  "leizilla.git_sha": "abc1234def5678901234567890abcdef12345678"
}
```

Writer choice (PyArrow `write_table` vs DuckDB `COPY ... (KV_METADATA ...)`) deferido para M4.

### 3.4 Gatilhos de revert para schema multi-tabela

Single-table é decisão transicional. Revisita em M5 com dados reais. Gatilhos concretos:

- `file > 100 MB`
- `cold-fetch > 5s P50` em DuckDB-WASM
- `DuckDB-WASM memory > 500 MB`
- `search > 1s P95`
- `rows > 2M`

**1 gatilho → RFC** discutindo split. **2+ gatilhos → split obrigatório** antes de M5 close. M4 inclui benchmark scripts medindo todos.

---

## 4. Leizilla XML v0.1 — formato canônico

### 4.1 Estrutura

```
<lei> [xmlns, schema-version, urn-lex, vigente-em]
  <revogacao>?              [em, por?, tipo]
    <fonte/>+               [ia-id]
  <dispositivo>+ [path, quality?]
    <versao>+               [em?, alterado-por?]
      <inicio>?             [tipo]
        <fonte/>+           [ia-id]
      <texto/>
      <fonte/>+             [ia-id, diverge?]
        <texto/>?           (só quando diverge="true")
    <dispositivo>*          (recursivo)
    <revogacao>?            [em, por?, tipo]
      <fonte/>+
```

**6 elementos** (`<lei>`, `<dispositivo>`, `<versao>`, `<inicio>`, `<texto>`, `<fonte>`, `<revogacao>`). `<texto>` e `<fonte>` são folhas com semântica contextual (`<fonte>` em `<versao>` testemunha texto; em `<inicio>` testemunha vigência; em `<revogacao>` testemunha revogação — mesma tag, contexto distinto).

### 4.2 Token map — contrato público

Path determina tipo. Token map é a fonte única de verdade.

**Tokens normativos** (dispositivos com texto):

| Token (path prefix) | Tipo | Rótulo derivado |
|---|---|---|
| `titulo-lei` | titulo-lei | "Título" |
| `ementa` | ementa | "Ementa" |
| `preambulo` | preambulo | "Preâmbulo" |
| `art-N` | artigo | "Art. Nº" (1º–9º com ordinal; Nº a partir de 10) |
| `par-N` ou `par-unico` | paragrafo | "§ Nº" ou "Parágrafo único" |
| `inc-N` | inciso | numeral romano de N |
| `ali-X` (a, b, c...) | alinea | "X)" |
| `item-N` | item | "N." |
| `anexo-N` | anexo | "Anexo N" (romanos) |
| `disp-transitoria-N` | disposicao-transitoria | "Art. N (Disposições Transitórias)" |
| `disp-final-N` | disposicao-final | "Art. N (Disposições Finais)" |
| `ocr-ruim` ou `ocr-ruim-N` | bloco-ocr-ruim | (sem rótulo; render mostra banner) |

**Tokens organizacionais** (agrupadores; texto = nome do bloco):

| Token | Tipo | Rótulo derivado |
|---|---|---|
| `liv-N` | livro | "LIVRO Nº" |
| `parte-N` | parte | "PARTE Nº" |
| `tit-N` | titulo | "TÍTULO Nº" |
| `cap-N` | capitulo | "CAPÍTULO Nº" |
| `sec-N` | secao | "Seção Nº" |
| `subsec-N` | subsecao | "Subseção Nº" |

**Regras de path**:
- Normativos têm path **global**: `art-5` é sempre `art-5`, independente de onde está aninhado.
- Sub-dispositivos normativos compõem o path do ancestral normativo: `art-5-par-2`, `art-5-par-2-inc-3`, `art-5-par-2-inc-3-ali-a`.
- Organizacionais têm path **namespaceado pelo nesting**: `tit-2`, `tit-2-cap-1`, `tit-2-cap-1-sec-3`.
- Quando normativo está dentro de organizacional, path permanece global mas o nesting XML preserva o agrupamento. Não há duplicação de path.
- **Renumeração por emenda** (e.g., "Art. 5º-A" inserido por emenda entre art. 5 e art. 6): path usa sufixo letra → `art-5-a`. Token map mapeia `art-N` e `art-N-X` (X = letra) para tipo `artigo` com rótulo derivado "Art. Nº" ou "Art. Nº-X". Validação real desse padrão fica para M3 quando expusermos leis com emendas.

Adicionar novo tipo de dispositivo no futuro = adicionar entrada no token map. XSD não muda (path pattern é genérico).

### 4.3 Herança de vigência

Cadeia de resolução para `versao.em`:

1. Se `<versao em="X">` declarado → usa X.
2. Senão → herda do ancestral `<dispositivo>` mais próximo que tem uma `<versao>` com `em` declarado.
3. Senão → herda da `<lei>.data-publicacao` extraída da URN.

**`vigente-ate` não é armazenado**. Fim de uma versão é inferido por (em ordem):
1. Próxima `<versao em="...">` no mesmo dispositivo.
2. `<revogacao em="...">` filho do mesmo dispositivo.
3. `<revogacao em="...">` filho da `<lei>` (cascateia para todos os dispositivos).
4. Caso contrário → ainda vigente.

Caso comum (lei pequena sem alterações, todo dispositivo herda):

```xml
<lei xmlns="https://leizilla.org/lei/0.1"
     schema-version="0.1"
     urn-lex="urn:lex:br;estado:rondonia;lei:1999-06-15;9999"
     vigente-em="2026-05-20">

  <dispositivo path="ementa">
    <versao>
      <texto>Institui o Dia Estadual do Servidor Público.</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-09999"/>
    </versao>
  </dispositivo>

  <dispositivo path="art-1">
    <versao>
      <texto>Fica instituído...</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-09999"/>
    </versao>
  </dispositivo>

</lei>
```

Zero `em`, zero `vigente-ate`, zero ruído. Tudo herda.

### 4.4 `<inicio>` — proveniência da vigência

Sub-elemento opcional de `<versao>`. Carrega `tipo` enum + `<fonte>` filha(s) apontando para o IA item que materializa a prova.

```xml
<!-- Vacatio: lei publicada em 15/06, vigora 90 dias depois -->
<versao em="2003-09-13">
  <inicio tipo="vacatio-legis">
    <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-01234"/>
  </inicio>
  <texto>...</texto>
  <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-01234"/>
</versao>

<!-- Inferência LLM (baixa confiança) -->
<versao em="2015-03-15">
  <inicio tipo="inferencia-llm">
    <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-07777"/>
  </inicio>
  <texto>...</texto>
  <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-07777"/>
</versao>

<!-- Consolidacao sem prova textual no ato original -->
<versao em="2010-01-01">
  <inicio tipo="consolidacao">
    <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-03333"/>
  </inicio>
  <texto>...</texto>
  <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-03333"/>
</versao>
```

**Defaults implícitos** (`<inicio>` omitido):
- Primeira versão (sem `alterado-por`) com `em` herdado da `<lei>` → `tipo = data-publicacao`.
- Versão com `alterado-por` → `tipo = texto-lei-alteradora`.

**Obrigatório** quando: `em` declarado, `em ≠ data-publicacao` da lei, e sem `alterado-por`. Consistency checker (§7) valida.

### 4.5 `<revogacao>` — evento estruturado

Posição estrutural indica escopo:

**Revogação total da lei** (no root, antes de `<dispositivo>`):

```xml
<lei urn-lex="..." vigente-em="..." schema-version="0.1">
  <revogacao em="2025-01-01" tipo="expressa"
             por="urn:lex:br;estado:rondonia;lei:2024-12-01;9999">
    <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-09999"/>
  </revogacao>
  <dispositivo path="...">...</dispositivo>
</lei>
```

**Revogação parcial** (dentro de um `<dispositivo>`, depois das `<versao>`s e dos sub-dispositivos):

```xml
<dispositivo path="art-5">
  <versao>
    <texto>...</texto>
    <fonte ia-id="..."/>
  </versao>
  <revogacao em="2020-01-01" tipo="expressa"
             por="urn:lex:br;estado:rondonia;lei:2020-01-01;9999">
    <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-09999"/>
  </revogacao>
</dispositivo>
```

**Inconstitucionalidade**:

```xml
<dispositivo path="art-7">
  <versao>
    <texto>...</texto>
    <fonte ia-id="..."/>
  </versao>
  <revogacao em="2018-05-10" tipo="inconstitucionalidade"
             por="urn:lex:br;federal;adi:2017-03-15;5678">
    <fonte ia-id="leizilla-raw-federal-stf-adi-5678-2018"/>
  </revogacao>
</dispositivo>
```

**Caducidade** (sem `por`):

```xml
<dispositivo path="art-9">
  <versao em="1990-01-01">
    <texto>Esta Lei vigora por 5 anos a partir de sua publicação.</texto>
    <fonte ia-id="..."/>
  </versao>
  <revogacao em="1995-01-01" tipo="caducidade">
    <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-01111"/>
  </revogacao>
</dispositivo>
```

### 4.6 `<fonte>` — testemunhas

Mesma tag em 4 contextos. Atributos:

- `ia-id` (obrigatório): identifier do IA raw item.
- `diverge` (opcional, só no contexto `<versao>`): `true` se esta fonte tem texto diferente do `<texto>` canônico. Carrega `<texto>` filho inline.

```xml
<versao em="2003-06-15">
  <texto>Texto canônico estabelecido pelo ETL.</texto>
  <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-01234"/>
  <fonte ia-id="leizilla-raw-ro-diario-2003-06-15-p0012"/>
  <fonte ia-id="leizilla-raw-ro-assembleia-coddoc-01234" diverge="true">
    <texto>Texto alternativo desta fonte que discorda.</texto>
  </fonte>
</versao>
```

Caso comum (uma ou várias fontes que concordam): só `<fonte ia-id="..."/>`. Sem `canonica`. Texto canônico está no `<texto>` da versão.

### 4.7 OCR ruim — sem elemento especial

OCR irrecuperável vira dispositivo regular com `path="ocr-ruim"` e atributo `quality`. Render mostra banner; sem `<bloco-livre>` separado no XSD.

```xml
<dispositivo path="ocr-ruim" quality="raw">
  <versao>
    <texto>LE| N° 42/8S - 20 DE NOVEMBR0 DE 19BS

O G0VERNAD0R D0 ESTAD0 DE R0NDONIA, faç0 saber que a A55embleia Legislativa decret@ e eu sancion0 a seguinte Lei:

Art. 1° Fica criad0 0 Conselh0 Estadual de Cultura...
[trecho i|egível n0 OCR]
Art. 4° Esta Lei entra em vigor na data de 5ua publicação.</texto>
    <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00042"/>
  </versao>
</dispositivo>
```

`quality` enum: `low` / `medium` / `high` / `raw`. Atributo só aparece quando `path` começa com `ocr-ruim` (consistency checker valida).

**Múltiplos blocos OCR-ruim**: quando uma lei tem várias seções ilegíveis intercaladas com dispositivos parseados, usar `path="ocr-ruim-1"`, `path="ocr-ruim-2"`, ... — token `ocr-ruim-N` é parte do token map (§4.2). Path único na árvore continua sendo invariante (`xs:unique` no XSD).

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

### 5.3 Parsed canônico
```
^leizilla-(?P<ente>[a-z][a-z0-9-]*)-(?P<tipo>[a-z]+)-(?P<numero>\d{5,})-(?P<ano>\d{4})$
```

`numero` em `id` é **sempre zero-padded** (mínimo 5 dígitos). Numero não-numérico (raro em leis antigas) → fallback pattern.

### 5.4 Parsed fallback
```
^leizilla-(?P<ente>[a-z][a-z0-9-]*)-(?P<tipo>[a-z]+)-fallback-(?P<fonte>[a-z]+)-(?P<chave>[a-z0-9-]+)$
```

`{fonte}` obrigatório evita colisão entre fontes com mesma `chave`.

### 5.5 Dataset
```
^leizilla-dataset-(?P<ente>[a-z][a-z0-9-]*)-v(?P<version>\d+)$
```

`v0` (pre-M5, schema_version "0.1") é válido e citável.

### 5.6 URN LEX

**Lei**: `urn:lex:br;{jurisdicao};{tipo}:{YYYY-MM-DD};{numero}`
- `{jurisdicao}` para estados: `estado:rondonia` / `estado:sao-paulo`
- `{jurisdicao}` para federal: `federal`
- `{jurisdicao}` para municípios: `municipio:rondonia;porto-velho`

**Dispositivo**: `{urn-lei}!{path}` — exemplo: `urn:lex:br;estado:rondonia;lei:2003-06-15;1234!art-5!par-2`.

**Constituição** (sem número): `urn:lex:br;federal;constituicao:1988-10-05` (sem `;numero` final).

**Lei sem numero** (fallback): omitir o `;{numero}` final OU registrar `urn_lex` como NULL no Parquet. Identifier IA usa pattern fallback (§5.4).

> Dialect provisório — pendente verificação contra spec CGPID atual. Ver §8.

### 5.7 Slug `{ente}`

- União: `federal`
- Estados: ISO 3166-2:BR sem `BR-`, lowercase: `ro`, `sp`, `mg`...
- Municípios: `{uf}-{slug-kebab}`: `ro-porto-velho`, `sp-sao-paulo`
- DF: `df`

Lista canônica em `src/leizilla/entes.py` (M1).

### 5.8 Slug `{fonte}`

Token único `[a-z]+` (sem hífens, sem underscores). Hífen quebraria parsing de `leizilla-raw-{ente}-{fonte}-{chave}`. Slugs canônicos: `casacivil`, `diario`, `assembleia`, `planalto`, `camara`, `senado`, `stf`.

Display names longos (`Diário Oficial do Estado`) ficam em `display_name` / metadata IA legível, nunca no slug.

---

## 6. Export LexML — gate de CI

LexML é representação reduzida, gerada sob demanda para gov interop. Não é round-trip.

**Perdas conhecidas** (documentadas no XSLT):
- `quality="raw"` (OCR ruim) → vira `<Texto>` cru sem marcação.
- `<fonte diverge="true">` → descartado (LexML não modela divergência multi-fonte).
- Atributos `<inicio tipo>` e `<revogacao tipo>` → mapeados em LexML quando equivalente existe, descartados caso contrário.
- Timeline `<versao>` colapsa para `<TextoArticulado>` da versão vigente em `vigente-em`; histórico mapeia para `<Alteracao>` LexML quando possível.

**CI gate**:
- A cada PR, `pytest tests/test_lexml_export.py`:
  1. Lê fixtures `tests/fixtures/leizilla_xml/*.xml`.
  2. Aplica `scripts/leizilla-to-lexml.xsl`.
  3. Valida XML resultante contra `tests/fixtures/lexml.xsd` (bundle no repo, reprodutibilidade).
  4. Falha se LexML não validar.

CI **não** valida round-trip (LexML → Leizilla XML não é objetivo).

---

## 7. Invariantes do consistency checker

XSD não consegue expressar tudo. `scripts/check_schema_consistency.py` (M0.2) valida:

1. **`<fonte diverge="true">` requer `<texto>` filho**; `<fonte>` sem `diverge` não pode ter `<texto>` filho.
2. **`<revogacao>` na raiz da `<lei>` exclui** qualquer `<revogacao>` em dispositivo descendente (revogação total cascateia).
3. **`<revogacao tipo="caducidade">` não tem atributo `por`**; demais tipos têm.
4. **`path` casa com token map** (§4.2). Tokens desconhecidos → erro.
5. **Herança de vigência**: `<versao>` sem `em` resolve para ancestral declarado ou `data-publicacao` da URN. *Carve-out*: quando `urn-lex` é ausente (caso OCR-ruim fallback), vigência genuinamente não tem âncora — checker exempta. Se `urn-lex` presente mas indecodificável (regex §5.6 falha), §7.5 reporta uma vez por lei.
6. **`<inicio>` obrigatório** quando `<versao em="X">` com `X ≠ data-publicacao(<lei>)` e sem `alterado-por`.
7. **Ordenação de versões** num dispositivo: `em` estritamente crescente.
8. **`<fonte ia-id>`** casa com regex de IA identifier (§5.1).
9. **`quality` atributo** só aparece em `<dispositivo>` com `path` começando por `ocr-ruim`.
10. **`urn-lex` da `<lei>`** (se presente) decompõe corretamente: ente, tipo, data, numero recuperados batem com o `id` do parsed item. **`urn-lex` ausente**: ente e tipo recuperados via decomposição do `id` do parsed item (regex §5.3 ou §5.4), e a fonte canônica de identidade vira o IA identifier.
11. **Exemplos no markdown** (`docs/SCHEMA.md`, `IMPLEMENTATION.md`) que aparentam ser IA identifiers casam com regex em §5.
12. **`schema_version`** no XSD, no footer KV do Parquet, e no `schema-version` attribute do `<lei>` root concordam.
13. **Path único** em toda a árvore de dispositivos da lei (validado pelo `xs:unique` no XSD; checker confirma como duplo-check).
14. **URN LEX sem zero-pad**: número da lei na URN é o número legal raw (`;1234`, `;42`). Zero-pad é exclusivo do identifier IA (`leizilla-ro-lei-00042-1985`); checker rejeita URNs com `;0+\d+` quando o número subjacente tem &lt; 5 dígitos.
15. **Elemento raiz é `<lei>`** no namespace `https://leizilla.org/lei/0.1`. XML bem-formado com root diferente é violação estrutural (checker exit 1), distinta de XML mal-formado (parse error, exit 2).

---

## 8. Decisões resolvidas / pendentes / abertas

### 8.1 Resolvidas em M0.2 (este redesign)

- ✅ **Dispositivo é unidade universal**; tipo, parent, urn, rotulo todos derivados.
- ✅ **Vigência herda do pai**; `vigente-ate` é inferido, não armazenado.
- ✅ **`<inicio>` com `tipo` enum + `<fonte>` filha** documenta proveniência da vigência.
- ✅ **`<revogacao>` rica**: `em`, `por`, `tipo` enum, `<fonte>` filha; posição estrutural = escopo (total vs parcial).
- ✅ **`<fonte>` é uma só** em 4 contextos; sem `canonica`; `diverge="true"` carrega texto inline.
- ✅ **`<bloco-livre>` desaparece**: OCR ruim vira `<dispositivo path="ocr-ruim" quality="...">`.
- ✅ **Processo (parse method, confiança, divergências detalhadas)** vai 100% para `parsed_meta.json`; XML carrega só estrutura normativa.
- ✅ **Token map** é fonte única de verdade para tipo de dispositivo.
- ✅ **Auditoria por embeddings raw vs parseado** substitui flags manuais de "revisão pendente".

### 8.2 Pendentes (resolver em M0.3 antes de fechar M0)

- [ ] **URN LEX dialect**: verificar contra spec CGPID atual se separadores são `;`/`,`/`:` em casos como `urn:lex:br;rondonia:estadual:lei,2003-06-15;1234`.
- [ ] **Compressão Parquet**: SNAPPY vs ZSTD. Verificar suporte em DuckDB-WASM via benchmark real.
- [ ] **Granularidade bundle ZIP**: semanal vs mensal — revisitar se tamanho ficar trivial em M2.
- [ ] **Política de re-scrape**: PDF re-publicado pela fonte (hash diferente) vira `{chave}-r{N}`? Só sob auditoria, nunca automático.
- [ ] **Robots.txt + rate limiting** como princípio explícito do crawler (ADR-0008 em M1).
- [ ] **Estimativa real de custo LLM** após M2 expor casos reais.

### 8.3 Open questions (v0.2+)

- **Catálogo de fontes federais** (Câmara, Senado, Planalto, DOU) — modelo acomoda, vocabulário concreto quando atacarmos `ente=federal`.
- **Catálogo de fontes municipais** — 5.570 estruturas distintas; modelo escala, curadoria é desafio próprio.
- **Auditoria por embeddings** detalhada em plano separado (M3+).

---

## 9. Migração desde a v1 do schema (PR #6/#7)

| v1 (PR #6/#7) | v2 (este PR) | Razão |
|---|---|---|
| `<header>` com `<ente>`, `<tipo>`, `<numero>`, `<ano>`, `<data-publicacao>`, `<vigente-em>`, `<revogada>` | Atributos do root `<lei>` (`urn-lex`, `vigente-em`); revogada vira `<revogacao>` elemento; o resto é derivado da URN | Header inteiro era 90% derivável da URN LEX |
| `<rotulo>` armazenado | Derivado de `(tipo, path)` via token map em render-time | Apresentação, não dado |
| `<rotulo_versao>` para override | Eliminado | Cai junto com `<rotulo>` |
| Atributo `tipo` no dispositivo | Derivado do `path` via token map | Redundante |
| Atributo `parent` no dispositivo | Nesting XML é o parent | Duplicação = bug surface |
| Atributo `urn` no dispositivo | `lei.urn-lex + "!" + path` em render-time | Derivado |
| `<versoes>` wrapper | `<versao>` filha direta de `<dispositivo>` | XML-academic |
| `<versao numero="N">` | `<versao em="...">` (data é chave natural) | Mais self-documenting |
| `<fonte-canonica>` elemento separado + `<fonte>` lista | `<fonte>` única tag; texto canônico está em `<texto>` da versão | "Fonte canônica" não existe — texto canônico existe |
| `<anotacoes>` no XML (`<divergencia>`, `<parse>`) | Vai para `parsed_meta.json` sidecar | Processo, não conteúdo |
| `<bloco-livre>` elemento separado | `<dispositivo path="ocr-ruim" quality="...">` | Tudo é dispositivo |
| `<revogada>true/false</revogada>` | `<revogacao em="..." por="..." tipo="...">` com `<fonte>` filha | Revogação é evento estruturado |
| `vigente-de` / `vigente-ate` em toda versão | Herança implícita; `em` só onde difere; `vigente-ate` é inferido | Caso comum não declara nada |
| Flag manual de auditoria/revisão | Auditoria por embeddings (sistema externo) | LLM não sabe quando errou |

**Status do PR #7**: superseded. Fica como referência histórica do design v1.
