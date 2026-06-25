# RFC-0001: Pipeline e Convenções do Leizilla

**Status**: Vigente  
**Data**: 2026-06-25  
**Autores**: Franklin Silveira Baldo

---

## 1. Sumário

Este documento descreve as regras operacionais vigentes do Leizilla: etapas do pipeline, convenções de nomeação de itens no Internet Archive, estrutura de arquivos, estratégias de descoberta, e contrato do módulo de parse via LLM. Serve como referência para quem implementar novas fontes, adaptar o scraper, ou integrar novos provedores de LLM.

---

## 2. Pipeline

O pipeline tem seis etapas sequenciais. Cada etapa tem uma entrada e uma saída bem definidas.

```
discover → scrape → [aguardar OCR do IA] → parse → consolidate → release-dataset
```

| Etapa | Comando | Entrada | Saída |
|---|---|---|---|
| **discover** | `leizilla discover` | manifest `{ente}.json` | tabela `discovered_resources` no DuckDB |
| **scrape** | `leizilla scrape` | URL da fonte + Wayback | PDF no range bucket do IA + registro no DuckDB |
| **parse** | `leizilla parse` / `parse-all` | `_djvu.txt` do IA (OCR) | Leizilla XML + `parsed_meta.json` no IA |
| **consolidate** | `leizilla consolidate` | itens parsed no IA | tabela `leis` no DuckDB |
| **release-dataset** | `leizilla release-dataset` | tabela `leis` | Parquet no IA (`leizilla-dataset-{ente}-v{N}`) |

O passo de OCR é assíncrono e gerenciado pelo Internet Archive (horas). O pipeline não tenta controlar esse tempo.

---

## 3. Internet Archive como Pilar Central

O IA cumpre quatro papéis simultâneos:

1. **Armazenamento permanente** dos PDFs brutos e dos XMLs parseados
2. **OCR gratuito** — gera `_djvu.txt` automaticamente após o upload de PDF
3. **CDN global** — `archive.org/download/...` é o endpoint de leitura
4. **Torrents** — gerados automaticamente para todos os itens

Nenhum outro storage é usado na produção. O DuckDB local é staging apenas.

---

## 4. Convenções de Nomeação no IA

### 4.1 Identificadores lógicos vs. físicos

O **identificador lógico** (`ia_id`) é o nome pelo qual o código referencia um item. Ele nunca é o upload target — é resolvido pelo `ia_utils.resolve_ia_id_to_url` para a URL física real.

| Tipo | Padrão lógico | Exemplo |
|---|---|---|
| Raw | `leizilla-raw-{ente}-{fonte}-{chave}` | `leizilla-raw-ro-casacivil-lei-05120` |
| Parsed | `leizilla-{ente}-{tipo}-{numero:05d}-{ano}` | `leizilla-ro-lei-05120-1993` |
| Dataset | `leizilla-dataset-{ente}-v{version}` | `leizilla-dataset-ro-v1` |

### 4.2 Range buckets (upload físico)

PDFs brutos são agrupados em **range buckets** de 1000 itens. O upload físico sempre vai para o bucket, nunca para um item individual.

**Fórmula do bucket:**
```
leizilla_{ente}_{fonte}_{tipo}_{start:04d}-{end:04d}
```

Para tipo `coddoc` (assembleia), o tipo é omitido:
```
leizilla_{ente}_{fonte}_{start:04d}-{end:04d}
```

**Exemplos:**
- Leis 1–1000: `leizilla_ro_casacivil_lei_0001-1000`
- Leis 5001–6000: `leizilla_ro_casacivil_lei_5001-6000`
- Decretos 1–1000: `leizilla_ro_casacivil_decreto_0001-1000`
- Assembleia 1–1000: `leizilla_ro_assembleia_0001-1000`

**Limites do range:**
```python
start = ((num - 1) // 1000) * 1000 + 1
end   = start + 999
```

Limites superiores acima de 9999 usam 5 dígitos — comportamento intencional.

### 4.3 Convenção de nomes de arquivo dentro do bucket

Cada lei dentro do bucket ganha um nome determinístico com **hash de 8 caracteres**:

```
{num:06d}_{hash_8}.pdf
{num:06d}_{hash_8}_meta.json
```

O hash é gerado por:
```python
sha256_hex = hashlib.sha256(pdf_bytes).hexdigest()
hash_8 = str(uuid.uuid5(uuid.NAMESPACE_DNS, sha256_hex))[:8]
```

O nome sem hash (`{num:06d}.pdf`) é **reservado** para futuros arquivos canônicos parseados.

**Manifesto incremental**: cada bucket mantém `manifest.csv` com colunas `filename,url`. O upload é idempotente — arquivos existentes não são re-enviados (flag `--checksum` do `ia` CLI).

### 4.4 Delimitadores

- `_` (underscore): separa **seções** do identificador (ente, fonte, tipo, range)
- `-` (hífen): uso **interno** dentro de seções (ex: `ro-porto-velho`, `decreto-lei`)
- **Regra**: `{fonte}` nunca contém hífen — quebraria o parser de identificadores

