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
- **Qualidade de parse não é caso de modelagem.** OCR ruim, LLM falhou parcialmente, etc. são **processo**, não conteúdo. Política: lei mal-parseada **não tem parsed item** (fica só como raw IA item público com OCR); lei parcialmente parseada carrega o texto cru no próprio `<texto>` do dispositivo afetado — sem flag, sem atributo, sem path mágico. Audit por embeddings (§0.5) e `confianca_parse_global` em `parsed_meta.json` são as fontes de verdade pra qualidade. Esse é o mesmo princípio aplicado a `revisao-pendente`: o sistema que produz o texto não é o sistema que sabe se errou.
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

### 0.6 Granularidade é incremental — publica cedo, refina depois

O schema **permite explicitamente** que uma lei inteira viva num único `<dispositivo>` com o texto integral no `<texto>`. Isso é XSD-válido e checker-válido:

```xml
<lei urn-lex="..." vigente-em="..." schema-version="0.1">
  <dispositivo path="art-1">
    <versao>
      <texto>[texto integral da lei, sem separar artigos/parágrafos/etc.]</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-coddoc-00042"/>
    </versao>
  </dispositivo>
</lei>
```

Por design — não é fallback nem caso degenerado. É a ponta "mínima viável" de um espectro contínuo:

- **Pass 1** (deterministic, regex bruto): identifica que é Lei nº 42/1985 mas não separa artigos. Publica como 1 dispositivo carregando o corpo inteiro.
- **Pass 2** (LLM Haiku): refina, identifica artigos e parágrafos. Sobrescreve parsed item.
- **Pass 3** (LLM Opus + curadoria): chega ao ideal (incisos, alíneas, blocos organizacionais).

O dataset é útil desde o pass 1 — busca full-text funciona, identifier é citável, audit por embeddings já roda. Não precisamos esperar parsing perfeito pra publicar.

Implicações que decorrem disso (e estão em outras seções):
- Token map (§4.2) é a única fonte de tipo — `<dispositivo>` é o único elemento de conteúdo.
- Pipeline binário pra qualidade (§4.7): publica o que conseguir; lei totalmente ilegível fica só como raw.
- Sem `<bloco-livre>`, sem `quality`, sem flag de "parse parcial" — texto cru é só texto.

---

## 1. Internet Archive — granularidade dos items

(Carregado da v1 — esta parte funciona inalterada.)

### 1.1 Raw items — identity-keyed range buckets (ADR-0011)

> **Atualizado por [ADR-0011](adr/0011-raw-identity-keyed-range-items.md).** A
> camada raw deixou de ter "um item IA por PDF". Hoje o item IA é um *range
> bucket* por **identidade** `(ente, fonte, tipo, número)`, e os arquivos dentro
> dele são content-addressed (UUIDv5 truncado). O `leizilla-raw-{ente}-{fonte}-{chave}`
> abaixo permanece como o **raw_id lógico** (chave no DuckDB/CLI e em `<fonte
> ia-id="…">`); ele não é mais o identificador do item IA — é resolvido para a URL
> real via o `index.csv` do item.

**raw_id lógico**: `leizilla-raw-{ente}-{fonte}-{chave}`, onde `{chave}` identifica
a norma como `{tipo}-{número:05d}` (ex.: `lei-05120`, `lc-00042`, `decreto-01234`).

**Identidade é evidência, não catraca de ingestão** (ADR-0011, §1 revisada): a
captura é decidida pelo **contexto da descoberta** (uma estratégia ciente de
legislação apontou para o recurso), não pela leitura do documento. Tudo o que se
descobre é **preservado** content-addressed; a identidade `(tipo, número)` é uma
hipótese refinada a jusante (padrão → listagem → OCR/parse) que **promove** o
recurso ao item de range. Chaves não-identificantes (`coddoc`, `seq`, `fallback`,
`documento`) ainda não entram no **catálogo navegável** — ficam na área de espera
`leizilla_{ente}_{fonte}_unidentified` até a reconciliação, nunca descartadas.

| ente | fonte | chave | Item IA (range) |
|---|---|---|---|
| `ro` | `casacivil` | `{tipo}-{N:05d}` (de `L{N}.pdf`) | `leizilla_ro_casacivil_lei_5001-6000` |
| `federal` | `planalto` | `{tipo}-{N:05d}` | `leizilla_federal_planalto_lei_12001-13000` |
| `ro` | `assembleia` | `{tipo}-{N:05d}` (título da página) | `leizilla_ro_assembleia_lei_5001-6000` |
| (qualquer) | (qualquer) | sem número resolvido → **preservado**, aguardando reconciliação | `leizilla_{ente}_{fonte}_unidentified` |

