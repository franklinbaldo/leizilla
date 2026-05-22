# ADR-0008 — Robots.txt e Rate Limiting

**Status**: Aprovada  
**Data**: 2026-05-21  
**Contexto**: M0.3 (principio load-bearing #10); registrado formalmente em M1

## Decisão

O crawler respeita `robots.txt` e limita taxa de requisições:

1. **Robots.txt**: rejeição é **permanente** para aquela URL. Sem retry, sem
   fallback direto para URL rejeitada. Registra `robots_rejected: true` em
   `raw_meta.json`.

2. **Rate limiting**: baseline de **1 requisição/segundo por host** no fallback
   direto (quando Wayback não está disponível). O bot do Wayback Machine (ADR-0004)
   já atua como buffer — bates diretas só no fail-open.

## Justificativa

Sites estaduais (Assembleia Legislativa, Casa Civil) têm infraestrutura frágil.
Um crawler irresponsável pode derrubar serviços públicos. Além do impacto prático,
há risco de bloqueio de IP e dano à reputação do projeto.

Robots.txt é contrato público: violar implica que o site não autorizou a indexação.
Dados de sites que proíbem crawling não devem entrar no dataset.

## Trade-offs aceitos

- Leis publicadas em portais que bloqueiam crawlers ficam fora do dataset.
  Isso é **correto**: se o ente não quer que sua legislação seja indexada por
  terceiros, respeitamos. (Na prática, portais gov.br raramente bloqueiam.)
- Rate limit de 1 req/s é conservador e pode ser relaxado por ente se auditoria
  confirmar que o portal suporta mais carga.

## Implementação

M2 — `src/leizilla/crawler.py` verifica `robots.txt` antes de qualquer fetch
direto. `urllib.robotparser.RobotFileParser` ou similar.

Cadência de auditoria de fontes (re-scrape, nova fonte): demand-driven por
enquanto; formalizar como trimestral em M2 quando tivermos dados reais.
