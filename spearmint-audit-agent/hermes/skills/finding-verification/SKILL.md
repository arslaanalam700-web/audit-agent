---
name: finding-verification
description: Spearmint audit skill used by the finding-verification step.
---

Verify findings before they reach a client report.

## Rules
- List findings with status `open` and the engine's `verified` set.
- For an agent finding, open `get_page` and check the evidence still matches. If it does not, `update_finding` status to `rejected`.
- You may `a2a_call` the specialist who wrote a finding, at most two turns, when the evidence is unclear. Then decide.
- Reject anything with no evidence id.
- Do not raise the severity of an engine finding without new evidence. You may lower it.
- Engine scores stay as the engine wrote them.

## Reply
`{"type":"QaResult","audit_id","verified":0,"rejected":0,"notes":""}`
