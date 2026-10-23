"""Checks that need the whole crawl, not a single page: links, schema, DNS, TLS, templates."""
import ipaddress
import re
import socket
import ssl
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from .site_audit.checks import IssueSet

AI_BOTS = ("GPTBot", "Google-Extended", "ClaudeBot", "CCBot", "Bytespider", "Applebot-Extended")
SCHEMA_REQUIRED = {
    "Organization": ["name"],
    "LocalBusiness": ["name", "address"],
    "Article": ["headline"],
    "BlogPosting": ["headline"],
    "Product": ["name"],
    "FAQPage": ["mainEntity"],
    "BreadcrumbList": ["itemListElement"],
}
_LANG = re.compile(r"^[a-z]{2,3}(-[a-z0-9]{2,8})*$", re.I)


def template_key(url: str) -> str:
    parts = []
    for seg in (urlparse(url).path or "/").split("/"):
        if not seg:
            continue
        parts.append(re.sub(r"\d+", "{n}", seg).lower())
    return "/" + "/".join(parts) if parts else "/"


def pagerank(edges: list[tuple[str, str]], iters: int = 20, damping: float = 0.85) -> dict[str, float]:
    nodes = {n for edge in edges for n in edge}
    if not nodes:
        return {}
    count = len(nodes)
    rank = {n: 1 / count for n in nodes}
    outgoing = defaultdict(list)
    for src, dst in edges:
        outgoing[src].append(dst)
    for _ in range(iters):
        nxt = {n: (1 - damping) / count for n in nodes}
        for node in nodes:
            dests = outgoing[node]
            if not dests:
                share = damping * rank[node] / count
                for other in nodes:
                    nxt[other] += share
            else:
                share = damping * rank[node] / len(dests)
                for dest in dests:
                    nxt[dest] += share
        rank = nxt
    return rank


def _same(a: str, b: str) -> bool:
    return (a or "").rstrip("/") == (b or "").rstrip("/")


def _nodes(data):
    if isinstance(data, list):
        for item in data:
            yield from _nodes(item)
    elif isinstance(data, dict):
        yield data
        if "@graph" in data:
            yield from _nodes(data["@graph"])


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def txt_records(name: str) -> list[str]:
    try:
        out = subprocess.run(["nslookup", "-type=TXT", name], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return re.findall(r'"([^"]*)"', (out.stdout or "") + (out.stderr or ""))


def tls_probe(host: str) -> dict:
    if not host or _is_ip(host):
        return {"skipped": True}
    try:
        context = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=12) as sock:
            with context.wrap_socket(sock, server_hostname=host) as secure:
                cert = secure.getpeercert()
        expires = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
        days = (expires - datetime.now(timezone.utc)).days
        return {"ok": True, "days_left": days}
    except Exception as exc:  # certificate, DNS, or connection failure is itself a finding
        return {"ok": False, "error": str(exc)[:240]}


def llms_txt(origin: str) -> dict:
    url = origin.rstrip("/") + "/llms.txt"
    try:
        response = httpx.get(url, timeout=15, follow_redirects=True)
    except httpx.HTTPError as exc:
        return {"found": False, "url": url, "error": str(exc)[:160]}
    body = response.text[:500]
    found = response.status_code == 200 and body.strip() and "<html" not in body[:200].lower()
    return {"found": found, "url": url, "status": response.status_code}


def blocked_ai_bots(robots_txt: str) -> list[str]:
    agents: list[str] = []
    blocked: dict[str, list[str]] = defaultdict(list)
    for raw in robots_txt.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            agents = []
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            agents.append(value)
        elif key == "disallow":
            for agent in agents:
                blocked[agent.lower()].append(value)
    found = []
    for bot in AI_BOTS:
        if "/" in blocked.get(bot.lower(), []):
            found.append(bot)
    return found


