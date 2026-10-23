---
name: offpage-review
description: Spearmint audit skill used by the offpage-review step.
---

Backlinks, keywords, and client analytics. Skip cleanly when the data source is not configured.

## Rules
- Call `offpage_summary` for the domain. If `available` is false, report that off-page data was not run. Do not estimate traffic.
- Call `search_console` and `ga4_overview` only when the task includes a site URL or GA4 property id. If they return available:false, say the client has not granted access.
- Findings must cite a number from the tool response.
- Do not recommend buying links.

## Reply
`{"type":"FindingsSummary","audit_id","focus":"offpage","finding_ids":[],"notes":""}`
