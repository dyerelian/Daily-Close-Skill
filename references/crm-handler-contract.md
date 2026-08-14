# Delegated CRM handler contract

Read this reference when `modules.crm-google-sheet.mode` is `delegated_handler`.

## Contents

1. Configuration
2. Request and proposal
3. Daily lifecycle
4. Evidence and inference
5. State and failure behavior

## Configuration

Bind every handler to explicit `scope_ids`. Use `handler_skill` to name the installed skill and
optionally use `handler_path` for a local `SKILL.md`. `review_mode` must be `incremental_daily`.
Keep `roll_weekly_jira` false; a handler's standalone weekly workflow remains separate.

Use `first_run_lookback_days` when no successful CRM review exists. Later requests begin at the
last completed `reviewed_through` minus `overlap_hours`. The overlap protects provider boundary
reads; stable provider ids and deterministic change ids prevent duplicates.

## Request and proposal

Prepare a request with:

```powershell
python scripts/crm_review_contract.py prepare `
  --profile <id> --evidence <routed-evidence.json> `
  --close-at <ISO-datetime> --output <request.json>
```

The request contains contract version, deterministic request id, handler, profile, scopes, review
window, policy, and already-routed compact evidence. Never pass excluded, unclassified, or
out-of-scope evidence to the handler.

The handler returns a proposal with:

- matching `contract_version` and `request_id`
- source coverage and explicit gaps
- `changes` using `add_row` or `update_cells`
- the request-permitted `scope_id` on every change and derived follow-up
- row identity using company, contact name, or email
- exact column-level old and new values
- medium/high confidence, an `inferred` boolean, evidence references, and rationale
- low-confidence questions in `review_flags`, not `changes`
- separately approvable tasks in `derived_follow_ups`

Normalize and validate it with:

```powershell
python scripts/crm_review_contract.py validate-proposal `
  --request <request.json> --proposal <handler-proposal.json> `
  --output <validated-proposal.json>
```

The validator assigns deterministic `change_id` values and rejects mismatched requests,
duplicates, malformed cells, low-confidence changes, and any daily request that permits weekly
Jira rollover.

## Daily lifecycle

1. Read the authoritative CRM header, validations, and populated rows.
2. Give the handler routed evidence, then let it make bounded source reads needed to corroborate
   account and contact interactions inside the request window.
3. Validate the handler proposal and show exact cell changes and derived tasks inside the single
   consolidated close proposal.
4. After approval, re-read every affected row and check new-row identities. If any baseline value
   changed or a new row now exists, stop all CRM writes and rebase the CRM proposal.
5. Apply only approved change ids, re-read the affected rows, and verify each value.
6. Record the compact result in `crm_review` before creating the final close state and EOD log.

Build the compact state object after the proposal decision and write verification:

```powershell
python scripts/crm_review_contract.py build-state `
  --request <request.json> --proposal <validated-proposal.json> `
  --outcome <outcome.json> --output <crm-review-state.json>
```

The outcome lists approved, applied, and rejected change ids. A completed result requires a
decision for every proposal and verification of every approved change.

Treat derived tasks as separate proposal lines. Approval of a CRM cell change does not implicitly
approve an undisclosed task, and approval of one row does not authorize another row.

## Evidence and inference

Treat a completed event accepted by the owner and involving an external attendee as medium-
confidence interaction evidence. Email, Slack, meeting notes, or later artifacts can corroborate
outcomes and raise confidence. Calendar titles, descriptions, and attendees may support reasonable
inferences, but label every inference and use only validation values already present in the CRM.

Match existing rows by normalized company plus email, then company plus contact name. Propose a new
row only when `allow_new_rows` is true and company/contact identity is clear. Put low-confidence or
ambiguous matches in `review_flags`.

## State and failure behavior

Store only compact audit data: status, handler, profile/scopes, request id, window,
`reviewed_through`, source coverage/gaps, approved/applied/rejected change ids, counts, summary
items, and review flags. Do not store full messages, transcripts, or sheet snapshots.

Use `status: completed` only after the proposal decision and any approved writes are verified. A
completed no-change or user-rejected proposal may advance the watermark. Do not advance it when
the handler or CRM is unavailable, the baseline changed, or a write/verification failed.

CRM failure does not block unrelated local close artifacts. Report the gap or failure in the EOD
log, keep the CRM watermark unchanged, and never roll the handler's weekly Jira task in daily mode.
