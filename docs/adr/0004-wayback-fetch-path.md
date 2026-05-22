# ADR-0004 — Wayback Machine como caminho primário de fetch

**Status**: Aprovada  
**Data**: 2026-05-20  
**Contexto**: M1 — Foundation

## Decisão

O crawler dispara `POST /save` no Wayback Machine para `fonte_url` + `pdf_url`,
depois faz o fetch do PDF a partir do snapshot Wayback (não da fonte original),
para então fazer upload na nossa coleção Internet Archive.

## Motivação

1. **Polite com gov.br**: bate na fonte original uma única vez (via bot do Wayback).
   Sites da Assembleia Legislativa e Casa Civil de estados pequenos têm infra frágil.
2. **Testemunha independente**: timestamp Wayback funciona como prova forense
   da existência do documento naquela data — útil para auditoria jurídica.
3. **Cache gratuito**: `GET /wayback/available?url=...` reutiliza snapshots < 24h,
   evitando round-trips repetidos.

## Comportamento

- Antes de disparar save, checa `GET https://archive.org/wayback/available?url={url}`.
  Reutiliza snapshot existente se < 24h.
- Fail-open: se Wayback retorna erro/timeout, faz download direto da fonte.
  Registra `fetched_from: "source-fallback"` em `raw_meta.json.provenance_wayback`.

## Trade-offs aceitos

- Dependência de terceiro (Wayback) no caminho primário. Mitigado pelo fail-open.
- Latência adicional (save do Wayback pode demorar ~30s). Aceitável para pipeline
  não-realtime.

## Implementação

M2 — `src/leizilla/crawler.py` extende `download_pdf` com lógica Wayback.
`raw_meta.json` especificado em SCHEMA.md §2.1.
