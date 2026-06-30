# Leizilla — Documento de Requisitos do Produto

**Status:** ativo — implementação em curso
**Versão:** 2.0-reconciliado
**Baseado em:** PRD V2 (franklinbaldo, 2026-06-30) × implementação M0–M14

> Este documento é o PRD canônico do Leizilla. Incorpora as ideias do PRD V2 e as
> reconcilia com as decisões de implementação já tomadas (M0–M14), explicitando onde
> a implementação diverge do PRD original e por quê essa divergência é mantida.
> Nas seções onde há divergência, um bloco `> Implementação` documenta a escolha ativa.

**Princípio central:** toda informação exibida pelo Leizilla deve ser rastreável até
uma evidência documental verificável.

---

## 1. Visão do produto

O Leizilla é uma infraestrutura aberta para capturar, preservar, estruturar, versionar
e pesquisar legislação brasileira publicada em fontes oficiais — federal, estadual e
municipal.

O produto não é um site. É um **dataset público endereçável** que por acaso tem um
frontend de referência, e esse frontend é descartável: qualquer pessoa baixa o dataset,
levanta o próprio DuckDB e constrói a própria interface. O artefato é o dado, não a
hospedagem. Some o GitHub Pages amanhã e o corpus continua íntegro, baixável e
verificável.

A unidade de valor não é "uma lei encontrada", mas um trecho normativo acompanhado de
identificação da norma, texto estruturado, fonte oficial, artefato original preservado,
localização verificável no documento, data de captura, versão do parser e grau de
confiança da estruturação.

---

## 2. Problema

A legislação brasileira permanece dispersa entre milhares de portais de qualidade
desigual. Os problemas centrais:

1. fontes oficiais instáveis, incompletas ou difíceis de pesquisar;
2. PDFs digitalizados sem camada textual confiável;
3. ausência de versões estruturadas por artigo, parágrafo, inciso e alínea;
4. dificuldade de verificar a origem de textos reproduzidos em repositórios secundários;
5. custo operacional alto de manter crawling, OCR, banco de dados e APIs tradicionais;
6. risco de confundir texto publicado, texto consolidado e texto juridicamente vigente —
   três coisas distintas que ferramentas ingênuas tratam como uma só.

---

## 3. Princípios de design

### 3.1. Evidência antes de inferência

Toda conclusão estruturada aponta para um artefato, trecho, URL, hash ou metadado de
origem. O sistema pode inferir, mas distingue sempre fato observado, dado extraído,
dado inferido, dado revisado e dado consolidado.

### 3.2. Artefatos imutáveis

Arquivos capturados não são alterados. O raw IA item é imutável após upload. Toda
transformação gera um novo artefato versionado, identificado por hash e vinculado ao
insumo que o originou.

### 3.3. Estado derivado, não escondido

O registro canônico é o conjunto de itens IA (raw + parsed + dataset). O DuckDB local
é uma projeção materializada para consulta — não o banco canônico do sistema.

### 3.4. Separação entre documento, estrutura e consolidação

O produto distingue três camadas:

- **Documento publicado** — arquivo ou página capturada da fonte oficial (raw IA item);
- **Edição estrutural** — o documento segmentado em dispositivos (Leizilla XML v0.1);
- **Consolidação normativa** — reconstrução temporal de alterações e vigência (S5, fora
  do MVP; parcialmente representada via `<versao em>` no XML atual).

### 3.5. Provedores substituíveis

Internet Archive, Wayback Machine, GitHub Pages, GitHub Actions e Claude são
implementações substituíveis, não identidades do domínio. O domínio não depende de
identificadores internos, nomes de arquivos ou peculiaridades de um provedor.

### 3.6. Sem servidor permanente

O produto opera sem API própria, banco relacional always-on ou worker residente. O
orçamento de custo é explícito: zero infraestrutura always-on + orçamento de LLM
controlado por `--limit` e `--error-threshold` em cada batch.

---

## 4. Escopo do MVP e não-objetivos

A V2 começa por Rondônia (RO) com fontes `casacivil` e `assembleia`, provando o
ciclo completo antes de expandir:

```text
fonte oficial
→ descoberta (manifest-driven)
→ captura (Wayback + IA upload)
→ preservação do artefato (raw IA item, content-hashed)
→ extração textual (IA OCR _djvu.txt ou HTML nativo)
→ estruturação (segmenter.py + Claude Haiku → Leizilla XML v0.1)
→ validação (XSD + consistency checker)
→ release versionado (Parquet no IA)
→ busca pública (DuckDB-WASM no browser)
→ auditoria da evidência (parsed_meta.json + provenance.json)
```

