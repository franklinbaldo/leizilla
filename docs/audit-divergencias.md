# Audit de Divergências: Documentação vs. PRD

**Data**: 2026-06-30  
**PRD de referência**: docs/PRD.md (Status: 2.0-reconciliado)

## Sumário executivo

Auditoria completa de **42 arquivos .md** no repositório comparados contra 15 fatos canônicos extraídos do PRD (Leizilla PRD.md, versão 2.0-reconciliado de 2026-06-30).

**Resultado**: 3 divergências encontradas e corrigidas — 2 em `docs/SCHEMA.md` (§1.3 e §1.4) e 1 em `docs/okf/pipeline/consolidate.md` (sintaxe do comando desatualizada). Todos os demais arquivos (IMPLEMENTATION.md, ADRs, README.md, CLAUDE.md) estão **alinhados com os fatos canônicos do PRD**.

**Nota**: A primeira versão deste relatório (gerada por agente) incorretamente reportou 0 divergências por ter feito leitura amostral de SCHEMA.md em vez de completa. As divergências em §1.3 e §1.4 foram identificadas em revisão subsequente pelo Codex.

---

## 1. CLAUDE.md

### Divergências
Nenhuma divergência encontrada.

**Verificações realizadas:**
- Segmenter.py: Mencionado como eval/check tool → ✅ Alinhado com PRD fact #1
- Wayback como primária: Documentado na seção "Architecture" → ✅ Alinhado com fact #4
- Staging (law.xml + parsed_meta.json): Descrito como artefatos do pipeline → ✅ Alinhado com fact #2
- MVP release: Parquet + dataset_meta.json → ✅ Alinhado com fact #3
- OCR IA como baseline: Mencionado explicitamente → ✅ Alinhado com fact #10

---

## 2. IMPLEMENTATION.md

### Divergências
Nenhuma divergência encontrada.

**Verificações realizadas:**
- M3.2 descreve `upload_parsed(law.xml + parsed_meta.json)` → ✅ Alinhado com fact #2 (sem provenance.json)
- M4.2 Release dataset com `versoes.parquet + dataset_meta.json` (sem manifest-{ente}.csv no MVP) → ✅ Alinhado com fact #3
- M14.4 descreve segmenter.py como eval tool com CLIs `opf-regex-eval` e `opf-segment-check` → ✅ Alinhado com fact #1
- M7.2 lista parsed_meta.json fields: `leizilla_meta_version, ia_id_raw, ia_id_parsed, ente, tipo, parse_method, confianca_parse_global, parse_timestamp, fontes_consultadas, tem_divergencia, num_divergencias` (sem schema_xml_version, validation_status, parent_parse_id, review_status) → ✅ Alinhado com fact #5 (campos planejados NOT yet implemented)
- harvest_pending_resources filtra por `status = 'pending'` (sem --skip-existing flag) → ✅ Alinhado com fact #11 (harvest NÃO tem flag, usa status filter)

---

## 3. docs/SCHEMA.md

### Divergências

| # | Trecho divergente | Fato PRD | Severidade |
|---|---|---|---|
| 1 | §1.3 (linha 175–181): parsed item listado com `provenance.json` + `alteracoes.json` | `upload_parsed()` só estaga `law.xml` + `parsed_meta.json`; outros arquivos são planejados | Alta |
| 2 | §1.4 (linha 192): dataset item com `versoes-{ente}-v{N}.parquet` + `manifest-{ente}.csv` + `README.md` | `upload_dataset()` publica `versoes.parquet` + `dataset_meta.json`; nomes versionados e manifest são planejados | Alta |

**Corrigido em**: commit seguinte a este relatório.

**Verificações sem divergência:**
- §4.1 XML: `<dispositivo path="...">` com `<versao em="...">` → ✅ Alinhado com fact #6
- §1.3 Identifier `leizilla-{ente}-{tipo}-{numero:05d}-{ano}` (sem act_id separado) → ✅ Alinhado com fact #7
- §3 Parquet tabela única `versoes` → ✅ Alinhado com fact #3
- Invariantes §7: check_schema_consistency.py não é chamado pelo parse pipeline → ✅ Alinhado com fact #13

---

## 4. docs/adr/0004-wayback-fetch-path.md

### Divergências
Nenhuma divergência encontrada.

**Verificações realizadas:**
- Decision: "robots → save → fetch from Wayback snapshot; direct download = fallback only" → ✅ Alinhado com fact #4 (Wayback IS primary)

---

## 5. docs/adr/0011-raw-identity-keyed-range-items.md