Dentro do item: `{uuid5}.pdf` / `{uuid5}_djvu.txt` (OCR derivado pelo IA) /
`{uuid5}_meta.json`, e um `index.csv` mapeando `(tipo, número, rendição, formato)
→ {uuid5, sha256, captured_at, source}` (newest-wins). A coluna `source` é a
chave de colheita / URL de origem (ADR-0010), mapeando cada arquivo à sua fonte
— é o que permite à identidade descartar o `coddoc`. Versões e rendições coexistem
como arquivos hash distintos; dedup e detecção de colisão usam o `sha256` completo.

**Justificativa**: IA faz OCR **apenas** em PDFs individuais (não em ZIP), e
agrupar por range mantém o catálogo navegável e o número de items sob controle.

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

### 4.7 Qualidade de parse não vive no XML

Não há elemento, atributo, ou path mágico para "OCR ruim" / "LLM falhou". A política é binária:

- **Parse confiável** (audit por embeddings passa) → publica parsed item normalmente.
- **Parse parcial** (alguns dispositivos OK, outros saem com texto cru) → publica mesmo assim; texto cru entra no `<texto>` do dispositivo afetado, sem flag. Erros tipo `LE| N° 42/8S` ficam visíveis no render (usuário humano percebe) e disparáveis via similaridade no audit.
- **Parse falhou inteiro** → **não publica parsed item**. Lei fica só como raw IA item (PDF + OCR público no IA); frontend mostra "em processamento" + link pro raw.

Onde a sinalização de qualidade vive:
- Granular: `parsed_meta.json.confianca_parse_global` + `auditoria_embeddings.dispositivos_flagged[]` (por path).
- Agregada: filtro Parquet em `confianca_parse < X` ou `min_similarity < Y`.

Esse é o mesmo princípio que eliminou `revisao-pendente` no XML (§0.5): o sistema que produz o texto não é o sistema que sabe se errou. Audit por embeddings dispara reprocessamento automaticamente.

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

### 5.6 URN LEX (spec oficial CGPID 2008)

Resolvida em M0.3 contra a spec oficial **LexML Brasil Parte 2 — LexML URN v1.0 (Dezembro/2008)** (`https://projeto.lexml.gov.br/documentacao/Parte-2-LexML-URN.pdf`). Gramática canônica:

```
urn:lex:br(;{local})*:{autoridade}:{tipo}:{descritor}(!{path-dispositivo})*
```

**`<local>`** — começa com `br`, opcionalmente seguido de `;{estado}` e `;{municipio}`:
- Federal: `br`
- Estado de Rondônia: `br;rondonia`
- Município de Porto Velho-RO: `br;rondonia;porto.velho`
- Distrito Federal: `br;distrito.federal`

Nomes em minúsculas, por extenso, sem hífen — espaços viram `.`. **Não há prefixo `estado:` ou `municipio:`**: a posição no `<local>` define a hierarquia.

**`<autoridade>`** — para normas comuns (leis, decretos, etc.) usa-se uma das três strings convencionadas:
- `federal` (esfera União)
- `estadual` (esfera estado)
- `municipal` (esfera município)

Outras normas (resoluções, portarias, instruções normativas) especificam autoridade emitente unívoca (ex: `ministerio.fazenda;secretaria.receita.federal`).

**`<tipo-documento>`** — vocabulário fixo: `lei`, `decreto`, `lei.complementar`, `medida.provisoria`, `constituicao`, `emenda.constitucional`, `resolucao`, `portaria`...

**`<descritor>`** — combina data e número:
- Canônica: `{YYYY-MM-DD};{numero}` (ex: `2003-10-01;10741`).
- Reduzida (URN de Referência): só ano permitido (`2003;10741`).
- Sem número (raro): usa `lex-{N}` autogerado (`1999-12-21;lex-16`) ou apelido (`2003-10-01;estatuto.idoso`).

**`<path-dispositivo>`** — separado por `!`. Sintaxe interna usa `_` entre tokens (formato LexML idArtigo): `!art1`, `!art5_par2`, `!art5_par2_inc3`, `!art12-2_inc3_alt1` (renumeração com letra → `-N`, alteração com `_alt{N}`).

### Exemplos

| Norma | URN canônica |
|---|---|
| Lei federal 14.133/2021 | `urn:lex:br:federal:lei:2021-04-01;14133` |
| Lei RO 1234/2003 | `urn:lex:br;rondonia:estadual:lei:2003-06-15;1234` |
| Lei municipal Porto Velho 123/2010 | `urn:lex:br;rondonia;porto.velho:municipal:lei:2010-05-15;123` |
| CF/88 | `urn:lex:br:federal:constituicao:1988-10-05` |
| EC 45/2004 | `urn:lex:br:federal:emenda.constitucional:2004-12-30;45` |
| Art. 5º CF | `urn:lex:br:federal:constituicao:1988-10-05!art5` |
| Art. 5º §2º inc. III CF | `urn:lex:br:federal:constituicao:1988-10-05!art5_par2_inc3` |
| Anexo I lei RO 9999/1999 | `urn:lex:br;rondonia:estadual:lei:1999-06-15;9999!anexo.1` |

