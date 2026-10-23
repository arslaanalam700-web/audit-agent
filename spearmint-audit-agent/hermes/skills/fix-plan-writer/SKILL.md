---
name: fix-plan-writer
description: Spearmint audit skill used by the fix-plan-writer step.
---

Turn verified findings into tickets a developer, writer, or SEO can execute.

## Rules
- Call `create_fix_tickets` and `build_report`.
- Tickets already carry owner, hours, and acceptance checks. Do not inflate hours.
- The rate is Rs 1000 per hour. The estimate tool is the quote. You may explain it. You may not change the arithmetic.
- Group the first week of work as quick wins: titles, metas, redirects, sitemap, compression, viewport.
- Write replacement titles into platform_fixes only when the content agent did not already supply them.

## Reply
`{"type":"FixPlan","audit_id","hours":0,"total_inr":0,"report_dir":"","top_tickets":[]}`
