"""Turn crawl data into a list of prioritized, client-ready issues."""
from collections import defaultdict
from dataclasses import dataclass, field

from .crawler import CrawlResult

CRITICAL, HIGH, MEDIUM, LOW = "critical", "high", "medium", "low"
SEVERITY_ORDER = {CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3}

TECH, ONPAGE, CONTENT, PERF, SECURITY, MOBILE, SOCIAL = (
    "Technical SEO", "On-Page SEO", "Content", "Performance", "Security", "Mobile & Accessibility",
    "Social & Rich Results",
)
CATEGORIES = [TECH, ONPAGE, CONTENT, PERF, MOBILE, SECURITY, SOCIAL]

# id: (title, category, severity, why it matters, how to fix)
CATALOG = {
    "broken_pages": ("Broken internal pages (4xx)", TECH, CRITICAL,
        "Visitors and search engines hit dead ends. Link equity is wasted and crawl budget is burned.",
        "Restore the pages, 301-redirect them to the closest relevant page, or remove the links pointing at them."),
    "server_errors": ("Server errors (5xx)", TECH, CRITICAL,
        "Pages returning server errors can be dropped from Google's index and lose all traffic.",
        "Check server/application logs for these URLs and fix the underlying errors."),
    "unreachable": ("Pages that failed to load (timeouts / connection errors)", TECH, HIGH,
        "If the crawler could not load these pages, Googlebot likely struggles too.",
        "Investigate hosting performance, firewall/WAF rules and timeouts for these URLs."),
    "redirect_chains": ("Redirect chains (2+ hops)", TECH, MEDIUM,
        "Every extra hop slows users down and dilutes the ranking signals passed along.",
        "Point each redirect straight at its final destination in a single 301."),
    "internal_redirects": ("Internal links pointing to redirects", TECH, LOW,
        "Linking to redirected URLs adds latency and wastes crawl budget.",
        "Update internal links to point directly at the final URL."),
    "no_https": ("Site is not served over HTTPS", SECURITY, CRITICAL,
        "Browsers flag the site as 'Not secure' and Google uses HTTPS as a ranking signal.",
        "Install a TLS certificate and redirect all HTTP traffic to HTTPS."),
    "http_no_redirect": ("HTTP version does not redirect to HTTPS", SECURITY, HIGH,
        "Two versions of the site exist, splitting ranking signals and exposing users to an insecure version.",
        "Add a site-wide 301 redirect from http:// to https://."),
    "www_duplicate": ("Both www and non-www versions resolve", TECH, MEDIUM,
        "Search engines may index two copies of every page, splitting authority between them.",
        "Pick one preferred host and 301-redirect the other to it."),
    "soft_404": ("Missing pages return 200 instead of 404 (soft 404)", TECH, MEDIUM,
        "Google may index junk URLs, and genuine errors are hidden from Search Console.",
        "Configure the server to return a real 404 status for pages that do not exist."),
    "robots_missing": ("robots.txt is missing", TECH, LOW,
        "Without robots.txt you lose control over crawling and a common place to declare your sitemap.",
        "Add a robots.txt at the site root that references the XML sitemap."),
    "robots_blocks_all": ("robots.txt blocks search engines from the whole site", TECH, CRITICAL,
        "Google cannot crawl the site, so it effectively cannot rank.",
        "Remove the 'Disallow: /' rule (this is often left over from a staging site)."),
    "sitemap_missing": ("No XML sitemap found", TECH, MEDIUM,
        "Sitemaps help search engines discover and prioritise pages, especially new or deep ones.",
        "Generate an XML sitemap, submit it in Google Search Console and reference it in robots.txt."),
    "sitemap_not_in_robots": ("Sitemap is not referenced in robots.txt", TECH, LOW,
        "Other search engines rely on robots.txt to discover the sitemap.",
        "Add a 'Sitemap: https://.../sitemap.xml' line to robots.txt."),
    "sitemap_bad_urls": ("Sitemap lists broken, redirected or noindex URLs", TECH, MEDIUM,
        "A dirty sitemap sends mixed signals and makes search engines trust it less.",
        "Only include canonical, indexable URLs that return 200 in the sitemap."),
    "orphan_pages": ("Pages in the sitemap with no internal links (orphans)", TECH, LOW,
        "Orphaned pages receive no internal link equity and are hard for users to find.",
        "Link to these pages from relevant navigation, hub or content pages."),
    "deep_pages": ("Pages buried more than 3 clicks from the homepage", TECH, LOW,
        "Deep pages are crawled less often and are seen as less important.",
        "Flatten the site structure with better navigation, category pages and internal links."),
    "noindex": ("Pages set to noindex", TECH, MEDIUM,
        "These pages are excluded from Google. Confirm this is intentional.",
        "Remove the noindex directive from any page that should rank."),
    "canonical_missing": ("Missing canonical tag", TECH, LOW,
        "Without a canonical, URL variations (tracking params, filters) can create duplicate content.",
        "Add a self-referencing <link rel=\"canonical\"> to every indexable page."),
    "canonical_elsewhere": ("Canonical points to a different URL", TECH, LOW,
        "These pages tell Google to rank another URL instead. Check this is intended.",
        "Make sure canonicals point to the correct preferred version of each page."),
    "title_missing": ("Missing page title", ONPAGE, HIGH,
        "The title tag is the single most important on-page ranking element and the headline in search results.",
        "Write a unique, descriptive title (50-60 characters) containing the page's main keyword."),
    "title_duplicate": ("Duplicate page titles", ONPAGE, MEDIUM,
        "Identical titles make pages compete with each other and confuse searchers.",
        "Give every page a unique title that reflects its specific content."),
    "title_long": ("Title too long (> 60 characters)", ONPAGE, LOW,
        "Google truncates long titles in search results, hiding key messaging.",
        "Shorten titles to roughly 50-60 characters, with the keyword near the start."),
    "title_short": ("Title too short (< 30 characters)", ONPAGE, LOW,
        "Short titles waste valuable search result space and keyword opportunities.",
        "Expand titles to 50-60 characters with descriptive keywords and branding."),
    "meta_missing": ("Missing meta description", ONPAGE, MEDIUM,
        "Google will auto-generate a snippet, which usually lowers click-through rate.",
        "Write a compelling 120-155 character description with a clear call to action."),
    "meta_duplicate": ("Duplicate meta descriptions", ONPAGE, MEDIUM,
        "Duplicate snippets make listings look identical and reduce click-through rate.",
        "Write a unique meta description for every important page."),
    "meta_length": ("Meta description length not optimal", ONPAGE, LOW,
        "Descriptions that are too long get cut off; too short ones under-sell the page.",
        "Keep descriptions between roughly 70 and 160 characters."),
    "h1_missing": ("Missing H1 heading", ONPAGE, MEDIUM,
        "The H1 tells users and search engines what the page is about.",
        "Add one clear H1 per page that includes the primary keyword."),
    "h1_multiple": ("Multiple H1 headings", ONPAGE, LOW,
        "Several H1s dilute the page's main topic signal.",
        "Use a single H1 and structure the rest of the content with H2/H3."),
    "thin_content": ("Thin content (< 300 words)", CONTENT, MEDIUM,
        "Pages with little content rarely rank and can drag down overall site quality.",
        "Expand these pages with useful, original content, or consolidate/noindex them."),
    "img_alt": ("Images missing alt text", MOBILE, MEDIUM,
        "Alt text is needed for screen readers (accessibility compliance) and image search rankings.",
        "Add short, descriptive alt text to every meaningful image (alt=\"\" for decorative ones)."),
    "viewport_missing": ("Missing mobile viewport tag", MOBILE, HIGH,
        "Without it the page is not mobile-friendly, and Google indexes the mobile version first.",
        "Add <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">."),
    "lang_missing": ("Missing language attribute", MOBILE, LOW,
        "Screen readers and search engines use it to understand the page language.",
        "Add a lang attribute, e.g. <html lang=\"en\">."),
    "mixed_content": ("Mixed content (HTTP resources on HTTPS pages)", SECURITY, HIGH,
        "Browsers block or warn on insecure resources, breaking pages and eroding trust.",
        "Load every image, script and stylesheet over https://."),
    "security_headers": ("Missing security headers", SECURITY, MEDIUM,
        "Security headers protect visitors from clickjacking, XSS and protocol downgrade attacks.",
        "Configure the server/CDN to send the missing headers listed below."),
    "slow_response": ("Slow server response (> 1 second)", PERF, MEDIUM,
        "Slow server response delays everything else and hurts Core Web Vitals and conversions.",
        "Add page caching/CDN, optimise database queries, or upgrade hosting."),
    "large_html": ("Large HTML documents (> 500 KB)", PERF, LOW,
        "Heavy HTML slows rendering, especially on mobile networks.",
        "Remove inline bloat (base64 images, inline scripts/styles, huge menus)."),
    "no_compression": ("Text compression not enabled", PERF, MEDIUM,
        "Uncompressed HTML can be 3-5x larger than it needs to be.",
        "Enable Gzip or Brotli compression on the server or CDN."),
    "psi_performance": ("Poor mobile performance score (Lighthouse)", PERF, HIGH,
        "Slow mobile pages lose visitors: bounce probability rises sharply as load time increases.",
        "Address the top PageSpeed opportunities listed in the Performance section."),
    "cwv_fail": ("Failing Core Web Vitals (real-user data)", PERF, HIGH,
        "Core Web Vitals are a Google ranking factor and are measured from real Chrome users.",
        "Prioritise fixes for the metrics rated 'Poor' or 'Needs improvement'."),
    "schema_missing": ("No structured data (schema.org) found", SOCIAL, MEDIUM,
        "Structured data unlocks rich results (stars, FAQs, breadcrumbs) that increase click-through rate.",
        "Add JSON-LD markup: Organization/LocalBusiness site-wide, plus Product, Article, FAQ, Breadcrumb as relevant."),
    "og_missing": ("Missing Open Graph tags", SOCIAL, LOW,
        "Links shared on social media and messaging apps show without a proper title/image.",
        "Add og:title, og:description and og:image to every page."),
    "favicon_missing": ("No favicon", SOCIAL, LOW,
        "Google shows favicons in mobile results; a missing one looks unprofessional.",
        "Add a favicon via <link rel=\"icon\">."),
    "broken_external": ("Broken outbound links", CONTENT, MEDIUM,
        "Links to dead pages hurt user experience and signal a poorly maintained site.",
        "Update or remove these links."),
    "redirect_loop": ("Redirect loop", TECH, CRITICAL,
        "The URL redirects back to itself, so nobody can reach the page.",
        "Remove the circular redirects and point the URL at one final page."),
    "temporary_redirect": ("Temporary redirects (302/307) used for permanent moves", TECH, MEDIUM,
        "A 302 does not pass ranking signals the way a 301 does, so the old URL can stay in the index.",
        "Change permanent moves to a 301 redirect."),
    "canonical_conflict": ("Canonical tags conflict with each other", TECH, HIGH,
        "Pages point at each other (or at a chain) as canonical, so Google has to guess which URL to index.",
        "Pick one canonical URL per piece of content and point every variant at it."),
    "hreflang_missing_self": ("hreflang set is missing a self reference", TECH, MEDIUM,
        "Invalid hreflang is ignored, so the language versions may not be connected.",
        "Each page's hreflang set must include a tag pointing at itself."),
    "hreflang_no_return": ("hreflang link has no return tag", TECH, MEDIUM,
        "Google ignores hreflang pairs that do not point back at each other.",
        "Add a matching hreflang tag on the target page pointing back at the source."),
    "hreflang_bad_code": ("Invalid hreflang language code", TECH, LOW,
        "Unrecognised language codes are dropped.",
        "Use BCP 47 codes such as en, en-IN or x-default."),
    "near_duplicate": ("Near-duplicate pages", CONTENT, MEDIUM,
        "Pages that repeat the same copy compete with each other and dilute rankings.",
        "Merge them, or rewrite one so it answers a different query, and canonicalise the rest."),
    "low_internal_equity": ("Important pages receive very little internal link equity", TECH, LOW,
        "Pages few links point at are crawled less often and rank more weakly.",
        "Add internal links from related, well-linked pages."),
    "schema_invalid": ("Structured data is not valid JSON-LD", SOCIAL, HIGH,
        "Broken JSON-LD is ignored, so the page cannot earn rich results.",
        "Validate the JSON-LD in Google's Rich Results test and fix the syntax."),
    "schema_incomplete": ("Structured data is missing required properties", SOCIAL, MEDIUM,
        "Incomplete schema is not eligible for rich results.",
        "Add the missing properties listed for each type."),
    "image_legacy_format": ("Most images are JPEG or PNG rather than modern formats", PERF, LOW,
        "WebP or AVIF images are much smaller, which improves LCP on mobile.",
        "Serve photographs as WebP or AVIF, with the original as a fallback if needed."),
    "img_missing_dimensions": ("Images are missing width and height", MOBILE, LOW,
        "Browsers cannot reserve space, so the layout jumps as images load (hurts CLS).",
        "Set width and height attributes, or aspect-ratio in CSS, on every image."),
    "no_cache_validators": ("No cache validators on the homepage", PERF, LOW,
        "Browsers and the CDN cannot revalidate the document cheaply.",
        "Send Cache-Control and an ETag or Last-Modified header."),
    "cookie_flags": ("Cookies are missing Secure or HttpOnly", SECURITY, MEDIUM,
        "A cookie without these flags can be stolen by a script or sent over an insecure connection.",
        "Set Secure, HttpOnly and SameSite on every session cookie."),
    "tls_expiring": ("TLS certificate expires soon", SECURITY, HIGH,
        "An expired certificate takes the whole site offline for visitors and Google.",
        "Renew the certificate and turn on automatic renewal."),
    "tls_problem": ("TLS certificate could not be validated", SECURITY, CRITICAL,
        "Browsers warn visitors away, and the site can drop out of search results.",
        "Install a valid certificate that matches the hostname."),
    "spf_missing": ("No SPF record for the domain", SECURITY, MEDIUM,
        "Without SPF, anyone can send email that looks like it came from this domain.",
        "Publish an SPF TXT record listing the servers allowed to send mail."),
    "dmarc_missing": ("No DMARC record for the domain", SECURITY, MEDIUM,
        "Without DMARC, spoofed email is not rejected and the business gets no reports.",
        "Publish a DMARC TXT record on _dmarc, starting with p=none if you need monitoring first."),
    "ai_crawlers_blocked": ("robots.txt blocks AI crawlers from the whole site", TECH, LOW,
        "Assistants that cite the web cannot read the site, which removes it from AI answers.",
        "If the business wants to be cited, allow the AI crawlers you care about. Keep the block only if it is a deliberate choice."),
    "llms_txt_missing": ("No llms.txt file", SOCIAL, LOW,
        "llms.txt is an emerging way to point AI systems at the pages worth citing.",
        "Add /llms.txt with a short description and links to the key pages."),
    "a11y_unlabeled_inputs": ("Form fields have no accessible label", MOBILE, MEDIUM,
        "Unlabelled fields fail WCAG and are harder to complete, which costs enquiries.",
        "Add a <label for> or aria-label to every input."),
    "a11y_empty_controls": ("Links or buttons have no accessible name", MOBILE, MEDIUM,
        "Screen-reader users hear 'link' or 'button' with no destination.",
        "Give every control visible text or an aria-label."),
    "rendered_content_gap": ("Important content only appears after JavaScript runs", TECH, HIGH,
        "If the primary copy is missing from the raw HTML, some crawlers index a thin page.",
        "Server-render the main content, or pre-render it for search engines."),
    "local_nap_inconsistent": ("Business name, address or phone is inconsistent", ONPAGE, MEDIUM,
        "Inconsistent contact details weaken local rankings and Google Business Profile trust.",
        "Use one name, address and phone everywhere, including LocalBusiness schema."),
    "axe_violations": ("Accessibility violations (axe-core, WCAG 2.2)", MOBILE, HIGH,
        "These failures are the ones most likely to block a real user and to show up in an accessibility claim.",
        "Fix the violations listed for each sampled template."),
}


@dataclass
class Issue:
    id: str
    title: str
    category: str
    severity: str
    why: str
    fix: str
    scope: str = "page"  # "page" or "site"
    affected: list = field(default_factory=list)  # [{"url":..., "detail":...}]

    @property
    def count(self):
        return len(self.affected)


class IssueSet:
    def __init__(self):
        self._issues: dict[str, Issue] = {}

    def add(self, issue_id: str, url: str = "", detail: str = "", scope: str = "page"):
        if issue_id not in self._issues:
            title, cat, sev, why, fix = CATALOG[issue_id]
            self._issues[issue_id] = Issue(issue_id, title, cat, sev, why, fix, scope)
        self._issues[issue_id].affected.append({"url": url, "detail": detail})

    def set_severity(self, issue_id: str, severity: str):
        if issue_id in self._issues:
            self._issues[issue_id].severity = severity

    def all(self) -> list[Issue]:
        return sorted(self._issues.values(), key=lambda i: (SEVERITY_ORDER[i.severity], -i.count))


def run_checks(crawl: CrawlResult, psi: dict | None) -> list[Issue]:
    iss = IssueSet()
    html_pages = [p for p in crawl.pages if p.is_html]
    status_by_url = {}
    for p in crawl.pages:
        status_by_url[p.url] = p
        if p.final_url:
            status_by_url.setdefault(p.final_url, p)

    def referrers(url):
        refs = crawl.inlinks.get(url, [])
        if not refs:
            return "found in sitemap" if url in crawl.sitemap.get("urls", []) else ""
        more = f" (+{len(refs) - 3} more)" if len(refs) > 3 else ""
        return "linked from: " + ", ".join(refs[:3]) + more

    # --- status codes & redirects ---
    for p in crawl.pages:
        if p.error:
            iss.add("unreachable", p.url, p.error)
        elif 400 <= p.status < 500:
            iss.add("broken_pages", p.url, f"HTTP {p.status}; {referrers(p.url)}")
        elif p.status >= 500:
            iss.add("server_errors", p.url, f"HTTP {p.status}; {referrers(p.url)}")
        if len(p.redirect_chain) > 2:
            iss.add("redirect_chains", p.url, " -> ".join(p.redirect_chain))
        if p.redirect_chain and crawl.inlinks.get(p.url):
            iss.add("internal_redirects", p.url, f"redirects to {p.final_url}; {referrers(p.url)}")

    # --- site-level ---
    site = crawl.site
    if not site.get("https"):
        iss.add("no_https", crawl.start_url, scope="site")
    elif site.get("http_redirects_to_https") is False:
        iss.add("http_no_redirect", crawl.start_url.replace("https://", "http://", 1), scope="site")
    if site.get("www_duplicate"):
        iss.add("www_duplicate", crawl.start_url, "the alternate www/non-www host serves content without redirecting", scope="site")
    if site.get("soft_404"):
        iss.add("soft_404", crawl.start_url, "a random non-existent URL returned HTTP 200", scope="site")

    robots = crawl.robots
    if not robots["exists"]:
        iss.add("robots_missing", robots["url"], scope="site")
    elif robots["blocks_all"]:
        iss.add("robots_blocks_all", robots["url"], scope="site")

    sm = crawl.sitemap
    if not sm["found"]:
        iss.add("sitemap_missing", crawl.start_url, scope="site")
    else:
        if robots["exists"] and not sm["declared_in_robots"]:
            iss.add("sitemap_not_in_robots", robots["url"], scope="site")
        for u in sm["urls"]:
            p = status_by_url.get(u)
            if not p:
                continue
            if p.error or p.status >= 400:
                iss.add("sitemap_bad_urls", u, f"HTTP {p.status or p.error}")
            elif p.redirect_chain:
                iss.add("sitemap_bad_urls", u, f"redirects to {p.final_url}")
            elif p.is_html and p.data["noindex"]:
                iss.add("sitemap_bad_urls", u, "noindex")
            elif p.is_html and not crawl.inlinks.get(u) and p.depth > 0:
                iss.add("orphan_pages", u, "listed in sitemap but no internal links found")

    hh = site.get("homepage_headers", {})
    if hh:
        missing = []
        if site.get("https") and "strict-transport-security" not in hh:
            missing.append("Strict-Transport-Security (HSTS)")
        if "content-security-policy" not in hh:
            missing.append("Content-Security-Policy")
        if "x-content-type-options" not in hh:
            missing.append("X-Content-Type-Options")
        if "x-frame-options" not in hh and "frame-ancestors" not in hh.get("content-security-policy", ""):
            missing.append("X-Frame-Options")
        if "referrer-policy" not in hh:
            missing.append("Referrer-Policy")
        if missing:
            iss.add("security_headers", crawl.start_url, "missing: " + ", ".join(missing), scope="site")
        if "content-encoding" not in hh:
            iss.add("no_compression", crawl.start_url, "homepage HTML served without gzip/brotli", scope="site")

    # --- page-level on-page / content ---
    titles, metas = defaultdict(list), defaultdict(list)
    for p in html_pages:
        d, u = p.data, p.final_url
        indexable = not d["noindex"]

        if d["noindex"]:
            iss.add("noindex", u, d["meta_robots"] or "X-Robots-Tag header")
        if not d["canonical"]:
            iss.add("canonical_missing", u)
        elif d["canonical"].rstrip("/") != u.rstrip("/"):
            iss.add("canonical_elsewhere", u, f"canonical: {d['canonical']}")

        t = (d["title"] or "").strip()
        if not t:
            iss.add("title_missing", u)
        else:
            if indexable:
                titles[t.lower()].append(u)
            if len(t) > 60:
                iss.add("title_long", u, f"{len(t)} chars: {t}")
            elif len(t) < 30:
                iss.add("title_short", u, f"{len(t)} chars: {t}")

        md = (d["meta_description"] or "").strip()
        if not md:
            iss.add("meta_missing", u)
        else:
            if indexable:
                metas[md.lower()].append(u)
            if len(md) > 160 or len(md) < 70:
                iss.add("meta_length", u, f"{len(md)} chars")

        if not d["h1"]:
            iss.add("h1_missing", u)
        elif len(d["h1"]) > 1:
            iss.add("h1_multiple", u, f"{len(d['h1'])} H1s: " + " | ".join(h[:60] for h in d["h1"][:4]))

        if indexable and d["word_count"] < 300:
            iss.add("thin_content", u, f"{d['word_count']} words")
        if d["images_missing_alt"]:
            iss.add("img_alt", u, f"{len(d['images_missing_alt'])} of {d['image_count']} images")
        if not d["viewport"]:
            iss.add("viewport_missing", u)
        if not d["lang"]:
            iss.add("lang_missing", u)
        if d["mixed_content"]:
            iss.add("mixed_content", u, f"{len(d['mixed_content'])} insecure resources, e.g. {d['mixed_content'][0]}")
        if not (d["og_title"] and d["og_image"]):
            iss.add("og_missing", u, "missing " + ", ".join(k for k, v in (("og:title", d["og_title"]), ("og:description", d["og_description"]), ("og:image", d["og_image"])) if not v))
        if p.response_ms > 1000:
            iss.add("slow_response", u, f"{p.response_ms} ms")
        if p.size_bytes > 500_000:
            iss.add("large_html", u, f"{p.size_bytes // 1024} KB")
        if p.depth > 3:
            iss.add("deep_pages", u, f"{p.depth} clicks deep")

    for group, iid in ((titles, "title_duplicate"), (metas, "meta_duplicate")):
        for text, urls in group.items():
            if len(urls) > 1:
                for u in urls:
                    iss.add(iid, u, f"shared by {len(urls)} pages: \"{text[:80]}\"")

    if html_pages:
        if not any(p.data["schema_types"] for p in html_pages):
            iss.add("schema_missing", crawl.start_url, "no JSON-LD or microdata on any crawled page", scope="site")
        home = html_pages[0]
        if not home.data["favicon"]:
            iss.add("favicon_missing", home.final_url, scope="site")

    # --- external links ---
    for u, code in crawl.external_status.items():
        if code in (404, 410) or code >= 500 or code == -1:
            label = "DNS / connection failed" if code == -1 else f"HTTP {code}"
            refs = crawl.external_links.get(u, [])
            iss.add("broken_external", u, f"{label}; linked from: " + ", ".join(refs[:3]))

    # --- PageSpeed (one result, or one per sampled template) ---
    psi_list = psi if isinstance(psi, list) else ([psi] if psi else [])
    for item in psi_list:
        if not item:
            continue
        perf = item["scores"].get("performance")
        if perf is not None and perf < 90:
            iss.add("psi_performance", item["url"], f"mobile performance score {perf}/100", scope="site")
            if perf >= 50:
                iss.set_severity("psi_performance", MEDIUM)
        bad = [f"{k}: {v['value']}{v['unit']} ({v['category'].replace('_', ' ').lower()})"
               for k, v in item["field"].items()
               if k in ("LCP", "INP", "CLS") and v.get("category") in ("AVERAGE", "SLOW")]
        if bad:
            iss.add("cwv_fail", item["url"], "; ".join(bad), scope="site")

    return iss.all()
