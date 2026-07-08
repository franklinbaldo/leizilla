# RFC-0003: Convergência de pipeline — uma única geração (discover→harvest)

**Status**: proposto — **não implementado neste PR** (aguarda merge de #93 e #94, que
tocam os mesmos arquivos)
**Data**: 2026-07-07
**Relacionados**: ADR-0010, ADR-0011, PR #94 ("o sistema atual ainda carrega duas
gerações de pipeline"), M10.A (discovery manifest-driven)

## Problema

O repositório mantém **duas gerações de pipeline de captura em produção simultânea**:

| | Geração 1 (legada) | Geração 2 (atual) |
|---|---|---|
| Comando | `scrape --fonte X --tipo Y --start N --end M` | `discover` + `harvest` |
| Descoberta | range sequencial hardcoded por flag/workflow | manifesto (`src/leizilla/manifests/{ente}.json`) |
| Estado | nenhum (stateless, por range) | fila `discovered_resources` no DuckDB |
| Idempotência | `--skip-existing` (consulta IA por prefixo) | `status='pending'` na fila |
| Workflow | `rondonia_crawler.yml` (dom 00:00 UTC) | `discover-harvest.yml` (sáb 02:00 UTC) |

As duas rodam toda semana sobre as mesmas fontes. Consequências:

1. **Dois modelos de idempotência** que não se enxergam: o harvest não sabe o que o
   scrape subiu (só via IA), e vice-versa. Upload no IA é idempotente, então não há
   corrupção — mas há trabalho duplicado e dois caminhos de código para todo bug de
   captura (o fix do PR #93, fallback quando Wayback devolve HTML, precisou considerar
   os dois fluxos).
2. **Dois vocabulários na CLI e nos workflows**: ranges por input de workflow
   (`casacivil_lei_start/end`) vs ranges no manifesto. O PR #94 já começou a erodir a
   distinção (scrape com `--start/--end` opcionais descobertos via CDX) — ou seja, o
   scrape está sendo reinventado como um harvest.
3. **Custo cognitivo para novas fontes**: quem adiciona um ente precisa decidir em qual
   geração implementá-lo, e a resposta hoje depende de qual doc leu primeiro.

## Proposta

**`discover→harvest` é o caminho canônico. `scrape` é absorvido e deprecado em 3 fases.**

### Fase 1 — capacidade (pós-merge de #93/#94)

- Portar para as estratégias de discovery o que só o scrape tem hoje:
  - descoberta de `cdx_max` via Wayback CDX (do #94) vira parte da
    `WaybackCdxDiscovery`/`SequentialDiscovery` (limite dinâmico do range no manifesto,
    ex.: `"end": "cdx-auto"`);
  - fallback HTML→direct-download do #93 já vive no scraper compartilhado — garantir
    teste cobrindo o caminho harvest.
- `harvest` ganha paridade de relatório com o scrape (`OK: <ia_id> → URL`, contadores).

### Fase 2 — redirecionamento

- `rondonia_crawler.yml` passa a chamar `discover --ente ro` + `harvest --ente ro`
  (um único workflow semanal; `discover-harvest.yml` é absorvido/removido).
- `cmd_scrape` vira wrapper fino: traduz flags para uma entrada de manifesto efêmera e
  enfileira + processa — um só código de captura por baixo.
- `pipeline` (discover→harvest→export) vira o comando demonstrado no README.

### Fase 3 — deprecação

- `scrape` emite aviso de deprecação apontando para `discover`/`harvest`; docs OKF
  (`docs/okf/pipeline/scrape.md`) anotadas.
- Remoção só depois de duas execuções semanais completas sem regressão de cobertura
  (comparar contagens `leizilla stats --ia` antes/depois).

### Critérios de aceitação

- Uma nova fonte é adicionada tocando **apenas** `manifests/{ente}.json` (+ módulo em
  `fontes/` quando precisar de parsing específico) — zero mudanças em workflow.
- Um único workflow de captura semanal por ente.
- Nenhum item capturado a menos: `stats --ia` por fonte não regride na transição.

## Por que não neste PR

As PRs #93 e #94 (abertas, do mesmo autor) modificam `scraper.py`, `wayback.py`,
`cli.py` e o manifesto de RO — exatamente a superfície desta RFC. Implementar agora
criaria conflito de merge triplo. Ordem correta: mergear #93 → #94 → implementar a
Fase 1 desta RFC por cima.

## Alternativas consideradas

- **Manter as duas gerações documentadas como "aditivas"** (decisão de M10.2):
  rejeitado agora — era razoável quando o harvest era novo; após a produção real de
  06/2026 (PRs #93/#94) ficou claro que todo fix precisa ser feito duas vezes.
- **Deprecar o harvest e ficar com o scrape**: rejeitado — o scrape não tem fila nem
  estado; reprocessamento seletivo (ex.: re-tentar `not-pdf`) já exige a fila do
  harvest, e o ADR-0011 (reconciliação de não-identificados) depende dela.
