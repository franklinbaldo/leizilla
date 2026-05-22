# ADR-0005 — Internet Archive Identifiers

**Status**: Aprovada  
**Data**: 2026-05-20  
**Contexto**: M1 — Foundation

## Decisão

Padrão de naming para IA items:

| Tipo | Pattern | Exemplo |
|---|---|---|
| Raw (individual) | `leizilla-raw-{ente}-{fonte}-{chave}` | `leizilla-raw-ro-casacivil-coddoc-00042` |
| Raw (bundle ZIP) | `leizilla-bundle-{ente}-{fonte}-{periodo}` | `leizilla-bundle-ro-casacivil-2026-W20` |
| Parsed (lei canônica) | `leizilla-{ente}-{tipo}-{numero:05d}-{ano}` | `leizilla-ro-lei-01234-2003` |
| Dataset (Parquet) | `leizilla-dataset-{ente}-v{N}` | `leizilla-dataset-ro-v1` |

## Regras

- `{ente}`: slug do catálogo `entes.py` (kebab-case, ex: `ro`, `sp`, `federal`,
  `ro-porto-velho`).
- `{fonte}`: token único `[a-z]+` sem hífens (ex: `casacivil`, `assembleia`,
  `diario`). Hífen quebraria o parsing do identifier.
- `{chave}`: identificador natural da fonte (ex: `coddoc-00042`).
- `{numero}` no parsed item: zero-padded 5 dígitos. Sem normalização extra —
  `id` Parquet é lookup literal.
- Fallback parsed: `leizilla-{ente}-{tipo}-fallback-{fonte}-{chave}` quando
  número/ano não puderem ser extraídos.

## Manifest CSV

IA item do dataset serve como source of truth (padrão baliza). Colunas mínimas:
`ia_id`, `ente`, `fonte`, `chave`, `raw_uploaded_at`, `ocr_ready`, `parsed_ia_id`,
`parsed_at`.

## Implementação

M2 — geração automática dos identifiers em `publisher.py`.
Manifest em M4 junto com exportação Parquet.
