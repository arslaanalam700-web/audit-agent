---
name: wordpress-apply
description: Spearmint audit skill used by the wordpress-apply step.
---

Propose WordPress title updates. Apply them only after a human approval.

## Rules
- Call `wordpress_propose` and show the list to the person who asked.
- Call `wordpress_apply` only after they have run `python -m engine.wordpress approve <audit_id>` on the engine machine.
- If apply returns "Not approved", stop. Do not look for another way to edit the site.
- After a successful apply, ask the lead to re-audit and `diff_audits` against the previous id.

## Reply
The propose list, or the applied and skipped rows from apply.
