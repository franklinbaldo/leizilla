---
type: Convencao
title: Invariantes do sistema
description: Regras que nunca devem ser violadas em nenhuma etapa do pipeline.
tags: [regras, invariantes, pipeline]
timestamp: 2026-06-25T00:00:00Z
---

Estas regras são invariantes — violá-las corrompe dados ou quebra a resolução de URLs.

## Nomeação

1. `{fonte}` **nunca contém hífen** — o parser de identificadores usa hífen como separador de seções
2. `{ente}` é sempre um slug do catálogo `entes.py` — não inventar novos slugs sem registrar lá
3. Nomes de arquivo **sem hash** (`000500.pdf`) são reservados para artefatos canônicos futuros — nunca usar no upload atual

## Storage

4. PDFs brutos **nunca vão para itens individuais** — sempre para range buckets
5. O DuckDB local pode estar desatualizado em relação ao IA — `--skip-existing` consulta o IA diretamente, não o DuckDB

## Fetch e robots

6. Rejeição por `robots.txt` é **permanente** para aquela URL — sem retry; `robots_blocked: true` registrado no `raw_meta.json`
7. O `manifest.csv` é a fonte de verdade sobre o que está dentro de um range bucket

## Parse

8. Parse com `confidence < 0.5` é descartado **silenciosamente** — não é erro de rede, não gera retry automático
9. O `_djvu.txt` OCR só existe após processamento assíncrono do IA — o pipeline não policia esse tempo; `fetch_ocr` retorna `None` enquanto não disponível

# Citations

[1] [Range Buckets](storage/range-buckets.md)
[2] [ADR-0008: robots e rate limiting](/docs/adr/0008-robots-rate-limit.md)
[3] [Contrato de parse](llm/parse-contract.md)
