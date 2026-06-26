---
type: Convencao
title: Identificadores IA
description: Padrões lógicos e físicos para todos os tipos de item no Internet Archive.
tags: [naming, internet-archive, identifiers]
timestamp: 2026-06-25T00:00:00Z
---

Há dois níveis de identificadores: **lógico** (como o código referencia) e **físico** (onde o upload vai no IA).

## Identificadores lógicos

| Tipo | Padrão | Exemplo |
|---|---|---|
| Raw | `leizilla-raw-{ente}-{fonte}-{chave}` | `leizilla-raw-ro-casacivil-lei-00500` |
| Parsed | `leizilla-{ente}-{tipo}-{numero:05d}-{ano}` | `leizilla-ro-lei-00500-1993` |
| Bundle | `leizilla-bundle-{ente}-{fonte}-{year}-W{week:02d}` | `leizilla-bundle-ro-casacivil-2026-W20` |
| Dataset | `leizilla-dataset-{ente}-v{version}` | `leizilla-dataset-ro-v1` |

O identificador lógico raw **nunca é o upload target** — é resolvido para a URL do range bucket via `resolve_raw_url`.

## Identificadores físicos (upload target)

| Tipo | Padrão | Exemplo |
|---|---|---|
| Range bucket (raw) | `leizilla_{ente}_{fonte}_{tipo}_{start:04d}-{end:04d}` | `leizilla_ro_casacivil_lei_0001-1000` |
| Parsed (individual) | mesmo que lógico | `leizilla-ro-lei-00500-1993` |
| Dataset | mesmo que lógico | `leizilla-dataset-ro-v1` |

## Regras de caracteres

- `{ente}`: kebab-case do catálogo `entes.py` (ex: `ro`, `sp`, `ro-porto-velho`)
- `{fonte}`: `[a-z]+` — **sem hífen** (quebraria o parser de identificadores)
- `{tipo}`: slug minúsculo (`lei`, `decreto`, `lc`, `decreto-lei`, …)
- Delimitador de seção no bucket: `_`; hífen é intra-seção

## Parsed: número zero-padded

O `{numero:05d}` no identificador parsed é o número da lei com 5 dígitos.

```
Lei 500   → leizilla-ro-lei-00500-1993
Lei 5120  → leizilla-ro-lei-05120-1993
Lei 12345 → leizilla-ro-lei-12345-1993
```

# Citations

[1] [ADR-0005: Padrão de identificadores IA](/docs/adr/0005-ia-identifiers.md)
[2] [Range Buckets](../storage/range-buckets.md)
[3] [Resolução de URL](url-resolution.md)
