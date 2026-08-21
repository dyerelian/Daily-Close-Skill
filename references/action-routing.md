# Action routing contract

Use this contract when `action-routing` is enabled. Its purpose is to prevent action loss and
duplicate execution across Jira, GTD, and CRM.

## Primary ownership

Every actionable item gets one `close_action_id`, one `external_key`, and exactly one primary
destination. Team, delegated, multi-step, or acceptance-criteria work normally belongs in Jira.
Personal next actions, small follow-ups, and waiting-fors normally belong in GTD. A CRM record may
be primary only for a non-executable record update; CRM must never be the sole home for work that
someone still needs to perform.

These defaults are configurable through `modules.action-routing.rules`. Onboarding must ask for the
primary destination of team work, personal/small actions, waiting-fors, and non-executable CRM
updates, and each answer must name a configured destination or `drop`.

When the same evidence affects more than one system, keep execution in the primary destination and
create linked secondary records. Each secondary record must carry the primary `close_action_id` or
the created external key. Do not create parallel GTD and Jira tasks for the same work.

## Proposal and approval

Run `scripts/action_routing_contract.py prepare` after evidence has a resolved scope. Pause when an
item lacks a title, scope, or configured destination, or when executable work is routed only to
CRM. Show the proposed primary destination and every linked secondary record in the consolidated
close proposal.

Before writes, run the validator with the exact approved action ids. Destination-specific
permissions remain narrow: `jira_writes_enabled`, `gtd_writes_enabled`, and `crm_writes_enabled`.
General external-write permission does not replace these gates.

## Failure and retry

Use `close_action_id` and `external_key` for duplicate searches and retry idempotence. If a primary
write fails, stop its dependent secondary writes and leave the action unresolved. If a secondary
link fails after the primary succeeds, retain the primary key, report the partial failure, and
retry only the missing link.
