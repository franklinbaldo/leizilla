# Dataset publication failures

`release-dataset` succeeds only after the immutable release and the default
`latest` pointer have been uploaded and their public files match the candidate
byte-for-byte (SHA-256). The release checks `versoes.parquet` and
`dataset_meta.json`; latest checks both plus `latest.json`. A zero upload exit
status alone is insufficient. Verification uses at most three GETs per file,
waiting 30 and 60 seconds when bytes are stale or reads fail transiently. Access
refusals (including 403/429) stop immediately. Already confirmed files are not
read again. Visibility after this window is unconfirmed and produces exit 1.

Upload refusals mentioning spam, reduced request rate, queue quota, SlowDown or
429 are not retried. The `ia` CLI does not expose reliable Retry-After headers;
we do not guess a cooldown for these refusals. Other recognized transport/5xx
failures receive at most three attempts, waiting 30 and 60 seconds plus up to
25% jitter. This shared upload policy also applies to raw/parsed/coverage uploads.
Unknown errors still stop immediately. This is per invocation, not a distributed
rate limiter across unrelated workflows.

If the release succeeds but latest fails, the result has `success=false` and
`release_success=true`, retaining the immutable release URL and the latest error.
The CLI exits 1, so the existing workflow failure notification runs and coverage
publication is skipped. No rollback or automatic repair is attempted. A failed
upload or verification can leave partial remote files: do not assume no write
occurred, and inspect before any separately authorized recovery.

The count floor, XML validation, intentional consolidation `continue-on-error`,
and seven-day candidate artifact retention are unchanged. Download the candidate
artifact before expiry for diagnosis; do not weaken the count floor to recover.
A successful web deploy does not establish dataset freshness: the browser uses a
same-origin mirror populated during deployment from IA latest.

## Evidence for the October 25, 2026 correction

Inspected main: `159323aa1bd06eb0a07fd3c736870ad7a698607c`. Open PRs #340 and
#341 only changed dependencies. Neither AGENTS.md nor .agents/skills exists in
this Leizilla checkout.

Historical context supplied for this investigation (not newly verified remote
state): run 40186162094 failed publication after five spam/rate refusals, with a
2,104-row candidate from 88 of 89 XMLs, artifact 12596876063 retained seven days.
Run 40085457709 published a 1,951-row immutable release but latest failed with
`accesskey_tasks_queued exceeds rationed amount` while the job remained green.
The last confirmed latest in the supplied October 23 logs had 1,766 rows.

Current public reads of IA latest.json, dataset_meta.json, and the site's mirrored
dataset_meta.json returned HTTP 403 from the cloud environment. Thus neither the
current IA dataset nor the mirror count/hash is confirmed. GitHub CLI reads of the
historical run/artifact returned Forbidden, so artifact expiry was not refreshed.
No publication, rerun, deploy, credential creation or third-party contact was
performed. The separate Casa Civil LC parse failure is outside this correction.