### Fallback (Leizilla)

Quando data ou número não são extraíveis do PDF (caso raro em leis antigas), o `urn-lex` da `<lei>` é **omitido** no XML. Identidade é recuperada do filename canônico ou fallback (§5.3/§5.4). Consistency checker §7.10 valida cross-check.

### 5.7 Slug `{ente}` (interno Leizilla)

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

### 6.1 Por que não adotamos LexML diretamente

LexML/Akoma Ntoso são **document-centric** com vocabulário rico (~30 elementos prescritos com cardinalidades fixas). Funciona bem quando o produto final é "um documento jurídico canônico para tramitação". Nosso produto é "indexar tudo o que existe e melhorar com o tempo" — trade-off oposto.

| Dimensão | LexML/Akoma Ntoso | Leizilla XML |
|---|---|---|
| **Filosofia** | Document-centric. `<Documento>` → `<ParteInicial>` → `<ParteNormativa>` → `<Articulacao>` → `<Artigo>` → `<Caput>` → ..., cada nível com cardinalidade prescrita. | Dispositivo-centric. Lei é árvore de `<dispositivo>` recursivos. Tipologia jurídica vive no `path` via token map. |
| **Elementos** | ~30+ elementos distintos: `<Artigo>`, `<Paragrafo>`, `<Inciso>`, `<Alinea>`, `<Caput>`, `<Capitulo>`, `<Secao>`... | 6 elementos: `<lei>`, `<dispositivo>`, `<versao>`, `<inicio>`, `<texto>`, `<fonte>`, `<revogacao>`. |
| **Validação parcial** | Tudo-ou-nada. Schema exige estrutura completa; lei mal-parseada falha XSD. | Spectrum contínuo (§0.6). Lei inteira em 1 dispositivo é XSD-válido + checker-válido. |
| **Adicionar tipo novo** | Adiciona elemento → bump major → migra documentos existentes. Caro. | Adiciona entrada ao token map. XSD não muda. Documentos antigos seguem válidos. Barato. |
| **Linha do tempo de redações** | Akoma Ntoso: `<TLCEvent>` + `<modifies>` + URI dimensions (`work@expression`). Pesado. | `<versao em="...">` filha de `<dispositivo>`. `em` é chave natural; `vigente-ate` é inferido. |
| **Manutenção** | LexML brasileiro parado desde ~2010 (CGPID/Senado). Akoma Ntoso vivo mas focado em parlamento internacional. | Nós. ~235 linhas XSD + 14 invariantes — pequeno o suficiente pra evoluir rápido. |
| **Interop gov** | É o padrão oficial — Senado/Câmara esperam LexML pra entrega formal. | XSLT export sob demanda (`leizilla-to-lexml.xsl`); validado em CI contra XSD oficial. |

LexML ganha em **interop padronizada com governo** e **vocabulário canônico cross-projeto**. Perde em **tolerância a parse incompleto**, **velocidade de evolução**, e **simplicidade**.

Nossa escolha alinha com o resto da arquitetura: Wayback como caminho primário (captar o que conseguir), audit por embeddings (refinamento contínuo, não gating prévio), IA OCR como verdade base (texto sempre disponível mesmo sem estrutura). LexML seria a escolha certa se o objetivo fosse produzir documentos para tramitação — não é.

### 6.2 Perdas conhecidas no export

Documentadas no XSLT:
- `<fonte diverge="true">` → descartado (LexML não modela divergência multi-fonte).
- Atributos `<inicio tipo>` e `<revogacao tipo>` → mapeados em LexML quando equivalente existe, descartados caso contrário.
- Timeline `<versao>` colapsa para `<TextoArticulado>` da versão vigente em `vigente-em`; histórico mapeia para `<Alteracao>` LexML quando possível.
- Texto cru de parse parcial (lei inteira em 1 dispositivo) → vira `<TextoArticulado>` com `<Caput>` único carregando o corpo.

### 6.3 Suporte completo a Anexos (multi-document export)

LexML modela anexos como documentos **separados** linkados via URN — não como conteúdo inline da `<Norma>`. Nosso XSLT respeita isso:

