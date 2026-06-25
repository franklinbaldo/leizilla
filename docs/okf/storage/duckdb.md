---
type: Infraestrutura
title: DuckDB local
description: Staging local para discovered_resources e leis. Não é source of truth — pode ser reconstruído do IA.
tags: [storage, duckdb]
timestamp: 2026-06-25T00:00:00Z
---

O DuckDB em `data/leizilla.duckdb` é staging local. Se perdido, pode ser reconstruído:
- `discovered_resources`: rodando discover novamente
- `leis`: rodando consolidate contra o IA

## Tabelas

### `discovered_resources`

URLs descobertas e seu status de processamento.

| Coluna | Tipo | Descrição |
|---|---|---|
| `url` | VARCHAR PK | URL original da fonte |
| `ente` | VARCHAR | Ex: `ro` |
| `fonte` | VARCHAR | Ex: `casacivil` |
| `tipo_documento` | VARCHAR | Ex: `lei`, `decreto` |
| `chave` | VARCHAR | Ex: `lei-00500` |
| `status` | VARCHAR | `pending`, `downloaded`, `failed`, `not-pdf`, `robots-blocked` |
| `wayback_snapshot` | VARCHAR | URL do snapshot Wayback usado |
| `data_descoberta` | TIMESTAMP | |
| `ultima_tentativa` | TIMESTAMP | |

### `leis`

Leis parseadas com texto completo e metadados.

| Coluna | Tipo | Descrição |
|---|---|---|
| `id` | VARCHAR PK | Ex: `ro-casacivil-lei-00500` |
| `titulo` | TEXT | |
| `numero` | VARCHAR | |
| `ano` | INTEGER | |
| `data_publicacao` | DATE | |
| `tipo_lei` | VARCHAR | |
| `ente` | VARCHAR | |
| `texto_completo` | TEXT | OCR bruto |
| `metadados` | JSON | Inclui `hash_8` do PDF |
| `url_pdf_ia` | VARCHAR | URL no range bucket |
| `hash_conteudo` | VARCHAR | SHA-256 do texto |

## Limitações no Windows

**Single-writer**: processos paralelos causam lock error ("O arquivo já está sendo usado por outro processo"). Matar processos pendentes antes de iniciar novos. O `--checksum` do IA CLI e os inserts com `INSERT OR IGNORE`/`INSERT OR REPLACE` garantem que re-runs são seguros.

## Localização

`DUCKDB_PATH` env var; default: `data/leizilla.duckdb` relativo ao `PROJECT_ROOT`.
