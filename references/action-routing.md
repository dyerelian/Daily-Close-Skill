# Action routing contract

Use this contract when `action-routing` is enabled. Its purpose is to prevent action loss and
duplicate execution across Jira, GTD, and CRM.

## Primary ownership

Every actionable item gets one `close_action_id`, one `external_key`, and exactly one master
reminder. When GTD is configured as the comprehensive system, every non-excluded executable
commitment has a GTD Next Action or Waiting For reminder. Jira remains the detailed team execution
record and is linked from the GTD row; CRM remains a relationship record. CRM must never be the
sole home for work that someone still needs to perform.

These defaults are configurable through `modules.action-routing.rules`. Onboarding must ask for the
primary destination of team work, personal/small actions, waiting-fors, and non-executable CRM
updates, and each answer must name a configured destination or `drop`.

When the same evidence affects more than one system, keep one action definition in GTD and create
linked secondary records. A Jira-linked GTD row must contain the Jira key/URL as source evidence;
Jira holds the detailed team task, not a second independently maintained reminder. Each secondary
record must carry the primary `close_action_id` or created external key. If a Jira record must be
created, create and verify it before writing the dependent GTD link.

Normalize work delegated to someone else as `waiting_for`, with the responsible owner and an
intentional follow-up date. Do not store another person's commitment as Dan's executable next
action unless Dan's action is to contact, review, approve, or otherwise advance it.

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