**Fora do MVP:** certificação oficial de autenticidade; interpretação jurídica;
declaração automática de vigência; consolidação temporal completa (S5); crawling
genérico de todos os municípios; OCR próprio em infraestrutura permanente; publicação
de estruturação sem rastreabilidade documental.

---

## 5. Modelo de domínio

O sistema trabalha com cinco camadas lógicas. A identidade jurídica da norma, a
identidade técnica do conteúdo e o identificador de provedor são coisas distintas, e
o modelo as mantém separadas.

### 5.1. Ato normativo (lei)

A identidade jurídica de uma norma. Keyed pelo `lei_id`, que codifica ente, tipo,
número e ano — separando assim a identidade jurídica do identificador de provedor.

```
lei_id                  # leizilla-{ente}-{tipo}-{numero:05d}-{ano} (chave fundamental)
ente                    # "ro", "federal", "ro-porto-velho"
tipo_lei                # "lei", "decreto", "lc", "constituicao"
numero_lei              # nullable em fallbacks
ano_lei
data_publicacao         # extraída da URN LEX
urn_lex_lei             # urn:lex:br;rondonia:estadual:lei:2003-06-15;1234
vigente_em              # data de referência da compilação
stage                   # S1|S2|S3|S4 — estágio máximo alcançado (ver §6)
```

> **Nota de design:** O PRD V2 original propunha um `act_id` interno separado do
> id-do-IA. Mantemos `lei_id` = IA identifier do parsed item porque: (1) o padrão
> `leizilla-{ente}-{tipo}-{numero:05d}-{ano}` já codifica identidade jurídica sem
> depender de coddoc ou URL de origem; (2) ADR-0011 já separou `raw_id lógico` do
> item real no IA — a separação de identidade já existe onde importa; (3) adicionar
> uma quarta camada de indireção (act_id → lei_id → ia_id) não traria ganho concreto
> para o MVP.
>
> O `lei_id` é o `act_id` do PRD V2 — apenas com naming mais explícito.

### 5.2. Fonte (recurso descoberto)

Uma observação de uma publicação oficial. Alimenta a fila de harvest.

```
url                     # PK — URL da fonte oficial
ente
fonte                   # "casacivil", "assembleia", "planalto"
tipo_documento
chave                   # "lei-05120", "lc-00042" — identidade candidata
status                  # discovered|pending|fetching|captured|duplicate|
                        # blocked_by_policy|not_document|
                        # failed_retryable|failed_terminal
identificacao_status    # candidato | confirmado | em_espera
wayback_snapshot
data_descoberta
```

> **Implementação ativa:** `discovered_resources` tem `status` simplificado
> (`pending|downloaded`). Os estados ricos e `identificacao_status` são evolução
> planejada — adicionar colunas sem breaking change.

### 5.3. Artefato

Bytes preservados e verificáveis. O SHA-256 é a identidade técnica do conteúdo.

```
raw_id                  # leizilla-raw-{ente}-{fonte}-{chave} (lógico, CLI + XML)
sha256                  # identidade técnica (no index.csv do range item)
mime_type               # application/pdf | text/html
capturado_em
storage_location        # item IA real: leizilla_{ente}_{fonte}_{tipo}_{range}
arquivo_interno         # {uuid5}.pdf ou {uuid5}.html (dentro do range item)
```

O `raw_id` lógico é resolvido para o `storage_location` real via `index.csv` do
range item (ADR-0010/11). Deduplicação por SHA-256. O identificador do IA é um
atributo de localização, não a identidade do artefato.

### 5.4. Parse

Uma estrutura produzida a partir de um artefato. Reside no parsed item IA como
`law.xml` + `parsed_meta.json`.

```
ia_id_parsed            # leizilla-{ente}-{tipo}-{numero:05d}-{ano}
ia_id_raw               # raw_id de origem
parse_method            # "{model}+{input_type}" ex: "claude-haiku-4-5+ocr"
schema_xml_version      # "0.1"
confianca_parse_global  # 0.0–1.0
validation_status       # "passed" | "failed"
review_status           # "auto" | "pending" | "reviewed" | "rejected"
parse_timestamp
parent_parse_id         # ia_id_parsed da versão anterior (para correções)
fontes_consultadas      # [raw_id, ...]
```

> **Implementação ativa:** `parsed_meta.json` tem a maioria dos campos. `parent_parse_id`
> e `review_status` ainda não estão implementados — adicionar ao sidecar JSON sem
> mudança de schema XML.

### 5.5. Release

Uma publicação consultável do dataset, reprodutível a partir de um manifesto.

```
dataset_id              # leizilla-dataset-{ente}-v{N}
ente
schema_version          # "0.1"
row_count
git_sha
generated_at
manifest_sha256
```

---

## 6. Arquitetura em estágios

