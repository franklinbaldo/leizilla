---
type: Infraestrutura
title: Internet Archive
description: Pilar central de armazenamento — OCR gratuito, CDN global, torrents automáticos.
tags: [storage, internet-archive, ocr]
timestamp: 2026-06-25T00:00:00Z
---

O Internet Archive (IA) cumpre quatro papéis simultâneos no Leizilla:

| Papel | Detalhe |
|---|---|
| **Armazenamento permanente** | PDFs brutos + XMLs parseados + Parquet |
| **OCR gratuito** | Gera `_djvu.txt` automaticamente após upload de PDF |
| **CDN global** | `archive.org/download/…` é o endpoint de leitura |
| **Torrents** | Gerados automaticamente para todos os itens |

Nenhum outro storage é usado em produção. O DuckDB local é staging apenas.

## Autenticação

Variáveis: `IA_ACCESS_KEY` + `IA_SECRET_KEY`. Escritas em `.ini` temporário e passadas via `-c FILE` ao CLI `ia`. Nunca persistidas em disco permanente.

## Upload

- CLI `ia upload` com flags `--no-derive` (pula pipeline de mídia do IA) e `--checksum` (idempotência)
- O `--no-derive` é essencial: evita que o IA processe PDFs como "livros digitalizados" com OCR duplicado
- O IA gera OCR (`_djvu.txt`) **somente para PDFs uploadados sem `--no-derive`** — confirmar se esse flag está correto para o fluxo de OCR

## Metadados padrão por tipo de item

| Campo | Raw | Parsed | Dataset |
|---|---|---|---|
| `mediatype` | `texts` | `texts` | `data` |
| `creator` | `leizilla-crawler` | `leizilla-parser` | `leizilla-etl` |
| `subject` | `leis;leizilla;{ente};{fonte}` | `leis;leizilla;{ente};{tipo}` | `leis;leizilla;{ente};parquet;versoes` |
| `language` | `pt` | `pt` | — |

## OCR assíncrono

O IA processa OCR em background. Tempo típico: minutos a horas. O pipeline não policia esse tempo — `fetch_ocr` simplesmente retorna `None` enquanto o `_djvu.txt` não existe.

# Citations

[1] [ADR-0001: IA como pilar arquitetural](/docs/adr/0001-projeto-estatico-duckdb-torrent.md)
[2] [Range Buckets](range-buckets.md)
