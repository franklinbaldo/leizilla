---
type: Convencao
title: head_check
description: Flag que controla se URLs são validadas com HEAD requests antes de serem adicionadas.
tags: [discovery, head-check, performance]
timestamp: 2026-06-25T00:00:00Z
---

O `head_check` é uma propriedade de cada estratégia `sequential` no manifest.

## Semântica

| Valor | Comportamento | Custo |
|---|---|---|
| `false` | URL adicionada sem verificar existência | Nenhum — instantâneo |
| `true` | HEAD request antes de adicionar; aceita 200 ou 302 | 0.5s por URL |

## Por que `false` para lei/lc no casacivil

O servidor do casacivil retorna HTTP 200 mesmo para leis inexistentes — mas com corpo HTML em vez de PDF. O `head_check: false` é intencional: a validação real acontece no scrape via magic bytes `%PDF`.

## Custo de `head_check: true`

Exemplo: D1–D15000 + DEC1–D15000 = 30.000 URLs × 0.5s = **~4 horas**.

Por isso existe o flag `--no-head-check` no discover: pula todas as estratégias com `head_check: true`. O CDX (wayback-cdx) descobre essas URLs via snapshots do Wayback de qualquer forma.

## Estratégias com `head_check: true` no RO

- `D{N}.pdf` (decreto): 1–15000
- `EC{N}.pdf` (ec): 1–200
- `Res{N}.pdf` (resolucao): 1–1000
- `Port{N}.pdf` (portaria): 1–3000
- `DEC{N}.pdf` (decreto): 1–15000
- `DL{N}.pdf` (decreto-lei): 1–1000

## Recomendação operacional

Para runs rápidos: `--no-head-check`. O CDX do Wayback é o principal mecanismo de descoberta — `head_check` serve como fallback para URLs que nunca foram arquivadas.
