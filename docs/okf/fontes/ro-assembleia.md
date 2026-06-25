---
type: Fonte
title: assembleia (RO)
description: Portal da Assembleia Legislativa de Rondônia — leis numeradas por coddoc.
resource: https://www.al.ro.leg.br
tags: [fonte, rondonia, assembleia]
timestamp: 2026-06-25T00:00:00Z
---

## URL pattern

```
https://www.al.ro.leg.br/legislacao/leis/{coddoc}
```

## Características

- Identificação por `coddoc` (código interno do sistema, não o número da lei)
- Portal com JavaScript — requer Playwright para crawling
- Todos os recursos tipados como `lei` com chave `coddoc-{N:05d}`
- Range: 1–5000

## Estratégia de discovery

`playwright-crawler` — delega ao `LeisCrawler(crawler_type="playwright")`.

Não usa `head_check` — o Playwright navega diretamente em cada URL.

## Mapeamento coddoc → número de lei

O coddoc não é o número oficial da lei. O mapeamento é extraído pelo Playwright da página HTML durante o crawl.

# Citations

[1] [Estratégias de discovery](../discovery/strategies.md)
[2] [manifests/ro.json](/src/leizilla/manifests/ro.json)
