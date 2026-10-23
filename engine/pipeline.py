"""Run a crawl, the deterministic checks, and the report. Agents call this through the MCP tools."""
import asyncio
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from .deep import deep_issues, llms_txt, pagerank, template_key, tls_probe, txt_records, _is_ip
from .fixpack import write_fix_pack
from .render import looks_js_rendered, render_page, run_axe
from .site_audit.ai import ai_summary, template_summary
from .site_audit.checks import CATALOG, SEVERITY_ORDER, run_checks
from .site_audit.crawler import Crawler, bare_host
from .site_audit.pagespeed import run_pagespeed
from .site_audit.report import write_reports
from .site_audit.scoring import score
from .store import AuditStore
from .tickets import build_tickets, estimate

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def merge_issues(base: list, extra: list) -> list:
    by_id = {issue.id: issue for issue in base}
    for issue in extra:
        current = by_id.get(issue.id)
        if current is None:
            by_id[issue.id] = issue
            continue
        current.affected.extend(issue.affected)
        if SEVERITY_ORDER[issue.severity] < SEVERITY_ORDER[current.severity]:
            current.severity = issue.severity
    return sorted(by_id.values(), key=lambda issue: (SEVERITY_ORDER[issue.severity], -issue.count))


def representative_urls(crawl, limit: int) -> list[str]:
    picked = [crawl.start_url]
    seen = {template_key(crawl.start_url)}
    for page in crawl.pages:
        if not page.is_html:
            continue
        key = template_key(page.final_url or page.url)
        if key in seen:
            continue
        seen.add(key)
        picked.append(page.final_url or page.url)
        if len(picked) >= limit:
            break
    return picked


def _page_row(page, rank: float | None) -> dict:
    data = page.data or {}
    payload = {
        "content_type": page.content_type,
        "response_ms": page.response_ms,
        "size_bytes": page.size_bytes,
        "error": page.error,
        "canonical": data.get("canonical"),
        "h1": data.get("h1"),
        "meta_description": data.get("meta_description"),
        "schema_types": data.get("schema_types"),
        "image_count": data.get("image_count"),
        "images_missing_alt": len(data.get("images_missing_alt") or []),
        "headers": {k: v for k, v in (page.headers or {}).items() if k in (
            "cache-control", "etag", "content-encoding", "strict-transport-security", "content-security-policy")},
    }
    return {
        "url": page.url,
        "final_url": page.final_url,
        "status": page.status,
        "depth": page.depth,
        "template": template_key(page.final_url or page.url),
        "title": data.get("title"),
        "word_count": data.get("word_count"),
        "noindex": data.get("noindex"),
        "simhash": data.get("simhash"),
        "pagerank": rank,
        "payload": payload,
    }


def _persist_issues(store: AuditStore, audit_id: str, issues) -> None:
    for issue in issues:
        evidence_ids = []
        for item in issue.affected:
            evidence_ids.append(store.add_evidence(audit_id, issue.id, item.get("url") or "", item.get("detail") or ""))
        if not evidence_ids:
            evidence_ids.append(store.add_evidence(audit_id, issue.id, "", issue.title))
        store.insert_finding(audit_id, {
            "rule_id": issue.id, "category": issue.category, "severity": issue.severity,
            "title": issue.title, "why": issue.why, "fix": issue.fix, "scope": issue.scope,
            "affected": issue.affected, "evidence_ids": evidence_ids,
            "business_impact": issue.why, "fix_steps": issue.fix,
            "acceptance_check": f"A re-audit no longer reports {issue.id} for the listed URLs.",
            "confidence": 1.0, "agent": "engine", "status": "verified",
        })


