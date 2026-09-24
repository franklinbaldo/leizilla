---
type: Etapa
title: Estratégias de discovery
description: As três estratégias de descoberta de URLs — wayback-cdx, sequential, playwright-crawler.
tags: [discovery, wayback, playwright]
timestamp: 2026-06-25T00:00:00Z
---

Cada fonte define uma lista de estratégias em `manifests/{ente}.json`. O discover executa todas em sequência.

## Estratégias disponíveis

### `wayback-cdx`

Consulta a CDX API do Wayback Machine para um prefixo de URL.

```
GET https://web.archive.org/cdx/search/cdx
  ?url={prefix}&matchType=prefix&output=json
```

Filtra: apenas `.pdf` + status HTTP `200`. Timeout: 90s.

Cada resultado tem um `wayback_snapshot` URL já disponível — o scrape pode usar diretamente sem novo fetch do Wayback.

### `sequential`

Gera URLs numericamente: `L1.pdf`, `L2.pdf`, … até o limite.

- Com `head_check: false`: URLs adicionadas sem verificar existência
- Com `head_check: true`: HEAD request antes de adicionar; aceita 200 ou 302

Pula URLs já presentes na tabela `discovered_resources` (verificação no DuckDB).

`end` aceita um inteiro fixo **ou** a string `"cdx-auto"` (RFC-0003 Fase 1). Com
`"cdx-auto"`, o limite é resolvido em `run()`: consulta a CDX API uma única vez
para o diretório do primeiro `template` e toma o maior número já arquivado para
o `tipo_documento` desse template (`resolve_cdx_max_by_tipo`, a mesma função que
`WaybackCdxDiscovery` usa internamente). Fail-safe: resposta vazia, erro de rede
ou timeout na CDX não abortam o discover — caem no `end_fallback` (default `10`,
configurável por estratégia no manifesto).

```json
{
  "strategy": "sequential",
  "templates": ["https://.../Files/L{num}.pdf"],
  "start": 1,
  "end": "cdx-auto",
  "end_fallback": 10,
  "head_check": false
}
```

### `playwright-crawler`

Crawlea portais com JavaScript via Playwright.

Usado exclusivamente para a assembleia legislativa (`al.ro.leg.br`). Todos os recursos produzidos são tipados como `lei` com chave `coddoc-{N:05d}`.

## Estrutura de recurso emitido (todas as estratégias)

```python
{
    "url": str,
    "ente": str,
    "fonte": str,
    "tipo_documento": str,
    "chave": str,           # ex: "lei-00500"
    "status": "pending",   # ou "downloaded" se já no manifest do IA
    "wayback_snapshot": Optional[str],
}
```

# Citations

[1] [head_check](head-check.md)
[2] [src/leizilla/discovery.py](/src/leizilla/discovery.py)
[3] [manifests/ro.json](/src/leizilla/manifests/ro.json)
