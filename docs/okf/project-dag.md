---
type: "Project Map"
title: "Leizilla Project DAG"
description: "Canonical OKF graph of Leizilla delivery fronts, OKRs, dependencies, blockers and next actions. Work branches and GitHub issues execute the graph; they are not the durable project ledger."
tags: [leizilla, okf, project-dag, okr, delivery, governance]
timestamp: 2026-09-24T14:30:00-04:00
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
    next_action: "Establish the S1-S4 baseline, reduce the measured pre-S4 backlog, and restore consecutive healthy scheduled cycles."
    key_results:
      - id: "kr-ro-s1-s4-observable"
        status: active
        metric: "Number of canonical coverage stages (S1 discovered, S2 raw preserved, S3 text/OCR available, S4 structured/published) exposed machine-readably and on /cobertura/."
        current: "S4 is publicly visible; S1-S3 are not yet canonical public counters."
        target: "4/4 stages exposed with timestamp/provenance and source/type breakdown where available."
        issues: [174]
        next_action: "Implement issue #174 and record the first real baseline."
      - id: "kr-ro-backlog-conversion"
        status: blocked
        metric: "Share of the reproducibly measured S1/S2/S3 backlog that has reached S4."
        current: "Unknown until the first S1-S4 census exists."
        target: "Reduce the first measured pre-S4 backlog by at least 50% by 2026-12-31 without relaxing provenance/quality gates."
        blockers: [174]
        next_action: "After #174 produces a baseline, freeze the denominator semantics and start tracking conversion per source/type."
      - id: "kr-ro-recurring-cycle-health"
        status: active
        metric: "Consecutive scheduled discover/harvest/parse/release cycles without an unresolved systemic failure."
        current: "Recent failure trackers remain open for crawl, discover/harvest, parse/release and Wayback-save paths."
        target: "2 consecutive complete scheduled cycles with no unresolved systemic failure and with per-source results visible."
        issues: [114, 136, 140, 141, 149]
        next_action: "Triage the current workflow failures, distinguish stale/transient incidents from live defects, and close or repair them with evidence."

  - id: "coverage-observability"
    kind: workstream
    status: active
    parents: [ro-coverage-q4-2026]
    objective: "Make the coverage frontier itself a first-class, reproducible public artifact."
    origin: "PRD §10.4 requires exposing archived/text/structured coverage; current public surface mainly exposes S4."
    issues: [174]
    next_action: "Implement S1-S4 aggregation, machine-readable output and /cobertura/ presentation; record the first baseline as evidence."

  - id: "ingestion-resilience"
    kind: workstream
    status: active
    parents: [ro-coverage-q4-2026]
    objective: "Prevent transient network, robots, quota or workflow failures from becoming silent permanent document loss."
    origin: "Production crawl/harvest failures and issue #121."
    issues: [121, 136, 140, 141, 149]
    next_action: "Classify terminal vs retryable states end-to-end, fix retry/requeue semantics, then re-run affected scheduled lanes and close stale incident issues with evidence."

  - id: "pipeline-convergence"
    kind: workstream
    status: active
    parents: [ro-coverage-q4-2026, ingestion-resilience]
    objective: "Converge the legacy scrape path and manifest-driven discover→harvest path without regressing coverage or observability."
    origin: "RFC-0003; production fixes #93/#94 removed the original blocker."
    issues: [176]
    evidence_prs: [173]
    next_action: "Finish RFC-0003 Fase 1 by implementing #176 (cdx-auto in discovery); only then plan workflow redirection, and defer deprecation until two clean weekly cycles."

  - id: "dataset-release-integrity"
    kind: workstream
    status: active
    parents: [ro-coverage-q4-2026]
    objective: "Make every published dataset release independently citable and reproducible while preserving a convenient latest pointer for the portal."
    origin: "Verified risk from #151: scheduled releases default to --version 0 while the frontend points at leizilla-dataset-ro-v0."
    issues: [175]
    next_action: "Implement immutable release identifiers plus a small latest pointer; migrate frontend/docs without introducing an application backend."

  - id: "legal-semantic-integrity"
    kind: objective
    status: active
    parents: [leizilla-root]
    objective: "Ensure the structured dataset never states stronger legal provenance, temporal status or identity semantics than the underlying evidence supports."
    origin: "Post-go-live schema/ETL review found date, temporal and identifier conflation risks."
    next_action: "Close the date-provenance line first, then temporal-version and identifier consistency, while strengthening release-boundary validation."
    key_results:
      - id: "kr-date-provenance-honest"
        status: active
        metric: "Canonical schema/ETL/UI locations that conflate date-of-act with publication evidence."
        current: "Known conflation remains in vigência semantics and legacy public download labels."
        target: "0 known conflations; explicit publication provenance remains distinct from date-of-act fallback."
        issues: [157, 167]
        evidence_prs: [170]
        next_action: "Finish PR #170 against current main, reconcile SCHEMA/IMPLEMENTATION/checker, run final gates, then update the public surface."
      - id: "kr-temporal-version-valid"
        status: open
        metric: "Known code paths that can emit overlapping 'vigente' versions from null/out-of-order dates."
        current: "Issue #120 is open."
        target: "0 known overlapping-current states caused by missing/out-of-order dates; regression coverage present."
        issues: [120]
        next_action: "Reproduce #120 with a minimal fixture, define fail-closed temporal ordering semantics, and implement the regression test before the fix."
      - id: "kr-identifier-contract-consistent"
        status: open
        metric: "Parser/ETL/URN disagreements over accepted legal number formats."
        current: "Issue #127 is open for suffix/conflation risk."
        target: "One canonical accepted format across parser, ETL, URN and tests."
        issues: [127]
        next_action: "Resolve #127 with an explicit contract and round-trip tests."
      - id: "kr-release-validation-gated"
        status: open
        metric: "Build/release boundaries that publish without the declared schema/quality floor checks."
        current: "Issue #118 is open."
        target: "All ETL-build and release boundaries fail closed on declared floor violations and emit actionable diagnostics."
        issues: [118]
        next_action: "Implement #118 after current schema semantics are reconciled, so gates enforce the right contract."

  - id: "date-provenance"
    kind: workstream
    status: active
    parents: [legal-semantic-integrity]
    objective: "Separate date-of-act, publication evidence and vigência provenance throughout schema, ETL, fixtures and UI."
    origin: "Issues #129/#157 and follow-up public-surface issue #167."
    issues: [157, 167]
    evidence_prs: [170]
    next_action: "Bring PR #170 to current main, complete its documented remaining reconciliation and gates, then make the public download semantics match the published dataset."

  - id: "temporal-version-integrity"
    kind: workstream
    status: open
    parents: [legal-semantic-integrity]
    objective: "Guarantee deterministic non-overlapping version intervals even when source dates are incomplete or out of order."
    origin: "Issue #120."
    issues: [120]
    next_action: "Add a failing regression fixture for #120, define the temporal ordering fallback explicitly, then fix ETL behavior."

  - id: "identifier-integrity"
    kind: workstream
    status: open
    parents: [legal-semantic-integrity]
    objective: "Use one canonical legal-number identity contract from parse through URN and release."
    origin: "Issue #127."
    issues: [127]
    next_action: "Decide the suffix grammar from real source evidence, implement it once, and add round-trip tests."

  - id: "release-boundary-validation"
    kind: gate
    status: open
    parents: [legal-semantic-integrity, dataset-release-integrity]
    objective: "Fail closed before publishing datasets that violate schema, identity, temporal or quality-floor contracts."
    origin: "Issue #118 and post-go-live audit findings."
    issues: [118]
    next_action: "After the live schema semantics settle, wire explicit ETL/release gates and regression tests into the production release path."

  - id: "public-surface-auditability"
    kind: objective
    status: active
    parents: [leizilla-root, legal-semantic-integrity]
    objective: "Make the public portal legible and auditable on desktop and narrow viewports, with evidence/provenance semantics matching the dataset."
    origin: "Public-product reviews after M13."
    issues: [102, 159, 167]
    next_action: "Close semantic labeling dependencies from date-provenance, then execute responsive/auditability regression work in #159 and model/format tests in #102."
    key_results:
      - id: "kr-public-semantic-legibility"
        status: blocked
        metric: "Known public labels/download affordances that imply stronger publication/vigência evidence than the dataset supports."
        current: "Issue #167 remains open and depends on the canonical schema migration."
        target: "0 known misleading labels; legacy fields are explained where still published."
        blockers: [157]
        issues: [167]
        next_action: "Unblock by completing date-provenance, then verify the published route with the real dataset."
      - id: "kr-public-responsive-audit"
        status: active
        metric: "Declared public routes passing the project's desktop + narrow viewport audit."
        current: "Issue #159 remains open."
        target: "All declared critical routes pass the canonical audit with preserved screenshots/evidence."
        issues: [159]
        next_action: "Run the canonical surface audit on the currently published site, fix reproducible defects, and preserve evidence."
      - id: "kr-law-page-regression-tests"
        status: open
        metric: "Core law-page modeling/formatting behaviors covered by deterministic tests."
        current: "Issue #102 remains open."
        target: "All critical model/format branches identified in #102 covered by regression tests."
        issues: [102]
        next_action: "Implement #102 in a bounded test-focused PR."

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
    blockers: [175, 157, 118]
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