def collect_probe(crawl, render: bool, axe: bool, log=print) -> dict:
    host = crawl.base_host
    probe = {"pagerank": {}, "rendered": [], "axe": [], "tls": {}, "dns": {}, "llms": {}}
    edges = []
    for page in crawl.pages:
        if not page.data:
            continue
        for link in page.data["links"]:
            if crawl.base_host == bare_host(link):
                edges.append((page.final_url, link))
    probe["pagerank"] = pagerank(edges)

    origin = f"{urlparse(crawl.start_url).scheme}://{urlparse(crawl.start_url).netloc}"
    if crawl.site.get("https"):
        log("  checking TLS certificate...")
        probe["tls"] = tls_probe(host)
    if host and not _is_ip(host) and host not in ("localhost",):
        log("  checking SPF and DMARC...")
        spf = txt_records(host)
        dmarc = txt_records(f"_dmarc.{host}")
        probe["dns"] = {
            "checked": True,
            "spf": any(item.lower().startswith("v=spf1") for item in spf),
            "dmarc": any("v=dmarc1" in item.lower() for item in dmarc),
        }
    probe["llms"] = llms_txt(origin)

    home = next((p for p in crawl.pages if p.is_html), None)
    should_render = render or (home and looks_js_rendered(home.data))
    if should_render:
        targets = representative_urls(crawl, 2)
        log(f"  rendering {len(targets)} page(s) in a headless browser...")
        for url in targets:
            probe["rendered"].append(render_page(url))
            if axe:
                probe["axe"].append(run_axe(url))
    return probe


def diff_audits(store: AuditStore, old_id: str, new_id: str) -> dict:
    def keys(audit_id):
        found = set()
        for finding in store.list_findings(audit_id, limit=5000):
            urls = [item.get("url") or "" for item in finding["affected"]] or [""]
            for url in urls:
                found.add((finding["rule_id"], url))
        return found

    old, new = keys(old_id), keys(new_id)

    def rows(pairs):
        return [{"rule_id": rule, "url": url} for rule, url in sorted(pairs)]

    return {"fixed": rows(old - new), "still_open": rows(old & new), "new": rows(new - old)}