def _schema_issues(iss: IssueSet, pages):
    for page in pages:
        if not page.data:
            continue
        for block in page.data.get("schema_blocks") or []:
            if block.get("_invalid"):
                iss.add("schema_invalid", page.final_url, block.get("snippet") or "JSON-LD did not parse")
                continue
            for node in _nodes(block):
                types = node.get("@type")
                if isinstance(types, str):
                    types = [types]
                for schema_type in types or []:
                    short = schema_type.rstrip("/").split("/")[-1]
                    missing = [key for key in SCHEMA_REQUIRED.get(short, []) if not node.get(key)]
                    if missing:
                        iss.add("schema_incomplete", page.final_url, f"{short} missing {', '.join(missing)}")


def _hreflang_issues(iss: IssueSet, pages):
    by_url = {p.final_url: p for p in pages if p.is_html}
    for page in pages:
        if not page.data:
            continue
        tags = page.data.get("hreflang") or []
        if not tags:
            continue
        if not any(_same(tag.get("href") or "", page.final_url) for tag in tags):
            iss.add("hreflang_missing_self", page.final_url, "no hreflang href points at this page")
        for tag in tags:
            code = (tag.get("lang") or "").strip()
            if code.lower() != "x-default" and not _LANG.match(code):
                iss.add("hreflang_bad_code", page.final_url, code)
            target = by_url.get(tag.get("href") or "")
            if target and target.data is not None:
                back = target.data.get("hreflang") or []
                if not any(_same(item.get("href") or "", page.final_url) for item in back):
                    iss.add("hreflang_no_return", page.final_url, f"{code} -> {tag.get('href')} does not point back")


def _canonical_conflicts(iss: IssueSet, pages):
    canon = {}
    for page in pages:
        if page.data and page.data.get("canonical"):
            canon[page.final_url.rstrip("/")] = page.data["canonical"].rstrip("/")
    for src, dst in canon.items():
        if dst == src:
            continue
        seen = {src}
        cursor = dst
        while cursor in canon and canon[cursor] != cursor:
            if cursor in seen:
                iss.add("canonical_conflict", src, " -> ".join(list(seen) + [cursor]))
                break
            seen.add(cursor)
            cursor = canon[cursor]


def _near_duplicates(iss: IssueSet, pages):
    grouped = defaultdict(list)
    for page in pages:
        if not page.data or page.data.get("noindex"):
            continue
        digest = page.data.get("simhash") or ""
        if digest and page.data.get("word_count", 0) >= 120:
            grouped[digest].append(page.final_url)
    # Also catch hashes within a distance of 3 by comparing a bounded sample.
    keys = list(grouped)
    for i, left in enumerate(keys):
        for right in keys[i + 1:i + 40]:
            if (int(left, 16) ^ int(right, 16)).bit_count() <= 3:
                grouped[left].extend(grouped[right])
    reported = set()
    for urls in grouped.values():
        uniq = tuple(sorted(set(urls)))
        if len(uniq) > 1 and uniq not in reported:
            reported.add(uniq)
            for url in uniq:
                iss.add("near_duplicate", url, "same or nearly the same copy as " + ", ".join(u for u in uniq if u != url))


