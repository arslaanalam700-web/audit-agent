"""Tool functions shared by the MCP server and the tests. No LLM calls live here."""
import csv
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from .deep import tls_probe, txt_records, _is_ip
from .pipeline import DATA_DIR, diff_audits, execute
from .render import render_page, run_axe
from .site_audit.checks import CATALOG, SEVERITY_ORDER
from .site_audit.pagespeed import run_pagespeed
from .store import AuditStore
from .tickets import build_tickets, estimate

SEVERITIES = set(SEVERITY_ORDER)


class AuditService:
    def __init__(self, db_path: str | Path | None = None):
        self.store = AuditStore(db_path or (DATA_DIR / "audits.db"))
        self._threads: dict[str, threading.Thread] = {}

    def start_audit(self, url: str, client_name: str = "", max_pages: int = 2000, max_depth: int = 10,
                    check_external: bool = False, pagespeed: bool = True, render: bool = False,
                    psi_samples: int = 3, consent_probe: bool = False) -> dict:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        host = url.split("/")[2].replace(".", "-").replace(":", "-")
        audit_id = f"{host}-{datetime.now():%Y%m%d-%H%M%S}"
        self.store.create_audit(audit_id, url, client_name, consent_probe=consent_probe)
        options = dict(max_pages=min(max_pages, 2000), max_depth=max_depth, check_external=check_external,
                       pagespeed=pagespeed, render=render, axe=render, psi_samples=psi_samples,
                       client_name=client_name or None, out=str(DATA_DIR.parent / "reports"))
        thread = threading.Thread(target=self._run, args=(audit_id, url, options), daemon=True)
        self._threads[audit_id] = thread
        thread.start()
        return {"audit_id": audit_id, "status": "running", "url": url}

    def _run(self, audit_id: str, url: str, options: dict):
        try:
            execute(url, audit_id=audit_id, store=self.store, log=lambda *a, **k: None, **options)
        except Exception as exc:
            self.store.update_audit(audit_id, status="failed", error=str(exc)[:500],
                                     finished_at=datetime.now().isoformat(timespec="seconds"))

    def wait_for_audit(self, audit_id: str, timeout_s: int = 600) -> dict:
        deadline = time.time() + min(int(timeout_s), 600)
        while time.time() < deadline:
            audit = self.store.get_audit(audit_id)
            if audit is None:
                return {"error": "unknown audit", "audit_id": audit_id}
            if audit["status"] in ("done", "failed"):
                return self.get_site_overview(audit_id)
            time.sleep(1.5)
        audit = self.store.get_audit(audit_id)
        return {"audit_id": audit_id, "status": audit["status"] if audit else "missing",
                "message": "Still running. Call wait_for_audit again."}

    def get_site_overview(self, audit_id: str) -> dict:
        audit = self.store.get_audit(audit_id)
        if not audit:
            return {"error": "unknown audit"}
        findings = self.store.list_findings(audit_id, limit=500)
        by_sev = {}
        for finding in findings:
            by_sev[finding["severity"]] = by_sev.get(finding["severity"], 0) + 1
        return {
            "audit_id": audit_id,
            "url": audit["url"],
            "status": audit["status"],
            "error": audit.get("error"),
            "score": audit.get("score"),
            "stats": audit.get("stats"),
            "findings": len(findings),
            "by_severity": by_sev,
            "templates": self.store.list_templates(audit_id),
            "report_dir": audit.get("report_dir"),
            "artifacts": self.store.artifacts(audit_id),
        }

    def list_findings(self, audit_id: str, status: str = "", severity: str = "", limit: int = 50, offset: int = 0) -> dict:
        rows = self.store.list_findings(audit_id, status or None, severity or None, min(limit, 500), offset)
        return {"audit_id": audit_id, "count": len(rows), "findings": rows}

    def query_pages(self, audit_id: str, template: str = "", limit: int = 25, offset: int = 0) -> dict:
        return self.store.query_pages(audit_id, template or None, min(limit, 100), offset)

    def get_page(self, audit_id: str, url: str) -> dict:
        page = self.store.get_page(audit_id, url)
        return page or {"error": "page not in this audit", "url": url}

    def list_templates(self, audit_id: str) -> dict:
        return {"audit_id": audit_id, "templates": self.store.list_templates(audit_id)}

    def submit_findings(self, audit_id: str, findings: list, agent: str) -> dict:
        if self.store.get_audit(audit_id) is None:
            return {"error": "unknown audit"}
        saved, rejected = [], []
        for index, raw in enumerate(findings or []):
            problem = _validate_finding(raw)
            if problem:
                rejected.append({"index": index, "error": problem})
                continue
            evidence_ids = []
            for item in raw.get("evidence") or []:
                evidence_ids.append(self.store.add_evidence(
                    audit_id, raw["rule_id"], item.get("url") or "", item.get("detail") or ""))
            for evidence_id in raw.get("evidence_ids") or []:
                if not self.store.evidence_exists(audit_id, evidence_id):
                    rejected.append({"index": index, "error": f"unknown evidence {evidence_id}"})
                    evidence_ids = []
                    break
                evidence_ids.append(evidence_id)
            if not evidence_ids:
                if not any(item.get("error", "").startswith("unknown evidence") for item in rejected[-1:]):
                    rejected.append({"index": index, "error": "evidence is required"})
                continue
            catalog = CATALOG.get(raw["rule_id"])
            finding_id = self.store.insert_finding(audit_id, {
                "rule_id": raw["rule_id"],
                "category": raw.get("category") or (catalog[1] if catalog else "Content"),
                "severity": raw["severity"],
                "title": raw.get("title") or (catalog[0] if catalog else raw["rule_id"]),
                "why": raw.get("why") or raw.get("business_impact") or (catalog[3] if catalog else ""),
                "fix": raw.get("fix") or raw.get("fix_steps") or (catalog[4] if catalog else ""),
                "scope": raw.get("scope") or "page",
                "affected": raw.get("affected") or raw.get("evidence") or [],
                "evidence_ids": evidence_ids,
                "business_impact": raw.get("business_impact") or "",
                "fix_steps": raw.get("fix_steps") or raw.get("fix") or "",
                "platform_fixes": raw.get("platform_fixes") or {},
                "acceptance_check": raw.get("acceptance_check") or "",
                "confidence": float(raw.get("confidence") or 0.7),
                "agent": agent or "agent",
                "status": "open",
            })
            saved.append(finding_id)
        return {"saved": saved, "rejected": rejected}

    def update_finding(self, finding_id: int, status: str = "", severity: str = "", note: str = "") -> dict:
        if status and status not in ("open", "verified", "rejected", "fixed"):
            return {"error": "status must be open, verified, rejected or fixed"}
        if severity and severity not in SEVERITIES:
            return {"error": "unknown severity"}
        fields = {}
        if status:
            fields["status"] = status
        if severity:
            fields["severity"] = severity
        if note:
            fields["business_impact"] = note
        ok = self.store.update_finding(int(finding_id), **fields)
        return {"updated": ok, "finding_id": finding_id}

    def create_fix_tickets(self, audit_id: str) -> dict:
        existing = {t["finding_id"] for t in self.store.list_tickets(audit_id)}
        created = []
        for ticket in build_tickets(self.store.list_findings(audit_id, status="verified", limit=500)):
            if ticket["finding_id"] in existing:
                continue
            created.append(self.store.add_ticket(audit_id, ticket))
        tickets = self.store.list_tickets(audit_id)
        return {"created": created, "estimate": estimate(build_tickets(
            self.store.list_findings(audit_id, status="verified", limit=500))), "tickets": len(tickets)}

    def build_report(self, audit_id: str) -> dict:
        audit = self.store.get_audit(audit_id)
        if not audit:
            return {"error": "unknown audit"}
        self.create_fix_tickets(audit_id)
        folder = Path(audit["report_dir"] or (DATA_DIR / "reports" / audit_id))
        folder.mkdir(parents=True, exist_ok=True)
        findings = self.store.list_findings(audit_id, status="verified", limit=500)
        lines = [f"# Verified findings for {audit['url']}", ""]
        for finding in findings:
            lines.append(f"## {finding['severity']}: {finding['title']}")
            lines.append(finding.get("why") or "")
            lines.append("")
            for item in finding["affected"][:20]:
                lines.append(f"- {item.get('url')} — {item.get('detail')}")
            lines.append("")
        path = folder / "verified-findings.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        self.store.add_artifact(audit_id, "verified_findings", str(path.resolve()))
        exported = self.export_tickets(audit_id, str(folder / "tickets.csv"))
        return {"report_dir": str(folder), "verified_findings": str(path), "tickets_csv": exported.get("path"),
                "artifacts": self.store.artifacts(audit_id)}

    def export_tickets(self, audit_id: str, path: str = "") -> dict:
        tickets = self.store.list_tickets(audit_id)
        target = Path(path) if path else DATA_DIR / "reports" / audit_id / "tickets.csv"
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(["id", "owner", "hours", "title", "steps", "acceptance", "status"])
            for ticket in tickets:
                writer.writerow([ticket["id"], ticket["owner"], ticket["effort_hours"], ticket["title"],
                                 ticket["steps"], ticket["acceptance"], ticket["status"]])
        return {"path": str(target), "rows": len(tickets)}

    def diff_audits(self, old_audit_id: str, new_audit_id: str) -> dict:
        return diff_audits(self.store, old_audit_id, new_audit_id)

    def render_page(self, url: str) -> dict:
        return render_page(url)

    def run_lighthouse(self, url: str, strategy: str = "mobile") -> dict:
        result = run_pagespeed(url, strategy, os.environ.get("PAGESPEED_API_KEY"), log=lambda *_: None)
        return result or {"available": False, "reason": "PageSpeed did not return a result. Set PAGESPEED_API_KEY."}

    def run_axe(self, url: str) -> dict:
        return run_axe(url)

    def check_structured_data(self, audit_id: str, url: str) -> dict:
        page = self.store.get_page(audit_id, url)
        if not page:
            return {"error": "page not in this audit"}
        return {"url": url, "schema_types": (page.get("payload") or {}).get("schema_types") or [],
                "findings": [f for f in self.store.list_findings(audit_id, limit=200)
                             if f["rule_id"] in ("schema_missing", "schema_invalid", "schema_incomplete")
                             and any(a.get("url") == url for a in f["affected"])]}

    def check_tls(self, host: str) -> dict:
        return tls_probe(host)

    def dns_email_auth(self, domain: str) -> dict:
        if _is_ip(domain) or domain in ("localhost",):
            return {"checked": False, "reason": "not a public domain"}
        spf = txt_records(domain)
        dmarc = txt_records("_dmarc." + domain)
        return {"checked": True, "spf": [item for item in spf if "spf1" in item.lower()],
                "dmarc": [item for item in dmarc if "dmarc" in item.lower()]}

    def queue_delivery(self, audit_id: str, channel: str, note: str = "") -> dict:
        """Park a finished audit for a human at Spearmint. Nothing is sent to the client."""
        audit = self.store.get_audit(audit_id)
        if not audit or audit["status"] != "done":
            return {"error": "audit is not finished"}
        payload = {"audit_id": audit_id, "url": audit["url"], "report_dir": audit.get("report_dir"),
                   "note": note, "score": audit.get("score")}
        delivery_id = self.store.queue_delivery(audit_id, channel, payload)
        outbox = DATA_DIR / "outbox"
        outbox.mkdir(parents=True, exist_ok=True)
        (outbox / f"{delivery_id}.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return {"delivery_id": delivery_id, "status": "pending_review",
                "message": "Waiting for Spearmint review. Nothing was sent to the client."}

    def approve_delivery(self, delivery_id: int) -> dict:
        delivery = self.store.get_delivery(int(delivery_id))
        if not delivery:
            return {"error": "unknown delivery"}
        self.store.set_delivery_status(int(delivery_id), "approved")
        return {"delivery_id": delivery_id, "status": "approved",
                "message": "Marked approved. Send the report from the report folder yourself, or wire a channel later."}

    def offpage_summary(self, domain: str) -> dict:
        from .connectors import offpage_summary
        return offpage_summary(domain)

    def search_console(self, site_url: str) -> dict:
        from .connectors import search_console
        return search_console(site_url)

    def ga4_overview(self, property_id: str) -> dict:
        from .connectors import ga4_overview
        return ga4_overview(property_id)

    def wordpress_propose(self, audit_id: str) -> dict:
        from .wordpress import propose
        return propose(self.store, audit_id)

    def wordpress_apply(self, audit_id: str, site: str) -> dict:
        from .wordpress import apply_approved
        import os
        user = os.environ.get("WP_USER", "")
        password = os.environ.get("WP_APP_PASSWORD", "")
        if not user or not password:
            return {"error": "WP_USER and WP_APP_PASSWORD are not set on the engine."}
        return apply_approved(self.store, audit_id, site, user, password)


def _validate_finding(raw: dict) -> str:
    if not isinstance(raw, dict):
        return "finding must be an object"
    if not raw.get("rule_id"):
        return "rule_id is required"
    if raw.get("severity") not in SEVERITIES:
        return "severity must be critical, high, medium or low"
    if raw["rule_id"] not in CATALOG and not (raw.get("title") and (raw.get("why") or raw.get("business_impact")) and (raw.get("fix") or raw.get("fix_steps"))):
        return "custom rules need title, why, and fix"
    if not raw.get("evidence") and not raw.get("evidence_ids"):
        return "evidence is required"
    return ""