def execute(url: str, *, audit_id: str, store: AuditStore, max_pages: int = 200, max_depth: int = 10,
            concurrency: int = 5, timeout: float = 20, respect_robots: bool = True, check_external: bool = False,
            pagespeed: bool = True, strategy: str = "mobile", psi_samples: int = 1, render: bool = False,
            axe: bool = False, ai: bool = False, client_name: str | None = None, agency: str = "Spearmint",
            brand_color: str = "#12a37f", contact: str | None = None, max_urls: int = 50, out: str = "reports",
            open_browser: bool = False, log=print) -> dict:
    import os
    import webbrowser

    log(f"[1/4] Crawling {url} (up to {max_pages} pages)...")
    crawler = Crawler(url, max_pages=max_pages, max_depth=max_depth, concurrency=concurrency, timeout=timeout,
                      respect_robots=respect_robots, check_external=check_external, log=log)
    crawl = asyncio.run(crawler.run())
    html_pages = [p for p in crawl.pages if p.is_html]
    log(f"  crawled {len(crawl.pages)} URLs ({len(html_pages)} HTML pages) in {crawl.duration_s}s")

    psi_list = []
    if pagespeed:
        log("[2/4] Measuring speed and Core Web Vitals...")
        key = os.environ.get("PAGESPEED_API_KEY")
        for sample in representative_urls(crawl, max(1, psi_samples)):
            result = run_pagespeed(sample, strategy, key, log=log)
            if result:
                psi_list.append(result)
            if not key:
                break  # the shared quota is one request; don't burn it on more URLs
    else:
        log("[2/4] PageSpeed skipped")

    log("[3/4] Analysing issues...")
    probe = collect_probe(crawl, render=render, axe=axe, log=log)
    issues = merge_issues(run_checks(crawl, psi_list), deep_issues(crawl, probe))
    primary_psi = psi_list[0] if psi_list else None
    sc = score(issues, len(html_pages), primary_psi)

    ranks = probe["pagerank"]
    link_rows = []
    page_rows = [_page_row(p, ranks.get(p.final_url)) for p in crawl.pages]
    for page in crawl.pages:
        if not page.data:
            continue
        for link in page.data["links"]:
            link_rows.append((page.final_url, link, int(bare_host(link) == crawl.base_host)))
    store.save_graph(audit_id, page_rows, link_rows)
    _persist_issues(store, audit_id, issues)

    domain = crawl.base_host
    sev = Counter(i.severity for i in issues)
    stats = {
        "urls_crawled": len(crawl.pages),
        "html_pages": len(html_pages),
        "indexable": sum(1 for p in html_pages if not p.data["noindex"]),
        "issue_types": len(issues),
        "checks_run": len(CATALOG),
        "by_severity": {k: sev.get(k, 0) for k in ("critical", "high", "medium", "low")},
        "avg_response_ms": round(sum(p.response_ms for p in html_pages) / len(html_pages)) if html_pages else 0,
        "avg_words": round(sum(p.data["word_count"] for p in html_pages) / len(html_pages)) if html_pages else 0,
        "status_codes": dict(sorted(Counter(str(p.status) if not p.error else "Error" for p in crawl.pages).items())),
        "schema_types": sorted({t for p in html_pages for t in p.data["schema_types"]}),
        "templates": len({row["template"] for row in page_rows}),
    }
    findings = store.list_findings(audit_id, limit=500)
    tickets = build_tickets(findings)
    for ticket in tickets:
        store.add_ticket(audit_id, ticket)
    cost = estimate(tickets)

    now = datetime.now()
    ctx = {
        "agency": agency, "client_name": client_name or domain, "domain": domain,
        "start_url": crawl.start_url, "brand_color": brand_color, "contact": contact,
        "generated": now.isoformat(timespec="seconds"), "generated_human": now.strftime("%d %B %Y"),
        "score": sc, "issues": issues, "stats": stats, "psi": primary_psi, "pages": crawl.pages,
        "inlinks": crawl.inlinks, "robots": crawl.robots, "sitemap": crawl.sitemap, "site": crawl.site,
        "duration_s": crawl.duration_s, "max_urls": max_urls, "tickets": tickets, "estimate": cost,
        "audit_id": audit_id,
    }
    log("[4/4] Writing report and fix pack...")
    summary = ai_summary(ctx, log=log) if ai else None
    ctx["summary"] = summary or template_summary(ctx)
    out_dir = Path(out) / f"{domain}-{now:%Y%m%d-%H%M%S}"
    paths = write_reports(ctx, out_dir)
    pack = write_fix_pack(out_dir, issues, domain)
    paths["fix_pack"] = Path(pack["dir"])
    pdf = _write_pdf(paths["html"])
    if pdf:
        paths["pdf"] = pdf
    pitch = _write_pitch(ctx, out_dir)
    paths["pitch"] = pitch

    for name, path in paths.items():
        if path:
            store.add_artifact(audit_id, name, str(Path(path).resolve()))
    store.update_audit(
        audit_id, status="done", finished_at=now.isoformat(timespec="seconds"),
        score_json=json.dumps(sc), stats_json=json.dumps(stats),
        psi_json=json.dumps(primary_psi, default=str) if primary_psi else None,
        report_dir=str(out_dir.resolve()),
    )
    if open_browser:
        webbrowser.open(paths["html"].resolve().as_uri())
    return {"audit_id": audit_id, "paths": {k: str(v) for k, v in paths.items() if v},
            "score": sc, "stats": stats, "estimate": cost, "report_dir": str(out_dir.resolve())}


def _write_pdf(html_path: Path):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    pdf_path = html_path.with_suffix(".pdf")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(html_path.resolve().as_uri(), wait_until="networkidle")
            page.pdf(path=str(pdf_path), format="A4", print_background=True)
            browser.close()
    except Exception:
        return None
    return pdf_path


def _write_pitch(ctx: dict, out_dir: Path) -> Path:
    cost = ctx["estimate"]
    lines = [
        f"# {ctx['client_name']} — website audit pitch",
        "",
        f"Score: {ctx['score']['overall']}/100 (grade {ctx['score']['grade']}).",
        f"Pages crawled: {ctx['stats']['html_pages']}.",
        f"Fix estimate: {cost['hours']} hours × ₹{cost['rate_inr']} = ₹{cost['total_inr']}.",
        "",
        "## Say this",
    ]
    for point in ctx["summary"].get("pitch_points") or []:
        lines.append(f"- {point}")
    lines += ["", "## First tickets"]
    for ticket in ctx["tickets"][:8]:
        lines.append(f"- ({ticket['owner']}, {ticket['effort_hours']}h) {ticket['title']}")
    path = out_dir / "pitch.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
