---
type: Etapa
title: Consolidate
description: Converte XMLs Leizilla em Parquet (tabela versoes).
tags: [pipeline, parquet, etl]
timestamp: 2026-06-25T00:00:00Z
---

Lê um diretório de arquivos `{lei_id}.xml` (Leizilla XML v0.1) e gera o Parquet
`versoes` — grain: lei × dispositivo × versão.

## Comando

```bash
leizilla consolidate data/parsed --output data/versoes.parquet --ente ro
```

O argumento posicional é o diretório de XMLs; `--output` é obrigatório.

## Comportamento

- Itera sobre `*.xml` no diretório fornecido
- Chama `etl.xml_to_rows()` por arquivo → lista de dicts
- Escreve Parquet SNAPPY via `etl.write_parquet()`

## Nota

Use `leizilla fetch-all-parsed --ente ro --output-dir data/parsed` para baixar
os XMLs do IA antes de consolidar. O Parquet resultante é publicado com
`leizilla release-dataset`.
