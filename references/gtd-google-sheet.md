# GTD Google Sheet contract

Use this reference when `gtd-google-sheet` is enabled.

## Required lifecycle surfaces

The profile maps four logical tabs: `next_actions`, `waiting_fors`, `inbox`, and `archive`.
`Next Actions` and `Waiting Fors` own clarified active work. `Inbox` holds unclarified capture that
must be reviewed. `Action Archive` receives completed, cancelled, resolved, or dropped rows before
they are removed from an active tab. `archive_before_clear` must remain true.

Each active row must expose `Close Action ID`, source provider/id/link, external key, created time,
and last-sync time. These metadata columns may be hidden for usability. Scope-to-Area values and
per-scope project tabs are profile configuration, not hard-coded assumptions.

## Safe write sequence

Before proposing changes, read spreadsheet metadata, required header rows, and candidate rows.
Run `scripts/gtd_sheet_contract.py audit` against the observed headers. Build operations only from
approved primary GTD actions, then validate them under both `allow_writes` and
`permissions.gtd_writes_enabled`.

For an upsert, search `Close Action ID` first. Update the matched row or append once when no match
exists. For completion, append the archive record, verify it, then clear the active row. Never
clear an active row if the archive write or verification failed. Re-read affected rows immediately
before a write and verify the exact cells afterward.

Stale dates are review signals, not evidence of completion. Preserve stale items until the user
explicitly completes, cancels, resolves, or drops them.
