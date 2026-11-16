# ADR-0018 — Anthropic authentication through Google federation

Status: accepted for the manual teacher batch workflow, 2026-11-16.

## Context

The teacher batch needs repeatable authentication before the November 27 batch.
There is no static Anthropic API key in this repository. The existing Anthropic
federation rule for Jatoba already trusts the Google service account subject
`116539724070023927528`. Its helper successfully authenticated on November 16.
The operator has authenticated `gh` and `gcloud`, but no demonstrated Anthropic
administration credential. Creating a Cloud Run broker is unnecessary.

## Decision

Use GitHub OIDC, Google STS, and IAM Credentials `generateIdToken` to obtain a
Google-signed JWT for the identity already trusted by Anthropic. The Anthropic
SDK exchanges that JWT and renews its short-lived access tokens automatically.
`scripts/anthropic_wif.py` atomically refreshes the Google JWT every 40 minutes
while supervising the Python command. Failed renewal terminates that command.
Temporary credentials are deleted when the wrapper exits and never uploaded.

Google project: `virtual-computer-fsb` (number `590717404688`). Pool:
`leizilla-anthropic`; provider: `github`. The provider condition requires:

- repository ID `1009863583` and owner ID `6721640`;
- branch `refs/heads/main` and event `workflow_dispatch`;
- workflow `teacher-batch.yml` or `anthropic-auth-check.yml` in this repository.

The exact `repo:franklinbaldo/leizilla:ref:refs/heads/main` pool principal has
`roles/iam.serviceAccountOpenIdTokenCreator` on
`590717404688-compute@developer.gserviceaccount.com`. This grants only
`iam.serviceAccounts.getOpenIdToken`, not access-token creation, signing,
service-account management, or general access to Google resources.
Google does not restrict the requested ID-token audience through this role;
trusted workflow code must therefore remain controlled. Reuse of the existing
identity is intentional; a dedicated Anthropic trust rule can later separate it.

The repository variables `ANTHROPIC_GOOGLE_WIF_PROVIDER`,
`ANTHROPIC_GOOGLE_SERVICE_ACCOUNT`, `ANTHROPIC_ORGANIZATION_ID`,
`ANTHROPIC_FEDERATION_RULE_ID`, and `ANTHROPIC_SERVICE_ACCOUNT_ID` contain only
public identifiers. There is no `ANTHROPIC_API_KEY` secret in this design.

## Verification and operation

Run `gh workflow run anthropic-auth-check.yml --repo franklinbaldo/leizilla`.
It obtains identities twice with independent SDK clients, lists models, and
calls the free token-count endpoint. It does not create messages or batches.
The paid teacher `submit` still requires its explicit `max_usd` budget.
Existing harvest, parse/release, and Claude maintenance workflows are unchanged;
the latter does not gain authentication from this teacher-specific integration.

Offline tests cover the exchange chain, secret-free error reporting, atomic file
replacement, renewal, subprocess exit propagation, and fail-closed renewal.

To revoke, remove the exact principal's OpenID-token role binding, or disable
the `github` provider in pool `leizilla-anthropic`. Do not change the existing
Anthropic rule or the Jatoba VM service account: those serve other workloads.

References: [Google deployment pipeline federation](https://cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines),
[Anthropic Google federation](https://platform.claude.com/docs/en/manage-claude/wif-providers/gcp).
