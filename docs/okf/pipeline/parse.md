---
type: Etapa
title: Parse
description: Lê OCR do IA, envia ao LLM via LiteLLM, produz Leizilla XML e parsed_meta.json.
tags: [pipeline, llm, parse]
timestamp: 2026-06-25T00:00:00Z
---

O parse é a etapa de extração de estrutura. Depende do OCR assíncrono do IA — pode levar horas após o scrape para o `_djvu.txt` estar disponível.

## Comandos

```bash
# Item individual
leizilla parse --raw-id leizilla-raw-ro-casacivil-lei-00500 --ente ro --upload

# Batch
leizilla parse-all --ente ro --fonte casacivil --start 500 --end 600 \
  --upload --skip-existing --input-type ocr
```

## Input types

| `--input-type` | Arquivo lido do IA | Casos de uso |
|---|---|---|
| `ocr` (default) | `{num:06d}_{hash}_djvu.txt` | PDFs (casacivil, assembleia) |
| `html` | `{num:06d}_{hash}.html` | Fontes HTML (Planalto) |

## Fluxo

1. Resolve URL do `_djvu.txt` via `resolve_ia_id_to_url` (usa hash do DuckDB)
2. Fetch do arquivo OCR
3. Chama `parse_law(ocr_text, ia_id, ente, model=LITELLM_MODEL)`
4. Valida: `confidence >= 0.5` + XML bem-formado
5. Upload do `law.xml` + `parsed_meta.json` para item parsed no IA

## Identificador do item parsed

```
leizilla-{ente}-{tipo}-{numero:05d}-{ano}
```

Exemplo: `leizilla-ro-lei-00500-1993`

## Rejeição silenciosa

Parse retorna `None` (sem erro, sem upload) quando:
- `confidence < 0.5`
- JSON malformado
- XML mal-formado
- Campos obrigatórios ausentes (`tipo`, `numero`, `ano`)

# Citations

[1] [LiteLLM](../llm/litellm.md)
[2] [Contrato de parse](../llm/parse-contract.md)
[3] [src/leizilla/parser.py](/src/leizilla/parser.py)