O pipeline é uma escada onde cada degrau materializa um artefato publicável. O `stage`
de um recurso é o **estágio máximo que ele alcançou**:

```text
S1 arquivar → S2 identificar → S3 texto → S4 estruturar → S5 temporal
```

- **S1 — arquivado:** raw IA item existe. Artefato preservado, content-hashed,
  deduplicado. *Já é evidência estável.*
- **S2 — identificado:** chave `(tipo, número, ano)` extraída do contexto de
  descoberta. Entra no catálogo navegável. *Já é mais do que o portal de origem
  oferece.*
- **S3 — texto:** texto extraído via IA OCR (`_djvu.txt`) ou HTML nativo. Habilita
  busca textual e leitura sem PDF.
- **S4 — estruturado:** Leizilla XML v0.1 com dispositivos, timeline via `<versao>`,
  proveniência por `<fonte ia-id>`. Parsed item publicado no IA. Habilita navegação
  por artigo e proveniência por dispositivo.
- **S5 — temporal:** eventos de alteração resolvidos externamente como log imutável.
  *Fora do MVP.* O XML atual já carrega dados parciais via `<versao alterado-por>` e
  `<revogacao>` que alimentarão S5 quando implementado.

O frontend renderiza cada lei no estágio em que está, com aviso de fidelidade (§10.3),
e expõe a fronteira de cobertura como dado público — "1.243 arquivadas · 890 com
texto · 412 estruturadas". Expor o próprio gap é credibilidade, não vergonha.

As cadências de custo desacoplam-se: S1–S2 são gratuitas e rodam agressivo
(`discover-harvest.yml`, sábado); S4 consome token de LLM e roda incremental
(`parse-release.yml`, segunda, `--limit 50 --error-threshold 20`). A frente
gratuita nunca espera o passo caro.

> **Implementação ativa:** os estágios são atualmente implícitos via existência de
> itens IA. O campo `stage` explícito no modelo e o aviso de fidelidade no frontend
> são parte do M13 (frontend polish).

---

## 7. Pipeline (requisitos funcionais)

### 7.1. Descoberta

Lê manifestos declarativos em `manifests/{ente}.json` e popula `discovered_resources`:

```json
{
  "ente": "ro",
  "fontes": {
    "casacivil": {
      "tipo_ingestion": "pdf",
      "discovery": [{"strategy": "wayback-cdx", "prefix": "..."}],
      "probe": [
        {"templates": ["...L{num}.pdf"], "start": 1, "end": 6000},
        {"templates": ["...LC{num}.pdf"], "start": 1, "end": 1300}
      ]
    }
  }
}
```

Estratégias implementadas: `WaybackCdxDiscovery`, `SequentialDiscovery`,
`PlaywrightCrawlerDiscovery`. Cada candidato vai para o ledger com contexto de
descoberta, chave candidata e status.

Extração de `(tipo, número)` do contexto de descoberta (metadados / padrão de
URL / nome de arquivo) é a tarefa primária e resolve >90% dos casos — o recurso
identificado vai direto ao catálogo com `identificacao_status = "confirmado"`.
O resíduo (<10%) fica em `identificacao_status = "em_espera"` na área
`leizilla_{ente}_{fonte}_unidentified` e é promovido por reconciliação.

### 7.2. Captura e preservação

O Internet Archive é a *source of truth* pós-ingestão. Protocolo:

1. Verificar `robots.txt` — rejeição permanente, rate-limit 1 req/s por host (ADR-0008);
2. Reutilizar artefato já conhecido por hash ou URL normalizada (`--skip-existing`);
3. Disparar Wayback save (fire-and-forget — apenas para preservação);
4. Fetch do Wayback com fallback direto (fail-open);
5. Upload para range item IA com `index.csv` mapeando identidade → hash.

**Range items:** `leizilla_{ente}_{fonte}_{tipo}_{range}` (ex:
`leizilla_ro_casacivil_lei_5001-6000`). Cada item contém:
- `index.csv`: `(tipo, número, rendição, formato) → (uuid5, sha256, captured_at, source)`
- `{uuid5}.pdf` ou `{uuid5}.html`
- `{uuid5}_djvu.txt` (OCR gerado automaticamente pelo IA)
- `{uuid5}_meta.json`

Deduplicação por SHA-256. O `raw_id` lógico é resolvido via `index.csv`.

Estados de captura no ledger:
```
discovered · pending · fetching · captured · duplicate
blocked_by_policy · not_document · failed_retryable · failed_terminal
```

### 7.3. Extração de texto (S3)

Hierarquia de prioridade:

1. **Texto nativo do HTML** — `fetch_html(url)` para fontes como Planalto;
2. **OCR do Internet Archive** — `fetch_ocr(ia_id)` busca `{uuid5}_djvu.txt` do
   range item via `resolve_raw_url()`.

