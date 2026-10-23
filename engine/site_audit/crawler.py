"""Async same-site crawler plus site-wide probes (robots, sitemap, HTTPS, www, soft 404)."""
import asyncio
import re
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from urllib import robotparser
from urllib.parse import urlparse

import httpx

from .extract import extract, normalize_url

USER_AGENT = "Mozilla/5.0 (compatible; SpearmintAuditBot/1.0; +https://spearmint.agency)"

SKIP_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".bmp", ".avif",
    ".pdf", ".zip", ".rar", ".gz", ".7z", ".mp4", ".mp3", ".mov", ".avi", ".webm", ".wav",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".csv", ".css", ".js", ".json",
    ".xml", ".txt", ".woff", ".woff2", ".ttf", ".eot", ".exe", ".dmg", ".apk",
)


def bare_host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


@dataclass
class Page:
    url: str
    depth: int
    status: int = 0
    final_url: str = ""
    redirect_chain: list = field(default_factory=list)
    response_ms: int = 0
    content_type: str = ""
    size_bytes: int = 0
    headers: dict = field(default_factory=dict)
    redirect_hops: list = field(default_factory=list)
    set_cookies: list = field(default_factory=list)
    error: str | None = None
    data: dict | None = None
    duplicate_of: str | None = None

    @property
    def is_html(self) -> bool:
        return self.data is not None


@dataclass
class CrawlResult:
    start_url: str
    base_host: str
    pages: list
    inlinks: dict
    external_links: dict
    robots: dict
    sitemap: dict
    site: dict
    external_status: dict = field(default_factory=dict)
    duration_s: float = 0.0


