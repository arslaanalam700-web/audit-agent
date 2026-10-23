"""Google PageSpeed Insights (Lighthouse + Chrome UX Report field data)."""
import httpx

API = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
CATEGORIES = ["performance", "seo", "accessibility", "best-practices"]

FIELD_METRICS = {
    "LARGEST_CONTENTFUL_PAINT_MS": ("LCP", "ms"),
    "INTERACTION_TO_NEXT_PAINT": ("INP", "ms"),
    "CUMULATIVE_LAYOUT_SHIFT_SCORE": ("CLS", ""),
    "FIRST_CONTENTFUL_PAINT_MS": ("FCP", "ms"),
    "EXPERIMENTAL_TIME_TO_FIRST_BYTE": ("TTFB", "ms"),
}

LAB_AUDITS = {
    "largest-contentful-paint": "LCP",
    "cumulative-layout-shift": "CLS",
    "total-blocking-time": "TBT",
    "first-contentful-paint": "FCP",
    "speed-index": "Speed Index",
}


def run_pagespeed(url: str, strategy: str = "mobile", api_key: str | None = None, log=print) -> dict | None:
    params = [("url", url), ("strategy", strategy)] + [("category", c) for c in CATEGORIES]
    if api_key:
        params.append(("key", api_key))
    log(f"  running PageSpeed Insights ({strategy})...")
    try:
        r = httpx.get(API, params=params, timeout=150)
    except httpx.HTTPError as e:
        log(f"  ! PageSpeed failed: {e}")
        return None
    if r.status_code != 200:
        msg = r.json().get("error", {}).get("message", r.text[:200]) if r.headers.get("content-type", "").startswith("application/json") else r.text[:200]
        log(f"  ! PageSpeed returned {r.status_code}: {msg}")
        if r.status_code == 429:
            log("    (set PAGESPEED_API_KEY - a free key from Google Cloud removes the rate limit)")
        return None

    d = r.json()
    lh = d.get("lighthouseResult", {})
    scores = {k: round((v.get("score") or 0) * 100) for k, v in lh.get("categories", {}).items()}

    lab = {}
    for audit_id, label in LAB_AUDITS.items():
        a = lh.get("audits", {}).get(audit_id)
        if a:
            lab[label] = a.get("displayValue", "")

    field = {}
    metrics = (d.get("loadingExperience") or {}).get("metrics") or {}
    for key, (label, unit) in FIELD_METRICS.items():
        m = metrics.get(key)
        if not m:
            continue
        p = m.get("percentile")
        if key == "CUMULATIVE_LAYOUT_SHIFT_SCORE" and p is not None:
            p = p / 100
        field[label] = {"value": p, "unit": unit, "category": m.get("category")}

    opportunities = []
    for a in lh.get("audits", {}).values():
        details = a.get("details") or {}
        if details.get("type") == "opportunity" and (a.get("score") is not None and a["score"] < 0.9):
            opportunities.append({
                "title": a.get("title"),
                "savings_ms": round(details.get("overallSavingsMs") or 0),
                "display": a.get("displayValue", ""),
            })
    opportunities.sort(key=lambda o: -o["savings_ms"])

    return {
        "strategy": strategy,
        "url": url,
        "scores": scores,
        "lab": lab,
        "field": field,
        "field_overall": (d.get("loadingExperience") or {}).get("overall_category"),
        "opportunities": opportunities[:8],
    }
