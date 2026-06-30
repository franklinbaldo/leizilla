---
type: Etapa
title: Release Dataset
description: Exporta a tabela leis do DuckDB para Parquet e publica no Internet Archive.
tags: [pipeline, dataset, parquet]
timestamp: 2026-06-25T00:00:00Z
---

Gera um snapshot versionado da base de leis como Parquet e sobe para o IA.

## Comando

```bash
leizilla release-dataset data/versoes.parquet --ente ro --version 1
```

O argumento posicional `parquet` (saída de `consolidate`) é **obrigatório**.

## Identificador do dataset

```
leizilla-dataset-{ente}-v{version}
```

Restrições: `version >= 0`, `ente` deve casar `^[a-z][a-z0-9-]*$`.

## Arquivo publicado

- `versoes.parquet` — tabela `leis` exportada via DuckDB native Parquet (SNAPPY)
- `dataset_meta.json` — metadados de rastreabilidade

## `dataset_meta.json`

```json
{
  "leizilla_meta_version": "0.1",
  "schema_version": "0.1",
  "ente": "ro",
  "version": 1,
  "table": "versoes",
  "generated_at": "2026-06-25T00:00:00Z",
  "row_count": 1234,
  "file_size_bytes": 567890,
  "hash_parquet": "sha256:abc..."
}
```

## Metadados no IA

| Campo | Valor |
|---|---|
| `mediatype` | `data` |
| `subject` | `leis;leizilla;{ente};parquet;versoes` |
| `creator` | `leizilla-etl` |