**Evolução planejada:** para PDFs digitalmente nativos (born-digital), extração local
via `pymupdf` como pré-passo — produz texto mais limpo com metadados de posição
(`page`, `bbox`, `confidence`) por trecho, habilitando `evidence_refs` granulares
futuros.

> **Princípio load-bearing #2 mantido:** OCR é responsabilidade do IA por padrão.
> `pymupdf` é otimização opcional para documentos born-digital, não substitui o
> IA OCR como baseline universal. O sistema nunca substitui texto nativo por OCR
> inferior.

O pipeline nunca usa OCR onde há texto nativo disponível. O roteamento é do sistema,
não de um gate opaco de terceiro.

### 7.4. Estruturação (S4)

A estruturação converte o texto extraído em Leizilla XML v0.1 via parse LLM
(`parser.py`): Claude Haiku recebe o texto (até 8.000 chars OCR ou 32.000 chars
HTML) e gera Leizilla XML v0.1 completo — `<dispositivo path>`, `<versao>`,
`<texto>`, `<fonte ia-id>`. Confiança mínima para publicação: 0.5.

O módulo `segmenter.py` (Regex Pattern B, micro-F1 exact=0.95, overlap=0.99
contra gold v0) existe como ferramenta de avaliação e verificação — acessível via
`leizilla dev check-segmenter` e `leizilla dev eval-segmenter`. Ele **não** é
chamado pelo pipeline de produção (`parse`/`parse-all`) neste momento. A integração
como pré-passo determinístico na produção é trabalho futuro (ver ADR-0012).

> **Nota de design:** O PRD V2 original propunha "LLM marca (insere fronteiras sobre
> texto verbatim), Python estrutura (monta a árvore)". A implementação atual faz o
> LLM gerar o XML completo, sem pré-passo determinístico em produção. O
> `segmenter.py` existe como fundação para auditoria e para eventual integração
> futura caso documentos maiores ou mais complexos mostrem falhas estruturais do LLM.
> Não há razão para integrar antes de ter evidência de falha.

O LLM **não pode**: inventar texto; suprimir texto sem registrar omissão; declarar
revogação sem base no documento; preencher lacunas com conhecimento externo.

**Regras de publicação automática:**
- XML valida contra `leizilla-v0.1.xsd` via `xmllint` (`_xsd_gate`);
- `confianca_parse_global` ≥ 0.5;
- `tipo`, `numero`, `ano` extraídos e parseáveis;
- XML bem-formado.

Parse abaixo do limiar **não é publicado** — a lei fica como raw IA item. Parse
parcial (alguns dispositivos OK, outros com texto cru) é publicado como está; o
texto cru no `<texto>` do dispositivo é visível no render e detectável via audit
de embeddings.

**Correção de parse:**
Atualmente, re-parse sobrescreve `law.xml` no mesmo IA item (`ia_id_parsed`). O
campo `parent_parse_id` em `parsed_meta.json` é o mecanismo planejado para
rastrear a cadeia de correções, mas a criação de itens IA imutáveis por re-parse
ainda não está implementada em `upload_parsed()`. O campo `review_status`
(`"auto"` | `"pending"` | `"reviewed"` | `"rejected"`) rastreia a origem da
correção no sidecar.

### 7.5. Consolidação temporal (S5 — fora do MVP)

A consolidação temporal é um produto separado da estruturação.

O XML atual já carrega os dados necessários para alimentar S5:
- `<versao em="..." alterado-por="...">` — cada redação com data e lei alteradora;
- `<revogacao em="..." por="..." tipo="...">` — eventos de revogação estruturados;
- ETL (`etl.py`) já infere `ate` (vigente-até) deterministicamente.

Quando S5 for implementado, será *event-sourced*: eventos imutáveis
`(lei_origem, alvo, tipo, data_efeito, fonte, confianca)` e vigência derivada por
função pura sobre o log. A tabela de versões (`ate` no Parquet) será uma
materialized view, não a fonte de verdade.

A plataforma só exibe "vigente em determinada data" quando há fonte oficial
consolidada, OU cadeia de alterações suficientemente evidenciada, OU revisão
humana com justificativa registrada — nunca por inferência implícita de linguagem
natural.

---

## 8. Formato canônico do documento

O artefato canônico de parse é **Leizilla XML v0.1**, definido em
`docs/schemas/leizilla-v0.1.xsd` e documentado em `docs/SCHEMA.md`.

A representação primária é o XML. JSON, Parquet e CSV são projeções determinísticas.

### 8.1. Estrutura

