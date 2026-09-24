---
type: "Project Map"
title: "Leizilla Project DAG"
description: "Canonical OKF graph of Leizilla delivery fronts, OKRs, dependencies, blockers and next actions. Work branches and GitHub issues execute the graph; they are not the durable project ledger."
tags: [leizilla, okf, project-dag, okr, delivery, governance]
timestamp: 2026-09-24T18:55:00-04:00
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
    next_action: "Verify public S1-S4 publication, convert the frozen baseline toward S4, and restore consecutive healthy scheduled cycles."
    key_results:
      - id: "kr-ro-s1-s4-observable"
        status: active
        metric: "Number of canonical coverage stages (S1 archived, S2 identified, S3 text available, S4 structured) exposed machine-readably and on /cobertura/."
        current: "Instrumentation and UI for all 4 stages are merged (#185/#174). Reproducible baseline: casacivil S1=1196, S2=1196, S3=540, S4=20; assembleia 0/0/0/0. The first production coverage.json + /cobertura/ consumption has not yet been independently observed."
        target: "4/4 stages publicly exposed from the production -latest dataset item with timestamp/provenance and source/type breakdown."
        issues: [174]
        evidence_prs: [185]
        next_action: "Observe the next production parse-release output: verify coverage.json on the -latest item and /cobertura/ rendering the same counters; only then mark met."
      - id: "kr-ro-backlog-conversion"
        status: active
        metric: "Share of the frozen first S1 baseline that has reached S4."
        current: "Baseline S1=1196 and S4=20: conversion=1.67%; 1176 archived records have not yet reached S4."
        target: "Reduce the baseline pre-S4 backlog by at least 50% by 2026-12-31: backlog <=588, equivalently S4 >=608 while the frozen baseline denominator remains 1196."
        next_action: "Track S4 against the frozen S1=1196 baseline per source/type and prioritize the S2->S3 (656) and S3->S4 (520) gaps without relaxing provenance/quality gates."
      - id: "kr-ro-recurring-cycle-health"
        status: active
        metric: "Consecutive scheduled discover/harvest/parse/release cycles without an unresolved systemic failure."
        current: "The parse-release incident #114 is closed. Incident trackers #136, #140, #141 and #149 remain open; #121 was fixed by #190 so transient fetch failures remain retryable instead of becoming silent terminal loss."
        target: "2 consecutive complete scheduled cycles with no unresolved systemic failure and with per-source results visible."
        issues: [114, 121, 136, 140, 141, 149]
        evidence_prs: [190]
        next_action: "Observe post-#190 scheduled lanes, close stale incident trackers only with run evidence, and address throughput/time-budget failures that still reproduce."

  - id: "coverage-observability"
    kind: workstream
    status: active
    parents: [ro-coverage-q4-2026]
    objective: "Make the coverage frontier itself a first-class, reproducible public artifact."
    origin: "PRD §10.4 and issue #174."
    issues: [174]
    evidence_prs: [185]
    next_action: "Verify the first real coverage.json on leizilla-dataset-ro-v0-latest and the published /cobertura/ page against the recorded 1196/1196/540/20 casacivil baseline."

  - id: "ingestion-resilience"
    kind: workstream
    status: active
    parents: [ro-coverage-q4-2026]
    objective: "Prevent transient network, robots, quota or workflow failures from becoming silent permanent document loss."
    origin: "Production crawl/harvest failures and issue #121."
    issues: [121, 136, 140, 141, 149]
    evidence_prs: [190]
    next_action: "Use post-#190 runs to distinguish retryable-network recovery from remaining throughput/time-budget failures; keep #136/#140/#141/#149 open until their affected lanes have reproducible healthy evidence."

  - id: "pipeline-convergence"
    kind: workstream
    status: active
    parents: [ro-coverage-q4-2026, ingestion-resilience]
    objective: "Converge the legacy scrape path and manifest-driven discover→harvest path without regressing coverage or observability."
    origin: "RFC-0003; Phase 1 completed via #173/#176/#179."
    issues: [176, 136, 140, 141]
    evidence_prs: [173, 179]
    next_action: "Start RFC-0003 Phase 2: redirect scheduled legacy scrape lanes to discover→harvest with bounded batches/checkpoints so backlog growth cannot exceed a fixed job budget; defer scrape deprecation until two clean scheduled cycles."

  - id: "dataset-release-integrity"
    kind: workstream
    status: completed
    parents: [ro-coverage-q4-2026]
    objective: "Make every published dataset release independently citable and reproducible while preserving a convenient latest pointer for the portal."
    origin: "Issue #175."
    issues: [175]
    evidence_prs: [180]
    next_action: "Completed: immutable revision identifiers plus the mutable -latest pointer are implemented and documented; retain as a dependency/evidence node."

  - id: "legal-semantic-integrity"
    kind: objective
    status: active
    parents: [leizilla-root]
    objective: "Ensure the structured dataset never states stronger legal provenance, temporal status or identity semantics than the underlying evidence supports."
    origin: "Post-go-live schema/ETL review found date, temporal and identifier conflation risks."
    next_action: "Finish the remaining date-provenance documentation/public verification, correct identifier-contract scope in #191, and then strengthen release-boundary validation."
    key_results:
      - id: "kr-date-provenance-honest"
        status: active
        metric: "Canonical schema/ETL/UI locations that conflate date-of-act with publication evidence."
        current: "Runtime/schema/web contracts are corrected by #169/#170: data_ato is canonical and data-publicacao is reserved for explicit publication evidence. One stale data_publicacao description remains in canonical docs/PRD.md, and public-route verification requested by #167 is still open."
        target: "0 known conflations; explicit publication provenance remains distinct from date-of-act fallback in code, canonical docs and published UI/downloads."
        issues: [129, 157, 167]
        evidence_prs: [169, 170]
        next_action: "Land the PRD reconciliation prepared on steward/reconcile-prd-contracts-20260924 (ae00d23), then observe the real published Dados route before closing #167."
      - id: "kr-temporal-version-valid"
        status: met
        metric: "Known code paths that can emit overlapping 'vigente' versions from null/out-of-order dates."
        current: "PR #189 is merged: multi-version timelines with unresolved effective dates fail closed, and dated versions are sorted before deriving ate. Regression tests cover two/three scrambled versions and missing-date cases."
        target: "0 known overlapping-current states caused by missing/out-of-order dates; regression coverage present."
        issues: [120]
        evidence_prs: [189]
        next_action: "Met; keep the regression suite as the contract and reopen only on contrary evidence."
      - id: "kr-identifier-contract-consistent"
        status: active
        metric: "Parser/ETL/URN disagreements over accepted legal number formats."
        current: "PR #191 accepts producer numbers like 72-A, but also narrows the generic URN-LEX descriptor grammar in XSD/checker/ETL, conflicting with documented LexML forms such as lex-16 and estatuto.idoso."
        target: "One explicit producer-number contract without rejecting valid generic URN-LEX descriptor forms; round-trip and compatibility tests present."
        issues: [127]
        evidence_prs: [191]
        next_action: "Revise #191 so parser/IA-ID production accepts digits plus optional letter suffix while generic URN-LEX validation preserves the broader descriptor grammar; add compatibility tests for non-producer LexML forms."
      - id: "kr-release-validation-gated"
        status: open
        metric: "Build/release boundaries that publish without the declared schema/quality floor checks."
        current: "Issue #118 remains open."
        target: "All ETL-build and release boundaries fail closed on declared floor violations and emit actionable diagnostics."
        issues: [118]
        next_action: "Implement #118 now that date and temporal semantics are settled, starting with the cheapest release-floor and uniqueness assertions."

  - id: "date-provenance"
    kind: workstream
    status: active
    parents: [legal-semantic-integrity]
    objective: "Separate date-of-act, publication evidence and vigência provenance throughout schema, ETL, fixtures, canonical docs and UI."
    origin: "Issues #129/#157/#167."
    issues: [129, 157, 167]
    evidence_prs: [169, 170]
    next_action: "Land the remaining PRD wording reconciliation (branch steward/reconcile-prd-contracts-20260924, commit ae00d23) and verify the published Dados route against the real latest dataset before closing the public-surface follow-up."

  - id: "temporal-version-integrity"
    kind: workstream
    status: completed
    parents: [legal-semantic-integrity]
    objective: "Guarantee deterministic non-overlapping version intervals even when source dates are incomplete or out of order."
    origin: "Issue #120."
    issues: [120]
    evidence_prs: [189]
    next_action: "Completed by #189; preserve fail-closed missing-date and chronological-order regressions."

  - id: "identifier-integrity"
    kind: workstream
    status: active
    parents: [legal-semantic-integrity]
    objective: "Use a canonical producer legal-number identity contract without conflating it with the broader URN-LEX descriptor grammar."
    origin: "Issue #127."
    issues: [127]
    evidence_prs: [191]
    next_action: "Correct #191's validator scope: keep suffix-aware parser/IA identity, preserve generic LexML descriptors in XSD/checker/ETL, and test both contracts."

  - id: "release-boundary-validation"
    kind: gate
    status: open
    parents: [legal-semantic-integrity, dataset-release-integrity]
    objective: "Fail closed before publishing datasets that violate schema, identity, temporal or quality-floor contracts."
    origin: "Issue #118 and post-go-live audit findings."
    issues: [118]
    next_action: "Implement #118 in bounded slices: release row-count floor/metadata consistency first, then remaining XML/URN/source/versao_id assertions with regression tests."

  - id: "public-surface-auditability"
    kind: objective
    status: active
    parents: [leizilla-root, legal-semantic-integrity]
    objective: "Make the public portal legible and auditable on desktop and narrow viewports, with evidence/provenance semantics matching the dataset."
    origin: "Public-product reviews after M13."
    issues: [102, 159, 167]
    next_action: "Finish the small remaining #102 DOM-helper test slice and independently observe #167 on the published real dataset."
    key_results:
      - id: "kr-public-semantic-legibility"
        status: active
        metric: "Known public labels/download affordances that imply stronger publication/vigência evidence than the dataset supports."
        current: "Current main exports data_ato and labels data-ato separately from explicit data-publicacao. Issue #167 still requires observation of the published route with the real dataset before declaring the surface clean."
        target: "0 known misleading labels; published downloads and labels match the canonical data_ato/data-publicacao distinction."
        issues: [167]
        next_action: "Verify the published Dados route with the real -latest dataset; if no legacy field remains, close the explanatory-workaround issue rather than adding obsolete copy."
      - id: "kr-public-responsive-audit"
        status: met
        metric: "Declared public routes passing the project's desktop + narrow viewport audit."
        current: "Issue #159 is closed with reproducible evidence: visual-capture.yml from #160/#165 captures desktop 1280x900 and narrow 390x844 on PR and main, records SHA, runs accessibility checks, and fails explicitly on render/capture failure."
        target: "All declared critical routes pass the canonical audit with preserved screenshots/evidence."
        issues: [159]
        evidence_prs: [160, 165]
        next_action: "Met; keep the visual-capture gate active on future web changes."
      - id: "kr-law-page-regression-tests"
        status: active
        metric: "Core law-page modeling/formatting behaviors covered by deterministic tests."
        current: "PR #186 merged 43 model/format tests and added npm run test to the web gate. Issue #102 intentionally left copyText/downloadBlob DOM helpers as a final small slice; commit 4c3d025 on steward/finish-law-page-tests-102 adds those tests but is not yet gated/merged."
        target: "All model/format and identified DOM-helper behaviors in #102 covered by deterministic tests."
        issues: [102]
        evidence_prs: [186]
        next_action: "Run web tests/build on 4c3d025 (or equivalent PR head), merge only with green gates, then close #102 and mark met."

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
    next_action: "Maintain Planalto pipeline readiness, but do not start broad federal ingestion until identifier semantics and release-boundary gates are stable."
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
