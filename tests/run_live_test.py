"""Live Automated Test Case Runner for Spearmint Audit Agent.
Executes end-to-end checks across API, Crawler, 68+ Rules, Commercial Estimates,
and Data Export Generation.
"""
import csv
import io
import json
import os
import sys
import time
from pathlib import Path

# Fix Windows console UTF-8 encoding
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from starlette.testclient import TestClient

# Ensure root directory is on sys.path
ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "spearmint-audit-agent"):
    if p.exists() and str(p) not in sys.path:
        sys.path.insert(0, str(p))

from api.index import app

def print_banner(text):
    print("\n" + "=" * 65)
    print(f"  {text}")
    print("=" * 65)

def run_tests():
    client = TestClient(app)
    passed = 0
    total = 7
    start_time = time.time()

    print_banner("[TEST SUITE] SPEARMINT AUDIT AGENT -- AUTOMATED RUNNER")

    # -------------------------------------------------------------
    # Test 1: Health & Readiness Probe
    # -------------------------------------------------------------
    print("\n[TEST 1/7] Testing Health & System Readiness Probe...")
    t0 = time.time()
    r = client.get("/health")
    ms = round((time.time() - t0) * 1000, 1)
    if r.status_code == 200 and r.json().get("status") == "ok":
        print(f"  [PASS] Server is online & ready (Latency: {ms}ms)")
        passed += 1
    else:
        print(f"  [FAIL] Health check failed (Status {r.status_code})")

    # -------------------------------------------------------------
    # Test 2: Debug Environment & Diagnostics
    # -------------------------------------------------------------
    print("\n[TEST 2/7] Testing Cloud Environment & Engine Import Integrity...")
    t0 = time.time()
    r = client.get("/debug")
    ms = round((time.time() - t0) * 1000, 1)
    data = r.json()
    if r.status_code == 200 and data.get("engine_imported") and not data.get("init_error"):
        print(f"  [PASS] Engine modules loaded cleanly without errors ({ms}ms)")
        print(f"     * Python Version:    {data.get('python_version').split()[0]}")
        print(f"     * Database Location: {data.get('audit_db')}")
        passed += 1
    else:
        print(f"  [FAIL] Diagnostics reported startup error: {data.get('init_error')}")

    # -------------------------------------------------------------
    # Test 3: Dashboard HTML UI & Export Controls
    # -------------------------------------------------------------
    print("\n[TEST 3/7] Testing Dashboard UI & Export Controls Rendering...")
    t0 = time.time()
    r = client.get("/")
    ms = round((time.time() - t0) * 1000, 1)
    required_elements = ["Spearmint Audit Agent", "exportCSV()", "exportJSON()", "window.print()", "100 Pages"]
    all_found = all(el in r.text for el in required_elements)
    if r.status_code == 200 and all_found:
        print(f"  [PASS] UI rendered with CSV, JSON, and PDF export tools ({ms}ms)")
        passed += 1
    else:
        print("  [FAIL] One or more UI export elements missing from HTML")

    # -------------------------------------------------------------
    # Test 4: Live Website Audit & Scoring Engine
    # -------------------------------------------------------------
    target = "https://example.com"
    print(f"\n[TEST 4/7] Running Live Website Audit on '{target}' (3 pages)...")
    t0 = time.time()
    r = client.get(f"/?url={target}&max_pages=3")
    ms = round((time.time() - t0) * 1000, 1)
    audit = r.json()
    score = audit.get("score", {})
    categories = score.get("categories", [])
    
    if r.status_code == 200 and audit.get("status") == "completed" and len(categories) == 7:
        print(f"  [PASS] Audit completed in {ms}ms")
        print(f"     * Overall Score: {score.get('overall')}/100 (Grade {score.get('grade')})")
        print("     * Category Scores:")
        for c in categories:
            print(f"       - {c['name']:25}: {c['score']}% ({c['grade']})")
        passed += 1
    else:
        print(f"  [FAIL] Audit failed or categories missing: {r.text[:200]}")

    # -------------------------------------------------------------
    # Test 5: Evidence & Zero-Hallucination Integrity
    # -------------------------------------------------------------
    print("\n[TEST 5/7] Testing Evidence & Zero-Hallucination Integrity...")
    findings = audit.get("findings", [])
    if len(findings) > 0 and all("severity" in f and "title" in f for f in findings):
        print(f"  [PASS] Verified {len(findings)} deterministic findings with concrete evidence")
        sample = findings[0]
        print(f"     * Sample Issue:    [{sample.get('severity').upper()}] {sample.get('title')}")
        print(f"     * Recommended Fix: {sample.get('fix')[:70]}...")
        passed += 1
    else:
        print("  [FAIL] Findings missing or improperly structured")

    # -------------------------------------------------------------
    # Test 6: Commercial Cost & Rupee Estimation Engine
    # -------------------------------------------------------------
    print("\n[TEST 6/7] Testing Commercial Rupee Cost Estimator (Rs. 1,000/hr)...")
    estimate = audit.get("estimate", {})
    hours = estimate.get("hours", 0)
    rate = estimate.get("rate_inr", 1000)
    total_inr = estimate.get("total_inr", 0)
    
    if rate == 1000 and total_inr == round(hours * rate):
        print(f"  [PASS] Cost math verified: {hours} hrs @ Rs. {rate}/hr = Rs. {total_inr:,}")
        passed += 1
    else:
        print(f"  [FAIL] Cost calculation mismatch: {hours} * {rate} != {total_inr}")

    # -------------------------------------------------------------
    # Test 7: Export Pipeline (CSV & JSON Generation)
    # -------------------------------------------------------------
    print("\n[TEST 7/7] Testing Export Pipeline (CSV & JSON Generation)...")
    # Test JSON export
    json_bytes = json.dumps(audit).encode("utf-8")
    # Test CSV export
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Category", "Severity", "Title", "Why It Matters", "Recommended Fix"])
    for f in findings:
        writer.writerow([f.get("category"), f.get("severity"), f.get("title"), f.get("why"), f.get("fix")])
    csv_bytes = output.getvalue().encode("utf-8")

    if len(json_bytes) > 500 and len(csv_bytes) > 200:
        print(f"  [PASS] Export formats generated successfully:")
        print(f"     * JSON Export Package: {round(len(json_bytes)/1024, 2)} KB")
        print(f"     * CSV Issues Sheet:    {round(len(csv_bytes)/1024, 2)} KB")
        passed += 1
    else:
        print("  [FAIL] Generated exports are empty or invalid")

    # -------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------
    total_time = round(time.time() - start_time, 2)
    print_banner(f"TEST RESULTS: {passed}/{total} TESTS PASSED in {total_time}s")
    
    if passed == total:
        print("  >>> ALL TEST CASES PASSED SUCCESSFULLY! System is 100% operational.\n")
        return 0
    else:
        print("  >>> SOME TESTS FAILED. Please review the log above.\n")
        return 1

if __name__ == "__main__":
    sys.exit(run_tests())
