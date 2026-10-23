---
name: performance-review
description: Spearmint audit skill used by the performance-review step.
---

Review speed using the engine's PageSpeed samples and per-template notes.

## Rules
- Call `run_lighthouse` for at most three template URLs (homepage plus two others from `list_templates`).
- Report lab LCP, INP or TBT, and CLS, and field data when it is present.
- Group fixes by template, not by every URL.
- Evidence is the metric value and the URL. Do not invent milliseconds.

## Reply
`{"type":"FindingsSummary","audit_id","focus":"performance","finding_ids":[],"notes":""}`
