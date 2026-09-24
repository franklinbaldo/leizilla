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
    next_action: "Verify the first public coverage artifact, reduce the frozen S1→S4 baseline backlog, and restore consecutive healthy scheduled cycles."
    key_results:
      - id: "kr-ro-s1-s4-observable"
        status: active
        metric: "Number of canonical coverage stages (S1 archived, S2 identified, S3 text/OCR available, S4 structured/published) exposed machine-readably and on /cobertura/."
        current: "PR #185 merged and #174 is closed. First measured RO baseline: casacivil S1=1196, S2=1196, S3=540, S4=20; assembleia S1=S2=S3=S4=0. Public coverage.json on the -latest item is not yet verified."
        target: "4/4 stages exposed with timestamp/provenance and source/type breakdown where available."
        issues: [174]
        evidence_prs: [185]
        next_action: "Verify the first scheduled coverage.json publication on the -latest dataset item and confirm /cobertura/ renders the same counters before marking the KR met."
      - id: "kr-ro-backlog-conversion"
        status: active
        metric: "Share of the frozen first S1 baseline cohort that has reached S4, plus remaining pre-S4 backlog by source/type."
        current: "Casacivil baseline is S1=1196 and S4=20: 1.67% structured, with 1176 baseline documents still pre-S4. Assembleia baseline is 0 and is tracked separately."
        target: "Reduce the first measured pre-S4 backlog by at least 50% by 2026-12-31 without relaxing provenance/quality gates; for casacivil this means backlog <=588, i.e. at least 608 of the original 1196 at S4."
        next_action: "Track the frozen cohort by source/type and prioritize the measured casacivil gaps: 656 from S2→S3 and 520 from S3→S4."
      - id: "kr-ro-recurring-cycle-health"
        status: active
        metric: "Consecutive scheduled discover/harvest/parse/release cycles without an unresolved systemic failure."
        current: "0 consecutive clean cycles established. The latest recorded casacivil crawl on 2026-09-20 was cancelled; #187 has since merged so the next crawl can expose the previously hidden upload error detail. Other incident trackers remain open."
        target: "2 consecutive complete scheduled cycles with no unresolved systemic failure and with per-source results visible."
        issues: [114, 136, 140, 141, 149]
        next_action: "Use the next scheduled casacivil crawl after #187 to identify the upload failure cause, reconcile the remaining incident trackers, and then begin counting clean end-to-end cycles."

  - id: "coverage-observability"
    kind: workstream
    status: active
    parents: [ro-coverage-q4-2026]
    objective: "Make the coverage frontier itself a first-class, reproducible public artifact."
    origin: "PRD §10.4 requires exposing archived/text/structured coverage; current public surface mainly exposes S4."
    issues: [174]
    evidence_prs: [185]
    next_action: "Implementation and baseline exist; verify production coverage.json on the -latest item and the deployed /cobertura/ read path, then close this workstream if both match."

  - id: "ingestion-resilience"
    kind: workstream
    status: active
    parents: [ro-coverage-q4-2026]
    objective: "Prevent transient network, robots, quota or workflow failures from becoming silent permanent document loss."
    origin: "Production crawl/harvest failures and issue #121."
    issues: [121, 136, 140, 141, 149]
    evidence_prs: [187]
    next_action: "Use the first post-#187 casacivil run to classify the real upload failures. For #121, model robots/fetch outcomes explicitly: confirmed disallow is terminal; confirmed absence/allow permits access; robots-policy unavailability must stay retryable without becoming implicit permission for a direct fetch. Close only incident trackers disproved by new evidence."

  - id: "pipeline-convergence"
    kind: workstream
    status: active
    parents: [ro-coverage-q4-2026, ingestion-resilience]
    objective: "Converge the legacy scrape path and manifest-driven discover→harvest path without regressing coverage or observability."
    origin: "RFC-0003; production fixes #93/#94 removed the original blocker."
    issues: [176]
    evidence_prs: [173, 179]
    next_action: "RFC-0003 Fase 1 is complete and #176 is closed. Materialize Fase 2 as a bounded issue, redirect production workflows to discover→harvest with before/after coverage evidence, and defer scrape deprecation until two clean weekly cycles."

  - id: "dataset-release-integrity"
    kind: workstream
    status: completed
    parents: [ro-coverage-q4-2026]
    objective: "Make every published dataset release independently citable and reproducible while preserving a convenient latest pointer for the portal."
    origin: "Verified risk from #151: scheduled releases default to --version 0 while the frontend points at leizilla-dataset-ro-v0."
    issues: [175]
    evidence_prs: [180]
    next_action: "No active implementation slice: immutable release identifiers and the mutable -latest pointer are merged and #175 is closed; monitor recurring releases for regressions."

  - id: "legal-semantic-integrity"
    kind: objective
    status: active
    parents: [leizilla-root]
    objective: "Ensure the structured dataset never states stronger legal provenance, temporal status or identity semantics than the underlying evidence supports."
    origin: "Post-go-live schema/ETL review found date, temporal and identifier conflation risks."
    next_action: "Date-of-act provenance is reconciled in #170; advance temporal-version and identifier consistency and implement the now-unblocked release-boundary validation gate."
    key_results:
      - id: "kr-date-provenance-honest"
        status: active
        metric: "Canonical schema/ETL/UI locations that conflate date-of-act with publication evidence."
        current: "PR #170 merged with Lint & Test, Schema Validation, Visual capture and credential checks green on head b5f432f. Schema, ETL, checker, fixtures and UI now distinguish data-ato from proven data-publicacao; #167 still tracks legacy public-download explanation."
        target: "0 known conflations; explicit publication provenance remains distinct from date-of-act fallback."
        issues: [157, 167]
        evidence_prs: [170]
        next_action: "Close #157 administratively when mutation is available, then complete #167 by observing a real public law route and explaining legacy download semantics without inventing DOE evidence."
      - id: "kr-temporal-version-valid"
        status: met
        metric: "Known code paths that can emit overlapping 'vigente' versions from null/out-of-order dates."
        current: "PR #189 merged a fail-closed chronological normalization with 5 focused regression cases: two- and three-version reordering, fully/partially unknown multi-version dates rejected, and single dateless version preserved. Lint & Test and credential checks are green on head aac3fdb. Issue #120 remains administratively open."
        target: "0 known overlapping-current states caused by missing/out-of-order dates; regression coverage present."
        issues: [120]
        evidence_prs: [189]
        next_action: "Close #120 administratively when issue mutation is available; retain the regression cases as the temporal-integrity gate."
      - id: "kr-identifier-contract-consistent"
        status: active
        metric: "Parser/ETL/URN disagreements over accepted legal number formats."
        current: "Issue #127 is open. Official RO SAPL evidence confirms a real single-letter-suffixed legal identifier (Decreto-Lei nº 9-A, cited on https://sapl.al.ro.leg.br/norma/10966), so suffix handling is not hypothetical; the end-to-end contract still needs merged evidence."
        target: "One canonical accepted format across parser, ETL, URN and tests."
        issues: [127]
        next_action: "Normalize the evidence-backed single-letter suffix grammar across parser, parsed identifier, URN, ETL and schema checker with collision/round-trip tests; keep the raw harvest-key identity layer separate."
      - id: "kr-release-validation-gated"
        status: open
        metric: "Build/release boundaries that publish without the declared schema/quality floor checks."
        current: "Issue #118 is open."
        target: "All ETL-build and release boundaries fail closed on declared floor violations and emit actionable diagnostics."
        issues: [118]
        next_action: "Schema provenance semantics are reconciled by #170; implement #118 now, incorporating temporal and identifier checks as those contracts settle."

  - id: "date-provenance"
    kind: workstream
    status: active
    parents: [legal-semantic-integrity]
    objective: "Separate date-of-act, publication evidence and vigência provenance throughout schema, ETL, fixtures and UI."
    origin: "Issues #129/#157 and follow-up public-surface issue #167."
    issues: [157, 167]
    evidence_prs: [170]
    next_action: "Core schema/ETL/checker semantics are merged and green; finish the remaining public-download explanation in #167 and close #157 administratively."

  - id: "temporal-version-integrity"
    kind: workstream
    status: completed
    parents: [legal-semantic-integrity]
    objective: "Guarantee deterministic non-overlapping version intervals even when source dates are incomplete or out of order."
    origin: "Issue #120."
    issues: [120]
    evidence_prs: [189]
    next_action: "No active implementation slice: #189 is merged with green tests; close #120 administratively and reopen only on a reproduced temporal-overlap regression."

  - id: "identifier-integrity"
    kind: workstream
    status: active
    parents: [legal-semantic-integrity]
    objective: "Use one canonical legal-number identity contract from parse through URN and release."
    origin: "Issue #127."
    issues: [127]
    next_action: "Real RO source evidence now confirms the single-letter suffix case; finish the end-to-end grammar/collision implementation and require exact-head schema + test gates before closing #127."

  - id: "release-boundary-validation"
    kind: gate
    status: open
    parents: [legal-semantic-integrity, dataset-release-integrity]
    objective: "Fail closed before publishing datasets that violate schema, identity, temporal or quality-floor contracts."
    origin: "Issue #118 and post-go-live audit findings."
    issues: [118]
    next_action: "Schema provenance semantics are settled by #170; implement #118 now and wire explicit ETL/release gates and regression tests into the production release path."

  - id: "public-surface-auditability"
    kind: objective
    status: active
    parents: [leizilla-root, legal-semantic-integrity]
    objective: "Make the public portal legible and auditable on desktop and narrow viewports, with evidence/provenance semantics matching the dataset."
    origin: "Public-product reviews after M13."
    issues: [102, 159, 167]
    next_action: "Responsive auditability and law-page model tests are implemented; finish the remaining public-download semantics in #167 and keep the visual regression gate healthy."
    key_results:
      - id: "kr-public-semantic-legibility"
        status: active
        metric: "Known public labels/download affordances that imply stronger publication/vigência evidence than the dataset supports."
        current: "Core data-ato/data-publicacao semantics are merged in #170. Issue #167 remains for legacy download explanation; the visual gate currently audits the home surface, not a real law-page Dados route."
        target: "0 known misleading labels; legacy fields are explained where still published."
        issues: [167]
        next_action: "Observe a real public law-page Dados route with the published dataset, then implement the minimal #167 explanation and preserve visual evidence."
      - id: "kr-public-responsive-audit"
        status: met
        metric: "Declared public routes passing the project's desktop + narrow viewport audit."
        current: "Issue #159 is closed as completed. The canonical capture gate is green on PR #170's head and preserves desktop/narrow evidence artifacts."
        target: "All declared critical routes pass the canonical audit with preserved screenshots/evidence."
        issues: [159]
        next_action: "Maintain the capture gate on future surface changes and reopen only on reproducible regression."
      - id: "kr-law-page-regression-tests"
        status: met
        metric: "Core law-page modeling/formatting behaviors covered by deterministic tests."
        current: "PR #186 merged 43 Vitest/jsdom tests covering every model/format branch enumerated in #102; the issue is still administratively open."
        target: "All critical model/format branches identified in #102 covered by regression tests."
        issues: [102]
        evidence_prs: [186]
        next_action: "Close #102 as completed when issue mutation is available; DOM-side-effect tests remain optional follow-up outside its stated scope."

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
    blockers: [127, 118]
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