---

## 5. Resolução de URL

O `resolve_ia_id_to_url(ia_id, suffix, hash_8)` converte identificador lógico em URL de download:

1. Extrai `ente` por correspondência mais longa no catálogo `entes.py`
2. Extrai `fonte` e `chave` do restante
3. Calcula `(tipo, num)` via `parse_chave_numeric(chave)`
4. Monta `range_ia_id` e `filename` com o hash

**Lookup do hash** (em ordem de prioridade):
1. Parâmetro explícito `hash_8`
2. Campo `metadados.hash_8` no DuckDB local
3. Download de `manifest.csv` do bucket no IA

Itens não-numéricos (fallback): `leizilla_{ente}_{fonte}_fallback/{chave}_{hash_8}{suffix}`

---

## 6. Chaves de Documento (`chave`)

A `chave` identifica unicamente um documento dentro de uma fonte. Formato:

```
{tipo}-{numero:05d}
```

**Mapeamento de prefixo de arquivo → tipo + chave:**

| Prefixo arquivo | `tipo_documento` | `chave` |
|---|---|---|
| `L{N}.pdf` | `lei` | `lei-{N:05d}` |
| `LC{N}.pdf` | `lc` | `lc-{N:05d}` |
| `D{N}.pdf` | `decreto` | `decreto-{N:05d}` |
| `DEC{N}.pdf` | `decreto` | `decreto-{N:05d}` |
| `DL{N}.pdf` | `decreto-lei` | `decreto-lei-{N:05d}` |
| `EC{N}.pdf` | `ec` | `ec-{N:05d}` |
| `RES{N}.pdf` | `resolucao` | `resolucao-{N:05d}` |
| `PORT{N}.pdf` | `portaria` | `portaria-{N:05d}` |
| `coddoc-{N}` | `lei` | `coddoc-{N:05d}` |

Prefixos são casados do **mais longo para o mais curto** para evitar ambiguidade (`DEC` antes de `D`).

---

## 7. Descoberta

Cada fonte tem uma lista de estratégias de descoberta no manifest `{ente}.json`.

### 7.1 Estratégias disponíveis

| Estratégia | Classe | Comportamento |
|---|---|---|
| `wayback-cdx` | `WaybackCdxDiscovery` | Consulta CDX API do Wayback para um prefixo de URL; filtra PDFs com status 200 |
| `sequential` | `SequentialDiscovery` | Gera URLs `L1.pdf`, `L2.pdf`, … até o limite; opcionalmente valida com HEAD |
| `playwright-crawler` | `PlaywrightCrawlerDiscovery` | Crawlea portal JS com Playwright |

### 7.2 `head_check`

Estratégias `sequential` podem ter `head_check: true` ou `false`:

- **`false`**: URLs são adicionadas sem verificar se existem (mais rápido; indicado para casacivil lei/lc onde o servidor retorna HTML para inexistentes)
- **`true`**: HEAD request antes de adicionar; aceita HTTP 200 ou 302; rate limit de 0.5s/req

Com `--no-head-check`, estratégias com `head_check: true` são puladas inteiramente.

### 7.3 Verificação cruzada com IA

Durante a descoberta, cada recurso é verificado contra o `manifest.csv` do range bucket no IA. Se já presente, o status é definido como `"downloaded"` antes de inserir no DuckDB.

---

## 8. Scrape

O comando `scrape` é o caminho primário para ingestão de PDFs. Diferente do `harvest` (que usa a tabela `discovered_resources`), o `scrape` opera via CDX:

1. Consulta CDX API para URLs arquivadas na faixa de `coddoc`
2. Para cada snapshot: verifica robots.txt, tenta fetch do Wayback, fallback direto
3. Upload para range bucket com hash
4. Rate limit por host: 1 req/s (só no fallback direto)

**Comportamento com múltiplos snapshots CDX da mesma lei**: todos são processados. A deduplicação ocorre entre runs via `--skip-existing` (consulta IA), não dentro de um run.

---

## 9. Parse (LLM)

### 9.1 Entrada

O parser lê o OCR gerado pelo IA (`_djvu.txt`). O IA processa OCR de forma assíncrona após o upload — pode levar horas. O pipeline não controla esse tempo.

Para fontes HTML (Planalto): `--input-type html` usa o arquivo `.html` armazenado no range bucket.

### 9.2 Modelo LLM

O Leizilla usa **LiteLLM** para abstrair o provider de LLM. O modelo padrão é:

```
gemini/gemini-2.5-flash
```

Configurável via env `LITELLM_MODEL` sem mudança de código. Providers suportados:

| Env var | Provider |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic (Claude) |
| `GEMINI_API_KEY` | Google Gemini (via AI Studio) |
| `OPENROUTER_API_KEY` | OpenRouter (qualquer modelo) |

Chaves são carregadas de `../workspace/.env` (base) e `leizilla/.env` (override). LiteLLM lê as env vars automaticamente — não é passado `api_key` explícito na chamada.

