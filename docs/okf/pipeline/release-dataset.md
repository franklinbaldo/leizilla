---
type: Etapa
title: Release Dataset
description: Exporta a tabela leis do DuckDB para Parquet e publica no Internet Archive.
tags: [pipeline, dataset, parquet]
timestamp: 2026-06-25T00:00:00Z
---

Gera um snapshot versionado da base de leis como Parquet e sobe para o IA.

Desde a issue #175, cada chamada publica **dois** itens distintos no IA — um release
imutável e citável, e um ponteiro `latest` pequeno e deliberadamente mutável — para
que citar o dataset seja reprodutível sem perder a conveniência de um link estável
para "a release corrente".

## Comando

```bash
leizilla release-dataset data/versoes.parquet --ente ro --version 1
```

O argumento posicional `parquet` (saída de `consolidate`) é **obrigatório**. Uma
`revision` (timestamp UTC) é calculada automaticamente; passar `revision=` explícito
via API Python (`InternetArchivePublisher.upload_dataset`) é só para reprodutibilidade
de testes — a CLI sempre usa o momento da publicação.

## Identificadores

```
leizilla-dataset-{ente}-v{version}-{revision}   # release imutável e citável
leizilla-dataset-{ente}-v{version}-latest        # ponteiro mutável
```

`revision` tem o formato `YYYYMMDDtHHMMSSz` (UTC) — ex.: `20260924t181131z`.
Restrições: `version >= 0`, `ente` deve casar `^[a-z][a-z0-9-]*$`.

**Release imutável** (`...-{revision}`): nunca é sobrescrita nem reaproveitada — cada
publicação agendada cria um item novo. É o identifier a citar para reprodutibilidade;
`dataset_meta.json` registra `git_sha`, hash do Parquet e contagem de linhas dessa
publicação específica.

**Ponteiro `latest`** (`...-latest`): mesmo `versoes.parquet` + `dataset_meta.json` da
release mais recente, mais um `latest.json` pequeno apontando para o identifier
imutável em vigor (campo `identifier`). É o item que consumidores (o frontend
inclusive) devem usar por padrão para descobrir a release corrente sem hardcodar um
identifier específico — releases antigas seguem diretamente recuperáveis pelo próprio
identifier. **Nunca citar este item para reprodutibilidade**: seu conteúdo muda a cada
publicação.

Publicar o ponteiro é o comportamento padrão (`publish_latest=True`); uma falha em
publicá-lo é fail-open — não derruba a publicação do release imutável, que já é o
artefato citável.

## Arquivo publicado

- `versoes.parquet` — tabela `leis` exportada via DuckDB native Parquet (SNAPPY)
- `dataset_meta.json` — metadados de rastreabilidade
- `latest.json` — só no item `-latest`; aponta para o identifier imutável em vigor

## `dataset_meta.json`

```json
{
  "leizilla_meta_version": "0.1",
  "schema_version": "0.1",
  "ente": "ro",
  "version": 1,
  "revision": "20260624t120000z",
  "table": "versoes",
  "generated_at": "2026-06-25T00:00:00Z",
  "row_count": 1234,
  "file_size_bytes": 567890,
  "hash_parquet": "sha256:abc..."
}
```

## `latest.json` (só no ponteiro `-latest`)

```json
{
  "identifier": "leizilla-dataset-ro-v1-20260624t120000z",
  "ia_url": "https://archive.org/details/leizilla-dataset-ro-v1-20260624t120000z",
  "parquet_url": "https://archive.org/download/leizilla-dataset-ro-v1-20260624t120000z/versoes.parquet",
  "revision": "20260624t120000z",
  "generated_at": "2026-06-25T00:00:00Z",
  "git_sha": "abc123...",
  "row_count": 1234,
  "hash_parquet": "sha256:abc..."
}
```

## Metadados no IA

| Campo | Valor |
|---|---|
| `mediatype` | `data` |
| `subject` | `leis;leizilla;{ente};parquet;versoes` (item `-latest` acrescenta `;latest`) |
| `creator` | `leizilla-etl` |
