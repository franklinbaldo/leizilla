---
type: Convencao
title: Chaves de documento
description: Mapeamento de prefixo de arquivo fonte para tipo_documento e chave canônica.
tags: [naming, chaves, discovery]
timestamp: 2026-06-25T00:00:00Z
---

A `chave` identifica unicamente um documento dentro de uma fonte. Formato: `{tipo}-{numero:05d}`.

## Mapeamento (prefixo mais longo primeiro)

| Prefixo no arquivo | `tipo_documento` | `chave` | Exemplo |
|---|---|---|---|
| `PORT{N}.pdf` | `portaria` | `portaria-{N:05d}` | `portaria-00042` |
| `RES{N}.pdf` | `resolucao` | `resolucao-{N:05d}` | `resolucao-00010` |
| `DEC{N}.pdf` | `decreto` | `decreto-{N:05d}` | `decreto-01234` |
| `LC{N}.pdf` | `lc` | `lc-{N:05d}` | `lc-00150` |
| `EC{N}.pdf` | `ec` | `ec-{N:05d}` | `ec-00001` |
| `DL{N}.pdf` | `decreto-lei` | `decreto-lei-{N:05d}` | `decreto-lei-00003` |
| `L{N}.pdf` | `lei` | `lei-{N:05d}` | `lei-00500` |
| `D{N}.pdf` | `decreto` | `decreto-{N:05d}` | `decreto-05000` |
| `coddoc-{N}` | `lei` | `coddoc-{N:05d}` | `coddoc-00123` |

**Importante**: prefixos casados do **mais longo para o mais curto** para evitar ambiguidade (`DEC` antes de `D`, `PORT` antes de qualquer outro).

## Fallback

Se o nome do arquivo não casa com nenhum prefixo conhecido:
- `tipo_documento = "documento"`
- `chave = "fallback-{name_clean}"`

O item vai para `leizilla_{ente}_{fonte}_fallback/` no IA.

## Função de parse

```python
parse_filename(filename) -> (tipo_documento, chave)
# Ex: parse_filename("L500.pdf") -> ("lei", "lei-00500")
# Ex: parse_filename("DEC1234.pdf") -> ("decreto", "decreto-01234")
```

Implementada em `src/leizilla/discovery.py`.
