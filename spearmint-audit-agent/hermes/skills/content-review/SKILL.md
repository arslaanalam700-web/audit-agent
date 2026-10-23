---
name: content-review
description: Spearmint audit skill used by the content-review step.
---

Review titles, meta descriptions, headings, thin and duplicate copy, search intent, and trust signals.

## Rules
- Sample at most `page_budget` pages, spread across templates from `query_pages`.
- When a title or meta description should change, include `platform_fixes.replacement_title` or `platform_fixes.replacement_meta` with the replacement text (50-60 character titles, 120-155 character descriptions).
- Judge intent in plain language: what the page seems to want to rank for, and whether the copy matches.
- Evidence is required: quote the current title or the first words of the copy, plus the URL.
- Do not claim traffic or rankings. You do not have that data unless the off-page agent supplied it in the task.

## Reply
`{"type":"FindingsSummary","audit_id","focus":"content_seo","finding_ids":[],"notes":""}`
