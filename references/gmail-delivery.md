# Gmail Daily Plan delivery

## Contents

1. Approval model
2. App setup
3. Delivery and retry flow
4. Failure handling

## Approval model

Use one consolidated close approval. Show the sender, recipients, subject, body style, and
attachments in that proposal. After approval, record the deterministic delivery key as `approved`;
do not ask for a second skill-level approval for the same key.

ChatGPT app permissions are independent from close-day approval. Prefer a narrow, action-specific
approval override for Gmail `send_email` when the product surface offers it. If only a plugin-wide
`Never ask` option exists, keep the safer confirmation behavior rather than silently granting every
Gmail write action unattended access.

## App setup

- Connect the configured sender account and confirm Gmail reports that exact address.
- For a managed ChatGPT workspace, enable `send_email` in Gmail Action control. Remove or reset any
  obsolete parameter constraint that requires a `payload` field absent from the published action.
- Constrain the recipient and subject pattern when the workspace supports parameter constraints.
- For Google Workspace accounts, trust the ChatGPT/OpenAI app or approve the Gmail
  `https://www.googleapis.com/auth/gmail.modify` scope.
- Treat the profile's `connector_configured` value as authentication state only. A successful
  approved send is the write-path verification.

Official setup references:

- https://help.openai.com/en/articles/11487775-apps-in-chatgpt
- https://help.openai.com/en/articles/10408842-google-app-for-chatgpt-data-controls-faq

## Delivery and retry flow

1. Prepare the envelope after approved artifacts and DOCX render verification.
2. Record `approved`, prepare again, and confirm `approved_ready`.
3. Record `pending`, invoke Gmail once, and record `sent` or categorized `failed`.
4. For a matching `pending` or approved `failed` delivery, search Sent using the exact recipient
   and subject before retrying.
5. If found, record `sent` without sending. If absent, prepare with `--sent-check-absent` and resume
   only when the envelope reports `send: true`. If the search is unavailable or delivery is
   ambiguous, stop and request direction.

Legacy failed states without `approved_delivery_key` require both `--retry-failed`, which represents
an explicit retry instruction, and `--sent-check-absent`. Do not use `--retry-failed` for new close
approvals.

## Failure handling

- `workspace_policy`: schema or workspace constraint failure, including an unexpected required
  `payload`; provide the app-settings remediation and do not retry automatically.
- `authentication`: OAuth, authorization, or scope failure; reconnect or approve the required scope.
- `transient`: timeout, rate limit, or temporary provider outage; check Sent before a bounded retry.
- `ambiguous`: the provider may have accepted the message; do not retry unless Sent proves absence.
- `provider`: other provider rejection; report the exact non-sensitive reason.

The same delivery key is a fingerprint, not evidence that Gmail sent the message. Only `sent` state
or an exact Sent-folder match proves delivery.