- Documento principal: emite `<Anexos><ReferenciaAnexo AlvoURN="{lei.urn-lex}!anexo-N"/>...` dentro de `<Norma>`.
- Cada anexo: gera arquivo separado `{output-dir}/anexo-N.lexml.xml` via EXSLT `exsl:document`. Contém `<LexML><Anexo><DocumentoGenerico><PartePrincipal><p>{texto}</p></PartePrincipal></DocumentoGenerico></Anexo></LexML>` com URN derivada `{lei.urn-lex}!anexo-N`.

Invocação:
```bash
xsltproc --param output-dir "'/path/to/out'" \
  scripts/leizilla-to-lexml.xsl law.xml > /path/to/out/main.xml
# Produz: main.xml + anexo-1.lexml.xml + anexo-2.lexml.xml + ...
```

Param `output-dir` default `.` (cwd). Caller (CLI/ETL) deve isolar por lei.

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
9. ~~`quality` atributo só em `path="ocr-ruim"`~~ — **removida**. Qualidade de parse não vive no XML (§4.7); audit por embeddings + `confianca_parse_global` no sidecar cobrem. Número 9 fica reservado pra preservar chaves estáveis no checker/testes.
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
- ✅ **`<bloco-livre>` desaparece** (PR #8) — e a tentativa subsequente de modelar OCR ruim como `<dispositivo path="ocr-ruim" quality="...">` (PRs #8/#9 iniciais) também foi descartada (PR #9): qualidade de parse é processo, não conteúdo (§4.7).
- ✅ **Processo (parse method, confiança, divergências detalhadas)** vai 100% para `parsed_meta.json`; XML carrega só estrutura normativa.
- ✅ **Token map** é fonte única de verdade para tipo de dispositivo.
- ✅ **Auditoria por embeddings raw vs parseado** substitui flags manuais de "revisão pendente".

### 8.2 Resolvidas em M0.3 (este PR, fecha M0)

- ✅ **URN LEX dialect**: spec oficial CGPID 2008 ([Parte 2 — LexML URN v1.0](https://projeto.lexml.gov.br/documentacao/Parte-2-LexML-URN.pdf)) lida e adotada. Forma canônica documentada em §5.6 com exemplos para lei federal/estadual/municipal, CF, EC, e path-dispositivo. Regex XSD + checker + 6 fixtures + 4 helpers de teste atualizados para a forma correta. Substituídas formas erradas: `br;estado:rondonia;lei:` → `br;rondonia:estadual:lei:`, `br;federal;lei:` → `br:federal:lei:`, etc.

- ✅ **Política de re-scrape**: PDF re-publicado pela fonte (hash diferente do anterior) **NÃO** vira novo raw item automaticamente. Só sob **auditoria explícita** (humana ou via embeddings drift) — neste caso o novo raw vira `{chave}-r{N}` (sufixo `-r1`, `-r2`, ...) e o raw anterior permanece imutável. Implementação fica em M2 (crawler).

- ✅ **Robots.txt + rate limiting**: novo princípio load-bearing #10 em `IMPLEMENTATION.md`. Crawler **obedece robots.txt** (rejeição = não rascpear, não retry) e impõe **rate-limit baseline** de 1 request/segundo por host. Wayback bot (princípio 9) já atua como buffer — bates diretas só acontecem no fail-open. ADR formal (ADR-0008) fica em M1 com o package restructure.

### 8.3 Deferred (dependem de milestones futuros — não bloqueiam M0)

| Item | Bloqueio | Decisão deferida para |
|---|---|---|
| **Compressão Parquet** (SNAPPY vs ZSTD) | Precisa de Parquet writer e DuckDB-WASM real pra benchmark. | M4 (dataset items) |
| **Granularidade bundle ZIP** (semanal vs mensal) | Precisa de scrape real pra dimensionar arquivos. | M2 (crawler) |
| **Custo LLM realista** | Precisa de parse runs reais sobre casos diversos. | M2/M3 (após primeiras leis parseadas) |

### 8.4 Open questions (v0.2+)

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
| `<bloco-livre>` elemento separado | Sem elemento de OCR ruim no XML. Lei mal-parseada não tem parsed item; parcial usa texto cru no `<texto>` regular. | Qualidade de parse é processo (§4.7), não conteúdo. Audit por embeddings + `confianca_parse_global` cobrem detecção. |
| `<revogada>true/false</revogada>` | `<revogacao em="..." por="..." tipo="...">` com `<fonte>` filha | Revogação é evento estruturado |
| `vigente-de` / `vigente-ate` em toda versão | Herança implícita; `em` só onde difere; `vigente-ate` é inferido | Caso comum não declara nada |
| Flag manual de auditoria/revisão | Auditoria por embeddings (sistema externo) | LLM não sabe quando errou |

**Status do PR #7**: superseded. Fica como referência histórica do design v1.
