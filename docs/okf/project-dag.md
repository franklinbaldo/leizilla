---
type: "Project Map"
title: "Leizilla Project DAG"
description: "Canonical OKF graph of Leizilla delivery fronts, OKRs, dependencies, blockers and next actions. Work branches and GitHub issues execute the graph; they are not the durable project ledger."
tags: [leizilla, okf, project-dag, okr, delivery, governance]
timestamp: 2026-09-24T19:45:00-04:00
state_model: "project-dag-v1"
graph_policy:
  source_of_truth: "this authored Markdown/OKF document"
  model: "Git-like conceptual DAG committed to main; branches and PRs are implementation workspaces, issues are executable slices, and this graph is the durable state ledger"
  registration_gate: "Every materially new delivery/research front that can change priorities, dependencies or OKRs MUST be registered as a node before substantive execution."
  continuation_gate: "An autonomous session MUST resolve the relevant live node(s) here before choosing work."
  portfolio_rule: "When possible, each autonomous session advances 2-4 compatible live leaf nodes spanning at least two top-level workstreams; do not stop after the first completed issue if other safe, independent progress remains."
  fork_rule: "When one front splits into materially different outcomes or workstreams, create child nodes with parents=[parent_id] and state fork_reason."
  merge_rule: "When multiple fronts must converge into one deliverable, create a node with multiple parents rather than duplicating state."
  closure_rule: "Never silently drop a node. Mark it completed, narrowed, blocked, absorbed, superseded or abandoned with rationale and evidence."
  issue_rule: "Issues hold bounded executable slices and acceptance criteria. They may open/close/reorder without becoming the project source of truth."
  pr_rule: "PRs are disposable implementation workspaces and never durable blocker/state ledgers."
  okr_rule: "Objectives describe outcomes; key results must be measurable, carry a current state, and point to evidence or a next action. Do not replace KRs with task lists."
  derived_fields: "children, roots, leaves, live-front counts, blocked-front counts and lineage paths are derived and are not authored redundantly."
