---
type: "Project Map"
title: "Leizilla Project DAG"
description: "Canonical OKF graph of Leizilla delivery fronts, OKRs, dependencies, blockers and next actions. Work branches and GitHub issues execute the graph; they are not the durable project ledger."
tags: [leizilla, okf, project-dag, okr, delivery, governance]
timestamp: 2026-09-25T09:25:00+00:00
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
    next_action: "First S1-S4 production baseline captured 2026-09-25 (see kr-ro-backlog-conversion). #149's scope-split fix (PR #207) is now VERIFIED for wayback-save.yml: run 36082098747 reached `completed`/`success` this session — all 8 per-tipo matrix jobs finished cleanly, none hit the old 360min timeout. #141's companion discover-harvest.yml run (36082100347, `max-parallel: 1`) is NOT stuck, just slow by design: its `lei` matrix job (discover 1h31m + harvest 1h24m) completed `success` this session, and `lc` started right after — confirms the serialized-by-tipo approach works, but a full 8-tipo cycle now takes many hours per dispatch (was NOT observed to full completion this session; 6 of 8 tipos still queued behind `lc` as of session end). This is the real remaining question for kr-ro-recurring-cycle-health: does a full cycle now fit inside the weekly schedule's cron-to-cron window, or does the serialization trade timeout-avoidance for a cycle that never finishes before the next one is due? Next session: check run 36082100347's final conclusion and total wall-clock time; if it exceeds ~7 days keep #141 open and consider bounding matrix scope per scheduled run rather than max-parallel alone. #136/#140 stay deferred to pipeline-convergence. Re-checked 2026-09-25T05:45Z (later same day, new session): run 36082100347 is STILL in progress — `lei` remains the only completed matrix job, `lc` started at 04:23Z and was mid-discovery ~1h later, the other 5 tipos (resolucao, decreto-lei, portaria, ec, decreto) still queued. So ~3h in and only 1/8 tipos fully done — the full-cycle wall-clock question is not yet answerable and stays the single most important thing for the next session to check (either this run's eventual conclusion, or a subsequent scheduled run). Re-checked again 2026-09-25T06:45Z (same session as the 05:45Z note, ~1h later): `lc`'s Discover step is still running (started 04:23:53Z, so ~2h20m into discover alone at this check) — consistent with steady, non-hung progress rather than a new data point on total pace; still 6/8 tipos not yet started. This session also merged PR #227 (the previous session's stewardship PR) and PR #228 (fail-closed fix for a distinct data-publicacao default bug found while investigating #167 — see legal-semantic-integrity), and opened issue #229 for a related evidence-capture gap; did not dispatch decreto parsing (same daily-Gemini-quota reasoning as the 05:22Z note — the scheduled parse-release.yml cron for 2026-09-25 appears not to have fired yet as of this check, so its quota window is still live). New session 2026-09-25T07:2xZ: re-checked run 36082100347 — `lc`'s Discover step is now ~3h into discovery alone (started 04:23:53Z, still `in_progress` at 07:27Z), still 6/8 tipos not yet started; genuinely progressing (not hung) but this pushes the full-cycle wall-clock estimate higher still, reinforcing that a single scheduled dispatch may not complete before the next one is due — still the open question for kr-ro-recurring-cycle-health. Also this session: confirmed parse-release.yml's schedule reliably fires 4-6h late (10-12 UTC, not 06:00 UTC) on this low-traffic repo, and used that finding plus the cron's own 2-request/day spare margin to dispatch a small (`limit=2`) decreto parse (run 36107356330) without risking today's scheduled cron — see kr-ro-backlog-conversion. Opened PR #230 implementing issue #229 (surfaces `<inicio>/<fonte>` evidence into the Parquet and UI) — see legal-semantic-integrity. New session 2026-09-25T08:2x-08:40Z: root-caused #141's actual mechanism — it was never IA rate-limiting per se, it was `harvest-parallel`'s matrix re-running the full, non-tipo-scoped `leizilla discover` inside EACH of the 7 serialized matrix jobs (confirmed via run 36082100347's job log: `lc`'s Discover step alone ran >4h, still in_progress at session end, 6/8 tipos still queued behind it). Fixed on branch (not yet merged): split into a `discover-shared` job (runs discovery once, uploads the DuckDB as a build artifact) and a `harvest-parallel` matrix that downloads it and only harvests — see kr-ro-recurring-cycle-health. Also found and fixed a distinct, previously invisible bug: the `-latest` dataset release was silently stale (missing 2/22 already-\"structured\" casacivil items) because `fetch-all-parsed` ran ~20s after the parse job's IA upload and the Internet Archive's own listing hadn't indexed the new items yet — confirmed via job logs (the SAME run's own `coverage --upload` step at its tail still showed `decreto: S4=0`, contradicting the 2 decretos it had just parsed). Filed as issue #233. Fixed for now with a zero-LLM-cost re-dispatch (`parse-release.yml` workflow_dispatch, `limit=0`, `skip_existing=true` — `parse-all`'s `processed >= limit` check breaks before any item is attempted, so `parse-dispatch` does no new LLM calls, but the `etl` job still re-runs `fetch-all-parsed`→`consolidate`→`release-dataset` against IA's now-caught-up listing): `-latest` republished as revision `20260925t082945z`, git_sha `714fa94` (includes PR #230's `inicio_fontes` column), 445 rows (up from 223 — verified per-`lei_id` this is 100% real content from the 2 previously-missing decretos, `leizilla-ro-decreto-00010-1981` alone contributes 155 rows; no duplication)."
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
        current: "First production baseline captured 2026-09-25 (`uv run leizilla coverage --ente ro --json`, read-only against IA, reproducible by anyone with network access — no IA/LLM credentials required): ente=ro, fontes=casacivil+assembleia. casacivil: S1=1196 S2=1196 S3=572 S4=20 (decreto: S1=307 S2=307 S3=215 S4=0; lei: S1=889 S2=889 S3=357 S4=20). assembleia: S1=S2=S3=S4=0 (no resources discovered yet for this fonte). Denominator frozen: pre-S4 backlog = S1 total − S4 total = 1196 − 20 = 1176. First movement off the frozen baseline confirmed 2026-09-25T07:37Z (same session as the PR #230/#231 merges): re-ran `uv run leizilla coverage --ente ro --json` after the `limit=2` decreto dispatch (run 36107356330, completed `success`) — decreto S4 moved 0 → 2, casacivil total S4 20 → 22. Small (2/1176 ≈ 0.17%) but real, reproducible, non-credentialed evidence that the workflow_dispatch decreto lever from this session's earlier next_action works end-to-end (parse → upload → consolidate → release)."
        target: "Reduce the first measured pre-S4 backlog by at least 50% by 2026-12-31 without relaxing provenance/quality gates — i.e. S4 ≥ 608 (currently 22) against the frozen S1=1196 denominator."
        next_action: "Confirmed 2026-09-25T07:2x-07:37Z (same session): this repo's daily parse-release.yml SCHEDULE reliably fires 4-6h late (10:21-12:03 UTC across its last 10 scheduled runs, not the nominal 06:00 UTC cron), so a workflow_dispatch made before ~10 UTC on a given day still has the full daily Gemini free-tier quota available. Used that plus the cron's own reserved 2-request/day margin (20/day quota − 18/day cron budget = 2 spare) to dispatch a `limit=2` decreto batch (run 36107356330) — completed `success`, and `uv run leizilla coverage --ente ro --json` confirms decreto S4 0 → 2 (casacivil total 20 → 22). This is now a proven, repeatable, low-risk lever: before ~10 UTC on any day, dispatch parse-release.yml (workflow_dispatch, ente=ro fonte=casacivil tipo=decreto, `limit=2`, `skip_existing=true`) and re-read coverage to confirm growth — repeating this daily would close ~2/1176 of the frozen backlog per day (~persistent but slow; a session with idle Gemini-quota margin at a different time of day, or a maintainer raising the per-dispatch limit once quota headroom is independently confirmed, would accelerate this materially faster than the ~600-day pace 2/day implies). Do NOT repeat the dispatch lever again on the same UTC day it was already used — this session already spent the day's 2-request spare margin on the run above; re-running `leizilla coverage --ente ro --json` this same session confirmed the numbers are stable (decreto S4=2, no drift), so a second dispatch today would only have risked today's still-pending scheduled cron's quota for no measurable gain. Separately (see ro-coverage-q4-2026's next_action and issue #233): this session found and fixed the `-latest` release itself was lagging 2 items behind what `kr-ro-s1-s4-observable`'s own coverage baseline already counted as S4 — republished via a zero-LLM-cost `limit=0` dispatch, now at 445 rows / git_sha 714fa94, genuinely matching the 22-item S4 count."
      - id: "kr-ro-recurring-cycle-health"
        status: active
        metric: "Consecutive scheduled discover/harvest/parse/release cycles without an unresolved systemic failure."
        current: "#114 and #121 closed with evidence (2026-09-24). #141 closed 2026-09-25T00:35Z (github-actions bot issue, closed_by PR #207) — dropped from this KR's issues list; #136/#140/#149 remain open. #136/#140 are the legacy rondonia_crawler.yml Playwright range-scan exceeding the 360min job timeout on high-volume sources (untouched — gated on pipeline-convergence); #149 is wayback-save.yml's fixed 2s/URL pacing exceeding the 360min budget, PR #207's scope-split fix CONFIRMED working (run 36082098747, all 8 matrix jobs green) but still awaiting a second clean SCHEDULED run (wayback-save.yml's cron is Monday 03:00 UTC — next fire 2026-09-28, none fired between sessions yet). Root cause of the still-in-progress discover-harvest.yml run (36082100347, dispatched 2026-09-25T01:27Z) is now understood, not just observed: `lc`'s Discover step alone ran >4h (still in_progress at this session's end, 07:2x-08:4xZ checks) because `harvest-parallel`'s matrix re-ran the FULL, non-tipo-scoped `leizilla discover` inside every one of its 7 serialized (`max-parallel: 1`) jobs — 7x redundant full-site discovery, not IA rate-limiting or inherent harvest slowness. Fixed this session on branch (PR pending, not yet merged or verified against a live run): `.github/workflows/discover-harvest.yml` now has a `discover-shared` job that runs discovery once and hands the resulting DuckDB to the 7 harvest-only matrix jobs via `actions/upload-artifact`/`download-artifact`. Also confirmed via workflow source: `concurrency: {group: discover-harvest, cancel-in-progress: false}` means tomorrow's scheduled run (cron `0 2 * * 6`, next fire 2026-09-26T02:00Z) will queue behind run 36082100347 rather than execute in parallel or corrupt state — safe, but means that scheduled cycle may effectively not run/complete on schedule either, until the fix above lands and a full cycle actually finishes fast enough to clear before the next Saturday."
        target: "2 consecutive complete scheduled cycles with no unresolved systemic failure and with per-source results visible."
        issues: [136, 140, 149]
        next_action: "MERGED 2026-09-25T09:21:35Z: PR #234 (discover-shared/harvest-parallel split) merged to main (squash 383af50), well before the 2026-09-26T02:00Z Saturday cron — that scheduled run will be the first real test of the fix (or check discover-harvest.yml run 36082100347 from this session, which was still in_progress at merge time and running the OLD workflow version — its eventual conclusion is a data point on the old behavior's worst case, not the fix). Next session must verify: (a) the artifact hand-off works (harvest-parallel jobs actually find and use the downloaded DuckDB, i.e. resources discovered by discover-shared are the ones harvested), and (b) total wall-clock for a full cycle drops sharply now that discovery runs once instead of 7x — if a full cycle still doesn't fit the weekly window even with this fix, the next lever is bounding matrix tipo scope per scheduled run (e.g. rotate a subset of tipos weekly) rather than touching max-parallel again. #149 closes only after a second clean SCHEDULED (not dispatched) wayback-save.yml run — check after 2026-09-28T03:00Z. #136/#140 close only once rondonia_crawler.yml is deprecated (pipeline-convergence)."

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
    issues: [136, 140, 149]
    evidence_prs: [190, 207]
    next_action: "Issue #121 (the transient-failure-becomes-permanent-loss defect) is fixed and merged (PR #190). #149's scope-split fix (PR #207) is verified working (wayback-save.yml run 36082098747, all 8 matrix jobs green) but still needs a second SCHEDULED (not dispatched) clean run before closing — see kr-ro-recurring-cycle-health. #141 CLOSED 2026-09-25 (PR #207) — dropped from this node's issues list, but its actual root cause (discover re-run inside every harvest-parallel matrix job, not IA rate-limiting) was only found and fixed THIS session, on branch, not yet merged — see kr-ro-recurring-cycle-health for the discover-shared/harvest-parallel split and its verification status. #136/#140 stay deferred to pipeline-convergence. Also this session: found and filed issue #233 — `fetch-all-parsed` can run before the Internet Archive's own item listing has indexed a just-uploaded parse, silently making `-latest` releases miss items the same workflow run just parsed; not fixed (documented as accepted 1-cycle lag or a future retry, see the issue) but worked around live via a follow-up zero-LLM-cost republish — see dataset-release-integrity."

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
    issues: [175, 201, 233]
    evidence_prs: [198, 204, 210, 213, 215, 216, 218, 221, 222, 230]
    next_action: "New session 2026-09-25T08:2x-08:40Z: found `-latest` was silently stale again, one day after the previous session's milestone republish below — `fetch-all-parsed` (in the `etl` job) ran ~20s after a same-run parse job's IA upload and missed the 2 just-uploaded decreto items because the Internet Archive's own listing hadn't indexed them yet (confirmed via that exact run's own `coverage --upload` step at its tail still showing `decreto: S4=0`). Filed as issue #233 (root cause + two possible future fixes, neither implemented this session). Worked around live: a zero-LLM-cost `parse-release.yml` workflow_dispatch (`limit=0`, so `parse-all`'s `processed >= limit` check does zero new parses, but the `etl` job still re-runs `fetch-all-parsed`→`consolidate`→`release-dataset` against IA's by-then-caught-up listing) republished `-latest` as revision `20260925t082945z`, git_sha `714fa94` (now includes PR #230's `inicio_fontes` column), 445 rows — up from 223, and verified per-`lei_id` this is 100% genuine content from the 2 previously-missing decretos (`leizilla-ro-decreto-00010-1981` alone contributes 155 of the 222 new rows), not a duplication bug. Also checked directly against the live published Parquet (server-side DuckDB `read_parquet`, not a browser — sidesteps browser-read-cors-integrity's CORS gap entirely): 0/445 rows currently have `inicio_fontes` populated and 0/445 have `inicio_tipo='data-publicacao'` — the current small corpus simply has no XML with an explicit `<inicio>` assertion yet, so PR #230's evidence-links feature and #167's flagged categorical-label concern both have zero live instances right now; see legal-semantic-integrity/public-surface-auditability for what this means for #167's priority. MILESTONE (previous session): leizilla-dataset-ro-v0-latest published for the first time ever that session. parse-release.yml run 36094205340 (workflow_dispatch, ro/casacivil/lei items 4-13, skip_existing=false) completed successfully: item 4 reparsed cleanly (PR #221's OCR/token-limit fix, confirmed — was truncated at 8000/12788 OCR chars, now 24000); consolidate reached 19/20 items → 209 rows (≥199 floor, previously 171); release-dataset published leizilla-dataset-ro-v0-20260925t042644z and updated -latest — confirmed live via archive.org/metadata (previously 503). Restores the live public site (web/src/lib/db.ts defaults PUBLIC_PARQUET_URL to this exact -latest pointer). Issues #196/#205 closed with this evidence. Item 13 alone remains excluded — see legal-semantic-integrity's kr-release-validation-gated and issue #201. Re-investigated 2026-09-25T05:45Z: queried `archive.org/metadata/leizilla_ro_casacivil_lei_0001-1000` (the actual raw range-bucket item, per ADR-0011) directly — lei-00013_85b0957e.pdf is confirmed image-only (`_imgonly_pdfmeta.json` present, no `_djvu.txt` among its files) AND the item currently carries ~140 `pending_tasks` (`archive.php`, status `queued`) — i.e. the Internet Archive is mid-reprocessing this item right now (plausibly triggered by the numerous re-uploads/reparses across this and prior sessions), not permanently refusing to OCR it. This is materially softer than the prior 'confirmed genuine external IA gap' conclusion: the pending task queue may itself eventually produce the missing djvu.txt once it drains. Revised next_action: do NOT start building a local-OCR fallback yet — re-check `archive.org/metadata/leizilla_ro_casacivil_lei_0001-1000` for `pending_tasks` and lei-00013_85b0957e_djvu.txt in a later session (after the queue has had time to drain); only pursue local-OCR fallback or explicit IA re-derive request if the file is still image-only-with-no-djvu once pending_tasks clears to empty/near-empty. Re-confirmed 2026-09-25T07:3xZ (new session): `archive.org/metadata/leizilla_ro_casacivil_lei_0001-1000` still has `pending_tasks: true` and lei-00013_85b0957e still has no `_djvu.txt` among its files — no change since the 05:45Z reading, queue has not visibly drained yet; still not worth starting a local-OCR fallback."

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
        current: "Schema/ETL/checker conflation resolved: PR #170 merged, issue #157 closed with evidence (2026-09-24) — `inicio_tipo`'s no-explicit-`<inicio>` fallback is `data-ato`, not `data-publicacao`; docs/SCHEMA.md, the consistency checker and etl.py agree. #167 (frontend JSON/CSV downloads still expose the legacy `data_publicacao` name without explanation) remains open — also tracked under public-surface-auditability's kr-public-semantic-legibility; DAG already confirmed EXPORT_COLUMNS uses `data_ato`, so #167's criterion 1 is moot, only criterion 3 (`inicio_tipo=data-publicacao` rendered categorically) is live. New finding this session (PR #228, merged): a second, separate conflation risk existed one layer deeper — `xml_to_rows` defaulted a malformed `<inicio>` missing its `tipo` attribute to `data-publicacao` itself (the exact value docs/SCHEMA.md says must never be a default), so a non-XSD-gated XML could silently assert the strongest publication-evidence claim the schema supports. Fixed fail-closed (raises ValueError, mirrors the existing ia-id gate). Also found while fixing it: the `<fonte>` evidence element the schema requires inside `<inicio>` (proof of the publication claim) is read from XML for XSD validation but never extracted into `xml_to_rows`' output rows — it's schema-mandated but silently dropped before reaching the Parquet, so even a legitimate `data-publicacao` claim has no visible evidence in the published dataset or UI. Registered as issue #229 rather than implemented immediately (it's a schema/column extension touching etl.py, docs/SCHEMA.md, web/src/lib/db.ts, model.ts and Versoes.svelte, not a fail-closed one-liner)."
        target: "0 known conflations; explicit publication provenance remains distinct from date-of-act fallback."
        issues: [167, 229]
        evidence_prs: [170, 228, 230]
        next_action: "#167 has its own resume precondition (official visual capture of /lei/'s Dados section must succeed again, or a canonical UI fixture must exist) before implementing the frontend disclosure copy — see public-surface-auditability. #229 CLOSED this session: PR #230 merged (squash bc9b67f) — adds `inicio_fontes` (VARCHAR JSON, same {ia_id} shape as `fontes`) to PARQUET_SCHEMA/xml_to_rows, fail-closed on a missing ia-id, documents it in docs/SCHEMA.md §3.1, and surfaces it through LeiRow/EXPORT_COLUMNS/Versoes.svelte as archive.org evidence links next to each version's inicio_tipo label. All CI checks green (lint-test, build, GitGuardian, check-credentials, capture) and Codex security review completed with no findings before merge. New session 2026-09-25T08:3xZ: queried the live published Parquet directly (server-side DuckDB, not a browser) — 0/445 rows have `inicio_tipo='data-publicacao'` (100% are `data-ato`) and 0/445 have `inicio_fontes` populated (no XML in the current 22-item corpus asserts an explicit `<inicio>` at all yet). So #167's criterion 3 (the categorical \"vigência desde a publicação\" label) currently has zero live manifestation to observe or fix against — this doesn't close #167 (the code path is still reachable whenever a future parse does assert `data-publicacao`), but it does mean there's no real data to build #167's required non-fabricated fixture from yet, and lowers this KR's urgency relative to other live fronts. Only #167 remains open on this KR."
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
        issues: [118, 201, 229]
        evidence_prs: [192, 193, 198, 206, 213, 216, 218, 221, 222, 228, 230]
        next_action: "None on #118 (closed). #195 closed via merged PR #206. #201's item 4 is fully resolved (PR #221, confirmed live in run 36094205340). Item 13's PDF is still image-only with no djvu.txt as of 2026-09-25T06:45Z (re-confirmed this session — still absent among the item's files, item metadata `updatedate` unchanged since 2026-06-25, `pending_tasks` flag still true), and its raw IA item (leizilla_ro_casacivil_lei_0001-1000) is reported to still have pending archive.php tasks queued — see dataset-release-integrity for the revised (softer) read: this may resolve on its own once IA's queue drains, so hold off on a local-OCR fallback until that's ruled out. -latest published this session regardless (floor guard passed on total row count). Unrelated to #201 but same KR: PR #228 (merged) closes a second release-boundary gap — <inicio> without tipo could silently publish as data-publicacao; see kr-date-provenance-honest and issue #229 for the follow-up (evidence capture) this surfaced."

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
    issues: [118, 201, 229]
    evidence_prs: [192, 193, 198, 206, 213, 215, 216, 218, 221, 222, 228, 230]
    next_action: "See legal-semantic-integrity's kr-release-validation-gated for what's merged. `-latest` published for the first time this session (run 36094205340, 209 rows). Item 4 fully resolved (PR #221). Item 13's OCR-derivative gap still has no djvu.txt as of 2026-09-25T06:45Z; the raw item's pending-tasks flag is still set, so it may resolve without any Leizilla-side fix — see dataset-release-integrity for the forensics and revised next steps. PR #228 (merged) closed a distinct gate gap: <inicio> without tipo could silently publish as data-publicacao; issue #229 tracks the follow-up (the schema-mandated <inicio>/<fonte> evidence is parsed for XSD validation but never reaches the Parquet)."

  - id: "public-surface-auditability"
    kind: objective
    status: active
    parents: [leizilla-root, legal-semantic-integrity]
    objective: "Make the public portal legible and auditable on desktop and narrow viewports, with evidence/provenance semantics matching the dataset."
    origin: "Public-product reviews after M13."
    issues: [167, 229]
    next_action: "kr-public-responsive-audit and kr-law-page-regression-tests are met. #229 closed (PR #230). kr-public-semantic-legibility made real progress this session (fixture + label copy fix, PR #238) but stays blocked — #167's criterion 6 needs a live post-change observation of /lei/ that browser-read-cors-integrity currently makes impossible in any real browser — see that KR."
    key_results:
      - id: "kr-public-semantic-legibility"
        status: blocked
        metric: "Known public labels/download affordances that imply stronger publication/vigência evidence than the dataset supports."
        current: "Criterion 3 (categorical data-publicacao label) fixed and criteria 1/2/4/5 satisfied/moot this session — see below — but this KR is NOT fully met: verified directly against issue #167's own text that criterion 6 has two parts, not one. Part A (resume precondition: capture works again OR a canonical fixture exists) is satisfied by the fixture. Part B is separate and still open: 'Depois da mudança, a mesma rota precisa ser observada já publicada em desktop e celular' — after the change ships, the live route must actually be observed, published, on desktop and mobile. That observation is impossible today because of browser-read-cors-integrity (IA sends no CORS for .parquet, so no real browser can load any law page at all right now) — this is why status here is 'blocked', not 'met', and #167 stays open. The subagent PR that implemented this (merged, see evidence_prs) recommended closing #167 outright; verified against the issue's literal criteria before doing so and found criterion 6 Part B unmet, so did not close it — flagged with a PR/DAG-citing comment on the issue instead. RESOLVED this session via the canonical-UI-fixture resume path this KR's own previous next_action proposed (browser-read-cors-integrity is still unfixed — unrelated, no longer a blocker here). Added `web/src/components/lei/Versoes.test.ts` and `Dados.test.ts`: real Svelte 5 `mount`/`unmount` renders (jsdom, vitest — same tool as model.test.ts, applied to components for the first time) against representative fixture rows for `inicio_tipo='data-ato'`, `'data-publicacao'` with `inicio_fontes` (PR #230's evidence links), and `'data-publicacao'` without `inicio_fontes` (the legacy/unevidenced case #167 flags). This directly satisfies #167's own stated resume condition #6 ('quando o projeto ganhar uma fixture real/canônica de interface que represente o mesmo conjunto sem fabricar conteúdo') — a synthetic test fixture characterizing rendering behavior, not a claim about production data, so it doesn't conflict with #167's separate 'sem fabricar conteúdo' caution about *live* evidence. Finding: `Dados.svelte` renders no `inicio_tipo`/provenance label at all (only download buttons, dataset links, URN-LEX) — #167's criterion 3 concern lives entirely in `Versoes.svelte`'s per-version history line, confirmed by a dedicated fixture assertion. Finding in Versoes.svelte: the base label text ('vigência desde a publicação') was byte-identical whether or not `inicio_fontes` evidence existed — confirmed via a fixture test asserting `.inicio` textContent equality across both cases — so the evidence link alone (#229/PR #230) did not itself de-categorize the claim for a reader skimming the label. Judgment call made: this reads misleadingly categorical for the no-evidence case, so applied the minimal fix criterion 3 asked for — Versoes.svelte now renders '(sem evidência registrada no dataset)' next to any `inicio_tipo='data-publicacao'` version lacking `inicio_fontes`, distinguishing an unevidenced legacy claim from a proven one without touching the `data-ato` label (already accurate per SCHEMA.md §4.4 — it's a documented default, not a publication claim) or any export column (criteria 4/5 unaffected: JSON/CSV/EXPORT_COLUMNS untouched, fix is local to one .svelte file). `npm test` (vitest): 60/60 passing (53 pre-existing + 7 new); `npm run build` (astro) succeeds. vitest.config.ts gained `@sveltejs/vite-plugin-svelte` (already a transitive devDependency via @astrojs/svelte, no new package) plus the same client-build `svelte` alias astro.config.mjs already uses in production, so `mount`/`unmount` resolve to the client runtime under Vitest's SSR module pipeline instead of svelte's server build — verified this doesn't regress db.test.ts (a naive `resolve.conditions: ['browser']` alternative does, by flipping @duckdb/duckdb-wasm onto a browser Worker bundle jsdom can't satisfy)."
        target: "0 known misleading labels; legacy fields are explained where still published."
        blockers: ["browser-read-cors-integrity — issue #167's criterion 6 Part B requires observing the changed route live, published, on desktop and mobile; no real browser can load any law page today because archive.org sends no CORS header for .parquet."]
        issues: [167]
        evidence_prs: [230, 238]
        next_action: "#167 stays open: criterion 3 (categorical label) resolved, criterion 6 Part A (resume precondition) resolved via the fixture, criteria 1/2/4/5 satisfied or moot. Criterion 6 Part B (post-change live observation, desktop+mobile) is unmet and unmeetable until browser-read-cors-integrity is fixed — resolving that front (Cloudflare Worker proxy per ADR-0013, or an IA-side fix) is this KR's actual remaining next action, not further UI work. Once a real capture of /lei/ succeeds again, take it and close #167 with that evidence."
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
    origin: "New front registered 2026-09-25 while investigating #167's resume precondition. archive.org/download/{item}/{file} never sends Access-Control-Allow-Origin for .parquet files (application/octet-stream) but does for .json files of the SAME item on the SAME storage node."
    issues: [223]
    evidence_prs: [224]
    next_action: "ADR-0013 (docs/adr/0013-cors-proxy-parquet-browser-read.md) written this session: registers the decision (port causaganha's Cloudflare Worker proxy as the primary fix, pursue reporting the gap to the Internet Archive in parallel, non-blocking) per issue #223's own next-action item 2 and CLAUDE.md's infrastructure-minimal principle. Issue #223's next-action item 1 (confirm against the real deployed site, not just archive.org generically) is also done this session: curled the exact `-latest` pointer the live site's db.ts fallback uses (`archive.org/download/leizilla-dataset-ro-v0-latest/versoes.parquet`) with `Origin: https://franklinbaldo.github.io` — 206 Partial Content, no access-control-allow-origin, while dataset_meta.json on the same item has it. Both re-confirm PR #224's mitigation is still needed and correct, not yet a fix. Still blocked: Cloudflare (or equivalent) credentials no session has had yet — the Worker code to port already exists and is validated in production at causaganha (issue #1482/PR #1521 there), so this is a credential gap, not an engineering unknown. Reporting the CORS gap to the Internet Archive itself (ADR-0013's parallel path) needs a maintainer with an IA support channel — no session has one. This is an external/infrastructure blocker, not a Leizilla code defect — no further code-level PR should attempt to work around it beyond the classification already merged (PR #224) and the decision now on record (ADR-0013)."

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
    next_action: "#175, #157, #118 and #195 (urn_lex gate, PR #206) are all resolved. #196 is resolved — `-latest` published for the first time this session (run 36094205340, 209 rows). #201 is down to item 13 alone, confirmed a genuine external IA OCR-derivative gap (not a Leizilla code defect). Re-evaluate whether this single-item residual gap is acceptable to export alongside federal expansion, or whether it should block until resolved — a judgment call for the next session/maintainer, not yet made."
    blockers:
      - "Issue #201 — down to 1 item (item 13), confirmed external IA gap (no OCR derivative); not a code defect, needs either IA re-derivation or a local-OCR fallback."

  - id: "dependency-security-hygiene"
    kind: workstream
    status: active
    parents: [leizilla-root]
    objective: "Keep known-vulnerable dependencies out of the build/runtime surface without waiting for a dedicated incident."
    origin: "GitHub Dependabot summary surfaced 24 alerts (2 critical, 8 high, 13 moderate, 1 low) on the default branch on push during this session; `npm audit` in web/ independently confirmed 15 of them (1 critical, 7 high, 7 moderate) across astro/vite/esbuild/postcss/js-yaml/nanoid/sharp/svgo/smol-toml/devalue."
    current: "`npm audit fix` (non-major only) plus one explicit `postcss` override (nested transitively under astro's own vite dependency at <=8.5.22, GHSA-fxqj-rqcc-2cmp, not reachable by the top-level fix) resolved all critical/high findings in web/: 15 -> 2, both moderate. `npm test` (53/53) and `npm run build` verified green against the updated lockfile."
    target: "0 critical/high vulnerabilities in web/'s dependency tree; residual moderate findings tracked with an explicit reason, not silently ignored."
    next_action: "2 moderate findings remain (vitest/@vitest/mocker path-traversal, GHSA-82fw-gwwq-j7x9), deliberately not fixed here: the only available fix is a vitest 3->5 major bump, dev-only tooling (not shipped to the built site), and risks breaking the test API surface — deserves its own verified PR, not a blind `npm audit fix --force` riding this sweep. The Python side (pyproject.toml) was not audited this session (no `pip-audit`/equivalent run) — GitHub's 24-alert total exceeds npm's 15, so up to 9 alerts (the gap) may be Python-side or GitHub-Actions-side and still unexamined; a future session should run a Python dependency audit and check `.github/workflows/` action pins."
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