```xml
<lei xmlns="https://leizilla.org/lei/0.1" schema-version="0.1"
     urn-lex="urn:lex:br;rondonia:estadual:lei:2003-06-15;1234"
     vigente-em="2026-05-20">

  <!-- Revogação total da lei (opcional, antes dos dispositivos) -->
  <revogacao em="2025-01-01" tipo="expressa"
             por="urn:lex:br;rondonia:estadual:lei:2024-12-01;9999">
    <fonte ia-id="leizilla-raw-ro-casacivil-lei-09999"/>
  </revogacao>

  <!-- Dispositivos — recursivos, tipados pelo path via token map -->
  <dispositivo path="ementa">
    <versao>
      <texto>Institui o Programa Estadual de Habitação.</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-lei-01234"/>
    </versao>
  </dispositivo>

  <dispositivo path="art-1">
    <versao>
      <texto>Fica instituído o Programa Estadual de Habitação.</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-lei-01234"/>
    </versao>
    <!-- Sub-dispositivo com múltiplas versões (alteração) -->
    <dispositivo path="art-1-par-1">
      <versao>
        <texto>O Programa terá vigência por 10 anos.</texto>
        <fonte ia-id="leizilla-raw-ro-casacivil-lei-01234"/>
      </versao>
      <versao em="2020-01-01" alterado-por="urn:lex:...;5678">
        <texto>O Programa terá vigência por 20 anos.</texto>
        <fonte ia-id="leizilla-raw-ro-casacivil-lei-05678"/>
      </versao>
    </dispositivo>
  </dispositivo>

</lei>
```

**6 elementos** (`lei`, `dispositivo`, `versao`, `inicio`, `texto`, `fonte`,
`revogacao`). Schema completo e invariantes em `docs/SCHEMA.md` §4.

### 8.2. Endereçamento de dispositivos (locator)

O `path` do dispositivo serve como locator para deep-link e navegação:

| Path | Tipo (token map) | Rótulo derivado |
|---|---|---|
| `ementa` | ementa | "Ementa" |
| `art-5` | artigo | "Art. 5º" |
| `art-5-par-unico` | paragrafo | "Parágrafo único" |
| `art-5-par-2` | paragrafo | "§ 2º" |
| `art-5-par-2-inc-3` | inciso | "III" |
| `art-5-par-2-inc-3-ali-a` | alinea | "a)" |
| `tit-2-cap-1-sec-3` | secao | "Seção 3" |

O tipo é derivado do `path` via **token map** (`docs/SCHEMA.md` §4.2) — sem
atributo `tipo` duplicado no XML. A URN completa do dispositivo é
`{urn_lex_lei}!{path}` (composta em render-time, não armazenada).

A `dispositivo_ordem` no Parquet serve como base para ordenação hierárquica
(`sort_key` implícito).

> **Nota de design:** O PRD V2 original propunha `<disp kind="artigo" n="5">` com
> mixed content, `locator` e `sort_key` explícitos. A implementação usa
> `<dispositivo path="art-5">` com `<versao>` e `<texto>` separados. O design atual
> é **mais expressivo** para o caso de uso central: a timeline de redações embutida
> no XML (`<versao em>`) não tem equivalente no design do PRD V2. O `path` cobre o
> `locator`; `dispositivo_ordem` cobre o `sort_key`. Não há razão para migrar.

### 8.3. Proveniência por dispositivo

`<fonte ia-id="...">` em cada `<versao>` materializa a cadeia de rastreabilidade:

```
dispositivo (path)
→ versao (em)
→ fonte (ia-id = raw_id lógico)
→ index.csv do range item
→ sha256 do arquivo
→ URL original + wayback_snapshot
```

Esta cadeia está sempre presente no XML e no Parquet (coluna `fontes` JSON).

### 8.4. Granularidade incremental

O schema **permite explicitamente** que uma lei inteira viva num único `<dispositivo>`
com o texto integral. Isso é XSD-válido, checker-válido, e é o estado S4 mínimo:

```xml
<lei urn-lex="..." vigente-em="..." schema-version="0.1">
  <dispositivo path="art-1">
    <versao>
      <texto>[texto integral da lei, sem separar artigos]</texto>
      <fonte ia-id="leizilla-raw-ro-casacivil-lei-00042"/>
    </versao>
  </dispositivo>
</lei>
```

Passes futuros aprofundam a estrutura dentro do que já existe. A anotação é
monotônica: um passe só adiciona subdivisões dentro de dispositivos já presentes,
nunca move texto entre eles.

### 8.5. Correções versionadas

Correções de parse são rastreadas por `parent_parse_id` no `parsed_meta.json`, não
por elemento no XML. O texto corrigido substitui o anterior no `law.xml`; o parsed
item anterior permanece imutável no IA com seu `ia_id_parsed` original.

