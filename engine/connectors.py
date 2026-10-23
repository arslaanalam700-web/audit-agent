"""Optional paid and client-granted data sources. Each one returns available:false when it is not configured."""
import os
from urllib.parse import quote

import httpx


def offpage_summary(domain: str) -> dict:
    login = os.environ.get("DATAFORSEO_LOGIN")
    password = os.environ.get("DATAFORSEO_PASSWORD")
    if not login or not password:
        return {"available": False, "reason": "Set DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD to enable off-page data."}
    domain = domain.replace("https://", "").replace("http://", "").strip("/")
    auth = (login, password)
    try:
        backlinks = httpx.post(
            "https://api.dataforseo.com/v3/backlinks/summary/live",
            auth=auth, timeout=60,
            json=[{"target": domain}],
        )
        keywords = httpx.post(
            "https://api.dataforseo.com/v3/dataforseo_labs/google/ranked_keywords/live",
            auth=auth, timeout=90,
            json=[{"target": domain, "location_code": 2356, "language_code": "en", "limit": 20}],
        )
        backlinks.raise_for_status()
        keywords.raise_for_status()
    except httpx.HTTPError as exc:
        return {"available": False, "reason": str(exc)[:300]}
    return {"available": True, "domain": domain, "backlinks": backlinks.json(), "ranked_keywords": keywords.json()}


def search_console(site_url: str, days: int = 28) -> dict:
    token = os.environ.get("SEARCH_CONSOLE_ACCESS_TOKEN")
    if not token:
        return {"available": False, "reason": "Set SEARCH_CONSOLE_ACCESS_TOKEN after the client grants Search Console access."}
    endpoint = f"https://www.googleapis.com/webmasters/v3/sites/{quote(site_url, safe='')}/searchAnalytics/query"
    body = {"startDate": _days_ago(days), "endDate": _days_ago(1), "dimensions": ["query"], "rowLimit": 25}
    try:
        response = httpx.post(endpoint, headers={"Authorization": f"Bearer {token}"}, json=body, timeout=40)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        return {"available": False, "reason": str(exc)[:300]}
    return {"available": True, "site": site_url, "queries": response.json()}


def ga4_overview(property_id: str, days: int = 28) -> dict:
    token = os.environ.get("GA4_ACCESS_TOKEN")
    if not token:
        return {"available": False, "reason": "Set GA4_ACCESS_TOKEN after the client grants Analytics access."}
    endpoint = f"https://analyticsdata.googleapis.com/v1beta/properties/{property_id}:runReport"
    body = {
        "dateRanges": [{"startDate": f"{days}daysAgo", "endDate": "yesterday"}],
        "metrics": [{"name": "sessions"}, {"name": "engagedSessions"}, {"name": "conversions"}],
        "dimensions": [{"name": "sessionDefaultChannelGroup"}],
    }
    try:
        response = httpx.post(endpoint, headers={"Authorization": f"Bearer {token}"}, json=body, timeout=40)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        return {"available": False, "reason": str(exc)[:300]}
    return {"available": True, "property_id": property_id, "report": response.json()}


def _days_ago(days: int) -> str:
    from datetime import date, timedelta
    return (date.today() - timedelta(days=days)).isoformat()
