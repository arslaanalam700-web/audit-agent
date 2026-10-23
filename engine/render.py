"""Optional headless rendering and axe-core. Both no-op cleanly when Playwright is absent."""
import re

import httpx

AXE_URL = "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.3/axe.min.js"


def _words_and_links(html: str, url: str) -> tuple[int, set]:
    from .site_audit.extract import extract
    data = extract(html, url)
    return data["word_count"], set(data["links"])


def render_page(url: str) -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"available": False, "url": url, "reason": "playwright is not installed"}
    try:
        raw = httpx.get(url, timeout=25, follow_redirects=True, headers={"User-Agent": "SpearmintAuditBot/2.0"})
        raw_words, raw_links = _words_and_links(raw.text, url)
    except Exception as exc:
        return {"available": False, "url": url, "reason": str(exc)[:200]}
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            html = page.content()
            browser.close()
    except Exception as exc:
        return {"available": False, "url": url, "reason": str(exc)[:240], "raw_words": raw_words}
    rendered_words, rendered_links = _words_and_links(html, url)
    return {
        "available": True,
        "url": url,
        "raw_words": raw_words,
        "rendered_words": rendered_words,
        "links_only_after_js": len(rendered_links - raw_links),
    }


def run_axe(url: str) -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"available": False, "url": url, "reason": "playwright is not installed"}
    try:
        script = httpx.get(AXE_URL, timeout=20).text
    except httpx.HTTPError as exc:
        return {"available": False, "url": url, "reason": f"could not download axe-core: {exc}"}
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.add_script_tag(content=script)
            result = page.evaluate("() => axe.run()")
            browser.close()
    except Exception as exc:
        return {"available": False, "url": url, "reason": str(exc)[:240]}
    violations = []
    for item in result.get("violations") or []:
        violations.append({
            "id": item.get("id"),
            "impact": item.get("impact"),
            "help": item.get("help"),
            "count": len(item.get("nodes") or []),
        })
    return {"available": True, "url": url, "violations": violations[:25]}


def looks_js_rendered(page_data: dict | None) -> bool:
    if not page_data:
        return False
    text = page_data.get("text_sample") or ""
    return page_data.get("script_count", 0) >= 3 and len(re.findall(r"\w+", text)) < 80