def deep_issues(crawl, probe: dict | None = None):
    """Extra findings that look at the crawl as a whole. `probe` holds TLS, DNS, render and axe results."""
    probe = probe or {}
    iss = IssueSet()
    html_pages = [p for p in crawl.pages if p.is_html]

    for page in crawl.pages:
        if page.error and "redirect loop" in page.error:
            iss.add("redirect_loop", page.url, page.error)
        if any(hop.get("status") in (302, 307) for hop in page.redirect_hops):
            iss.add("temporary_redirect", page.url, ", ".join(f"{h['status']} {h['url']}" for h in page.redirect_hops))

    _canonical_conflicts(iss, html_pages)
    _hreflang_issues(iss, html_pages)
    _schema_issues(iss, html_pages)
    _near_duplicates(iss, html_pages)

    legacy = sum(p.data.get("legacy_images", 0) for p in html_pages)
    total_images = sum(p.data.get("image_count", 0) for p in html_pages)
    if total_images and legacy / total_images >= 0.5:
        iss.add("image_legacy_format", crawl.start_url,
                f"{legacy} of {total_images} images are JPEG/PNG", scope="site")
    for page in html_pages:
        missing = [img for img in page.data.get("images_meta") or [] if img.get("missing_dimensions") and img.get("src")]
        if missing:
            iss.add("img_missing_dimensions", page.final_url, f"{len(missing)} images")
        if page.data.get("unlabeled_inputs"):
            iss.add("a11y_unlabeled_inputs", page.final_url, f"{page.data['unlabeled_inputs']} fields")
        if page.data.get("empty_controls"):
            iss.add("a11y_empty_controls", page.final_url, f"{page.data['empty_controls']} controls")

    headers = crawl.site.get("homepage_headers") or {}
    if headers and "cache-control" not in headers and "etag" not in headers and "last-modified" not in headers:
        iss.add("no_cache_validators", crawl.start_url, "no Cache-Control, ETag or Last-Modified", scope="site")

    cookies = []
    for page in crawl.pages:
        cookies.extend(page.set_cookies)
    weak = [c.split(";", 1)[0][:40] for c in cookies if "httponly" not in c.lower() or ("secure" not in c.lower() and crawl.site.get("https"))]
    if weak:
        iss.add("cookie_flags", crawl.start_url, "examples: " + ", ".join(weak[:4]), scope="site")

    ranks = probe.get("pagerank") or {}
    if len(html_pages) >= 15 and ranks:
        ordered = sorted(((ranks.get(p.final_url, 0), p.final_url) for p in html_pages if not p.data.get("noindex")), key=lambda item: item[0])
        weak_pages = [url for score, url in ordered[:5] if score < (ordered[-1][0] if ordered else 0) * 0.15]
        for url in weak_pages:
            iss.add("low_internal_equity", url, f"internal PageRank {ranks.get(url, 0):.4f}")

    phones = {tel for p in html_pages for tel in (p.data.get("tels") or [])}
    if len(phones) > 1:
        iss.add("local_nap_inconsistent", crawl.start_url, "phone numbers found: " + ", ".join(sorted(phones)), scope="site")

    tls = probe.get("tls") or {}
    if tls.get("ok") and tls.get("days_left", 999) < 30:
        iss.add("tls_expiring", crawl.start_url, f"expires in {tls['days_left']} days", scope="site")
    elif tls.get("ok") is False and not tls.get("skipped"):
        iss.add("tls_problem", crawl.start_url, tls.get("error") or "validation failed", scope="site")

    dns = probe.get("dns") or {}
    if dns.get("checked"):
        if not dns.get("spf"):
            iss.add("spf_missing", crawl.start_url, "no TXT record starting with v=spf1", scope="site")
        if not dns.get("dmarc"):
            iss.add("dmarc_missing", crawl.start_url, "no TXT record on _dmarc", scope="site")

    robots = crawl.robots.get("content") or ""
    blocked = blocked_ai_bots(robots) if robots else []
    if blocked:
        iss.add("ai_crawlers_blocked", crawl.robots.get("url") or crawl.start_url,
                "blocked: " + ", ".join(blocked), scope="site")
    if probe.get("llms") and not probe["llms"].get("found"):
        iss.add("llms_txt_missing", probe["llms"].get("url") or crawl.start_url, "GET /llms.txt did not return a text file", scope="site")

    for item in probe.get("rendered") or []:
        if item.get("available") and item.get("rendered_words", 0) > max(80, item.get("raw_words", 0) * 1.8):
            iss.add("rendered_content_gap", item["url"],
                    f"raw HTML has {item['raw_words']} words, rendered page has {item['rendered_words']}")
    for item in probe.get("axe") or []:
        for violation in item.get("violations") or []:
            iss.add("axe_violations", item["url"], f"{violation.get('id')}: {violation.get('help')} ({violation.get('count')} nodes)")

    return iss.all()