> **Nota de design:** O PRD V2 original propunha `<corr from="..." reason="...">` no
> XML. Mantemos a abordagem de versionamento via IA items imutáveis:
> `parent_parse_id` rastreia a cadeia de correções sem adicionar elemento ao XML.
> Mais simples, igualmente auditável.

---

## 9. Releases

Cada release é reprodutível a partir de um manifesto imutável.

**Estrutura atual (MVP — Parquet único):**

```
leizilla-dataset-{ente}-v{N}/
  versoes.parquet      # tabela única, grain lei×dispositivo×versão, SNAPPY
  dataset_meta.json    # leizilla_meta_version, schema_version, ente, version,
                       # table, generated_at, row_count, file_size_bytes,
                       # hash_parquet, git_sha (opcional)
```

O arquivo Parquet é sempre nomeado `versoes.parquet` dentro do IA item
`leizilla-dataset-{ente}-v{N}` — o identificador do item carrega ente e versão.
O `catalog.parquet` não existe no MVP; navegação e filtros são resolvidos por
`SELECT DISTINCT` sobre `versoes.parquet` via DuckDB-WASM no browser.

**Evolução planejada (quando gatilhos forem atingidos — `docs/SCHEMA.md` §3.4):**

```
catalog.parquet                   # pequeno, carrega primeiro — lei_id, tipo, stage
acts.parquet                      # metadados de leis (sem texto)
devices.parquet                   # árvore de dispositivos (sem texto)
version_shards/{ente}/{ano}/      # texto, particionado por ente×ano×faixa
search_index/                     # índice invertido estático (term → postings)
provenance/                       # parsed_meta.json e provenance.json por lei
checksums.txt                     # SHA-256 de cada artefato no release
```

Gatilhos de split: `file > 100 MB` | `rows > 2M` | `search > 1s P95` (DuckDB-WASM).
Um gatilho → RFC. Dois gatilhos → split obrigatório antes do próximo release.

Uma release é reconstruível a partir do manifesto, dos hashes de artefato, do schema
e das versões de parser, prompt e modelo, mais a política de seleção de parse.

---

## 10. Serving e busca

### 10.1. Dois motores de busca

**Baseline (M5.2 — implementado):**
DuckDB-WASM no browser carrega o Parquet via `read_parquet(PARQUET_URL)`.
- Busca full-text: `ILIKE '%termo%'` sobre `texto_normalizado`
- Filtros: `ente`, `tipo_lei`, `ano` via SQL parameterizado (sem injeção)
- Paginação: `LIMIT/OFFSET`, `PAGE_SIZE = 20`
- TanStack Query: cache, retry, debounce 400ms

**Evolução planejada (M5.3):**
Índice invertido estático particionado (`term → postings`) gerado no release.
O browser faz range-request apenas das postings dos termos da query, obtém doc ids
e só então carrega os shards dos resultados. DuckDB-WASM continua para filtros
estruturados sobre o working set já selecionado.

M5.3 é desbloqueado quando o benchmark in-browser medir > 1s P95 com `ILIKE`.

### 10.2. Origem de serving

**Baseline:** Parquet lido diretamente do IA (`archive.org/download/...`).

**Evolução planejada:** espelhar em CDN CORS-friendly (jsDelivr via GitHub Releases,
ou R2/B2 free tier) para latência menor. IA permanece como origin de arquivo e
mirror permanente.

Texto pesado é separado do metadado no split de release: `catalog.parquet` e índice
enxuto carregam rápido; `version_shards/` são fetchados lazy, por range, por ente×ano.

### 10.3. Aviso de fidelidade por estágio

O frontend exibe cada lei no estágio em que está, com aviso explícito:

- **S1/S2:** metadado + link para PDF original no IA. "Texto ainda não processado."
- **S3:** texto OCR renderizado em HTML, via fetch do range item. "Texto automático —
  pode conter ruído de OCR, ainda não estruturado nem revisado."
- **S4:** dispositivos navegáveis, busca por artigo, evidência por nó (link para
  `parsed_meta.json` e raw IA item).

> **Implementação ativa:** o frontend atual (M5.2) não distingue estágios — exibe
> apenas o que está no Parquet (leis com S4 concluído). Aviso de estágio e link para
> raw PDF são M13.

### 10.4. Exposição de cobertura

O frontend exibe a fronteira de cobertura como dado público:

```
1.243 arquivadas · 890 com texto · 412 estruturadas
```

Expor o próprio gap é credibilidade, não vergonha. Os números vêm de
`leizilla stats --ia` (conta raw/parsed/dataset no IA).

---

## 11. Interface de busca

A interface permite busca por palavras e frases e filtros por ente, tipo normativo,
número, ano, situação de revisão e tipo de edição.