required_fields: [id, kind, status, objective, origin, next_action]
known_statuses: [open, active, blocked, narrowed, completed, absorbed, superseded, abandoned]
known_kinds: [root, objective, workstream, gate, research]
known_kr_statuses: [open, active, blocked, met, missed]
fronts:
  - id: "leizilla-root"
    kind: root
    status: active
    parents: []
    objective: "Make public legislation from Rondônia searchable, structured, preserved, current and auditable, while keeping the architecture static and infrastructure-minimal."
    origin: "Project mission and Q3/2026 go-live."
    next_action: "Advance live child fronts; never implement directly at the root."

  - id: "ro-coverage-q4-2026"
    kind: objective
    status: active
    parents: [leizilla-root]
    objective: "Turn the Q4/2026 roadmap promise of more complete Rondônia coverage into a measurable, recurring delivery outcome."
    origin: "README roadmap: Q4/2026 = cobertura RO mais completa + releases recorrentes."
    next_action: "Grow S4 from the measured baseline and make scheduled work bounded/resumable."
    key_results:
      - id: "kr-ro-s1-s4-observable"
        status: active
        metric: "Canonical stages exposed: S1 archived, S2 identified, S3 text, S4 structured."
        current: "Production baseline measured: casacivil S1=1196, S2=1196, S3=540, S4=20; publication code is merged, with first post-merge coverage.json observation still pending."
        target: "4/4 stages publicly observable with timestamp/provenance and source/type breakdown."
        issues: [174]
        next_action: "Verify the next coverage.json on the -latest item and /cobertura/ against the same counters."
      - id: "kr-ro-backlog-conversion"
        status: active
        metric: "S1 records reaching S4 and reduction of the initial pre-S4 backlog."
        current: "20/1196 = 1.67% at S4; initial backlog is 1176."
        target: "Reduce the initial backlog by at least 50% by 2026-12-31; with S1 frozen at 1196 this means S4 >= 608."
        next_action: "Track and reduce the S2->S3 gap (656) and S3->S4 gap (520) by source/type."
      - id: "kr-ro-recurring-cycle-health"
        status: active
        metric: "Consecutive scheduled coverage cycles without unresolved systemic failure."
        current: "parse-release: 10 consecutive successes; legacy casacivil crawl: 0/10; discover-harvest: 7/10; Wayback Save: 8/10."
        target: "2 consecutive complete scheduled cycles with no unresolved systemic failure."
        issues: [136, 140, 141, 149]
        next_action: "Use bounded/checkpointed batches, then observe two complete scheduled cycles."

  - id: "coverage-observability"
    kind: workstream
    status: active
    parents: [ro-coverage-q4-2026]
    objective: "Make the coverage frontier itself a first-class, reproducible public artifact."
    origin: "PRD §10.4 and issue #174."
    issues: [174]
    next_action: "Verify the first post-merge public coverage.json and /cobertura/ result, then close this workstream."

  - id: "ingestion-resilience"
    kind: workstream
    status: active
    parents: [ro-coverage-q4-2026]
    objective: "Prevent transient failures or oversized jobs from becoming silent coverage loss."
    origin: "Production incidents; retry/requeue semantics from #121 are complete."
    issues: [136, 140, 141, 149]
    next_action: "Bound work per run and persist progress so volume does not grow past fixed job budgets."

  - id: "pipeline-convergence"
    kind: workstream
    status: active
    parents: [ro-coverage-q4-2026, ingestion-resilience]
    objective: "Converge legacy scrape and manifest-driven discover->harvest without regressing coverage."
    origin: "RFC-0003; Fase 1 including #176 is complete."
    issues: [95, 136, 140, 141, 149]
    evidence_prs: [173]
    next_action: "Implement Fase 2 with bounded/resumable work, then redirect legacy lanes only after equivalent coverage and two clean weekly cycles."

  - id: "dataset-release-integrity"
    kind: workstream
    status: completed
    parents: [ro-coverage-q4-2026]
    objective: "Make releases independently citable while preserving a latest pointer."
    origin: "Issue #175."
    issues: [175]
    next_action: "Completed: immutable revision releases and a mutable -latest pointer are implemented; monitor for regression."

  - id: "legal-semantic-integrity"
    kind: objective
    status: active
    parents: [leizilla-root]
    objective: "Keep legal provenance, temporal status and identity semantics within the evidence."
    origin: "Post-go-live schema/ETL review."
    next_action: "Finish release-boundary validation, generic URN descriptor compatibility and remaining public date reconciliation."
    key_results:
      - id: "kr-date-provenance-honest"
        status: active
        metric: "Known code/docs/public locations that conflate date-of-act with publication evidence."
        current: "Runtime schema/ETL/downloads use data_ato and #129/#157 are closed; PRD text and #167 still need final reconciliation."
        target: "0 known conflations."
        issues: [129, 157, 167]
        evidence_prs: [170]
        next_action: "Land the documentation reconciliation and verify the deployed Dados route."
      - id: "kr-temporal-version-valid"
        status: met
        metric: "Known code paths that can emit overlapping current versions from incomplete/out-of-order dates."
        current: "Issue #120 is closed with regression coverage for ordering and unresolved timelines."
        target: "0 known overlapping-current states caused by missing/out-of-order dates."
        issues: [120]
        next_action: "Maintain the regression gate."
      - id: "kr-identifier-contract-consistent"
        status: active
        metric: "Producer-number and generic URN descriptor contracts remain explicit and compatible."
        current: "#127/#191 fixed produced numbers such as 72-A, but generic URN descriptors documented in SCHEMA §5.6 need compatibility restored."
        target: "Parser, ETL, XSD, checker and tests agree at both producer and generic URN boundaries."
        issues: [127]
        next_action: "Restore generic descriptor forms such as lex-16 and estatuto.idoso without relaxing the producer-side number contract."
      - id: "kr-release-validation-gated"
        status: active
        metric: "Declared ETL/release boundary gates enforced before publication."
        current: "Row floor is merged via #193; #192 is green for XSD-before-consolidate and non-empty provenance; URN export-boundary validation remains."
        target: "All declared floor/schema/provenance/identity checks enforced with diagnostics."
        issues: [118]
        evidence_prs: [192, 193]
        next_action: "Finish #192 and the narrow URN export-boundary validation slice."

  - id: "date-provenance"
    kind: workstream
    status: active
    parents: [legal-semantic-integrity]
    objective: "Separate date-of-act, publication evidence and vigência provenance throughout schema, ETL, docs and UI."
    origin: "Issues #129/#157/#167."
    issues: [129, 157, 167]
    evidence_prs: [170]
    next_action: "Reconcile stale PRD/naming text, verify the deployed route, then resolve #167."

  - id: "temporal-version-integrity"
    kind: workstream
    status: completed
    parents: [legal-semantic-integrity]
    objective: "Guarantee deterministic non-overlapping version intervals."
    origin: "Issue #120."
    issues: [120]
    next_action: "Completed; maintain regression coverage."

  - id: "identifier-integrity"
    kind: workstream
    status: active
    parents: [legal-semantic-integrity]
    objective: "Use a strict produced legal-number contract without narrowing valid generic URN descriptors."
    origin: "Issue #127/#191 and SCHEMA §5.6."
    issues: [127]
    next_action: "Restore generic URN descriptor grammar in ETL/XSD/checker and gate 72-a, lex-16 and estatuto.idoso."

  - id: "release-boundary-validation"
    kind: gate
    status: active
    parents: [legal-semantic-integrity, dataset-release-integrity]
    objective: "Reject datasets that violate declared release contracts before publication."
    origin: "Issue #118."
    issues: [118]
    evidence_prs: [192, 193]
    next_action: "Finish green #192 and the remaining URN validation requirement."

  - id: "public-surface-auditability"
    kind: objective
    status: active
    parents: [leizilla-root, legal-semantic-integrity]
    objective: "Keep the public portal legible, responsive and semantically faithful to the dataset."
    origin: "Public-product reviews after M13."
    issues: [102, 159, 167]
    next_action: "Verify deployed date semantics; responsive and core model regression gates are already evidenced."
    key_results:
      - id: "kr-public-semantic-legibility"
        status: active
        metric: "Known public labels/download affordances that overstate available evidence."
        current: "Source exports data_ato and distinguishes explicit publication semantics; the deployed route still needs verification for #167."
        target: "0 known misleading labels in the deployed public surface."
        issues: [167]
        next_action: "Audit the deployed Dados route with the real dataset and resolve #167 from observed behavior."
      - id: "kr-public-responsive-audit"
        status: met
        metric: "Declared critical routes passing desktop + narrow viewport audit."
        current: "Issue #159 is closed with reproducible visual evidence."
        target: "All declared critical routes pass the canonical audit."
        issues: [159]
        next_action: "Maintain the visual gate."
      - id: "kr-law-page-regression-tests"
        status: met
        metric: "Core law-page modeling/formatting behaviors covered by deterministic tests."
        current: "Issue #102 is closed; core modeling/formatting branches are covered. PR #194 adds extra DOM-side-effect coverage."
        target: "All critical model/format branches identified in #102 covered."
        issues: [102]
        next_action: "Maintain the web test gate; #194 is additional hardening, not a blocker."

  - id: "opf-structural-parser-rnd"
    kind: research
    status: blocked
    parents: [leizilla-root, ro-coverage-q4-2026]
    objective: "Evaluate OPF structural span tagging as an optional, evidence-based parser aid without displacing the production LLM pipeline prematurely."
    origin: "ADR-0012 / M14; gold v1 exists, while the next training step needs suitable GPU execution and broader representative RO data."
    next_action: "Do not spend routine CPU work on training. Accumulate representative multi-source gold as coverage grows and run the frozen notebook on an adequate GPU executor when available; record results without promoting it into production by default."
    blockers:
      - "M14.3 requires an adequate GPU executor."
      - "A stronger production claim requires noisier/multi-source RO evidence beyond the current small gold."

  - id: "m5-3-search-scaling"
    kind: workstream
    status: blocked
    parents: [public-surface-auditability, ro-coverage-q4-2026]
    objective: "Introduce heavier in-browser indexing/search only when the published dataset demonstrates a real performance need."
    origin: "M5.3 benchmark gate."
    next_action: "Keep blocked until the real browser benchmark reaches the declared trigger (for example >1s P95/search) or dataset scale crosses the documented threshold; then benchmark before choosing FTS/index architecture."
    blockers:
      - "Current dataset is too small for a meaningful scaling decision."

  - id: "federal-expansion-q1-2027"
    kind: objective
    status: blocked
    parents: [leizilla-root, dataset-release-integrity, legal-semantic-integrity]
    objective: "Expand the proven static/preserved pipeline to federal Planalto legislation in Q1/2027 without exporting unresolved RO semantic/release debt."
    origin: "README roadmap Q1/2027."
    next_action: "Maintain Planalto pipeline readiness, but do not start broad federal ingestion until release integrity and the core semantic contracts are stable."
    blockers: [118, 167]
