---
type: Etapa
title: Scrape
description: Baixa PDFs via Wayback Machine e faz upload para range buckets no Internet Archive.
tags: [pipeline, scrape, internet-archive]
timestamp: 2026-06-25T00:00:00Z
---

O scrape é o caminho primário de ingestão. Opera via CDX (Wayback Machine) — não depende de `discovered_resources` quando usado com `--fonte`.

## Comando

```bash
leizilla scrape --ente ro --fonte casacivil --tipo lei --start 500 --end 600
leizilla scrape --ente ro --fonte casacivil --tipo lei --start 500 --end 600 --skip-existing
```

## Flags

| Flag | Default | Descrição |
|---|---|---|
| `--ente` | `ro` | Ente federativo |
| `--fonte` | obrigatório | Fonte (casacivil, assembleia, …) |
| `--tipo` | — (todos) | Tipo de documento; omitido = todos os tipos da fonte |
| `--start` | — (auto via CDX) | Primeiro número |
| `--end` | — (auto via CDX) | Último número |
| `--skip-existing` | false | Consulta IA e pula itens já publicados |

## Fluxo por item

```
CDX API → [N snapshots da URL]
  para cada snapshot:
    1. robots.txt check (permanente se bloqueado)
    2. Wayback save (fire-and-forget)
    3. Wayback fetch (primário)
    4. Fallback direto com rate limit 1 req/s por host
    5. Validação magic bytes: %PDF
    6. Upload para range bucket com hash
    7. Atualiza manifest.csv do bucket
```

## Deduplicação

- **Entre runs**: `--skip-existing` consulta o IA antes de processar
- **Dentro de um run**: não há dedup — múltiplos snapshots CDX da mesma lei são todos processados

## Rate limiting

- Wayback save: fire-and-forget, sem rate limit explícito
- Fallback direto: 1 req/s por host (via `make_rate_limiter`)
- HEAD check (discover): 0.5 req/s global

## Validação de PDF

Antes do upload, valida os primeiros 4 bytes: `%PDF`. Se o servidor retornar HTML (ex: página de erro), o item é marcado como `not-pdf` no DuckDB e pulado.

# Citations

[1] [Range Buckets](../storage/range-buckets.md)
[2] [ADR-0004: Wayback como caminho primário](/docs/adr/0004-wayback-fetch-path.md)
[3] [src/leizilla/scraper.py](/src/leizilla/scraper.py)
