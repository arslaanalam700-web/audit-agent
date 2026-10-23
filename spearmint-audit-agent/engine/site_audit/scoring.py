from .checks import CATEGORIES, PERF, Issue

WEIGHTS = {"critical": 35, "high": 20, "medium": 10, "low": 4}


def grade(score: int) -> str:
    for cutoff, g in ((90, "A"), (80, "B"), (70, "C"), (55, "D")):
        if score >= cutoff:
            return g
    return "F"


def score(issues: list[Issue], html_page_count: int, psi: dict | None) -> dict:
    n = max(html_page_count, 1)
    cats = {c: 100.0 for c in CATEGORIES}
    for i in issues:
        w = WEIGHTS[i.severity]
        if i.scope == "site":
            penalty = w
        else:
            penalty = w * (0.5 + 0.5 * min(1.0, i.count / n))
        cats[i.category] -= penalty

    if psi and psi["scores"].get("performance") is not None:
        cats[PERF] = (cats[PERF] + psi["scores"]["performance"]) / 2

    cats = {c: max(0, round(v)) for c, v in cats.items()}
    overall = round(sum(cats.values()) / len(cats))
    return {
        "overall": overall,
        "grade": grade(overall),
        "categories": [{"name": c, "score": s, "grade": grade(s)} for c, s in cats.items()],
    }
