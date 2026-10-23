"""Turn verified findings into fix tickets and a rupee estimate."""
from .site_audit.checks import CATALOG, SEVERITY_ORDER

HOURS = {"critical": 4.0, "high": 2.0, "medium": 1.0, "low": 0.5}
RATE_INR = 1000

_CONTENT = {"title_missing", "title_duplicate", "title_long", "title_short", "meta_missing", "meta_duplicate",
            "meta_length", "h1_missing", "h1_multiple", "thin_content", "img_alt", "near_duplicate", "og_missing"}
_SEO = {"canonical_missing", "canonical_elsewhere", "canonical_conflict", "hreflang_missing_self",
        "hreflang_no_return", "hreflang_bad_code", "schema_missing", "schema_invalid", "schema_incomplete",
        "sitemap_missing", "sitemap_bad_urls", "noindex"}


def owner_for(rule_id: str) -> str:
    if rule_id in _CONTENT:
        return "content"
    if rule_id in _SEO:
        return "seo"
    return "developer"


def effort_hours(severity: str, affected_count: int) -> float:
    base = HOURS.get(severity, 1.0)
    extra = min(3.0, 0.15 * max(0, affected_count - 1))
    return round(base + extra, 1)


def ticket_from_finding(finding: dict) -> dict:
    affected = finding.get("affected") or []
    urls = [item.get("url") for item in affected if item.get("url")]
    steps = finding.get("fix_steps") or finding.get("fix") or ""
    return {
        "finding_id": finding.get("id"),
        "rule_id": finding["rule_id"],
        "title": finding.get("title") or finding["rule_id"],
        "owner": owner_for(finding["rule_id"]),
        "effort_hours": effort_hours(finding.get("severity") or "medium", len(affected)),
        "severity": finding.get("severity"),
        "steps": steps,
        "code": "",
        "acceptance": finding.get("acceptance_check") or f"A re-audit no longer reports {finding['rule_id']} on the listed URLs.",
        "urls": urls,
        "status": "open",
        "platform_fixes": finding.get("platform_fixes") or {},
    }


def build_tickets(findings: list[dict], verified_only: bool = True) -> list[dict]:
    chosen = []
    for finding in findings:
        if verified_only and finding.get("status") not in (None, "verified"):
            continue
        if finding.get("rule_id") not in CATALOG and not finding.get("title"):
            continue
        chosen.append(ticket_from_finding(finding))
    chosen.sort(key=lambda t: (SEVERITY_ORDER.get(t["severity"], 9), -t["effort_hours"]))
    return chosen


def estimate(tickets: list[dict], rate_inr: int = RATE_INR) -> dict:
    hours = round(sum(t["effort_hours"] for t in tickets), 1)
    return {"hours": hours, "rate_inr": rate_inr, "total_inr": int(round(hours * rate_inr)), "tickets": len(tickets)}
