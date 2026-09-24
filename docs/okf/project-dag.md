---
type: "Project Map"
title: "Leizilla Project DAG"
description: "Canonical OKF graph of Leizilla delivery fronts, OKRs, dependencies, blockers and next actions. Work branches and GitHub issues execute the graph; they are not the durable project ledger."
tags: [leizilla, okf, project-dag, okr, delivery, governance]
timestamp: 2026-09-24T20:00:00-04:00
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
    next_action: "Run the S1-S4 tooling against production data to capture the first real baseline, then triage the remaining scheduled-workflow timeout/throttling failures (#136/#140/#141/#149)."
    key_results:
      - id: "kr-ro-s1-s4-observable"
        status: met
        metric: "Number of canonical coverage stages (S1 discovered, S2 raw preserved, S3 text/OCR available, S4 structured/published) exposed machine-readably and on /cobertura/."
        current: "4/4 stages implemented: `src/leizilla/coverage.py` (S1-S4 aggregation, 22 tests), `leizilla coverage` CLI, and `/cobertura/` route. Issue #174 closed with evidence (2026-09-24)."
        target: "4/4 stages exposed with timestamp/provenance and source/type breakdown where available."
        issues: [174]
        next_action: "None — feeds kr-ro-backlog-conversion once run against production data for the first baseline."
      - id: "kr-ro-backlog-conversion"
        status: active
        metric: "Share of the reproducibly measured S1/S2/S3 backlog that has reached S4."
        current: "Tooling exists (kr-ro-s1-s4-observable, met) but no production baseline has been captured yet."
        target: "Reduce the first measured pre-S4 backlog by at least 50% by 2026-12-31 without relaxing provenance/quality gates."
        next_action: "Run `leizilla coverage` against production IA/DuckDB state to record the first real census; freeze the denominator semantics from that run."
      - id: "kr-ro-recurring-cycle-health"
        status: active
        metric: "Consecutive scheduled discover/harvest/parse/release cycles without an unresolved systemic failure."
        current: "#114 and #121 closed with evidence (2026-09-24): #121's transient-403/429-as-permanent-loss bug fixed via merged PR #190 (robots.py cache no longer poisoned by a transient failure; wayback.py fetch_bytes retries with backoff). #136/#140/#141/#149 remain open with root causes confirmed distinct from #121 and from each other: #136/#140 are the legacy rondonia_crawler.yml Playwright range-scan exceeding the 360min job timeout on high-volume sources; #141 is discover-harvest.yml hitting Internet Archive upload rate limits (~30% of runs); #149 is wayback-save.yml's fixed 2s/URL pacing exceeding the 360min budget on ~20% of runs. None of the three are fixable by raising timeout-minutes — 360min is the GitHub-hosted-runner ceiling — so each needs either scope-splitting (matrix/batched runs) or the rondonia_crawler.yml→discover-harvest.yml migration pipeline-convergence already tracks."
        target: "2 consecutive complete scheduled cycles with no unresolved systemic failure and with per-source results visible."
        issues: [136, 140, 141, 149]
        next_action: "Design a scope-split (matrix by tipo/fonte, or smaller per-run ranges) for wayback-save.yml and discover-harvest.yml so each run finishes inside the 360min ceiling; verify with a real scheduled run before closing #141/#149. #136/#140 close only once rondonia_crawler.yml is deprecated (pipeline-convergence)."

  - id: "coverage-observability"
    kind: workstream
    status: completed
    parents: [ro-coverage-q4-2026]
    objective: "Make the coverage frontier itself a first-class, reproducible public artifact."
    origin: "PRD §10.4 requires exposing archived/text/structured coverage; current public surface mainly exposes S4."
    issues: [174]
    next_action: "None — S1-S4 aggregation, machine-readable output and /cobertura/ presentation are implemented and merged. Producing the first production baseline is tracked as kr-ro-backlog-conversion, not further work here."

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
    issues: []
    evidence_prs: [173, 179]
    next_action: "RFC-0003 Fase 1 is done (#176 implemented cdx-auto in discovery, merged via PR #179). #136/#140 (rondonia_crawler.yml timing out on high-volume Playwright range-scans) now give a concrete forcing function to plan the workflow redirection; still defer actually deprecating rondonia_crawler.yml until discover-harvest.yml has two clean weekly cycles as originally planned."

  - id: "dataset-release-integrity"
    kind: workstream
    status: completed
    parents: [ro-coverage-q4-2026]
    objective: "Make every published dataset release independently citable and reproducible while preserving a convenient latest pointer for the portal."
    origin: "Verified risk from #151: scheduled releases default to --version 0 while the frontend points at leizilla-dataset-ro-v0."
    issues: [175]
    next_action: "None — immutable release identifiers + mutable latest pointer implemented and merged (PR #180). Release-time validation gates are tracked separately under release-boundary-validation."

  - id: "legal-semantic-integrity"
    kind: objective
    status: active
    parents: [leizilla-root]
    objective: "Ensure the structured dataset never states stronger legal provenance, temporal status or identity semantics than the underlying evidence supports."
    origin: "Post-go-live schema/ETL review found date, temporal and identifier conflation risks."
    next_action: "Date-provenance, temporal-version and identifier-contract KRs are met. Only release-validation-gated remains active: decide whether the deferred urn_lex-canonicalization slice of #118 needs a narrower follow-up issue."
    key_results:
      - id: "kr-date-provenance-honest"
        status: active
        metric: "Canonical schema/ETL/UI locations that conflate date-of-act with publication evidence."
        current: "Schema/ETL/checker conflation resolved: PR #170 merged, issue #157 closed with evidence (2026-09-24) — `inicio_tipo`'s no-explicit-`<inicio>` fallback is `data-ato`, not `data-publicacao`; docs/SCHEMA.md, the consistency checker and etl.py agree. #167 (frontend JSON/CSV downloads still expose the legacy `data_publicacao` name without explanation) remains open — also tracked under public-surface-auditability's kr-public-semantic-legibility."
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
        status: met
        metric: "Parser/ETL/URN disagreements over accepted legal number formats."
        current: "Resolved via PR #191 (merged): parser.py, etl.py's URN-LEX regex, the schema consistency checker and the XSD all now accept and agree on `\\d+(-[a-z])?` (digits, optional single lowercase-letter suffix, e.g. \"72-a\"). Issue #127 closed."
        target: "One canonical accepted format across parser, ETL, URN and tests."
        issues: [127]
        next_action: "None."
      - id: "kr-release-validation-gated"
        status: active
        metric: "Build/release boundaries that publish without the declared schema/quality floor checks."
        current: "Issue #118 substantially addressed across two independent PRs merged 2026-09-24: `versao_id` uniqueness was already enforced pre-existing; PR #193 added the row-count floor guard on `release-dataset` (refuses to publish fewer rows than the currently published release, latest-pointer-first with legacy-item fallback); PR #192 added empty/missing `ia-id` rejection in `xml_to_rows` and wired the existing `_xsd_gate` into `consolidate` (previously only `parse`/`parse-all` ran it). Deliberately NOT done: a hard urn_lex-grammar validation at the export boundary — it was found to regress the intentional lei_id-fallback degradation `_parse_lei_fields` uses for an unparseable/mis-cased urn-lex (tested behavior from PR #191/#127)."
        target: "All ETL-build and release boundaries fail closed on declared floor violations and emit actionable diagnostics."
        issues: [118]
        next_action: "Decide whether the residual risk (a malformed-but-parseable-looking urn-lex persisting verbatim in `urn_lex_lei`) is worth a narrower follow-up issue (e.g. reject only urn-lex that doesn't even start with `urn:lex:br`, letting grammar-level mismatches keep falling back as designed) or close #118 as-is."

  - id: "date-provenance"
    kind: workstream
    status: completed
    parents: [legal-semantic-integrity]
    objective: "Separate date-of-act, publication evidence and vigência provenance throughout schema, ETL, fixtures and UI."
    origin: "Issues #129/#157 and follow-up public-surface issue #167."
    issues: [157]
    evidence_prs: [170]
    next_action: "None for the schema/ETL scope (issues #129 and #157 both closed with evidence). The public-surface follow-up (#167) is tracked under public-surface-auditability, not here, since it has its own external observability precondition."

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
    status: completed
    parents: [legal-semantic-integrity]
    objective: "Use one canonical legal-number identity contract from parse through URN and release."
    origin: "Issue #127."
    issues: [127]
    next_action: "None — fixed, merged (PR #191), issue closed."

  - id: "release-boundary-validation"
    kind: gate
    status: active
    parents: [legal-semantic-integrity, dataset-release-integrity]
    objective: "Fail closed before publishing datasets that violate schema, identity, temporal or quality-floor contracts."
    origin: "Issue #118 and post-go-live audit findings."
    issues: [118]
    next_action: "See legal-semantic-integrity's kr-release-validation-gated for what's merged (PRs #192, #193) and what's deliberately deferred (urn_lex canonicalization)."

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
    blockers: [118]
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
