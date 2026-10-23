---
name: technical-seo-review
description: Spearmint audit skill used by the technical-seo-review step.
---

Review crawlability, indexability, redirects, canonicals, hreflang, sitemaps, internal links, and structured data.

## Rules
- Read pages with `query_pages` and `get_page`. Stay inside `page_budget`.
- Use `check_structured_data` on the homepage and one template sample.
- Submit findings only through `submit_findings`. Every finding needs evidence: the URL and the fact you saw (status code, tag, header).
- Do not report an issue the engine already saved unless you are adding a judgement the engine cannot make, such as a canonical that is technically valid but points at the wrong intent.
- No terminal, no file writes, no requests to change the client's site.

## Reply
`{"type":"FindingsSummary","audit_id","focus":"technical_seo","finding_ids":[],"notes":""}`
