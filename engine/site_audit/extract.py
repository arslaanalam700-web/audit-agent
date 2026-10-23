"""Pull SEO-relevant data out of an HTML document."""
import hashlib
import json
import re
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

SKIP_SCHEMES = ("mailto:", "tel:", "javascript:", "data:", "sms:", "whatsapp:")


def normalize_url(url: str) -> str | None:
    url, _ = urldefrag(url.strip())
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        return None
    host = p.hostname.lower() if p.hostname else ""
    port = p.port
    netloc = host
    if port and not ((p.scheme == "http" and port == 80) or (p.scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"
    path = p.path or "/"
    return p._replace(scheme=p.scheme.lower(), netloc=netloc, path=path).geturl()


def _schema_types(data, out: set):
    if isinstance(data, list):
        for item in data:
            _schema_types(item, out)
    elif isinstance(data, dict):
        t = data.get("@type")
        if isinstance(t, str):
            out.add(t)
        elif isinstance(t, list):
            out.update(x for x in t if isinstance(x, str))
        if "@graph" in data:
            _schema_types(data["@graph"], out)


def extract(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "lxml")

    base_tag = soup.find("base", href=True)
    base = urljoin(url, base_tag["href"]) if base_tag else url

    metas = {}
    charset = False
    for m in soup.find_all("meta"):
        if m.get("charset"):
            charset = True
        if (m.get("http-equiv") or "").lower() == "content-type":
            charset = True
        key = (m.get("name") or m.get("property") or "").strip().lower()
        if key and key not in metas:
            metas[key] = (m.get("content") or "").strip()

    title_tag = soup.find("title")
    title = title_tag.get_text(" ", strip=True) if title_tag else None

    canonical = None
    hreflang = []
    favicon = False
    for link in soup.find_all("link", href=True):
        rel = [r.lower() for r in (link.get("rel") or [])]
        if "canonical" in rel and canonical is None:
            canonical = normalize_url(urljoin(base, link["href"]))
        if "alternate" in rel and link.get("hreflang"):
            hreflang.append({
                "lang": link["hreflang"].strip(),
                "href": normalize_url(urljoin(base, link["href"])),
            })
        if "icon" in rel:
            favicon = True

    schema = set()
    schema_blocks = []
    for s in soup.find_all("script", type=re.compile("ld\\+json", re.I)):
        raw = s.string or ""
        try:
            parsed = json.loads(raw)
            schema_blocks.append(parsed)
            _schema_types(parsed, schema)
        except (ValueError, TypeError):
            schema_blocks.append({"_invalid": True, "snippet": raw.strip()[:160]})
    for el in soup.find_all(attrs={"itemtype": True}):
        schema.add(el["itemtype"].rstrip("/").split("/")[-1])

    is_https = url.startswith("https://")
    mixed = set()
    if is_https:
        for tag, attr in (("img", "src"), ("script", "src"), ("iframe", "src"),
                          ("link", "href"), ("source", "src"), ("video", "src"), ("audio", "src")):
            for el in soup.find_all(tag):
                v = (el.get(attr) or "").strip()
                if tag == "link" and "stylesheet" not in [r.lower() for r in (el.get("rel") or [])]:
                    continue
                if v.lower().startswith("http://"):
                    mixed.add(v)

    links, nofollow_links = [], 0
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#") or href.lower().startswith(SKIP_SCHEMES):
            continue
        u = normalize_url(urljoin(base, href))
        if not u:
            continue
        links.append(u)
        if "nofollow" in [r.lower() for r in (a.get("rel") or [])]:
            nofollow_links += 1

    images = soup.find_all("img")
    imgs_missing_alt = [urljoin(base, i.get("src") or i.get("data-src") or "")
                        for i in images if i.get("alt") is None]

    h1 = [h.get_text(" ", strip=True) for h in soup.find_all("h1")]
    h2_count = len(soup.find_all("h2"))

    html_tag = soup.find("html")
    lang = (html_tag.get("lang") or "").strip() if html_tag else ""
    script_count = len(soup.find_all("script", src=True))

    unlabeled_inputs = 0
    for inp in soup.find_all("input"):
        typ = (inp.get("type") or "text").lower()
        if typ in ("hidden", "submit", "button", "image"):
            continue
        if inp.get("aria-label") or inp.get("aria-labelledby") or inp.get("title"):
            continue
        iid = inp.get("id")
        if iid and soup.find("label", attrs={"for": iid}):
            continue
        if inp.find_parent("label"):
            continue
        unlabeled_inputs += 1
    empty_controls = 0
    for el in soup.find_all(["button", "a"]):
        if el.name == "a" and not el.get("href"):
            continue
        if el.get_text(" ", strip=True) or el.get("aria-label") or el.find("img", alt=True):
            continue
        empty_controls += 1
    images_meta = []
    legacy_images = 0
    for i in images:
        src = (i.get("src") or i.get("data-src") or "").strip()
        ext = src.lower().split("?")[0].rsplit(".", 1)[-1] if "." in src else ""
        if ext in ("jpg", "jpeg", "png", "bmp"):
            legacy_images += 1
        images_meta.append({
            "src": urljoin(base, src) if src else "",
            "missing_dimensions": not (i.get("width") and i.get("height")),
        })
    tels = [a["href"][4:].strip() for a in soup.find_all("a", href=True) if a["href"].lower().startswith("tel:")]
    addresses = [a.get_text(" ", strip=True) for a in soup.find_all("address")]

    for t in soup(["script", "style", "noscript", "template", "svg"]):
        t.decompose()
    body = soup.body or soup
    text = body.get_text(" ", strip=True)
    word_count = len(re.findall(r"\w+", text))

    robots = metas.get("robots", "").lower()

    return {
        "title": title,
        "meta_description": metas.get("description"),
        "meta_robots": robots,
        "noindex": "noindex" in robots or "none" in robots,
        "canonical": canonical,
        "h1": h1,
        "h2_count": h2_count,
        "lang": lang,
        "script_count": script_count,
        "viewport": "viewport" in metas,
        "charset": charset,
        "favicon": favicon,
        "og_title": metas.get("og:title"),
        "og_description": metas.get("og:description"),
        "og_image": metas.get("og:image"),
        "twitter_card": metas.get("twitter:card"),
        "schema_types": sorted(schema),
        "hreflang": hreflang,
        "schema_blocks": schema_blocks[:20],
        "links": links,
        "nofollow_links": nofollow_links,
        "image_count": len(images),
        "images_missing_alt": imgs_missing_alt,
        "images_meta": images_meta,
        "legacy_images": legacy_images,
        "unlabeled_inputs": unlabeled_inputs,
        "empty_controls": empty_controls,
        "tels": tels,
        "addresses": addresses,
        "mixed_content": sorted(mixed),
        "word_count": word_count,
        "simhash": _simhash(text),
        "text_sample": text[:1200],
    }


def _simhash(text: str) -> str:
    words = re.findall(r"[a-z0-9]+", text.lower())
    if len(words) < 8:
        return ""
    acc = [0] * 64
    for i in range(len(words) - 2):
        digest = hashlib.md5(" ".join(words[i:i + 3]).encode()).digest()
        bits = int.from_bytes(digest[:8], "big")
        for b in range(64):
            acc[b] += 1 if bits & (1 << b) else -1
    out = 0
    for b in range(64):
        if acc[b] > 0:
            out |= 1 << b
    return f"{out:016x}"
