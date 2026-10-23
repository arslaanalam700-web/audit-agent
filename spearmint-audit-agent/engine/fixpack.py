"""Developer fix pack: redirects, robots.txt, JSON-LD, and a bulk title/meta CSV."""
import csv
import json
from pathlib import Path


def _chain_target(detail: str, fallback: str) -> tuple[str, str]:
    if "->" in detail:
        parts = [p.strip().split()[-1] for p in detail.split("->")]
        if len(parts) >= 2 and parts[0].startswith("http") and parts[-1].startswith("http"):
            return parts[0], parts[-1]
    return fallback, ""


def write_fix_pack(out_dir: Path, issues, domain: str) -> dict:
    pack = out_dir / "fix-pack"
    pack.mkdir(parents=True, exist_ok=True)
    redirects = []
    titles = []
    for issue in issues:
        for item in issue.affected:
            url, detail = item.get("url") or "", item.get("detail") or ""
            if issue.id in ("redirect_chains", "temporary_redirect", "internal_redirects"):
                src, dst = _chain_target(detail, url)
                if src and dst and src != dst:
                    redirects.append((src, dst))
            if issue.id in ("title_missing", "title_long", "title_short", "title_duplicate",
                            "meta_missing", "meta_duplicate", "meta_length"):
                titles.append((url, issue.id, detail[:180]))

    htaccess = ["# Spearmint fix pack: permanent redirects", "RewriteEngine On"]
    nginx = ["# Spearmint fix pack"]
    vercel = []
    for src, dst in dict.fromkeys(redirects):
        path = "/" + src.split("/", 3)[-1] if src.startswith("http") else src
        htaccess.append(f"Redirect 301 {path} {dst}")
        nginx.append(f"rewrite ^{path}$ {dst} permanent;")
        vercel.append({"source": path, "destination": dst, "permanent": True})
    if any(i.id == "http_no_redirect" for i in issues):
        htaccess += ["RewriteCond %{HTTPS} off", f"RewriteRule ^ https://{domain}%{{REQUEST_URI}} [R=301,L]"]
        nginx.append(f"# redirect port 80 to https://{domain}")
    (pack / "redirects.htaccess").write_text("\n".join(htaccess) + "\n", encoding="utf-8")
    (pack / "redirects.nginx.conf").write_text("\n".join(nginx) + "\n", encoding="utf-8")
    (pack / "vercel.json").write_text(json.dumps({"redirects": vercel}, indent=2), encoding="utf-8")

    robots = [
        "User-agent: *",
        "Allow: /",
        "",
        "User-agent: GPTBot",
        "Allow: /",
        "User-agent: Google-Extended",
        "Allow: /",
        "User-agent: ClaudeBot",
        "Allow: /",
        "",
        f"Sitemap: https://{domain}/sitemap.xml",
        "",
    ]
    (pack / "robots.txt").write_text("\n".join(robots), encoding="utf-8")
    (pack / "llms.txt").write_text(
        f"# {domain}\n\n> Replace this with a one-paragraph description of the business.\n\n## Key pages\n- [Home](https://{domain}/)\n",
        encoding="utf-8",
    )
    schema = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": domain,
        "url": f"https://{domain}/",
        "logo": f"https://{domain}/favicon.ico",
    }
    (pack / "organization.jsonld").write_text(json.dumps(schema, indent=2), encoding="utf-8")

    with (pack / "yoast-titles.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["url", "issue", "current_detail", "new_title", "new_meta_description"])
        for row in titles:
            writer.writerow([*row, "", ""])

    notes = f"""# Platform notes for {domain}

## WordPress
Import `yoast-titles.csv` with a bulk meta plugin (WP All Import or Yoast's CSV tools).
Install the Redirection plugin and import `redirects.htaccess`, or paste those rules into the server.
Paste `organization.jsonld` into a site-wide header hook, or use RankMath's schema builder.

## Shopify
Add the JSON-LD in `theme.liquid` before `</head>`.
Create URL redirects under Online Store > Navigation > URL Redirects, one row per line in `redirects.htaccess`.
Edit titles and descriptions in the Shopify admin, using `yoast-titles.csv` as the worksheet.

## Webflow
Set titles and descriptions in Page settings from `yoast-titles.csv`.
Add 301 redirects in Project settings > Hosting > 301 redirects.
Add the JSON-LD in Project settings > Custom code > Head.

## Next.js
Put redirects from `vercel.json` into `next.config.js` `redirects()`.
Render the JSON-LD with `<script type="application/ld+json">` in the root layout.
Set `metadata.title` and `metadata.description` per route from the CSV.
"""
    (pack / "PLATFORMS.md").write_text(notes, encoding="utf-8")
    return {"dir": str(pack), "redirects": len(vercel), "title_rows": len(titles)}