Cada resultado apresenta:
- Identificação da norma (tipo, número, ano, ente);
- Endereço do dispositivo (locator = `path`, ex: `art.5.par.2`);
- Trecho destacado (`texto_normalizado`);
- Fonte original (link para raw IA item);
- Link de auditoria (link para `parsed_meta.json`);
- Data de captura;
- Aviso de estágio e incerteza quando aplicável.

A navegação de um dispositivo preserva o contexto hierárquico via `path`:
`Lei → Título → Capítulo → Seção → Artigo → Parágrafo → Inciso`.

Deep-link para dispositivo: `/{lei_id}#{path}` (URL hash baseado no `path` do
dispositivo).

---

## 12. Requisitos não-funcionais

### 12.1. Auditoria

Cadeia mínima de proveniência para todo dado público:

```
resultado exibido
→ dispositivo (path + versao_id no Parquet)
→ fonte (ia-id no XML → raw_id lógico)
→ index.csv do range item (sha256 + arquivo_interno)
→ wayback_snapshot (testemunha externa)
→ URL original da fonte oficial
```

### 12.2. Reprodutibilidade

Uma release reconstrói-se a partir de:
- `hash_parquet` em `dataset_meta.json` (SHA-256 do `versoes.parquet`)
- `index.csv` de cada range item (sha256 + arquivo_interno por lei)
- `schema_version` do XML em cada `parsed_meta.json`
- `parse_method` no `parsed_meta.json`
- `git_sha` do código que gerou o dataset

> **Evolução planejada:** um `manifest-{ente}.csv` (`lei_id → ia_id_parsed`) tornará
> a reprodutibilidade auto-suficiente sem depender de query no IA, quando adicionado
> a `upload_dataset()`. No MVP, a lista de parsed items é reconstruída via API IA.

Empacotamento: `src-layout`, `uv` com lock determinístico, Ruff, mypy, pre-commit.
Testes: 100% das chamadas externas mockadas (`uv run leizilla dev check`).

### 12.3. Custo

Zero infraestrutura always-on. Controles ativos:
- Budget LLM via `--limit 50 --error-threshold 20` em `parse-release.yml`
- Cache por hash: `--skip-existing` em `scrape` e `parse-all`
- Reprocessamento apenas quando parser, prompt ou schema mudam
- GitHub Step Summary reporta custo por batch

### 12.4. Performance

Metas (a serem validadas com M5.3 — benchmark in-browser real):
- Primeira renderização (sem engine analítica): < 2s
- Carregamento do catálogo: < 3s em conexão residencial
- Filtro sobre shard já carregado: P95 < 1s
- Busca textual no índice estático: P95 < 2s
- Nenhuma operação exige carregar todo o corpus por padrão

### 12.5. Resiliência

- Range items no IA: imutáveis, incluídos em torrents automáticos do IA
- `--skip-existing`: idempotência em todos os passos do pipeline
- Fail-open em captura: erro Wayback → fallback direto; erro IA → skip sem abort
- Dataset item versionado com `manifest_sha256`

---

## 13. Decisões arquiteturais

Resumo das decisões estruturais ativas (racional completo em `docs/adr/`):

1. **IA como camada de normalização** (ADR-0001/0011): source of truth pós-ingestão;
   range buckets content-addressed com `index.csv`; `raw_id` lógico ≠ item IA real.

2. **Wayback como caminho primário de fetch** (ADR-0004): robots → save no Wayback
   → fetch do snapshot Wayback; fallback direto só se Wayback falhar; portal
   tocado no máximo uma vez por URL.

3. **robots.txt + rate-limiting** (ADR-0008): rejeição permanente na descoberta;
   rate-limit baseline 1 req/s por host; Wayback como buffer.

4. **Leizilla XML v0.1 como formato canônico** (ADR-0006/0007): `<dispositivo path>`
   recursivo, token map, `<versao>` para timeline, LexML export sob demanda via XSLT.

5. **lei_id = IA identifier do parsed item** como chave fundamental: codifica ente,
   tipo, número, ano; separado do raw_id via ADR-0011; sem act_id extra.

6. **Parquet tabela única `versoes`** (SCHEMA.md §3): grain lei×dispositivo×versão,
   zero JOIN em DuckDB-WASM; split quando gatilhos SCHEMA.md §3.4 forem atingidos.

7. **DuckDB-WASM + ILIKE como baseline de busca** (M5.2): suficiente para ~300k
   rows; índice invertido estático quando P95 > 1s (M5.3).

8. **LGPD/ética** (ADR-0009): leis são públicas; sem despublicação.

9. **segmenter.py regex como baseline determinístico** (M14.4, ADR-0012): micro-F1
   exact=0.95 como fundação verificável; LLM parse sobre o resultado do segmenter;
   fine-tune OPF adiado — regex + Claude cobrem o regime atual.

