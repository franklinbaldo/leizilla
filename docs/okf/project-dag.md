---
type: "Project Map"
title: "Leizilla Project DAG"
description: "Canonical OKF graph of Leizilla delivery fronts, OKRs, dependencies, blockers and next actions. Work branches and GitHub issues execute the graph; they are not the durable project ledger."
tags: [leizilla, okf, project-dag, okr, delivery, governance]
timestamp: 2026-09-24T20:20:00-04:00
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
    next_action: "Use the measured S1-S4 baseline to grow S4, restore the first -latest release after #196/#198, and make scheduled ingestion bounded/resumable."
    key_results:
      - id: "kr-ro-s1-s4-observable"
        status: active
        metric: "Canonical stages S1 archived, S2 identified, S3 text available and S4 structured exposed machine-readably and on /cobertura/."
        current: "Implementation is merged and the production census is known (casacivil 1196/1196/540/20), but the first post-merge coverage.json on the -latest item cannot be observed until the current release incident #196/#198 is cleared."
        target: "4/4 stages publicly observable with timestamp/provenance and source/type breakdown where available."
        issues: [174, 196]
        next_action: "After #198 restores publication, verify coverage.json on the -latest item and /cobertura/ against the same production counters before marking met."
      - id: "kr-ro-backlog-conversion"
        status: active
        metric: "Share of the frozen S1 baseline that has reached S4 and reduction of the initial pre-S4 backlog."
        current: "Production baseline: S1=1196, S2=1196, S3=540, S4=20; S1->S4 = 1.67%, initial pre-S4 backlog = 1176."
        target: "Reduce the initial pre-S4 backlog by at least 50% by 2026-12-31; with S1 frozen at 1196 this requires S4 >= 608 (backlog <= 588)."
        next_action: "Track and reduce the S2->S3 gap (656) and S3->S4 gap (520) by source/type without relaxing provenance/quality gates."
      - id: "kr-ro-recurring-cycle-health"
        status: active
        metric: "Consecutive scheduled discover/harvest/parse/release cycles without an unresolved systemic failure."
        current: "#114 and #121 closed with evidence (2026-09-24): #121's transient-403/429-as-permanent-loss bug fixed via merged PR #190 (robots.py cache no longer poisoned by a transient failure; wayback.py fetch_bytes retries with backoff). #136/#140/#141/#149 remain open with root causes confirmed distinct from #121 and from each other: #136/#140 are the legacy rondonia_crawler.yml Playwright range-scan exceeding the 360min job timeout on high-volume sources; #141 is discover-harvest.yml hitting Internet Archive upload rate limits (~30% of runs); #149 is wayback-save.yml's fixed 2s/URL pacing exceeding the 360min budget on ~20% of runs. None of the three are fixable by raising timeout-minutes — 360min is the GitHub-hosted-runner ceiling — so each needs either scope-splitting (matrix/batched runs) or the rondonia_crawler.yml→discover-harvest.yml migration pipeline-convergence already tracks."
        target: "2 consecutive complete scheduled cycles with no unresolved systemic failure and with per-source results visible."
        issues: [136, 140, 141, 149]
        next_action: "Design a scope-split (matrix by tipo/fonte, or smaller per-run ranges) for wayback-save.yml and discover-harvest.yml so each run finishes inside the 360min ceiling; verify with a real scheduled run before closing #141/#149. #136/#140 close only once rondonia_crawler.yml is deprecated (pipeline-convergence)."

  - id: "coverage-observability"
    kind: workstream
    status: active
    parents: [ro-coverage-q4-2026]
    objective: "Make the coverage frontier itself a first-class, reproducible public artifact."
    origin: "PRD §10.4 and issue #174."
    issues: [174, 196]
    next_action: "Implementation and baseline exist; close only after #196/#198 permits a real -latest publication and coverage.json plus /cobertura/ are observed with matching counters."

  - id: "ingestion-resilience"
    kind: workstream
    status: active
    parents: [ro-coverage-q4-2026]
    objective: "Prevent transient network, robots, quota or workflow failures from becoming silent permanent document loss."
    origin: "Production crawl/harvest failures and issue #121."
    issues: [136, 140, 141, 149]
    next_action: "Issue #121 (the transient-failure-becomes-permanent-loss defect) is fixed and merged (PR #190). The remaining open issues (#136/#140/#141/#149) are scheduled-workflow timeout/throttling problems, not retry-semantics bugs — see kr-ro-recurring-cycle-health for the confirmed root causes and next action."

  - id: "pipeline-convergence"
    kind: workstream
    status: active
    parents: [ro-coverage-q4-2026, ingestion-resilience]
    objective: "Converge the legacy scrape path and manifest-driven discover→harvest path without regressing coverage or observability."
    origin: "RFC-0003; production fixes #93/#94 removed the original blocker."
    issues: [95, 136, 140, 141, 149]
    evidence_prs: [173, 179]
    next_action: "RFC-0003 Fase 1 is done (#176 implemented cdx-auto in discovery, merged via PR #179). #136/#140 (rondonia_crawler.yml timing out on high-volume Playwright range-scans) now give a concrete forcing function to plan the workflow redirection; still defer actually deprecating rondonia_crawler.yml until discover-harvest.yml has two clean weekly cycles as originally planned."

  - id: "dataset-release-integrity"
    kind: workstream
    status: active
    parents: [ro-coverage-q4-2026]
    objective: "Make every published dataset release independently citable and reproducible while preserving a convenient latest pointer for the portal."
    origin: "Issue #175 implemented the scheme; issue #196 exposed a first-release deadlock in the new row-floor guard before any -latest item existed."
    issues: [175, 196]
    evidence_prs: [180, 193, 198]
    next_action: "Finish green #198, re-run parse-release, verify leizilla-dataset-ro-v0-latest exists and the public site loads law data, then return this workstream to completed."

  - id: "legal-semantic-integrity"
    kind: objective
    status: active
    parents: [leizilla-root]
    objective: "Ensure the structured dataset never states stronger legal provenance, temporal status or identity semantics than the underlying evidence supports."
    origin: "Post-go-live schema/ETL review found date, temporal and identifier conflation risks."
    next_action: "Resolve the live release incident #196/#198, restore the generic URN descriptor contract regressed by #191, and reconcile the remaining public/documentation date semantics."
    key_results:
      - id: "kr-date-provenance-honest"
        status: active
        metric: "Canonical schema/ETL/UI locations that conflate date-of-act with publication evidence."
        current: "Schema/ETL use data_ato and #129/#157 are closed; source downloads now export data_ato, but the PRD/naming docs still contain stale date/release wording and #167 has not been reconciled against the deployed route."
        target: "0 known conflations; explicit publication provenance remains distinct from date-of-act fallback."
        issues: [167]
        evidence_prs: [170]
        next_action: "#167 has its own resume precondition (official visual capture of /lei/'s Dados section must succeed again, or a canonical UI fixture must exist) before implementing the frontend disclosure copy — see public-surface-auditability."
      - id: "kr-temporal-version-valid"
        status: met
        metric: "Known code paths that can emit overlapping 'vigente' versions from null/out-of-order dates."
        current: "Fixed and merged (commit 4a27206, PR #189, before #120 was formally closed): xml_to_rows fails closed (ValueError) on an unresolvable effective date across multiple <versao> elements, and sorts by `em` before deriving `ate` — no longer chains off document order. Regression coverage in tests/test_etl_temporal_integrity.py (5 tests). Issue #120 closed with evidence (2026-09-24)."
        target: "0 known overlapping-current states caused by missing/out-of-order dates; regression coverage present."
        issues: [120]
        next_action: "None."
      - id: "kr-identifier-contract-consistent"
        status: active
        metric: "Producer-number and generic URN-LEX descriptor contracts are explicit, compatible and independently tested."
        current: "#127/#191 correctly fixed produced numbers such as 72-A, but also narrowed the generic URN descriptor grammar even though SCHEMA §5.6 documents forms such as lex-16 and estatuto.idoso. A corrective branch now restores only the generic boundary."
        target: "Parser producer grammar remains strict while ETL/XSD/checker accept the documented generic LexML descriptor forms."
        issues: [127]
        next_action: "Gate and land the generic-descriptor correction without relaxing parser.py::_RE_NUMERO; add a bounded follow-up issue when issue mutation is available."
      - id: "kr-release-validation-gated"
        status: active
        metric: "Build/release boundaries that publish without the declared schema/quality floor checks."
        current: "PRs #192/#193 merged XSD-before-consolidate, non-empty provenance and the row-count floor, but #193 immediately exposed a first-release deadlock: missing -latest items return 503 on the download endpoint, causing #196. PR #198 is the active fix. A narrow URN export-boundary validation slice also remains unresolved."
        target: "All ETL-build and release boundaries fail closed on declared floor violations and emit actionable diagnostics."
        issues: [118]
        next_action: "Finish #198 and verify the first -latest publication, then define a narrow URN export-boundary gate against the corrected generic descriptor contract; do not treat closed #118 as proof this KR is met."

  - id: "date-provenance"
    kind: workstream
    status: active
    parents: [legal-semantic-integrity]
    objective: "Separate date-of-act, publication evidence and vigência provenance throughout schema, ETL, fixtures, docs and UI."
    origin: "Issues #129/#157 and follow-up public-surface issue #167."
    issues: [129, 157, 167]
    evidence_prs: [170]
    next_action: "Land the PRD/naming reconciliation, then audit the deployed Dados route after #196/#198 restores the public dataset and resolve #167 from observed behavior."

  - id: "temporal-version-integrity"
    kind: workstream
    status: completed
    parents: [legal-semantic-integrity]
    objective: "Guarantee deterministic non-overlapping version intervals even when source dates are incomplete or out of order."
    origin: "Issue #120."
    issues: [120]
    next_action: "None — fixed, merged, regression-tested, issue closed."

  - id: "identifier-integrity"
    kind: workstream
    status: active
    parents: [legal-semantic-integrity]
    objective: "Use a strict Leizilla-produced legal-number contract without narrowing valid generic URN-LEX descriptors."
    origin: "Issue #127/#191 plus the generic forms documented in SCHEMA §5.6."
    issues: [127]
    next_action: "Land the generic-descriptor regression fix and gate 72-a, lex-16 and estatuto.idoso end to end."

  - id: "release-boundary-validation"
    kind: gate
    status: active
    parents: [legal-semantic-integrity, dataset-release-integrity]
    objective: "Fail closed before publishing datasets that violate schema, identity, temporal or quality-floor contracts."
    origin: "Issue #118 and post-go-live audit findings."
    issues: [118, 196]
    evidence_prs: [192, 193, 198]
    next_action: "Resolve #196 via #198 and prove a successful first -latest publication; then close the remaining narrow URN validation requirement against the corrected descriptor contract."

  - id: "public-surface-auditability"
    kind: objective
    status: active
    parents: [leizilla-root, legal-semantic-integrity]
    objective: "Make the public portal legible and auditable on desktop and narrow viewports, with evidence/provenance semantics matching the dataset."
    origin: "Public-product reviews after M13."
    issues: [167]
    next_action: "kr-public-responsive-audit and kr-law-page-regression-tests are met. Only kr-public-semantic-legibility (#167) remains, gated on its own external observability precondition — see that KR."
    key_results:
      - id: "kr-public-semantic-legibility"
        status: blocked
        metric: "Known public labels/download affordances that imply stronger publication/vigência evidence than the dataset supports."
        current: "The schema-level conflation this KR depended on (date-provenance, #157) is resolved and closed. Issue #167 itself remains open and self-describes an explicit resume precondition: the project's official visual-capture capability must successfully load the published Parquet and open a norm's Dados section again (it failed with a timeout on archive.org's versoes.parquet in the last attempt, commit 84cfdc6, run 33956952230), or a canonical UI fixture representing the same dataset must exist — #167 explicitly asks not to change the presentation before that observability is restored."
        target: "0 known misleading labels; legacy fields are explained where still published."
        blockers: []
        issues: [167]
        next_action: "Do not implement #167's UI change yet. First confirm (via the official visual-capture workflow or a canonical fixture) that /lei/'s Dados section is observable again; only then add the legacy-naming disclosure copy before JSON/CSV downloads."
      - id: "kr-public-responsive-audit"
        status: met
        metric: "Declared public routes passing the project's desktop + narrow viewport audit."
        current: "Issue #159 closed with evidence: `.github/workflows/visual-capture.yml` implements the canonical desktop+narrow audit gate; the closing comment maps each of the issue's 6 acceptance criteria to a concrete mechanism."
        target: "All declared critical routes pass the canonical audit with preserved screenshots/evidence."
        issues: [159]
        next_action: "None."
      - id: "kr-law-page-regression-tests"
        status: met
        metric: "Core law-page modeling/formatting behaviors covered by deterministic tests."
        current: "Issue #102 closed with evidence: PR #186 added vitest+jsdom to web/ (previously no test framework) and 43 tests covering currentRows/buildTree/pathSegments/rotulo/breadcrumb/citation/CSV-JSON export/groupHistorico/aggregateFontes/formatDate; PR #194 added the remaining DOM-side-effect slice (copyText/downloadBlob, 7 more tests). 50 tests total in web/."
        target: "All critical model/format branches identified in #102 covered by regression tests."
        issues: [102]
        next_action: "None."

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
    next_action: "#175 and #157 are resolved. #118 is substantially addressed (row-floor guard, ia-id/XSD gates merged) with only a narrow, deliberately-deferred urn_lex-canonicalization slice open — re-evaluate this blocker once that's explicitly closed or superseded by a follow-up issue. Maintain Planalto pipeline readiness in the meantime."
    blockers: [118, 196, 167]
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
