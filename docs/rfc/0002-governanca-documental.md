# RFC-0002: Governança documental — hierarquia de fontes de verdade

**Status**: aceito — implementado parcialmente no PR desta RFC
**Data**: 2026-07-07
**Relacionados**: RFC-0001 (supersedido pelo OKF), `docs/audit-divergencias.md` (2026-06-30), PRD v2.0-reconciliado

## Problema

O projeto acumulou **seis documentos que competem como fonte de verdade**, e eles se
contradizem em fatos verificáveis:

1. **`README.md`** afirma que o MVP Rondônia (Q3/2025) está "✅ Implementado" e que o
   frontend é "📋 Planejado" — ambos falsos: nenhum dataset foi publicado no IA
   (M5.3 segue bloqueado por isso), e o frontend M5.1/M5.2 está pronto desde 05/2026.
2. **`CLAUDE.md`** mantém o roadmap Q3/2025–Q2/2026 original (todo vencido) e documenta
   `manifests/` na raiz do repositório, quando o diretório real é
   `src/leizilla/manifests/`.
3. **`docs/plans/MASTERPLAN.md`** declara "Current Phase: Pre-MVP … The repository is in
   its early stages, primarily containing documentation" — descrição de 2025, hoje
   absurda (21 módulos, ~660 testes, 9 workflows).
4. **`MANAGER-INTEL.md`** (raiz) é um snapshot gerado para sessões "Jules" com
   placeholders de rate-limit da API do GitHub; nunca foi atualizado.
5. **`IMPLEMENTATION.md`** tem cabeçalho de status correto, mas a cauda ("Como rodar
   localmente", "Próximos passos imediatos") usa a sintaxe antiga da CLI
   (`consolidate --ente ro`, `release-dataset --ente ro --version 1`, `uv sync --dev`)
   — exatamente as formas que a auditoria de 2026-06-30 corrigiu em `docs/okf/`.
6. **RFC-0001** aponta `docs/okf/` como "fonte de verdade", enquanto a auditoria de
   divergências usa o **PRD** como referência canônica. As duas afirmações coexistem
   sem hierarquia declarada.

O custo é concreto: a auditoria de 30/06 gastou uma sessão inteira reconciliando docs,
e uma semana depois o repositório ainda contém três roadmaps mutuamente inconsistentes.
Sem uma hierarquia explícita, cada sessão automática (claude-routine roda 2×/semana)
pode "corrigir" um documento usando outro desatualizado como referência.

## Decisão

### Hierarquia de fontes de verdade (da mais alta para a mais baixa)

| Nível | Documento | Responde a | Em conflito, cede para |
|---|---|---|---|
| 1 | `docs/PRD.md` | o quê e por quê (produto) | — |
| 2 | `docs/adr/` | decisões arquiteturais pontuais | PRD |
| 3 | `docs/SCHEMA.md` | modelo de dados canônico | ADRs |
| 4 | `docs/okf/` | referência operacional (comandos, pipeline, naming) | SCHEMA/ADRs |
| 5 | `IMPLEMENTATION.md` | status de milestones + log cronológico | todos acima |
| 6 | `CLAUDE.md`, `README.md` | onboarding (agentes / humanos) — **derivados**, nunca originais | todos acima |

Regras:

- **Roadmap vive em um único lugar**: seção de roadmap do `README.md`, re-baselineada
  pela RFC-0004. `CLAUDE.md` aponta para ela em vez de duplicá-la.
- **Documento de planejamento supersedido vai para `docs/archive/`** com banner de
  supersessão no topo (mesmo padrão do RFC-0001). Nunca deletar — o histórico é
  parte da transparência radical do projeto.
- **Snapshot gerado por ferramenta** (ex.: MANAGER-INTEL.md) não vive na raiz; se for
  regenerado, vive em `docs/archive/` ou fora do repo.
- **Status não se duplica**: continua valendo a regra do CLAUDE.md — status de
  milestone só em `IMPLEMENTATION.md`.

### Ações (implementadas no PR desta RFC)

1. Mover `docs/plans/MASTERPLAN.md` → `docs/archive/MASTERPLAN.md` com banner
   "supersedido pelo PRD v2".
2. Mover `MANAGER-INTEL.md` → `docs/archive/MANAGER-INTEL.md` com banner de snapshot
   histórico.
3. Corrigir `CLAUDE.md`: caminho `src/leizilla/manifests/`, roadmap substituído por
   ponteiro para o README.
4. Corrigir tabela de roadmap do `README.md` para refletir a realidade (ver RFC-0004).
5. Atualizar a cauda de `IMPLEMENTATION.md` (seções "Como rodar localmente" e
   "Próximos passos imediatos") para a sintaxe atual da CLI e o estado real.

## Alternativas consideradas

- **Consolidar tudo num documento único**: rejeitado — PRD, ADRs e OKF têm públicos e
  cadências de mudança diferentes; o problema não é a quantidade de docs, é a ausência
  de hierarquia.
- **Deletar os docs obsoletos**: rejeitado — viola a transparência radical e apaga o
  histórico de decisões que o IMPLEMENTATION.md referencia.
