import argparse
import sys
from datetime import datetime


def parse_args(argv=None):
    ap = argparse.ArgumentParser(prog="site_audit", description="Crawl a website and produce a client-ready SEO & website health report.")
    ap.add_argument("url", help="Website to audit, e.g. https://example.com")
    ap.add_argument("--max-pages", type=int, default=200, help="Maximum pages to crawl (default 200)")
    ap.add_argument("--max-depth", type=int, default=10, help="Maximum click depth (default 10)")
    ap.add_argument("--concurrency", type=int, default=5, help="Parallel requests (default 5, be polite)")
    ap.add_argument("--timeout", type=float, default=20, help="Per-request timeout in seconds")
    ap.add_argument("--ignore-robots", action="store_true", help="Crawl URLs disallowed by robots.txt")
    ap.add_argument("--check-external", action="store_true", help="Also check outbound links for 404s")
    ap.add_argument("--no-pagespeed", action="store_true", help="Skip Google PageSpeed Insights")
    ap.add_argument("--strategy", choices=["mobile", "desktop"], default="mobile", help="PageSpeed strategy")
    ap.add_argument("--ai", action="store_true", help="Write the executive summary with an LLM (needs OPENAI_API_KEY)")
    ap.add_argument("--client-name", help="Client name shown on the report (defaults to the domain)")
    ap.add_argument("--agency", default="Spearmint", help="Your agency name shown on the report")
    ap.add_argument("--brand-color", default="#12a37f", help="Report accent colour")
    ap.add_argument("--contact", help="Call-to-action line at the end of the report (e.g. email/phone)")
    ap.add_argument("--max-urls", type=int, default=50, help="Affected URLs listed per issue in the HTML report")
    ap.add_argument("--out", default="reports", help="Output folder (default ./reports)")
    ap.add_argument("--db", help="SQLite file for the audit store (default audit-agent/data/audits.db)")
    ap.add_argument("--render", action="store_true", help="Render sampled pages in a headless browser and compare with the raw HTML")
    ap.add_argument("--axe", action="store_true", help="Run axe-core on the rendered sample (implies extra time)")
    ap.add_argument("--psi-samples", type=int, default=1, help="How many templates to send to PageSpeed (default 1)")
    ap.add_argument("--no-open", action="store_true", help="Don't open the report in a browser when done")
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    from ..pipeline import DATA_DIR, execute
    from ..store import AuditStore

    host = args.url.split("/")[2] if "://" in args.url else args.url.split("/")[0]
    audit_id = f"{host.replace('.', '-').replace(':', '-')}-{datetime.now():%Y%m%d-%H%M%S}"
    store = AuditStore(args.db or (DATA_DIR / "audits.db"))
    store.create_audit(audit_id, args.url, args.client_name or "")
    try:
        result = execute(
            args.url, audit_id=audit_id, store=store, max_pages=args.max_pages, max_depth=args.max_depth,
            concurrency=args.concurrency, timeout=args.timeout, respect_robots=not args.ignore_robots,
            check_external=args.check_external, pagespeed=not args.no_pagespeed, strategy=args.strategy,
            psi_samples=args.psi_samples, render=args.render, axe=args.axe, ai=args.ai,
            client_name=args.client_name, agency=args.agency, brand_color=args.brand_color, contact=args.contact,
            max_urls=args.max_urls, out=args.out, open_browser=not args.no_open, log=print,
        )
    except Exception as exc:
        store.update_audit(audit_id, status="failed", error=str(exc)[:500], finished_at=datetime.now().isoformat(timespec="seconds"))
        raise

    print("")
    print(f"Overall score: {result['score']['overall']}/100 (grade {result['score']['grade']})")
    for cat in result["score"]["categories"]:
        print(f"  {cat['name']:<24} {cat['score']:>3}")
    print(f"Issues: {result['stats']['by_severity']}")
    cost = result["estimate"]
    print(f"Fix estimate: {cost['hours']} hours, Rs {cost['total_inr']} at Rs {cost['rate_inr']}/hour")
    print(f"Report: {result['paths'].get('html')}")
    print(f"Fix pack and pitch are in {result['report_dir']}")


if __name__ == "__main__":
    main()
