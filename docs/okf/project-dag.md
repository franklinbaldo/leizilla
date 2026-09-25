---
type: "Project Map"
title: "Leizilla Project DAG"
description: "Canonical OKF graph of Leizilla delivery fronts, OKRs, dependencies, blockers and next actions. Work branches and GitHub issues execute the graph; they are not the durable project ledger."
tags: [leizilla, okf, project-dag, okr, delivery, governance]
timestamp: 2026-09-25T04:00:00+00:00
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
    next_action: "First S1-S4 production baseline captured 2026-09-25 (see kr-ro-backlog-conversion). #141/#149's scope-split fix (PR #207) is now VERIFIED for wayback-save.yml: run 36082098747 (dispatched by the prior session) reached `completed`/`success` this session — all 8 per-tipo matrix jobs (single/resolucao/lc/decreto/portaria/lei/ec/decreto-lei) finished cleanly, none hit the old 360min timeout. discover-harvest.yml's companion run 36082100347 is still `queued` as of this session's end (~2.5h after dispatch, and after wayback-save's 8 jobs freed their runners) — confirms the runner-starvation read from last session (this account has very low concurrent ubuntu-latest capacity) rather than resolving it: this session's OWN 3 new PRs (#221/#222/#224) each triggered lint/schema-validate/check-credentials runs competing for the same limited pool, so the starvation is partly self-inflicted by continued Claude-session CI activity, not just discover-harvest's own weight. Next session: check run 36082100347's outcome; close #149 once discover-harvest.yml also completes cleanly (wayback-save alone is enough evidence to no longer treat #149 as unverified, but the KR wants both workflows and ideally a real scheduled — not just workflow_dispatch — cycle). #136/#140 stay deferred to pipeline-convergence."
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
        current: "First production baseline captured 2026-09-25 (`uv run leizilla coverage --ente ro --json`, read-only against IA, reproducible by anyone with network access — no IA/LLM credentials required): ente=ro, fontes=casacivil+assembleia. casacivil: S1=1196 S2=1196 S3=572 S4=20 (decreto: S1=307 S2=307 S3=215 S4=0; lei: S1=889 S2=889 S3=357 S4=20). assembleia: S1=S2=S3=S4=0 (no resources discovered yet for this fonte). Denominator frozen: pre-S4 backlog = S1 total − S4 total = 1196 − 20 = 1176."
        target: "Reduce the first measured pre-S4 backlog by at least 50% by 2026-12-31 without relaxing provenance/quality gates — i.e. S4 ≥ 608 (currently 20) against the frozen S1=1196 denominator."
        next_action: "Track S4 growth against this frozen baseline as parse-release.yml runs (18/day pacing, see dataset-release-integrity for the item-4/item-13 gate blockers still limiting throughput). Re-run `leizilla coverage --json` periodically to update `current` without changing the frozen denominator unless S1 itself grows (new discovery)."
      - id: "kr-ro-recurring-cycle-health"
        status: active
        metric: "Consecutive scheduled discover/harvest/parse/release cycles without an unresolved systemic failure."
        current: "#114 and #121 closed with evidence (2026-09-24). #136/#140/#141/#149 remain open, root causes confirmed distinct: #136/#140 are the legacy rondonia_crawler.yml Playwright range-scan exceeding the 360min job timeout on high-volume sources (untouched — gated on pipeline-convergence); #141 is discover-harvest.yml hitting Internet Archive upload rate limits; #149 is wayback-save.yml's fixed 2s/URL pacing exceeding the 360min budget. PR #207's scope-split fix is now VERIFIED for #149: run 36082098747 (dispatched 2026-09-25) reached `completed`/`success` this session, all 8 per-tipo matrix jobs finished cleanly, none timed out. #141's discover-harvest.yml companion run (36082100347, same dispatch) is still `queued` ~2.5h later — not a fix failure, this account's GitHub Actions runner concurrency is very low and this session's own PR CI activity (#221/#222/#224) kept competing for the same slots, so #141 stays genuinely unverified pending a run that actually executes."
        target: "2 consecutive complete scheduled cycles with no unresolved systemic failure and with per-source results visible."
        issues: [136, 140, 141, 149]
        next_action: "#149: wayback-save.yml's scope-split is verified working (run 36082098747) — close once a second clean run (scheduled or dispatched) confirms it wasn't a fluke. #141: still needs discover-harvest.yml (run 36082100347 or a fresh dispatch) to actually execute past `queued` before its fix can be called verified. #136/#140 close only once rondonia_crawler.yml is deprecated (pipeline-convergence)."

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
    evidence_prs: [190, 207]
    next_action: "Issue #121 (the transient-failure-becomes-permanent-loss defect) is fixed and merged (PR #190). #149's scope-split fix (PR #207) is verified: wayback-save.yml run 36082098747 completed successfully this session (all 8 matrix jobs). #141's companion discover-harvest.yml run (36082100347) is still queued — see kr-ro-recurring-cycle-health for why (runner starvation, not a fix failure) and what's still needed before closing. #136/#140 stay deferred to pipeline-convergence."

  - id: "pipeline-convergence"
    kind: workstream
    status: active
    parents: [ro-coverage-q4-2026, ingestion-resilience]
    objective: "Converge the legacy scrape path and manifest-driven discover→harvest path without regressing coverage or observability."
    origin: "RFC-0003; production fixes #93/#94 removed the original blocker."
    issues: [95]
    evidence_prs: [173, 179]
    next_action: "RFC-0003 Fase 1 is done (#176 implemented cdx-auto in discovery, merged via PR #179). #136/#140 (rondonia_crawler.yml timing out on high-volume Playwright range-scans) now give a concrete forcing function to plan the workflow redirection; still defer actually deprecating rondonia_crawler.yml until discover-harvest.yml has two clean weekly cycles as originally planned. Issue #95 (broader PRD: CaptureRef model, sources/ restructuring, LLM/compiler split) proposes a materially larger refactor than RFC-0003's scrape→harvest convergence — triaged 2026-09-25 and kept open as long-horizon reference, not folded into this workstream's Fase 2/3; fork a dedicated node from here if/when that broader refactor actually starts."

  - id: "dataset-release-integrity"
    kind: workstream
    status: active
    parents: [ro-coverage-q4-2026]
    objective: "Make every published dataset release independently citable and reproducible while preserving a convenient latest pointer for the portal."
    origin: "Verified risk from #151: scheduled releases default to --version 0 while the frontend points at leizilla-dataset-ro-v0."
    issues: [175, 196, 201, 205]
    evidence_prs: [198, 204, 210, 213, 215, 216, 218, 221, 222]
    next_action: "The 171-vs-199-row gap flagged last session is now ROOT-CAUSED, not just measured: this session diffed dispositivo counts for all 20 items in the live corpus against the published leizilla-dataset-ro-v0 parquet directly (xmllint + a small duckdb/ElementTree script, no IA credentials needed — all reads were public archive.org GETs). 19/20 items match their published row count exactly; the sole discrepancy is item 4 (leizilla-ro-lei-00004-1983), whose reparse produced only 3 dispositivos vs 20 previously published — its raw OCR is 12788 chars but parser.py's _OCR_CHAR_LIMIT was 8000 (texto_truncado=true in its live parsed_meta.json), so the LLM only ever saw 63% of the law. Item 13 (urn-lex literal 'null') is confirmed as the only remaining XSD-gate rejection via a live xmllint run against its actual IA-hosted law.xml — same root cause the DAG already suspected (issue #201), now traced to the model ignoring an explicit prompt instruction (same class as PR #218's roman-numeral fix), not an unrecoverable external IA gap as previously assumed. PR #221 (open, CI pending) raises _OCR_CHAR_LIMIT 8000->24000 and max_tokens 4096->16000. PR #222 (open, CI pending) adds a deterministic _strip_null_urn_lex post-parse step mirroring PR #218's pattern. Together these should let both items reparse cleanly, closing the row-floor gap entirely once merged and re-dispatched through parse-release.yml — this has NOT been re-verified live yet (needs the PRs merged, then a real parse-release.yml dispatch for items 4 and 13 specifically, then a fresh consolidate/release dry-run to confirm 20/20 items and >=199 rows)."

  - id: "legal-semantic-integrity"
    kind: objective
    status: active
    parents: [leizilla-root]
    objective: "Ensure the structured dataset never states stronger legal provenance, temporal status or identity semantics than the underlying evidence supports."
    origin: "Post-go-live schema/ETL review found date, temporal and identifier conflation risks."
    next_action: "Date-provenance, temporal-version and identifier-contract KRs are met. #195 (the deferred urn_lex-canonicalization slice of #118) closed via PR #206. Only release-validation-gated remains active, now solely on #201 (2 known-bad already-published items) — see that KR."
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
        current: "Issue #118 closed (2026-09-24) via two merged PRs: `versao_id` uniqueness was already enforced pre-existing; PR #193 added the row-count floor guard on `release-dataset` (refuses to publish fewer rows than the currently published release, latest-pointer-first with legacy-item fallback); PR #192 added empty/missing `ia-id` rejection in `xml_to_rows` and wired the existing `_xsd_gate` into `consolidate` (previously only `parse`/`parse-all` ran it). Deliberately NOT done: a hard urn_lex-grammar validation at the export boundary (tracked as its own follow-up, issue #195, since it was found to regress the intentional lei_id-fallback degradation `_parse_lei_fields` uses for an unparseable/mis-cased urn-lex from PR #191/#127). PR #193's floor guard itself then blocked the actual first `-latest` release live in production — archive.org returns 503, not 404, for a file under a nonexistent item, which the guard read as inconclusive; fixed in PR #198 (existence check via `archive.org/metadata`) — see dataset-release-integrity/#196 for the live incident this caused."
        target: "All ETL-build and release boundaries fail closed on declared floor violations and emit actionable diagnostics."
        issues: [118, 201]
        evidence_prs: [192, 193, 198, 206, 213, 216, 218, 222]
        next_action: "None on #118 (closed). #195 closed via merged PR #206. #201's item 13 (`urn-lex=\"null\"`) is NOT an external IA-side gap after all — this session traced it to the parser LLM ignoring the prompt's explicit \"omit the attribute, never write the literal null\" instruction (confirmed live via xmllint against item 13's actual IA-hosted law.xml). PR #222 (open, CI pending) adds a deterministic `_strip_null_urn_lex` post-parse step, the same pattern PR #218 used for roman-numeral paths. See dataset-release-integrity for item 4's parallel fix (PR #221) and what's needed to re-verify both live once merged."

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
    issues: [118, 201]
    evidence_prs: [192, 193, 198, 206, 213, 215, 216, 218, 221, 222]
    next_action: "See legal-semantic-integrity's kr-release-validation-gated for what's merged. #201's two remaining rejections (item 4: truncated OCR input; item 13: literal urn-lex=\"null\") are both root-caused and have open fix PRs this session (#221, #222 respectively) — neither is the unrecoverable external IA gap previously assumed. See dataset-release-integrity for the live forensics and what's left to re-verify once both merge."

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
        current: "The schema-level conflation this KR depended on (date-provenance, #157) is resolved and closed. This session found WHY the prior official visual-capture attempt (commit 84cfdc6, run 33956952230) timed out loading versoes.parquet, and it is not flakiness: see the new browser-read-cors-integrity node — archive.org never sends CORS for .parquet downloads, so read_parquet() cannot succeed from any real browser today, reproduced live via Playwright against the actually-published dataset. Also confirmed this session: EXPORT_COLUMNS in model.ts already uses `data_ato`, not the legacy `data_publicacao` name issue #167 was filed against — the published v0 parquet's own schema uses `data_ato` too (confirmed via direct duckdb read of the live dataset), so criterion 1 of #167 (legacy field name in JSON/CSV downloads) may already be moot; only criterion 3 (inicio_tipo='data-publicacao' rendered categorically as 'vigência desde a publicação' in Versoes.svelte/model.ts's INICIO_TIPO_LABELS) still looks live. Re-scope #167 against current field names before implementing."
        target: "0 known misleading labels; legacy fields are explained where still published."
        blockers: ["browser-read-cors-integrity — the Dados section cannot be observed against real, populated data (not just a fallback state) from any real browser until the CORS gap is fixed, ports causaganha's proxy, or a canonical UI fixture is built."]
        issues: [167]
        next_action: "Do not implement #167's UI change yet. Re-check which of its 3 criteria still apply given data_ato is already the live column name (only inicio_tipo='data-publicacao' labeling looks outstanding). Resume path is now clearer: either resolve browser-read-cors-integrity (proxy or fixed IA CORS) so a real `/lei/?id=...` capture becomes possible, or build a canonical UI fixture (e.g. a vitest+jsdom render of `Dados.svelte`/`Versoes.svelte` against representative sample rows, following the existing model.test.ts pattern) — only then add whatever disclosure copy is still warranted."
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

  - id: "browser-read-cors-integrity"
    kind: workstream
    status: active
    parents: [leizilla-root, public-surface-auditability]
    objective: "Make the browser's direct read of the published Parquet via DuckDB-WASM actually work in real browsers — ADR-0001's core claim that the Internet Archive alone (no servers) is enough to serve the product."
    origin: "New front registered 2026-09-25 while investigating #167's resume precondition. archive.org/download/{item}/{file} never sends Access-Control-Allow-Origin for .parquet files (application/octet-stream) but does for .json files of the SAME item on the SAME storage node — confirmed live via curl (with a real browser Origin header) against the published leizilla-dataset-ro-v0, and reproduced end-to-end with Playwright against a local astro dev server pointed at that real dataset: read_parquet() fails in-browser with a generic NetworkError on every attempt. This is very likely why the #167 visual-capture attempt (run 33956952230) timed out — not flakiness, a permanent per-file CORS gap. The identical root cause was already found and fixed (implementation ready, deploy blocked on missing Cloudflare credentials) in the sibling causaganha project: issue #1482 / PR #1521 there."
    issues: [223]
    evidence_prs: [224]
    next_action: "PR #224 (open, CI pending) is a mitigation, not a fix: it adds probeDatasetAccess() (web/src/lib/db.ts) to distinguish this permanent CORS block from a generic transient failure, so DatasetUnavailable.svelte stops telling users 'try again' for something that will never succeed. The actual fix needs a proxy (porting causaganha's Cloudflare Worker pattern) — an infrastructure decision beyond IA/GitHub that deserves an ADR given CLAUDE.md's infrastructure-minimal principle, and needs Cloudflare (or equivalent) credentials no session has had yet. Also still open: confirm this reproduces against the actually-deployed franklinbaldo.github.io site (this session only verified against a local astro dev server), and consider reporting the CORS gap to Internet Archive directly since it may be fixable upstream with no proxy needed at all."

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
    next_action: "#175, #157, #118 and #195 (urn_lex gate, PR #206) are all resolved. Re-evaluate this blocker once #201 (2 known-bad already-published `ro` items) and the first `-latest` release (#196) are resolved — federal expansion shouldn't export the same class of unresolved release-quality debt. Maintain Planalto pipeline readiness in the meantime."
    blockers:
      - "Issue #201 — 2 known-bad already-published ro items still failing the release XSD gate."
      - "Issue #196 — the first -latest dataset release is still unpublished."
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
