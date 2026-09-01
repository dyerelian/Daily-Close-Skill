# People outreach

`features.people_outreach` is an optional profile-level routine. When enabled, close-day reads a
private JSON list and proposes the configured number of people to contact. The list is never edited
by close-day; cursor and date assignments are stored in a separate private state file.

```json
{
  "schema_version": 1,
  "people": ["Person A", "Person B"]
}
```

Selection is deterministic round-robin. `schedule=workdays_and_manual_runs` runs on configured
workdays and on manually requested closes. `duplicate_policy=count_entries` preserves duplicate
list entries as separate rotation slots. A same-date rerun reuses the saved assignment.

Outreach is included in the consolidated proposal and Daily Plan outputs, but does not create GTD,
Jira, CRM, or Confluence records. State is committed only after the approved close artifacts are
successfully created.
