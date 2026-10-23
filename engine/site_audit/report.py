import csv
import json
from dataclasses import asdict
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES = Path(__file__).parent / "templates"


def _score_color(s):
    return "#16a34a" if s >= 80 else "#f59e0b" if s >= 55 else "#dc2626"


def write_reports(ctx: dict, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html", "j2"]))
    env.filters["score_color"] = _score_color
    html = env.get_template("report.html.j2").render(**ctx)
    paths = {"html": out_dir / "report.html", "issues_csv": out_dir / "issues.csv",
             "pages_csv": out_dir / "pages.csv", "json": out_dir / "audit.json"}
    paths["html"].write_text(html, encoding="utf-8")

    with paths["issues_csv"].open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["Severity", "Category", "Issue", "URL", "Detail", "Recommendation"])
        for i in ctx["issues"]:
            for a in i.affected:
                w.writerow([i.severity, i.category, i.title, a["url"], a["detail"], i.fix])

    with paths["pages_csv"].open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["URL", "Status", "Final URL", "Depth", "Response ms", "Size KB", "Title", "Title length",
                    "Meta description length", "H1 count", "Word count", "Images", "Images missing alt",
                    "Canonical", "Noindex", "Schema types", "Inlinks", "Error"])
        for p in ctx["pages"]:
            d = p.data or {}
            w.writerow([p.url, p.status, p.final_url, p.depth, p.response_ms, round(p.size_bytes / 1024, 1),
                        d.get("title") or "", len(d.get("title") or ""), len(d.get("meta_description") or ""),
                        len(d.get("h1", [])), d.get("word_count", ""), d.get("image_count", ""),
                        len(d.get("images_missing_alt", [])), d.get("canonical") or "",
                        d.get("noindex", ""), ", ".join(d.get("schema_types", [])),
                        len(ctx["inlinks"].get(p.final_url or p.url, [])), p.error or ""])

    data = {
        "domain": ctx["domain"], "start_url": ctx["start_url"], "generated": ctx["generated"],
        "score": ctx["score"], "stats": ctx["stats"], "summary": ctx["summary"], "pagespeed": ctx["psi"],
        "issues": [asdict(i) for i in ctx["issues"]],
        "pages": [{k: v for k, v in asdict(p).items() if k != "headers"} for p in ctx["pages"]],
        "robots": ctx["robots"], "sitemap": {k: v for k, v in ctx["sitemap"].items() if k != "urls"} | {"url_count": len(ctx["sitemap"]["urls"])},
    }
    paths["json"].write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return paths