---

## 14. Fases de entrega

Cada fase entrega um Leizilla estritamente mais capaz, em produção, desde a primeira.

### Fase 0 — Fundamentos ✅ (M0–M1)

Schema XML v0.1, XSD, 6 fixtures, consistency checker com 15 invariantes,
URN LEX (CGPID 2008), entes.py, ADRs 0004–0009.

**Saída:** um documento de teste pode ser capturado, identificado, armazenado
localmente, estruturado e reproduzido sem rede.

### Fase 1 — Vertical slice ✅ (M2–M3)

Conectores `casacivil` + `assembleia` (RO) + `planalto` (federal HTML). Scraping via
Wayback + fail-open. OCR fetch do IA. LLM parse → XSD gate → upload IA.
`--skip-existing` para idempotência.

**Saída:** ~100 atos atravessam o pipeline sem intervenção manual na maioria dos casos.

### Fase 2 — Release pública auditável ✅ (M4–M10)

ETL XML→Parquet (`versoes` tabela única). `release-dataset` publica
`versoes.parquet` + `dataset_meta.json` no IA. `parsed_meta.json` por parsed item.
Manifest-driven discovery. Workflows automatizados (`discover-harvest.yml` sábado,
`parse-release.yml` segunda). Rotina Claude Code (M7.1). Stats via IA.
Observabilidade (`--error-threshold`, GitHub Step Summary).

**Saída:** um terceiro reproduz uma consulta e alcança o documento-fonte correspondente.

### Fase 3 — Busca e frontend ✅ parcial (M5–M5.2, M11–M12)

Astro+Svelte+DuckDB-WASM. Busca ILIKE + filtros ente/tipo/ano + paginação.
TanStack Query (cache, retry). CI lint+test (ruff, mypy, pytest).
DiscoveryStrategy base class. Otimização scrape/parse via buscas em lote.

**Saída:** o usuário encontra um dispositivo e sua evidência sem depender de API própria.

### Fase 3.1 — Frontend polish 🟡 (M13)

- Aviso de fidelidade por estágio (S2/S3/S4) em cada resultado
- Deep-link para dispositivo via `#{path}`
- Painel de cobertura ("N arquivadas · N estruturadas")
- Navegação hierárquica (breadcrumb Lei → Artigo → Parágrafo → Inciso)
- Link para raw PDF e `parsed_meta.json`
- Campo `stage` explícito em `discovered_resources` e no Parquet

**Saída:** o usuário vê onde cada norma está na esteira e pode auditar a evidência
em dois cliques.

### Fase 3.2 — Serving evolution ⚪ (M5.3 + CDN)

- CDN CORS-friendly para Parquet (jsDelivr ou R2/B2)
- Índice invertido estático (quando benchmark WASM > 1s P95)
- Benchmark in-browser real (aguarda dataset publicado)

**Saída:** busca ampla sem carregar o corpus por padrão; catálogo e texto pesado
carregados separadamente.

### Fase 4 — Consolidação experimental ⚪

Representação de eventos modificativos como log imutável. Vínculo entre ato
alterador e dispositivo alterado. Status temporal com evidência. Comparação entre
versões. Revisão humana com `review_status`.

**Saída:** um subconjunto explicitamente delimitado de atos tem linha do tempo
juridicamente auditável, alimentada pelo `<versao alterado-por>` do XML atual.

---

## 15. Métricas de sucesso

**Cobertura:**
- Atos descobertos (raw items no IA, por fonte/ente)
- Artefatos capturados (raw items com arquivo presente)
- Artefatos com texto extraível (OCR `_djvu.txt` ou HTML presente)
- Documentos estruturados (parsed items no IA)
- Documentos com evidência por dispositivo (parsed items com `<fonte ia-id>` por versão)

**Qualidade:**
- Taxa de validação XSD (`validation_status = "passed"` em `parsed_meta.json`)
- Distribuição de `confianca_parse_global` (meta: mediana ≥ 0.8)
- Taxa de erro por batch (`--error-threshold 20` em `parse-release.yml`)
- Taxa de links de auditoria funcionais (raw items acessíveis no IA)
- Taxa de duplicação por hash (detectada pelo `index.csv`)

---

## 16. Critério supremo de qualidade

O Leizilla é confiável quando qualquer pessoa segue esta cadeia sem depender de
confiança pessoal no projeto:

```
resultado exibido no frontend
→ dispositivo estruturado (path + fontes no Parquet)
→ parsed item IA (law.xml + parsed_meta.json)
→ raw item IA (range bucket → index.csv → sha256)
→ wayback_snapshot (testemunha externa)
→ fonte oficial identificada
```

O produto não pede que o usuário confie no Leizilla. Ele permite que o usuário
verifique.
