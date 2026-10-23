"""Seeded-site test for the audit engine, plus the agent tool contract."""
import os
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from engine.service import AuditService
from engine.site_audit.extract import _simhash

FIXTURE = Path(__file__).parent / "fixture_site"

REQUIRED = {
    "title_duplicate", "thin_content", "h1_missing", "noindex", "canonical_elsewhere",
    "canonical_conflict", "hreflang_missing_self", "hreflang_no_return", "hreflang_bad_code",
    "broken_pages", "img_alt", "img_missing_dimensions", "image_legacy_format",
    "a11y_unlabeled_inputs", "a11y_empty_controls", "near_duplicate", "schema_invalid",
    "schema_incomplete", "redirect_loop", "temporary_redirect", "viewport_missing", "lang_missing",
    "meta_missing", "no_https", "robots_missing", "sitemap_missing",
}
UNEXPECTED = {"server_errors", "robots_blocks_all", "soft_404", "psi_performance", "www_duplicate"}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FIXTURE), **kwargs)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/old":
            self.send_response(302)
            self.send_header("Location", "/mid")
            self.end_headers()
            return
        if path == "/mid":
            self.send_response(302)
            self.send_header("Location", "/about.html")
            self.end_headers()
            return
        if path == "/loop":
            self.send_response(302)
            self.send_header("Location", "/loop2")
            self.end_headers()
            return
        if path == "/loop2":
            self.send_response(302)
            self.send_header("Location", "/loop")
            self.end_headers()
            return
        if path == "/missing.html":
            self.send_error(404)
            return
        super().do_GET()

    def end_headers(self):
        self.send_header("Set-Cookie", "session=abc; Path=/")
        super().end_headers()

    def log_message(self, fmt, *args):
        return


class FixtureAuditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        port = cls.httpd.server_address[1]
        cls.url = f"http://127.0.0.1:{port}/"
        cls.service = AuditService(Path(__file__).parent / "_fixture.db")
        started = cls.service.start_audit(cls.url, client_name="Fixture", max_pages=40, pagespeed=False, render=False)
        cls.audit_id = started["audit_id"]
        overview = cls.service.wait_for_audit(cls.audit_id, timeout_s=180)
        cls.overview = overview

    @classmethod
    def tearDownClass(cls):
        cls.service.store.close()
        cls.httpd.shutdown()
        db = Path(__file__).parent / "_fixture.db"
        if db.exists():
            db.unlink(missing_ok=True)

    def test_crawl_finished(self):
        self.assertEqual(self.overview["status"], "done", self.overview.get("error"))
        self.assertGreaterEqual(self.overview["stats"]["html_pages"], 8)

    def test_seeded_issues_found(self):
        rows = self.service.list_findings(self.audit_id, limit=500)["findings"]
        found = {row["rule_id"] for row in rows}
        missing = REQUIRED - found
        self.assertFalse(missing, f"seeded issues not found: {sorted(missing)}")

    def test_no_false_alarms_on_known_good_signals(self):
        rows = self.service.list_findings(self.audit_id, limit=500)["findings"]
        found = {row["rule_id"] for row in rows}
        self.assertFalse(found & UNEXPECTED, f"unexpected issues: {sorted(found & UNEXPECTED)}")

    def test_every_finding_has_evidence(self):
        rows = self.service.list_findings(self.audit_id, limit=500)["findings"]
        for row in rows:
            self.assertTrue(row["evidence_ids"], row["rule_id"])

    def test_score_and_fix_pack(self):
        self.assertIn(self.overview["score"]["grade"], list("ABCDF"))
        report = Path(self.overview["report_dir"])
        self.assertTrue((report / "report.html").exists())
        self.assertTrue((report / "fix-pack" / "redirects.htaccess").exists())
        self.assertTrue((report / "fix-pack" / "yoast-titles.csv").exists())
        self.assertTrue((report / "pitch.md").exists())
        self.assertGreater(self.overview["stats"]["issue_types"], 10)

    def test_templates_group_the_long_articles(self):
        templates = {item["template"] for item in self.service.list_templates(self.audit_id)["templates"]}
        self.assertIn("/blog-a.html", templates)
        self.assertIn("/blog-b.html", templates)

    def test_agent_findings_need_evidence(self):
        rejected = self.service.submit_findings(self.audit_id, [{
            "rule_id": "thin_content", "severity": "low",
        }], agent="qa")
        self.assertFalse(rejected["saved"])
        self.assertTrue(rejected["rejected"])
        saved = self.service.submit_findings(self.audit_id, [{
            "rule_id": "custom_trust", "severity": "medium", "title": "No reviews on the homepage",
            "why": "Visitors see no proof.", "fix": "Add two testimonials.",
            "evidence": [{"url": self.url, "detail": "homepage has no review markup"}],
            "affected": [{"url": self.url, "detail": "homepage"}],
        }], agent="content")
        self.assertEqual(len(saved["saved"]), 1)
        updated = self.service.update_finding(saved["saved"][0], status="rejected", note="Not evidenced well enough")
        self.assertTrue(updated["updated"])

    def test_diff_and_delivery_stay_internal(self):
        empty_id = "fixture-empty-" + os.urandom(4).hex()
        self.service.store.create_audit(empty_id, self.url, "Fixture")
        self.service.store.update_audit(empty_id, status="done")
        diff = self.service.diff_audits(self.audit_id, empty_id)
        self.assertGreater(len(diff["fixed"]), 5)
        self.service.store.update_audit(self.audit_id, status="done")
        queued = self.service.queue_delivery(self.audit_id, "email", "review before sending")
        self.assertEqual(queued["status"], "pending_review")
        approved = self.service.approve_delivery(queued["delivery_id"])
        self.assertEqual(approved["status"], "approved")