---

# Leizilla Project DAG

Este documento é o ledger operacional autorado do projeto. O grafo no frontmatter é
canônico; a seção textual existe apenas para explicar como usá-lo.

## Como uma sessão escolhe trabalho

1. Leia este DAG e derive raízes, folhas, frentes vivas e bloqueadas.
2. Reconcilie PRs/issues abertas com os nós correspondentes.
3. Escolha, quando possível, um portfólio de 2–4 folhas vivas em pelo menos dois
   workstreams de alto nível. Trabalho pode ser paralelo na sessão, mas cada PR deve
   continuar pequena/coerente.
4. Prefira desbloquear KRs, corrigir falhas sistêmicas e terminar PRs já verdes antes
   de criar trabalho novo.
5. Atualize o estado do DAG quando evidência real mudar status, blockers, KRs ou
   `next_action`. Não use o prompt de automação como memória transitória.

## Relação com GitHub

- **DAG**: estado durável, dependências, objetivos, KRs, blockers e próxima ação.
- **Issue**: fatia executável com critério de pronto.
- **PR/branch**: workspace descartável para implementar a fatia.
- **IMPLEMENTATION.md**: ledger de milestones/decisões já materializadas e histórico.
- **README roadmap**: horizonte temporal público; não substitui o DAG executável.

## Validação

```bash
uv run scripts/validate_project_dag_hygiene.py
uv run scripts/project_dag_from_okf.py
uv run scripts/project_dag_from_okf.py --json
```

Os validadores rejeitam IDs duplicados, pais desconhecidos, ciclos, status inválidos,
nós vivos sem `next_action` e KRs vivos sem próxima ação.
