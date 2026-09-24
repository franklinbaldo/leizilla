# RFC-0007: Project DAG e governança por OKRs

**Status**: proposto para adoção
**Data**: 2026-09-24
**Relacionados**: RFC-0002 (governança documental), `docs/okf/project-dag.md`

## Problema

O Leizilla já tem um roadmap público, um ledger extenso em `IMPLEMENTATION.md`,
issues, PRs e rotinas automáticas. O estado, porém, fica difícil de navegar quando
várias frentes avançam em paralelo: cobertura, ingestão, schema/semântica,
frontend, release, pesquisa OPF e expansão futura têm dependências diferentes.

A rotina antiga escolhia “o primeiro item” do `IMPLEMENTATION.md`. Isso favorece
progresso serial e transforma um documento histórico grande em fila operacional.

## Referência

O repositório `franklinbaldo/papers` usa um DAG conceitual autorado em OKF:

- um único documento canônico registra nós, pais, status e próxima ação;
- forks e merges são explícitos;
- filhos, raízes, folhas e frentes vivas são derivados;
- issues/PRs não são o ledger durável;
- validadores rejeitam IDs duplicados, pais inexistentes e ciclos.

O Leizilla adota o mesmo padrão de governança, adaptado de pesquisa para produto.

## Decisão

Criar `docs/okf/project-dag.md` como **fonte de verdade do estado executável**:

- objetivos e workstreams;
- OKRs e KRs mensuráveis;
- dependências (`parents`);
- blockers;
- issues/PRs de evidência;
- `next_action`.

A separação documental passa a ser:

| Artefato | Responsabilidade |
|---|---|
| `docs/PRD.md` | missão, produto e requisitos |
| ADRs / `docs/SCHEMA.md` | decisões e contratos de arquitetura/dados |
| `docs/okf/project-dag.md` | estado vivo de objetivos, KRs, dependências, blockers e próxima ação |
| `docs/okf/**` | referência operacional do pipeline |
| `IMPLEMENTATION.md` | milestones materializados, decisões e log cronológico |
| `README.md` | roadmap público em horizontes |
| GitHub issues | fatias executáveis com critério de pronto |
| PRs/branches | workspaces descartáveis para implementação |

Isso **refina** a regra da RFC-0002 que colocava o status de milestones em
`IMPLEMENTATION.md`: milestones/histórico continuam lá; a fila/estado vivo
multi-frente passa ao DAG.

## Regra de sessão autônoma

Uma sessão deve:

1. validar e ler o DAG;
2. reconciliar PRs/issues com os nós;
3. selecionar, quando possível, **2–4 folhas vivas** em pelo menos dois
   workstreams de alto nível;
4. terminar trabalho já desbloqueado/verde antes de abrir duplicatas;
5. criar/atualizar issues quando uma folha ainda não tiver uma fatia executável;
6. atualizar KRs/status/blockers/next_action quando a evidência mudar;
7. não parar após a primeira issue se houver outras ações seguras e independentes.

A sessão não deve gravar estado transitório no prompt.

## OKRs

KRs vivem dentro dos nós `kind: objective`. Um KR precisa de:

- `id`;
- `status`;
- `metric`;
- `current`;
- `target`;
- `next_action` enquanto estiver vivo.

Task lists não substituem KRs. Um KR só muda para `met` quando há evidência
reproduzível no repositório ou nos artefatos públicos.

## Validação

Dois validadores espelham o padrão do `papers`:

```bash
uv run scripts/validate_project_dag_hygiene.py
uv run scripts/project_dag_from_okf.py
uv run scripts/project_dag_from_okf.py --json
```

O primeiro parseia o YAML autorado sem reparo e rejeita corrupção/IDs duplicados.
O segundo consome o bundle via `okf-parser`, valida semântica, pais, ciclos,
status, KRs e produz a visão derivada.

## Consequências

- progresso pode ocorrer em várias frentes sem perder dependências;
- OKRs deixam de ser texto solto e passam a ter estado verificável;
- issues podem ser fechadas/reabertas sem apagar a linhagem do objetivo;
- `IMPLEMENTATION.md` pode ficar mais histórico e menos parecido com scheduler;
- a rotina horária ganha uma política explícita de portfólio, não “uma tarefa por vez”.
