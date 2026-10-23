---
name: ux-review
description: Spearmint audit skill used by the ux-review step.
---

Review accessibility and the mobile experience.

## Rules
- Call `run_axe` on one URL per template, maximum three.
- Call `render_page` when the overview suggests the copy only appears after JavaScript.
- A vision-capable model may comment on what a screenshot-equivalent render implies (clipped buttons, missing labels). Tie every comment to a URL.
- WCAG findings need the axe rule id or the engine's a11y rule id as evidence.
- Note conversion elements: a visible contact path, a form, click-to-call, WhatsApp. Missing ones are findings only when the page is clearly a business homepage.

## Reply
`{"type":"FindingsSummary","audit_id","focus":"ux_accessibility","finding_ids":[],"notes":""}`
