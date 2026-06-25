---
type: Etapa
title: Consolidate
description: Lê itens parsed do IA e popula a tabela leis no DuckDB local.
tags: [pipeline, duckdb]
timestamp: 2026-06-25T00:00:00Z
---

Lê `parsed_meta.json` e `law.xml` de cada item parsed no IA e insere/atualiza a tabela `leis` no DuckDB local.

## Comando

```bash
leizilla consolidate --ente ro
```

## Comportamento

- Lista itens parsed no IA com prefixo `leizilla-{ente}-`
- Para cada item: baixa `parsed_meta.json` e `law.xml`
- Insere ou atualiza em `leis` via `INSERT OR REPLACE`

## Nota

O DuckDB local **não é source of truth**. Se perdido, pode ser reconstruído rodando consolidate novamente contra o IA.
