---
type: Etapa
title: Discover
description: Popula a tabela discovered_resources com URLs de leis a partir do manifest da fonte.
tags: [pipeline, discovery]
timestamp: 2026-06-25T00:00:00Z
---

O discover lê `src/leizilla/manifests/{ente}.json` e executa cada estratégia de descoberta configurada, inserindo URLs na tabela `discovered_resources` do DuckDB.

## Comando

```bash
leizilla discover --ente ro
leizilla discover --ente ro --fonte casacivil          # filtra por fonte
leizilla discover --ente ro --no-head-check            # pula estratégias com head_check=true
```

## Flags

| Flag | Default | Descrição |
|---|---|---|
| `--ente` | `ro` | Ente federativo |
| `--fonte` | (todas) | Filtra por fonte específica |
| `--no-head-check` | false | Pula estratégias com `head_check: true` |

## Comportamento

1. Carrega `manifests/{ente}.json`
2. Para cada fonte (opcional: filtra por `--fonte`), para cada estratégia de discovery
3. Se `--no-head-check` e `head_check: true` na config → pula a estratégia
4. Executa a estratégia; para cada recurso descoberto, verifica cruzadamente com `index.csv` do range bucket no IA
5. Se presente no `index.csv` do IA → `status = "downloaded"`; senão → `status = "pending"`
6. Insere na tabela `discovered_resources` (duplicatas ignoradas via `INSERT OR IGNORE`)

## Verificação cruzada com IA

O módulo mantém um cache em memória dos prefixos presentes em cada range bucket (via `index.csv`). O cache persiste durante o processo mas não entre runs.

# Citations

[1] [Estratégias de discovery](../discovery/strategies.md)
[2] [head_check](../discovery/head-check.md)
[3] [src/leizilla/discovery.py](/src/leizilla/discovery.py)
