# CRM Google Sheet Module

Read this reference when `crm-google-sheet` is enabled or when the user asks to create a CRM seed
from Gmail or Outlook, update CRM rows, or include CRM follow-ups in the close-out.

## Sheets

Set `mode` to `portable_workbook` for the workbook described below. Existing profiles without a
mode retain this behavior.

Create a Google-Sheets-compatible workbook with these tabs:

- `Accounts`
- `Contacts`
- `Interactions`
- `FollowUps`
- `Lists`

Use `scripts/generate_crm_workbook.py` to create the workbook and optional CSV seed files.

## Accounts Columns

- `Account Name`
- `Relationship Type`
- `Stage`
- `Status`
- `Priority`
- `Owner`
- `Last Touch`
- `Next Follow-up`
- `Next Step`
- `Source Evidence`
- `Canonical Page URL`

## Contacts Columns

- `Name`
- `Account`
- `Role/Title`
- `Email`
- `Relationship Role`
- `Last Touch`
- `Follow-up Flag`
- `Notes`

## Interactions Columns

- `Date`
- `Channel`
- `Account`
- `Contacts`
- `Subject`
- `Summary`
- `Action Extracted`
- `Source Link`

## FollowUps Columns

- `Due Date`
- `Account`
- `Contact`
- `Ask/Task`
- `Owner`
- `Status`
- `Source Interaction`

## Controlled Lists

Use the `Lists` tab for stages, statuses, relationship types, priorities, channels, follow-up
statuses, and owners. Keep data validation list-backed where possible.

## Mail Proposal Workflow

Use provider-native mail search first. Keep searches narrow and recent. For initial seed scans, search
user-provided account, customer, prospect, program, and partner terms. Common categories:

- active customer or program
- active opportunity or customer pursuit
- active research or customer collaboration
- award or program onboarding
- partner or ecosystem relationship
- partner-led pipeline

Normalize Gmail or Outlook search/read output, then pass it to `scripts/propose_crm_from_mail.py`.
The script emits a dry-run
proposal containing:

- new account candidates
- new contact candidates
- interaction summaries
- follow-ups the owner owes
- follow-ups others owe the owner
- confidence and source message/thread references

Do not write CRM changes silently. Present the CRM section in the close-day proposal and wait for
explicit approval.

## Google Sheets

For v1, create a local `.xlsx` or CSV seed first. Live Google Sheets writes require an available
Google Drive/Sheets connector or a user-provided integration route and explicit approval. If the
connector is unavailable, deliver the local workbook/proposal and state that native Sheets import is
blocked.

## Existing CRM handler

Set `mode` to `delegated_handler` when another installed skill owns an existing CRM's schema,
matching rules, and provider-specific write path. Bind it to explicit scopes and keep organization-
specific URLs, account ids, and controlled values in private profile or handler configuration.

Use [crm-handler-contract.md](crm-handler-contract.md) for the deterministic request/proposal
interface, incremental windows, inference rules, consolidated approval, live-write verification,
and state watermark behavior.
