---
type: Visao Geral
title: Leizilla Knowledge Bundle
description: Conhecimento operacional do pipeline Leizilla — regras, convenções e contratos entre módulos.
okf_version: "0.1"
tags: [leizilla, pipeline, arquitetura]
timestamp: 2026-06-25T00:00:00Z
---

Bundle de conhecimento do Leizilla. Cada arquivo descreve um conceito operacional.

## Pipeline

- [Visão geral do pipeline](pipeline/overview.md) — 6 etapas, entradas e saídas
- [Discover](pipeline/discover.md) — estratégias de descoberta de URLs
- [Scrape](pipeline/scrape.md) — download + upload raw para o IA
- [Parse](pipeline/parse.md) — OCR → LLM → Leizilla XML
- [Consolidate](pipeline/consolidate.md) — IA → DuckDB local
- [Release Dataset](pipeline/release-dataset.md) — DuckDB → Parquet no IA

## Storage

- [Internet Archive](storage/internet-archive.md) — pilar central de armazenamento
- [Range Buckets](storage/range-buckets.md) — agrupamento de PDFs em lotes de 1000
- [DuckDB local](storage/duckdb.md) — staging local; não é source of truth

## Convenções de Nomeação

- [Identificadores IA](naming/identifiers.md) — lógico vs. físico, padrões por tipo
- [Chaves de documento](naming/chaves.md) — mapeamento prefixo → tipo + chave
- [Resolução de URL](naming/url-resolution.md) — lookup de hash em 3 níveis

## Discovery

- [Estratégias](discovery/strategies.md) — wayback-cdx, sequential, playwright-crawler
- [head_check](discovery/head-check.md) — quando usar, custo, alternativas

## LLM / Parse

- [LiteLLM](llm/litellm.md) — providers, chaves, modelo padrão
- [Contrato de parse](llm/parse-contract.md) — entrada, saída JSON, validação

## Fontes (RO)

- [casacivil](fontes/ro-casacivil.md) — portal COTEL, quirks L1–L499
- [assembleia](fontes/ro-assembleia.md) — al.ro.leg.br, Playwright

## Invariantes

- [Invariantes do sistema](invariants.md) — regras que nunca devem ser violadas