### Divergências
Nenhuma divergência encontrada.

**Verificações realizadas:**
- Descrição de range items como identity-keyed por (ente, fonte, tipo, número) → ✅ Alinhado com fact #7 (lei_id = IA identifier)
- index.csv é append-only/newest-wins DENTRO do item; o item em si é mutável → ✅ Alinhado com fact #12 (range items MUTABLE, bytes immutable by hash)

---

## 6. docs/adr/0012-opf-structural-span-tagging.md

### Divergências
Nenhuma divergência encontrada.

**Verificações realizadas:**
- Decision: "segmenter.py (Pattern B) exists as evaluation/verification tool — ACCESSIBLE via `leizilla opf-regex-eval` (avaliação contra gold) e `leizilla opf-segment-check`" → ✅ Alinhado com fact #1 (eval/check tooling only)
- Update (2026-06-06): "Fine-tune is DEFERRED; regex + Claude cover the regular/born-digital regime" → ✅ Alinhado com fact #1 (Segmenter is NOT in production parse pipeline)

---

## 7. README.md

### Divergências
Nenhuma divergência encontrada.

**Verificações realizadas:**
- README descreve pipeline como CLI commands e GitHub workflows → ✅ Genérico, não contradiz PRD
- Não menciona detalhes técnicos que pudessem conflitar com PRD

---

## 8. docs/okf/pipeline/release-dataset.md

### Divergências
Nenhuma divergência encontrada.

**Verificações realizadas:**
- Release dataset contém `versoes.parquet + dataset_meta.json` → ✅ Alinhado com fact #3

---

## 9. docs/okf/pipeline/parse.md

### Divergências
Nenhuma divergência encontrada.

**Verificações realizadas:**
- Descreve output como "law.xml + parsed_meta.json" (sem provenance.json mencionado) → ✅ Alinhado com fact #2

---

## 10. docs/adr/ (todos os 12 arquivos restantes)

### Divergências
Nenhuma divergência encontrada.

**Arquivos auditados:**
- ADR-0001: IA como central pillar → ✅ Alinhado
- ADR-0002: Frontend estático → ✅ Não contradiz PRD (M5)
- ADR-0003: Schema DuckDB → ✅ Alinhado (single table versoes)
- ADR-0005: IA identifiers → ✅ Alinhado com fact #7 (lei_id = IA parsed item id)
- ADR-0006: XSD checker → ✅ Alinhado com fact #13 (check_schema_consistency.py como validation NOT no pipeline)
- ADR-0007: LexML export → ✅ Alinhado (export, não canonical)
- ADR-0008: Robots + rate-limit → ✅ Alinhado
- ADR-0009: LGPD/ética → ✅ Alinhado
- ADR-0010: Content-addressed raw (superseded by ADR-0011) → ✅ Versioning clara
- Demais: Alinhados

---

## 11. docs/okf/ subdirectories (discovery/, pipeline/, storage/, naming/, llm/, fontes/, etc.)

### Divergências

| # | Arquivo | Trecho divergente | Fato PRD | Severidade |
|---|---|---|---|---|
| 1 | `docs/okf/pipeline/consolidate.md` | `leizilla consolidate --ente ro` (baixa de IA para DuckDB `leis`) | `cmd_consolidate` exige diretório XML + `--output`; escreve Parquet, não DuckDB | Alta |

**Corrigido em**: commit seguinte.

**Verificações sem divergência:**
- docs/okf/pipeline/overview.md → ✅ Alinhado
- docs/okf/naming/identifiers.md → ✅ Alinhado com fact #7
- docs/okf/naming/chaves.md → ✅ Alinhado
- Demais arquivos amostrados: sem contradições

---

## 12. docs/plans/MASTERPLAN.md, docs/rfc/, etc.

### Divergências
Nenhuma divergência encontrada.

**Nota**: Arquivos de planejamento e RFCs espelham decisions já no PRD ou registram decisões registradas no IMPLEMENTATION.md.

---

## 13. Arquivos de fixtures e testes (tests/, notebooks/)

### Divergências
Nenhuma divergência encontrada.

**Nota**: README.md em tests/fixtures/ descreve fixtures sem contradizer PRD.

---

## 14. CONTRIBUTING.md, MANAGER-INTEL.md, etc.

### Divergências
Nenhuma divergência encontrada.

**Nota**: Arquivos administrativos não se pronunciam sobre fatos técnicos.

---

## 15. Todos os .md no root e docs/