Ao menos uma das três chaves deve estar configurada; caso contrário, `parse_law` levanta `RuntimeError`.

### 9.3 Saída

O LLM retorna JSON com:

```json
{
  "xml": "<lei xmlns=...>...</lei>",
  "confidence": 0.0–1.0,
  "tipo": "lei",
  "numero": "500",
  "ano": 1993,
  "urn_lex": "urn:lex:br;rondonia:estadual:lei:1993-06-15;500"
}
```

Parse é rejeitado se `confidence < 0.5` ou o XML não é bem-formado.

O identificador do item parsed é: `leizilla-{ente}-{tipo}-{numero:05d}-{ano}`

### 9.4 `parsed_meta.json`

Cada item parsed contém metadados de rastreabilidade:

```json
{
  "leizilla_meta_version": "0.1",
  "ia_id_raw": "leizilla-raw-ro-casacivil-lei-00500",
  "ia_id_parsed": "leizilla-ro-lei-00500-1993",
  "ente": "ro",
  "tipo": "lei",
  "parse_method": "gemini/gemini-2.5-flash+ocr",
  "confianca_parse_global": 0.98,
  "parse_timestamp": "2026-06-25T17:30:00+00:00",
  "tem_divergencia": false
}
```

---

## 10. DuckDB Local

O DuckDB em `data/leizilla.duckdb` é staging local — nunca é o source of truth em produção.

**Tabelas:**

| Tabela | Propósito |
|---|---|
| `discovered_resources` | URLs descobertas e seu status (`pending`, `downloaded`, `failed`, `not-pdf`, `robots-blocked`) |
| `leis` | Leis parseadas com texto completo e metadados |

**`discovered_resources` — campos relevantes:**
- `url` (PK), `ente`, `fonte`, `tipo_documento`, `chave`, `status`, `wayback_snapshot`, `data_descoberta`, `ultima_tentativa`

O DuckDB tem limitação de **single-writer** no Windows. Processos paralelos causam lock error. Matar processos pendentes antes de iniciar novos.

---

## 11. Metadados no IA (raw upload)

Cada upload para o range bucket define os seguintes campos no IA:

| Campo | Valor |
|---|---|
| `title` | `Leizilla Raw {ENTE} {FONTE} {TIPO} {start:04d}-{end:04d}` |
| `mediatype` | `texts` |
| `subject` | `leis;leizilla;{ente};{fonte}` |
| `creator` | `leizilla-crawler` |
| `language` | `pt` |
| `coverage` | `"{Estado}, Brazil"` ou `"Brazil"` |

O campo `description` inclui ente, fonte, chave e identificador lógico.

---

## 12. Invariantes

1. `{fonte}` nunca contém hífen
2. `{ente}` é sempre kebab-case do catálogo `entes.py`
3. PDFs brutos nunca vão para itens individuais — sempre range buckets
4. Arquivos sem hash (`000500.pdf`) são reservados para artefatos canônicos futuros
5. Rejeição por robots.txt é permanente para aquela URL — sem retry
6. Parse com `confidence < 0.5` é descartado silenciosamente (não conta como falha de rede)
7. O manifesto `manifest.csv` é a fonte de verdade sobre o que está no IA dentro de um bucket
8. `_djvu.txt` OCR só existe após processamento assíncrono do IA — o pipeline não policia esse tempo
9. O DuckDB local pode estar desatualizado em relação ao IA — o `--skip-existing` consulta o IA diretamente

---

## 13. Fontes RO (estado atual)

| Fonte | Tipo | Estratégia | Range | `head_check` |
|---|---|---|---|---|
| casacivil | lei | wayback-cdx + sequential `L{N}.pdf` | 1–6000 | false |
| casacivil | lc | sequential `LC{N}.pdf` | 1–1300 | false |
| casacivil | decreto | sequential `D{N}.pdf` + `DEC{N}.pdf` | 1–15000 | true |
| casacivil | ec | sequential `EC{N}.pdf` | 1–200 | true |
| casacivil | resolucao | sequential `Res{N}.pdf` | 1–1000 | true |
| casacivil | portaria | sequential `Port{N}.pdf` | 1–3000 | true |
| casacivil | decreto-lei | sequential `DL{N}.pdf` | 1–1000 | true |
| assembleia | lei | playwright `al.ro.leg.br` | 1–5000 | n/a |

**Quirk casacivil**: URLs L1–L499 retornam HTML (não são PDFs reais). PDFs reais começam em L500. URLs zero-padded (`L001.pdf`) também retornam HTML. O CDX às vezes arquiva esses HTML — o scraper valida o magic byte `%PDF` antes de fazer upload.

---

## 14. Referências

- ADR-0001: IA como pilar arquitetural
- ADR-0004: Wayback como caminho primário de fetch
- ADR-0005: Padrão de identificadores IA
- ADR-0006: Schema XML Leizilla v0.1
- `src/leizilla/ia_utils.py`: implementação de URL resolution e range buckets
- `src/leizilla/publisher.py`: upload para IA
- `src/leizilla/manifests/ro.json`: configuração de discovery para RO
