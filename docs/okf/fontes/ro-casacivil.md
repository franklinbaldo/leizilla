---
type: Fonte
title: casacivil (RO)
description: Portal COTEL da Casa Civil de Rondônia — leis, decretos, LCs e atos normativos.
resource: http://ditel.casacivil.ro.gov.br/COTEL/Livros/Files/
tags: [fonte, rondonia, casacivil]
timestamp: 2026-06-25T00:00:00Z
---

## URL pattern

```
http://ditel.casacivil.ro.gov.br/COTEL/Livros/Files/{prefixo}{N}.pdf
```

## Tipos disponíveis

| Prefixo | Tipo | Range descoberto | `head_check` |
|---|---|---|---|
| `L{N}.pdf` | lei | 1–6000 | false |
| `LC{N}.pdf` | lc | 1–1300 | false |
| `D{N}.pdf` | decreto | 1–15000 | true |
| `DEC{N}.pdf` | decreto | 1–15000 | true |
| `DL{N}.pdf` | decreto-lei | 1–1000 | true |
| `EC{N}.pdf` | ec | 1–200 | true |
| `Res{N}.pdf` | resolucao | 1–1000 | true |
| `Port{N}.pdf` | portaria | 1–3000 | true |

## Quirks

**L1–L499 retornam HTML, não PDF.** O servidor retorna uma página HTML de erro com HTTP 200 para leis com número < 500. O scrape detecta isso via validação de magic bytes (`%PDF`) e marca como `not-pdf`.

**URLs zero-padded retornam HTML.** `L001.pdf`, `L002.pdf` etc. (com zeros à esquerda) retornam HTML — o servidor só aceita o número sem padding: `L500.pdf`. O CDX às vezes arquiva essas URLs zero-padded; o scrape filtra pelo magic byte.

**PDFs reais começam em L500.** Para ingestão via sequential, usar `--start-coddoc 500`.

## Estratégias de discovery configuradas

1. `wayback-cdx` — prefixo `http://ditel.casacivil.ro.gov.br/COTEL/Livros/Files/`
2. `sequential` para cada tipo (ver tabela acima)

# Citations

[1] [Estratégias de discovery](../discovery/strategies.md)
[2] [head_check](../discovery/head-check.md)
[3] [manifests/ro.json](/src/leizilla/manifests/ro.json)
