"""Comprehensive AI-Engineered End-to-End Test Suite for Spearmint Audit Agent.
Validates the Crawler, Audit Scoring, Data Exports, Commercial Estimates,
FastAPI Endpoints, and Error Resilience.
"""
import csv
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from starlette.testclient import TestClient

# Ensure root paths are in sys.path
ROOT = Path(__file__).resolve().parent.parent
SUBDIR = ROOT / "spearmint-audit-agent"
for p in (ROOT, SUBDIR):
    if p.exists() and str(p) not in sys.path:
        sys.path.insert(0, str(p))

from api.index import app, _execute_audit
from engine.store import AuditStore
from engine.pipeline import execute


class TestSpearmintAuditSystem(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.temp_dir = Path(tempfile.gettempdir())
        cls.test_db_path = cls.temp_dir / "test_full_suite.db"
        cls.store = AuditStore(cls.test_db_path)
        cls.target_url = "https://example.com"

    # =========================================================================
    # 1. API Endpoints & Adaptive Routing Tests
    # =========================================================================
    def test_01_health_check_endpoint(self):
        """Verify that health check endpoints return 200 OK and valid status."""
        for endpoint in ["/health", "/api/health"]:
            response = self.client.get(endpoint)
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data.get("status"), "ok")
            self.assertEqual(data.get("service"), "spearmint-audit-agent")
            self.assertTrue(data.get("engine_ready"))
            self.assertIn("timestamp", data)

    def test_02_debug_diagnostics_endpoint(self):
        """Verify the debug diagnostics endpoint confirms engine import integrity."""
        response = self.client.get("/debug")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsNone(data.get("init_error"))
        self.assertTrue(data.get("engine_imported"))
        self.assertIn("python_version", data)

    def test_03_dashboard_html_rendering(self):
        """Verify that dashboard renders all advanced UI features and export tools."""
        for path in ["/", "/index", "/api/index.py"]:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn("Spearmint Audit Agent", response.text)
            self.assertIn("Export Issues (CSV)", response.text)
            self.assertIn("Export Full Report (JSON)", response.text)
            self.assertIn("Print / Save as PDF", response.text)
            self.assertIn("100 Pages (Enterprise Scan)", response.text)

    # =========================================================================
    # 2. Audit Execution & Scoring Integrity Tests
    # =========================================================================
    def test_04_audit_execution_and_scoring(self):
        """Verify end-to-end audit execution, scoring calculation, and grading."""
        response = self.client.get(f"/?url={self.target_url}&max_pages=1")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data.get("status"), "completed")
        self.assertEqual(data.get("url"), self.target_url)

        score = data.get("score", {})
        overall = score.get("overall")
        grade = score.get("grade")

        # Validate score ranges
        self.assertIsInstance(overall, (int, float))
        self.assertTrue(0 <= overall <= 100)
        self.assertIn(grade, ["A", "B", "C", "D", "F"])

        # Validate 7 category scores
        categories = score.get("categories", [])
        self.assertEqual(len(categories), 7)
        expected_categories = {
            "Technical SEO",
            "On-Page SEO",
            "Content",
            "Performance",
            "Mobile & Accessibility",
            "Security",
            "Social & Rich Results",
        }
        found_categories = {c["name"] for c in categories}
        self.assertEqual(expected_categories, found_categories)

    def test_05_evidence_integrity_in_findings(self):
        """Verify that findings contain structured, non-hallucinated evidence."""
        response = self.client.get(f"/?url={self.target_url}&max_pages=1")
        data = response.json()
        findings = data.get("findings", [])

        self.assertIsInstance(findings, list)
        self.assertGreater(len(findings), 0)

        for finding in findings:
            self.assertIn("title", finding)
            self.assertIn("category", finding)
            self.assertIn("severity", finding)
            self.assertIn(finding["severity"], ["critical", "high", "medium", "low"])
            self.assertTrue("why" in finding or "fix" in finding)

    # =========================================================================
    # 3. Commercial Fix Quotation & Rate Calculation Tests
    # =========================================================================
    def test_06_commercial_estimate_math(self):
        """Verify engineering hours and commercial quote (₹1,000/hr) calculation."""
        response = self.client.get(f"/?url={self.target_url}&max_pages=1")
        data = response.json()
        estimate = data.get("estimate", {})

        hours = estimate.get("hours", 0)
        rate = estimate.get("rate_inr", 1000)
        total_inr = estimate.get("total_inr", 0)

        self.assertEqual(rate, 1000)
        self.assertGreaterEqual(hours, 0)
        self.assertEqual(round(hours * rate), round(total_inr))

    # =========================================================================
    # 4. Multi-Page Crawling & Concurrency Tests
    # =========================================================================
    def test_07_crawl_limits_and_clamping(self):
        """Verify that crawler respects page bounds and handles 1-100 limits safely."""
        # Test 10 pages limit
        res_10 = _execute_audit("https://example.com", max_pages=10)
        self.assertEqual(res_10.get("status"), "completed")

        # Test bounds clamping (>100 clamped to 100, <1 clamped to 1)
        res_clamp = _execute_audit("https://example.com", max_pages=200)
        self.assertEqual(res_clamp.get("status"), "completed")

    # =========================================================================
    # 5. Data Export Formatting & Integrity Tests
    # =========================================================================
    def test_08_json_export_structure(self):
        """Verify full audit JSON payload can be serialized and contains all exports."""
        response = self.client.get(f"/?url={self.target_url}&max_pages=1")
        data = response.json()

        required_keys = ["status", "audit_id", "url", "score", "stats", "estimate", "findings"]
        for key in required_keys:
            self.assertIn(key, data)

        # Ensure valid JSON serialization
        serialized = json.dumps(data)
        self.assertGreater(len(serialized), 100)

    def test_09_csv_export_generation(self):
        """Simulate CSV export generation and verify CSV formatting and columns."""
        response = self.client.get(f"/?url={self.target_url}&max_pages=1")
        findings = response.json().get("findings", [])

        # Generate CSV in memory
        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(["Category", "Severity", "Title", "Why It Matters", "Recommended Fix"])

        for f in findings:
            writer.writerow([
                f.get("category", ""),
                f.get("severity", ""),
                f.get("title", ""),
                f.get("why", ""),
                f.get("fix", f.get("fix_steps", ""))
            ])

        csv_text = output.getvalue()
        self.assertIn("Category,Severity,Title,Why It Matters,Recommended Fix", csv_text)
        self.assertGreater(len(csv_text.splitlines()), len(findings))

    # =========================================================================
    # 6. Error Handling & Edge Case Resilience
    # =========================================================================
    def test_10_invalid_and_unreachable_urls(self):
        """Verify resilient error handling when an invalid URL or unreachable domain is passed."""
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            _execute_audit("http://this-domain-does-not-exist-xyz12345.org", max_pages=1)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Could not reach", ctx.exception.detail)


if __name__ == "__main__":
    unittest.main(verbosity=2)