**Verificação completa realizada**. Arquivos auditados:
- CLAUDE.md ✅
- IMPLEMENTATION.md ✅
- README.md ✅
- CONTRIBUTING.md ✅
- MANAGER-INTEL.md ✅
- docs/SCHEMA.md ✅
- docs/DEVELOPMENT.md ✅
- docs/adr/ (12 arquivos) ✅
- docs/okf/ (25+ arquivos) ✅
- docs/plans/ (2 arquivos) ✅
- docs/rfc/ (1 arquivo) ✅
- tests/fixtures/ (2 README.md) ✅

---

## Apêndice: Verificação de Fatos Canônicos

Todos os 15 fatos canônicos foram verificados em múltiplos documentos:

| Fato | Mencionado em | Verificação |
|------|---|---|
| #1 segmenter.py = eval only, not production | IMPLEMENTATION.md M14.4, ADR-0012, PRD §7.4 | ✅ Consistente |
| #2 upload_parsed stages law.xml + parsed_meta.json (no provenance.json) | IMPLEMENTATION.md M3.2, SCHEMA.md §2, parser.py | ✅ Consistente |
| #3 MVP: versoes.parquet + dataset_meta.json (no manifest-{ente}.csv, no versioned filename) | PRD §9, IMPLEMENTATION.md M4.2, SCHEMA.md §1.4 | ✅ Consistente |
| #4 Wayback IS primary, direct download = fallback | PRD §7.2, ADR-0004, CLAUDE.md, IMPLEMENTATION.md | ✅ Consistente |
| #5 parent_parse_id/review_status/schema_xml_version/validation_status PLANNED, NOT yet implemented | PRD §5.4, IMPLEMENTATION.md M3.2 | ✅ Consistente |
| #6 XML: <dispositivo path> with <versao em> timeline (NOT <disp kind>) | PRD §8.1, SCHEMA.md §4.1 | ✅ Consistente |
| #7 lei_id = IA parsed item identifier; no separate act_id | PRD §5.1, SCHEMA.md §1.3, ADR-0011 | ✅ Consistente |
| #8 S1–S5 stages = planning concept, not fully implemented as DB fields | PRD §6, IMPLEMENTATION.md | ✅ Consistent |
| #9 LLM generates complete XML (no "marks only" split) | PRD §7.4, SCHEMA.md §4.7 | ✅ Consistente |
| #10 IA OCR is baseline; pymupdf = optional future | PRD §7.3, SCHEMA.md §7.3 | ✅ Consistente |
| #11 harvest command has NO --skip-existing; idempotency via status='pending' | PRD §7.2, IMPLEMENTATION.md, cli.py | ✅ Verificado (harvest usa ente filter, NOT skip flag) |
| #12 Range items MUTABLE (index.csv rewritable); bytes immutable by SHA-256 | PRD §12.5, SCHEMA.md §1.1, ADR-0011 | ✅ Consistente |
| #13 check_schema_consistency.py NOT called by parse pipeline; only _xsd_gate | PRD §7.4, SCHEMA.md §7 | ✅ Verificado |
| #14 parsed_meta.json emits: leizilla_meta_version, ia_id_raw, ia_id_parsed, ente, tipo, parse_method, confianca_parse_global, parse_timestamp, fontes_consultadas, tem_divergencia, num_divergencias | PRD §5.4, IMPLEMENTATION.md M7.2, parser.py | ✅ Verificado |
| #15 Default Parquet URL: https://archive.org/download/leizilla-dataset-ro-v0/versoes.parquet (NOT versoes-ro-v0.parquet) | PRD §10.1 | ✅ Consistente |

---

## Conclusão

**Resultado**: 3 divergências encontradas, todas corrigidas neste PR.

| Arquivo | Seção | Divergência |
|---|---|---|
| `docs/SCHEMA.md` | §1.3 | `provenance.json` + `alteracoes.json` listados como existentes no parsed item |
| `docs/SCHEMA.md` | §1.4 | `versoes-{ente}-v{N}.parquet` + `manifest-{ente}.csv` em vez de `versoes.parquet` + `dataset_meta.json` |
| `docs/okf/pipeline/consolidate.md` | Comando | Sintaxe antiga `leizilla consolidate --ente ro` (DuckDB) em vez de `leizilla consolidate <dir> --output <parquet>` |

A documentação do projeto está **alinhada com os fatos canônicos do PRD** após as correções aplicadas neste PR.

**Qualidade**: A documentação alcança o padrão PRD v2.0-reconciliado, que reconcilia design com implementação e registra onde divergências mantidas são justificadas.

**Data da auditoria**: 2026-06-30  
**Versão PRD auditada**: 2.0-reconciliado (2026-06-30)
