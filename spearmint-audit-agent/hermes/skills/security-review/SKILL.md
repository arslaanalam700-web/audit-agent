---
name: security-review
description: Spearmint audit skill used by the security-review step.
---

Passive security and trust review only.

## Rules
- Call `check_tls` and `dns_email_auth` for the host.
- Read security headers from `get_page` on the homepage.
- Do not request `/.git`, `/.env`, admin paths, or any URL you were not given. Do not test passwords. Do not send exploit payloads.
- SPF or DMARC gaps are findings because they support Spearmint's email offer. Say that in business_impact, without fear language.
- Evidence is the certificate day count, the header name, or the DNS result.

## Reply
`{"type":"FindingsSummary","audit_id","focus":"security","finding_ids":[],"notes":""}`
