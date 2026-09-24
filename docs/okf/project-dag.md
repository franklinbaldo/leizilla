---
type: "Project Map"
title: "Leizilla Project DAG"
description: "Canonical OKF graph of Leizilla delivery fronts, OKRs, dependencies, blockers and next actions. Work branches and GitHub issues execute the graph; they are not the durable project ledger."
tags: [leizilla, okf, project-dag, okr, delivery, governance]
timestamp: 2026-09-24T17:54:20-04:00
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
    next_action: "Use the measured S1-S4 baseline to drive conversion, verify the public coverage artifact, and restore consecutive healthy scheduled cycles."
    key_results:
      - id: "kr-ro-s1-s4-observable"
        status: active
        metric: "Number of canonical coverage stages (S1 archived, S2 identified, S3 text/OCR available, S4 structured/published) exposed machine-readably and on /cobertura/."
        current: "4/4 counters are implemented by #185; real IA baseline for casacivil is S1=1196, S2=1196, S3=540, S4=20. The first production coverage.json publication has not yet been independently verified."
        target: "4/4 stages exposed with timestamp/provenance and source/type breakdown where available."
        issues: [174]
        evidence_prs: [185]
        next_action: "Verify coverage.json on the mutable latest dataset item after a real parse-release run and confirm /cobertura/ renders the same counters."
      - id: "kr-ro-backlog-conversion"
        status: active
        metric: "Share of the reproducibly measured archived S1 corpus that has reached S4, with the first S1 census frozen as the baseline denominator."
        current: "Casacivil baseline: 20/1196 archived norms at S4 = 1.67%; pre-S4 backlog = 1176. A 50% backlog reduction on this frozen baseline requires backlog <=588, i.e. S4 >=608."
        target: "Reduce the first measured pre-S4 backlog by at least 50% by 2026-12-31 without relaxing provenance/quality gates."
        issues: [174]
        evidence_prs: [185]
        next_action: "Track conversion by source/type from the frozen baseline and prioritize the measured S2→S3 gap (656) and S3→S4 gap (520) without weakening provenance or validation."
      - id: "kr-ro-recurring-cycle-health"
        status: active
        metric: "Consecutive scheduled discover/harvest/parse/release cycles without an unresolved systemic failure."
        current: "Parse/release has 10 consecutive successful scheduled runs since 2026-09-13, but crawl casacivil lanes time out structurally (#136/#140), discover-harvest has intermittent volume/rate-limit timeout (#141), and Wayback-save has intermittent volume timeout (#149)."
        target: "2 consecutive complete scheduled cycles with no unresolved systemic failure and with per-source results visible."
        issues: [121, 136, 140, 141, 149]
        next_action: "Fix retry semantics without weakening robots policy, then remove the volume-vs-timeout bottlenecks while converging scheduled work onto the manifest-driven pipeline."

  - id: "coverage-observability"
    kind: workstream
    status: active
    parents: [ro-coverage-q4-2026]
    objective: "Make the coverage frontier itself a first-class, reproducible public artifact."
    origin: "PRD §10.4 requires exposing archived/identified/text/structured coverage."
    issues: [174]
    evidence_prs: [185]
    next_action: "Verify the first production coverage.json on the latest dataset item and confirm the deployed /cobertura/ surface reads the same baseline."

  - id: "ingestion-resilience"
    kind: workstream
    status: active
    parents: [ro-coverage-q4-2026]
    objective: "Prevent transient network, robots, quota or workflow failures from becoming silent permanent document loss."
    origin: "Production crawl/harvest failures and issue #121."
    issues: [121, 136, 140, 141, 149]
    evidence_prs: [187, 190]
    next_action: "Finish #121 with an explicit allow/deny/unknown robots outcome so a transient robots-fetch failure never becomes either permanent loss or implicit permission for a direct source fetch; then address the measured volume-vs-timeout failures in #136/#140/#141/#149."

  - id: "pipeline-convergence"
    kind: workstream
    status: active
    parents: [ro-coverage-q4-2026, ingestion-resilience]
    objective: "Converge the legacy scrape path and manifest-driven discover→harvest path without regressing coverage or observability."
    origin: "RFC-0003; production fixes #93/#94 removed the original blocker."
    issues: [95, 136, 140, 141, 149, 176]
    evidence_prs: [173, 178, 179]
    next_action: "RFC-0003 Fase 1 is complete. Execute Fase 2 as a bounded workflow-migration slice: make discover→harvest the scheduled primary path with batching/checkpoints sized to avoid the measured timeouts; keep rollback, and do not deprecate scrape until two clean weekly cycles."

  - id: "dataset-release-integrity"
    kind: workstream
    status: completed
    parents: [ro-coverage-q4-2026]
    objective: "Make every published dataset release independently citable and reproducible while preserving a convenient latest pointer for the portal."
    origin: "Verified risk from #151: scheduled releases defaulted to a moving v0 identifier."
    issues: [175]
    evidence_prs: [180]
    next_action: "Observe scheduled releases for regressions; reopen only if immutable citation or latest-pointer resolution fails in production."

  - id: "legal-semantic-integrity"
    kind: objective
    status: active
    parents: [leizilla-root]
    objective: "Ensure the structured dataset never states stronger legal provenance, temporal status or identity semantics than the underlying evidence supports."
    origin: "Post-go-live schema/ETL review found date, temporal and identifier conflation risks."
    next_action: "Finish identifier consistency (#127/#191) and strengthen release-boundary validation (#118); date-provenance and temporal-version fixes are now materialized."
    key_results:
      - id: "kr-date-provenance-honest"
        status: met
        metric: "Canonical schema/ETL/UI locations that conflate date-of-act with publication evidence."
        current: "0 known code/contract conflations after #169/#170: the dataset/export uses data_ato, fallback vigência provenance uses data-ato, and explicit data-publicacao remains distinct."
        target: "0 known conflations; explicit publication provenance remains distinct from date-of-act fallback."
        issues: [129, 157, 167]
        evidence_prs: [169, 170]
      - id: "kr-temporal-version-valid"
        status: met
        metric: "Known code paths that can emit overlapping 'vigente' versions from null/out-of-order dates."
        current: "0 known paths from #120 remain after #189: multi-version timelines with unresolved dates fail closed and dated versions are sorted before ate is derived; dedicated regression tests cover two/three-version reorder and missing-date cases."
        target: "0 known overlapping-current states caused by missing/out-of-order dates; regression coverage present."
        issues: [120]
        evidence_prs: [189]
      - id: "kr-identifier-contract-consistent"
        status: active
        metric: "Parser/ETL/URN disagreements over accepted legal number formats."
        current: "PR #191 defines digits plus an optional single-letter suffix end-to-end and has lint/schema/credential checks green; it remains unmerged."
        target: "One canonical accepted format across parser, ETL, URN and tests."
        issues: [127]
        evidence_prs: [191]
        next_action: "Review #191's narrowed number grammar against real source/spec evidence, then merge only if that contract is intentionally canonical and all gates remain green on the final head."
      - id: "kr-release-validation-gated"
        status: active
        metric: "Build/release boundaries that publish without the declared schema/quality floor checks."
        current: "#186 made the parse/release XSD gate fail closed in CI, but #118 still tracks remaining export/release checks such as floor/provenance/identity invariants."
        target: "All ETL-build and release boundaries fail closed on declared floor violations and emit actionable diagnostics."
        issues: [118]
        evidence_prs: [186]
        next_action: "Implement the remaining #118 gates now that date and temporal schema semantics are reconciled; keep diagnostics explicit and test the release boundary itself."

  - id: "date-provenance"
    kind: workstream
    status: completed
    parents: [legal-semantic-integrity]
    objective: "Separate date-of-act, publication evidence and vigência provenance throughout schema, ETL, fixtures and UI."
    origin: "Issues #129/#157 and follow-up public-surface issue #167."
    issues: [129, 157, 167]
    evidence_prs: [169, 170]
    next_action: "The structural migration is complete; public-surface-auditability owns the remaining deployed-route verification for the now-stale transitional wording in #167."

  - id: "temporal-version-integrity"
    kind: workstream
    status: completed
    parents: [legal-semantic-integrity]
    objective: "Guarantee deterministic non-overlapping version intervals even when source dates are incomplete or out of order."
    origin: "Issue #120."
    issues: [120]
    evidence_prs: [189]
    next_action: "Keep the fail-closed temporal tests as release-boundary evidence; reopen only on a new reproducible overlapping/inverted interval."

  - id: "identifier-integrity"
    kind: workstream
    status: active
    parents: [legal-semantic-integrity]
    objective: "Use one canonical legal-number identity contract from parse through URN and release."
    origin: "Issue #127."
    issues: [127]
    evidence_prs: [191]
    next_action: "Review the #191 digits-plus-optional-letter grammar against real source/spec evidence and merge only after the contract is deliberately accepted across parser, XSD, checker, ETL and identifiers."

  - id: "release-boundary-validation"
    kind: gate
    status: active
    parents: [legal-semantic-integrity, dataset-release-integrity]
    objective: "Fail closed before publishing datasets that violate schema, identity, temporal or quality-floor contracts."
    origin: "Issue #118 and post-go-live audit findings."
    issues: [118]
    evidence_prs: [186]
    next_action: "Complete #118's remaining export/release floor and provenance/identity checks; schema semantics are now sufficiently reconciled to enforce them."

  - id: "public-surface-auditability"
    kind: objective
    status: active
    parents: [leizilla-root, legal-semantic-integrity]
    objective: "Make the public portal legible and auditable on desktop and narrow viewports, with evidence/provenance semantics matching the dataset."
    origin: "Public-product reviews after M13."
    issues: [102, 159, 167]
    next_action: "Verify the deployed data semantics after #170, close or supersede the stale transitional #167 wording when observed, and finish the remaining side-effect coverage in #102."
    key_results:
      - id: "kr-public-semantic-legibility"
        status: active
        metric: "Known public labels/download affordances that imply stronger publication/vigência evidence than the dataset supports."
        current: "The code now exports data_ato and distinguishes data-ato from explicit data-publicacao after #170; #167's legacy-field premise is structurally obsolete, but the deployed law-data route has not yet been re-observed against the real public dataset."
        target: "0 known misleading labels; legacy fields are explained where still published."
        issues: [167]
        evidence_prs: [169, 170]
        next_action: "Observe the deployed law-data route with the real dataset; if it exposes the migrated contract, close/supersede #167 rather than adding a warning for a field no longer exported."
      - id: "kr-public-responsive-audit"
        status: met
        metric: "Declared public routes passing the project's desktop + narrow viewport audit."
        current: "Issue #159 is closed completed with the canonical visual-evidence workflow and preserved desktop/narrow-viewport evidence."
        target: "All declared critical routes pass the canonical audit with preserved screenshots/evidence."
        issues: [159]
      - id: "kr-law-page-regression-tests"
        status: active
        metric: "Core law-page modeling/formatting behaviors covered by deterministic tests."
        current: "#186 added 43 Vitest/jsdom tests covering the core pure model/format branches in #102; DOM side-effect helpers such as copyText/downloadBlob remain outside that suite."
        target: "All critical model/format branches identified in #102 covered by regression tests."
        issues: [102]
        evidence_prs: [186]
        next_action: "Finish the small remaining #102 side-effect/browser helper coverage without reopening already-covered pure modeling logic."

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
    blockers: [118, 127]
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
