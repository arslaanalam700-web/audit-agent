---
name: website-audit
description: Spearmint audit skill used by the website-audit step.
---

Run one full Spearmint website and SEO audit.

## Steps
1. Call `start_audit` with the URL. Default page cap is 2000. Do not raise it.
2. Call `wait_for_audit` until status is done or failed. If it is still running, call it again. Do not crawl the site yourself.
3. Read `get_site_overview`. The score in that payload is the score you report. Do not invent a different score.
4. Send one A2A task, in parallel, to every peer that advertises `audit_specialist`:
   `a2a_orchestrate(capability="audit_specialist", mode="all", message=<AuditTask>)`
   AuditTask is JSON: `{"type":"AuditTask","audit_id","site","focus":"your-area","page_budget":40,"deadline_s":1200,"reply_format":"FindingsSummary"}`
5. Ask the QA agent (`a2a_call` the qa peer) to verify findings. Wait for it.
6. Ask the fixer agent to create tickets and build the report.
7. Call `queue_delivery` so a person at Spearmint reviews it. Do not email the client. Do not post the report in a client channel.

## Reply
Return a short FindingsSummary: score, top five verified issues, report folder, delivery id.
If a specialist times out, say which area is missing. Do not fill the gap with guesses.