class SimhashTest(unittest.TestCase):
    def test_identical_text_matches(self):
        text = "spearmint audit " * 30
        self.assertEqual(_simhash(text), _simhash(text))
        self.assertNotEqual(_simhash(text), _simhash("completely different words about cooking and travel " * 20))


class Phase6GuardTest(unittest.TestCase):
    def test_offpage_and_wordpress_stay_closed_without_keys(self):
        for key in ("DATAFORSEO_LOGIN", "DATAFORSEO_PASSWORD", "SEARCH_CONSOLE_ACCESS_TOKEN", "GA4_ACCESS_TOKEN"):
            os.environ.pop(key, None)
        from engine.connectors import offpage_summary, search_console, ga4_overview
        from engine.wordpress import apply_approved
        self.assertFalse(offpage_summary("example.com")["available"])
        self.assertFalse(search_console("https://example.com/")["available"])
        self.assertFalse(ga4_overview("123")["available"])
        service = AuditService(Path(__file__).parent / "_guard.db")
        service.store.create_audit("guard", "https://example.com", "Guard")
        service.store.update_audit("guard", status="done")
        result = apply_approved(service.store, "guard", "https://example.com", "user", "password")
        self.assertIn("Not approved", result["error"])
        service.store.close()
        db = Path(__file__).parent / "_guard.db"
        if db.exists():
            db.unlink(missing_ok=True)


@unittest.skipUnless(os.environ.get("AUDIT_LIVE") == "1", "set AUDIT_LIVE=1 to crawl three public sites")
class LiveSitesTest(unittest.TestCase):
    def test_three_public_sites(self):
        service = AuditService(Path(__file__).parent / "_live.db")
        for url in ("https://example.com", "https://books.toscrape.com", "https://quotes.toscrape.com"):
            started = service.start_audit(url, max_pages=12, pagespeed=False, render=False)
            overview = service.wait_for_audit(started["audit_id"], timeout_s=240)
            self.assertEqual(overview["status"], "done", f"{url}: {overview.get('error')}")
            self.assertGreaterEqual(overview["stats"]["html_pages"], 1)
            self.assertIn(overview["score"]["grade"], list("ABCDF"))
        service.store.close()

    @classmethod
    def tearDownClass(cls):
        db = Path(__file__).parent / "_live.db"
        if db.exists():
            db.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