class Crawler:
    def __init__(self, start_url: str, max_pages: int = 200, max_depth: int = 10,
                 concurrency: int = 5, timeout: float = 20.0, respect_robots: bool = True,
                 check_external: bool = False, max_external: int = 300, log=print):
        if not start_url.startswith(("http://", "https://")):
            start_url = "https://" + start_url
        self.start_url = normalize_url(start_url)
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.concurrency = concurrency
        self.timeout = timeout
        self.respect_robots = respect_robots
        self.check_external = check_external
        self.max_external = max_external
        self.log = log

        self.base_host = bare_host(self.start_url)
        self.seen: set[str] = set()
        self.final_seen: dict[str, str] = {}
        self.pages: list[Page] = []
        self.inlinks: dict[str, set] = defaultdict(set)
        self.external_links: dict[str, set] = defaultdict(set)
        self.rp: robotparser.RobotFileParser | None = None
        self.queue: asyncio.Queue = asyncio.Queue()

    def is_internal(self, url: str) -> bool:
        return bare_host(url) == self.base_host

    def crawlable(self, url: str) -> bool:
        path = urlparse(url).path.lower()
        if path.endswith(SKIP_EXTENSIONS):
            return False
        if self.respect_robots and self.rp is not None:
            return self.rp.can_fetch(USER_AGENT, url) and self.rp.can_fetch("*", url)
        return True

    def enqueue(self, url: str, depth: int):
        if url in self.seen or len(self.seen) >= self.max_pages or depth > self.max_depth:
            return
        if not self.crawlable(url):
            return
        self.seen.add(url)
        self.queue.put_nowait((url, depth))

    async def run(self) -> CrawlResult:
        t0 = time.time()
        limits = httpx.Limits(max_connections=self.concurrency * 2)
        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
            follow_redirects=True, timeout=self.timeout, limits=limits, verify=True,
            max_redirects=8,
        ) as client:
            self.client = client

            # Resolve the canonical start URL (e.g. http -> https, apex -> www).
            try:
                r = await client.get(self.start_url)
                resolved = normalize_url(str(r.url))
                if resolved and bare_host(resolved) == self.base_host:
                    self.start_url = resolved
            except httpx.HTTPError as e:
                raise SystemExit(f"Could not reach {self.start_url}: {e}")

            origin = f"{urlparse(self.start_url).scheme}://{urlparse(self.start_url).netloc}"
            robots = await self._robots(origin)
            sitemap = await self._sitemap(origin, robots.get("sitemaps", []))
            site = await self._site_probes(origin)

            self.enqueue(self.start_url, 0)
            for u in sitemap.get("urls", []):
                if self.is_internal(u):
                    self.enqueue(u, 1)

            workers = [asyncio.create_task(self._worker()) for _ in range(self.concurrency)]
            await self.queue.join()
            for w in workers:
                w.cancel()

            external_status = {}
            if self.check_external and self.external_links:
                external_status = await self._check_external()

        self.pages.sort(key=lambda p: (p.depth, p.url))
        return CrawlResult(
            start_url=self.start_url, base_host=self.base_host, pages=self.pages,
            inlinks={k: sorted(v) for k, v in self.inlinks.items()},
            external_links={k: sorted(v) for k, v in self.external_links.items()},
            robots=robots, sitemap=sitemap, site=site,
            external_status=external_status, duration_s=round(time.time() - t0, 1),
        )

    async def _worker(self):
        while True:
            url, depth = await self.queue.get()
            try:
                await self._fetch(url, depth)
            except Exception as e:  # never let one page kill the crawl
                self.log(f"  ! error on {url}: {e}")
            finally:
                self.queue.task_done()

    async def _fetch(self, url: str, depth: int):
        page = Page(url=url, depth=depth)
        self.pages.append(page)
        t = time.perf_counter()
        try:
            r = await self.client.get(url)
        except httpx.TooManyRedirects:
            page.error = "redirect loop"
            page.response_ms = int((time.perf_counter() - t) * 1000)
            self.log(f"  [LOOP] {url}")
            return
        except httpx.HTTPError as e:
            page.error = type(e).__name__ + (f": {e}" if str(e) else "")
            page.response_ms = int((time.perf_counter() - t) * 1000)
            self.log(f"  [ERR] {url} ({page.error})")
            return

        page.response_ms = int(r.elapsed.total_seconds() * 1000) if r.elapsed else int((time.perf_counter() - t) * 1000)
        page.status = r.status_code
        page.final_url = normalize_url(str(r.url)) or str(r.url)
        page.redirect_chain = [str(h.url) for h in r.history] + ([str(r.url)] if r.history else [])
        page.redirect_hops = [{"url": str(h.url), "status": h.status_code} for h in r.history]
        page.set_cookies = list(r.headers.get_list("set-cookie"))
        page.content_type = r.headers.get("content-type", "")
        page.size_bytes = len(r.content)
        page.headers = {k.lower(): v for k, v in r.headers.items()}
        self.log(f"  [{r.status_code}] {url}")

        if r.history and page.final_url not in self.seen:
            self.seen.add(page.final_url)

        if r.status_code >= 400 or "html" not in page.content_type.lower():
            return
        if not self.is_internal(page.final_url):
            return
        if page.final_url in self.final_seen:
            page.duplicate_of = self.final_seen[page.final_url]
            return
        self.final_seen[page.final_url] = url

        data = await asyncio.to_thread(extract, r.text, page.final_url)
        xrobots = page.headers.get("x-robots-tag", "").lower()
        if "noindex" in xrobots:
            data["noindex"] = True
        page.data = data

        for link in data["links"]:
            if self.is_internal(link):
                self.inlinks[link].add(page.final_url)
                self.enqueue(link, depth + 1)
            else:
                self.external_links[link].add(page.final_url)

    async def _robots(self, origin: str) -> dict:
        info = {"url": origin + "/robots.txt", "exists": False, "blocks_all": False, "sitemaps": [], "content": ""}
        try:
            r = await self.client.get(info["url"])
        except httpx.HTTPError:
            return info
        if r.status_code == 200 and "html" not in r.headers.get("content-type", ""):
            info["exists"] = True
            info["content"] = r.text[:5000]
            self.rp = robotparser.RobotFileParser()
            self.rp.parse(r.text.splitlines())
            info["sitemaps"] = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", r.text)
            info["blocks_all"] = not self.rp.can_fetch("Googlebot", origin + "/")
        return info

    async def _sitemap(self, origin: str, declared: list) -> dict:
        info = {"found": False, "declared_in_robots": bool(declared), "sources": [], "urls": []}
        candidates = list(declared) or [origin + "/sitemap.xml", origin + "/sitemap_index.xml"]
        urls: list[str] = []
        to_visit, visited = list(candidates), set()
        while to_visit and len(visited) < 25 and len(urls) < 5000:
            sm = to_visit.pop(0)
            if sm in visited:
                continue
            visited.add(sm)
            try:
                r = await self.client.get(sm)
            except httpx.HTTPError:
                continue
            if r.status_code != 200 or "<" not in r.text[:200]:
                continue
            locs = [l.strip() for l in re.findall(r"<loc>\s*(.*?)\s*</loc>", r.text, re.S)]
            locs = [l.replace("&amp;", "&") for l in locs]
            info["found"] = True
            info["sources"].append(sm)
            if "<sitemapindex" in r.text:
                to_visit.extend(locs)
            else:
                urls.extend(u for u in (normalize_url(l) for l in locs) if u)
        info["urls"] = list(dict.fromkeys(urls))[:5000]
        return info

    async def _site_probes(self, origin: str) -> dict:
        site = {"https": origin.startswith("https://"), "http_redirects_to_https": None,
                "www_duplicate": None, "soft_404": None, "homepage_headers": {}}
        host = urlparse(origin).netloc

        try:
            r = await self.client.get(f"http://{host}/")
            site["http_redirects_to_https"] = str(r.url).startswith("https://")
        except httpx.HTTPError:
            pass

        alt = host[4:] if host.startswith("www.") else "www." + host
        try:
            r = await self.client.get(f"{urlparse(origin).scheme}://{alt}/")
            site["www_duplicate"] = r.status_code == 200 and (urlparse(str(r.url)).hostname or "") == alt
        except httpx.HTTPError:
            pass

        try:
            r = await self.client.get(f"{origin}/{uuid.uuid4().hex}-not-a-real-page")
            site["soft_404"] = r.status_code == 200
            site["not_found_status"] = r.status_code
        except httpx.HTTPError:
            pass

        try:
            r = await self.client.get(self.start_url)
            site["homepage_headers"] = {k.lower(): v for k, v in r.headers.items()}
        except httpx.HTTPError:
            pass
        return site

    async def _check_external(self) -> dict:
        targets = list(self.external_links)[: self.max_external]
        sem = asyncio.Semaphore(self.concurrency * 2)
        results = {}

        async def check(u):
            async with sem:
                try:
                    r = await self.client.head(u, timeout=10)
                    if r.status_code in (403, 405, 501) or r.status_code >= 500:
                        r = await self.client.get(u, timeout=10)
                    results[u] = r.status_code
                except httpx.ConnectError:
                    results[u] = -1
                except httpx.HTTPError:
                    results[u] = 0

        self.log(f"  checking {len(targets)} external links...")
        await asyncio.gather(*(check(u) for u in targets))
        return results
