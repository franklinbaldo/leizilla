---
type: Visao Geral
title: Visão geral do pipeline
description: As 6 etapas do Leizilla, suas entradas, saídas e dependências.
tags: [pipeline, arquitetura]
timestamp: 2026-06-25T00:00:00Z
---

O pipeline é linear e incremental. Cada etapa pode ser reexecutada com segurança — uploads são idempotentes via `--checksum` e `--skip-existing`.

```
discover → scrape → [OCR assíncrono no IA] → parse → consolidate → release-dataset
```

## Etapas

| # | Etapa | Comando | Entrada | Saída |
|---|---|---|---|---|
| 1 | [Discover](discover.md) | `leizilla discover` | `manifests/{ente}.json` | `discovered_resources` no DuckDB |
| 2 | [Scrape](scrape.md) | `leizilla scrape` | URLs da fonte / Wayback | PDF no range bucket do IA |
| — | OCR (IA) | — | PDF no IA | `_djvu.txt` no mesmo bucket (horas) |
| 3 | [Parse](parse.md) | `leizilla parse-all` | `_djvu.txt` do IA | Leizilla XML + `parsed_meta.json` no IA |
| 4 | [Consolidate](consolidate.md) | `leizilla consolidate <dir> --output <parquet>` | Diretório de XMLs (baixados de IA) | `versoes.parquet` local |
| 5 | [Release Dataset](release-dataset.md) | `leizilla release-dataset <parquet> --ente ro` | `versoes.parquet` local | `versoes.parquet` + `dataset_meta.json` no IA |

## Dependências entre etapas

- Scrape depende de discover (precisa de URLs na tabela `discovered_resources`), mas pode operar via CDX sem discover prévio com o flag `--fonte`.
- Parse depende do OCR do IA, que é assíncrono. O pipeline não controla esse tempo.
- Consolidate depende de parse.
- Release-dataset depende de consolidate.

## GitHub Actions

| Workflow | Cadência | Etapas |
|---|---|---|
| `rondonia_crawler.yml` | Domingo meia-noite | discover + scrape |
| `discover-harvest.yml` | Sábado 02:00 | discover + harvest |
| `parse-release.yml` | Segunda 06:00 | parse-all + consolidate + release-dataset |
| `claude-routine.yml` | Seg/Qui 10:00 | manutenção LLM |

# Citations

[1] [manifests/ro.json](/src/leizilla/manifests/ro.json)
[2] [.github/workflows/](/github/workflows/)
