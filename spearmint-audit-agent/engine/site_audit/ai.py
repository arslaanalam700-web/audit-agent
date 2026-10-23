"""Executive summary + sales pitch. Uses an LLM when OPENAI_API_KEY is set, otherwise a template."""
import json
import os

import httpx

PROMPT = """You are a senior SEO consultant at the digital agency "{agency}".
You have just audited {domain}. Using ONLY the audit data below, write client-facing copy that
helps the agency win this client. Be specific (cite numbers), plain-English, non-technical, and
persuasive without exaggerating. Return JSON with exactly these keys:
- "executive_summary": 2 short paragraphs on the site's overall health and what it is costing them.
- "top_priorities": list of 5 objects {{"title", "impact", "effort"}} (impact/effort: High/Medium/Low), ordered by business impact.
- "pitch_points": list of 4-6 short sentences the account manager can say on a sales call.
- "quick_wins": list of 3-5 fixes that can be done in under a week.

AUDIT DATA:
{data}
"""


def _facts(ctx: dict) -> dict:
    return {
        "domain": ctx["domain"],
        "pages_crawled": ctx["stats"]["html_pages"],
        "overall_score": ctx["score"]["overall"],
        "category_scores": {c["name"]: c["score"] for c in ctx["score"]["categories"]},
        "issues": [
            {"title": i.title, "severity": i.severity, "category": i.category,
             "pages_affected": i.count if i.scope == "page" else "site-wide",
             "example": (i.affected[0]["detail"] or i.affected[0]["url"])[:160] if i.affected else ""}
            for i in ctx["issues"][:25]
        ],
        "pagespeed": {k: ctx["psi"][k] for k in ("scores", "field", "lab")} if ctx.get("psi") else None,
    }


def ai_summary(ctx: dict, log=print) -> dict | None:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        log("  ! OPENAI_API_KEY not set - using template summary")
        return None
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    prompt = PROMPT.format(agency=ctx["agency"], domain=ctx["domain"],
                           data=json.dumps(_facts(ctx), indent=1, default=str))
    log(f"  writing AI summary with {model}...")
    try:
        r = httpx.post(f"{base}/chat/completions", timeout=120,
                       headers={"Authorization": f"Bearer {key}"},
                       json={"model": model, "response_format": {"type": "json_object"},
                             "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
        out = json.loads(r.json()["choices"][0]["message"]["content"])
        if isinstance(out.get("executive_summary"), list):
            out["executive_summary"] = "\n\n".join(out["executive_summary"])
        return out
    except (httpx.HTTPError, KeyError, ValueError) as e:
        log(f"  ! AI summary failed ({e}) - using template summary")
        return None


def template_summary(ctx: dict) -> dict:
    s, issues, stats = ctx["score"], ctx["issues"], ctx["stats"]
    worst = sorted(s["categories"], key=lambda c: c["score"])[:2]
    crit = [i for i in issues if i.severity in ("critical", "high")]
    health = ("in good shape overall" if s["overall"] >= 80 else
              "performing below its potential" if s["overall"] >= 60 else
              "held back by serious problems")

    para1 = (f"We crawled {stats['html_pages']} pages on {ctx['domain']} and the site scored "
             f"{s['overall']}/100 (grade {s['grade']}). The site is {health}. We found "
             f"{stats['issue_types']} types of issues, {len(crit)} of them critical or high priority.")
    para2 = (f"The weakest areas are {worst[0]['name']} ({worst[0]['score']}/100) and "
             f"{worst[1]['name']} ({worst[1]['score']}/100). Fixing the priorities below will improve "
             f"how search engines crawl and rank the site, and how visitors experience it.")

    pri = []
    for i in issues[:5]:
        impact = {"critical": "High", "high": "High", "medium": "Medium", "low": "Low"}[i.severity]
        n = "site-wide" if i.scope == "site" else f"{i.count} page{'s' if i.count != 1 else ''}"
        pri.append({"title": f"{i.title} ({n})", "impact": impact, "effort": "Medium"})

    quick_ids = {"title_missing", "meta_missing", "h1_missing", "viewport_missing", "lang_missing",
                 "sitemap_missing", "robots_missing", "sitemap_not_in_robots", "og_missing",
                 "no_compression", "favicon_missing", "http_no_redirect", "www_duplicate", "title_duplicate"}
    quick = [i.title for i in issues if i.id in quick_ids][:5]

    pitch = [f"Your site currently scores {s['overall']}/100 on our technical and SEO audit."]
    for i in crit[:3]:
        n = "across the whole site" if i.scope == "site" else f"on {i.count} of {stats['html_pages']} pages"
        pitch.append(f"{i.title} {n}: {i.why.split('. ')[0].rstrip('.')}.")
    if ctx.get("psi") and ctx["psi"]["scores"].get("performance") is not None:
        pitch.append(f"Your mobile speed score is {ctx['psi']['scores']['performance']}/100 on Google's own tool.")
    pitch.append("We can deliver the quick wins within the first week and show measurable improvement within 30-60 days.")

    return {"executive_summary": para1 + "\n\n" + para2, "top_priorities": pri,
            "pitch_points": pitch, "quick_wins": quick}
