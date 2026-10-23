"""Apply approved title fixes to a WordPress site. The agent cannot approve its own changes."""
import argparse
import os
from urllib.parse import urlparse

import httpx

from .pipeline import DATA_DIR
from .store import AuditStore


WHITELIST = {"title_missing", "title_short", "title_long", "title_duplicate"}


def propose(store: AuditStore, audit_id: str) -> dict:
    plan = []
    for finding in store.list_findings(audit_id, status="verified", limit=500):
        if finding["rule_id"] not in WHITELIST:
            continue
        replacement = (finding.get("platform_fixes") or {}).get("replacement_title")
        for item in finding["affected"]:
            plan.append({
                "rule_id": finding["rule_id"],
                "url": item.get("url"),
                "replacement_title": replacement,
                "ready": bool(replacement),
            })
    return {"audit_id": audit_id, "changes": plan,
            "note": "Nothing is sent to WordPress until a human runs: python -m engine.wordpress approve " + audit_id}


def apply_approved(store: AuditStore, audit_id: str, site: str, username: str, app_password: str) -> dict:
    if not store.wordpress_approved(audit_id):
        return {"applied": [], "error": "Not approved. A person must run: python -m engine.wordpress approve " + audit_id}
    plan = propose(store, audit_id)["changes"]
    applied, skipped = [], []
    auth = (username, app_password)
    for change in plan:
        if not change["ready"]:
            skipped.append({**change, "reason": "no replacement_title on the finding"})
            continue
        slug = urlparse(change["url"] or "").path.strip("/").split("/")[-1]
        if not slug:
            skipped.append({**change, "reason": "could not read a slug from the URL"})
            continue
        try:
            found = httpx.get(site.rstrip("/") + "/wp-json/wp/v2/pages", params={"slug": slug}, auth=auth, timeout=30)
            found.raise_for_status()
            pages = found.json()
            if not isinstance(pages, list):
                pages = []
            if not pages:
                found = httpx.get(site.rstrip("/") + "/wp-json/wp/v2/posts", params={"slug": slug}, auth=auth, timeout=30)
                found.raise_for_status()
                pages = found.json()
                if not isinstance(pages, list):
                    pages = []
        except httpx.HTTPError as exc:
            skipped.append({**change, "reason": str(exc)[:200]})
            continue
        if not pages:
            skipped.append({**change, "reason": "no WordPress page or post with that slug"})
            continue
        kind = "pages" if "/wp/v2/pages" in str(found.url) else "posts"
        post_id = pages[0]["id"]
        try:
            saved = httpx.post(
                f"{site.rstrip('/')}/wp-json/wp/v2/{kind}/{post_id}",
                auth=auth, timeout=30, json={"title": change["replacement_title"]},
            )
            saved.raise_for_status()
        except httpx.HTTPError as exc:
            skipped.append({**change, "reason": str(exc)[:200]})
            continue
        applied.append({"url": change["url"], "post_id": post_id, "title": change["replacement_title"]})
    return {"applied": applied, "skipped": skipped}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Approve or apply WordPress title fixes.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    approve = sub.add_parser("approve")
    approve.add_argument("audit_id")
    approve.add_argument("--reviewer", default=os.environ.get("USERNAME", "spearmint"))
    run = sub.add_parser("apply")
    run.add_argument("audit_id")
    run.add_argument("--site", required=True)
    run.add_argument("--user", default=os.environ.get("WP_USER", ""))
    run.add_argument("--app-password", default=os.environ.get("WP_APP_PASSWORD", ""))
    args = parser.parse_args(argv)
    store = AuditStore(os.environ.get("AUDIT_DB") or (DATA_DIR / "audits.db"))
    if args.cmd == "approve":
        store.approve_wordpress(args.audit_id, args.reviewer)
        print(f"Approved WordPress changes for {args.audit_id} by {args.reviewer}.")
        return
    if not args.user or not args.app_password:
        raise SystemExit("Set WP_USER and WP_APP_PASSWORD.")
    result = apply_approved(store, args.audit_id, args.site, args.user, args.app_password)
    print(result)


if __name__ == "__main__":
    main()
