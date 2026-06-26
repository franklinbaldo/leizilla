---
type: Configuracao
title: Contrato de parse
description: Entrada, saída JSON esperada do LLM e critérios de aceitação do parse.
tags: [llm, parse, contrato]
timestamp: 2026-06-25T00:00:00Z
---

## Entrada

O LLM recebe texto OCR ou HTML truncado ao limite de caracteres:

| `input_type` | Limite | System prompt |
|---|---|---|
| `ocr` | 8.000 chars | "Parse Brazilian law OCR text into a JSON object." |
| `html` | 32.000 chars | "Parse Brazilian law HTML page into a JSON object. Ignore nav/headers/footers." |

## Saída esperada

JSON puro — sem markdown fences, sem explicações.

```json
{
  "xml":        "<lei xmlns=\"https://leizilla.org/lei/0.1\" ...>...</lei>",
  "confidence": 0.98,
  "tipo":       "lei",
  "numero":     "500",
  "ano":        1993,
  "urn_lex":    "urn:lex:br;rondonia:estadual:lei:1993-06-15;500"
}
```

## Critérios de aceitação

| Critério | Rejeição |
|---|---|
| `confidence < 0.5` | Silenciosa (sem erro, sem upload) |
| JSON malformado | Silenciosa |
| XML mal-formado | Silenciosa |
| `tipo` ausente | Silenciosa |
| `numero` ausente ou não-numérico | Silenciosa |
| `ano` ausente | Silenciosa |

## `parsed_meta.json`

Gerado junto com o XML e enviado ao IA:

```json
{
  "leizilla_meta_version": "0.1",
  "ia_id_raw":    "leizilla-raw-ro-casacivil-lei-00500",
  "ia_id_parsed": "leizilla-ro-lei-00500-1993",
  "ente":         "ro",
  "tipo":         "lei",
  "parse_method": "gemini/gemini-2.5-flash+ocr",
  "confianca_parse_global": 0.98,
  "parse_timestamp": "2026-06-25T17:30:00Z",
  "tem_divergencia": false
}
```

# Citations

[1] [LiteLLM](litellm.md)
[2] [src/leizilla/parser.py](/src/leizilla/parser.py)
