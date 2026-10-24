import os
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Setup directories and sys.path
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
SUBDIR = PROJECT_ROOT / "spearmint-audit-agent"

for p in (PROJECT_ROOT, SUBDIR):
    if p.exists() and str(p) not in sys.path:
        sys.path.insert(0, str(p))

# Safe serverless writable directories (/tmp)
TMP_DIR = Path(tempfile.gettempdir())
AUDIT_DB_PATH = TMP_DIR / "audits.db"
REPORTS_DIR = TMP_DIR / "reports"
try:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

os.environ["AUDIT_DB"] = str(AUDIT_DB_PATH)

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(
    title="Spearmint Audit Agent",
    description="Advanced Autonomous Website & SEO Audit Agent API",
    version="2.0.0",
    redirect_slashes=False,
)

__all__ = ["app"]

# Safely import engine modules
_init_error: Optional[str] = None
execute = None
AuditStore = None

try:
    from engine.pipeline import execute
    from engine.store import AuditStore
except Exception:
    _init_error = traceback.format_exc()

_store = None


def get_store():
    global _store
    if _store is None and AuditStore is not None:
        _store = AuditStore(AUDIT_DB_PATH)
    return _store


def _execute_audit(url: str, max_pages: int = 5, client_name: Optional[str] = None) -> dict:
    if _init_error is not None:
        raise HTTPException(status_code=500, detail=f"Engine initialization error: {_init_error}")

    clean_url = url.strip()
    if not clean_url.startswith(("http://", "https://")):
        clean_url = "https://" + clean_url

    try:
        host = clean_url.split("/")[2].replace(".", "-").replace(":", "-")
    except Exception:
        host = "site"

    audit_id = f"{host}-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"
    store = get_store()

    # Cap maximum pages between 1 and 100 for safety and performance
    safe_pages = min(max(1, max_pages), 100)

    try:
        result = execute(
            clean_url,
            audit_id=audit_id,
            store=store,
            max_pages=safe_pages,
            concurrency=8,        # Fast parallel crawling
            timeout=4,            # Fast per-request timeout
            max_depth=3,
            pagespeed=False,      # Avoid slow external PSI rate-limits
            render=False,         # Deterministic fast crawler
            out=str(REPORTS_DIR),
            open_browser=False,
            log=lambda *a, **k: None,
            client_name=client_name,
        )

        findings = store.list_findings(audit_id, limit=250)

        return {
            "status": "completed",
            "audit_id": audit_id,
            "url": clean_url,
            "score": result.get("score"),
            "stats": result.get("stats"),
            "estimate": result.get("estimate"),
            "findings": findings,
            "report_dir": result.get("report_dir"),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Audit failed: {str(exc)[:400]}")


@app.get("/health")
@app.get("/api/health")
def health():
    return {
        "status": "ok" if _init_error is None else "degraded",
        "platform": "vercel",
        "service": "spearmint-audit-agent",
        "engine_ready": _init_error is None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/debug")
@app.get("/api/debug")
def debug():
    return {
        "init_error": _init_error,
        "python_version": sys.version,
        "cwd": os.getcwd(),
        "files_in_cwd": os.listdir(".") if os.path.exists(".") else [],
        "sys_path": sys.path,
        "audit_db": str(AUDIT_DB_PATH),
        "reports_dir": str(REPORTS_DIR),
        "engine_imported": execute is not None,
    }


@app.get("/api/findings")
@app.get("/findings")
def list_findings(audit_id: str, limit: int = 100, offset: int = 0):
    store = get_store()
    if store is None:
        raise HTTPException(status_code=500, detail="Store is not initialized")
    return store.list_findings(audit_id, limit=limit, offset=offset)


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Spearmint Audit Agent — Enterprise SEO & Technical Intelligence</title>
  <style>
    :root {
      --primary: #12a37f;
      --primary-light: #20c997;
      --primary-dark: #0e8063;
      --bg: #090e1a;
      --card-bg: #131c31;
      --card-hover: #1a2642;
      --card-border: #233354;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --danger: #ef4444;
      --warning: #f59e0b;
      --info: #3b82f6;
      --success: #10b981;
    }
    * { box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      margin: 0;
      padding: 30px 16px;
      display: flex;
      justify-content: center;
      min-height: 100vh;
    }
    .container {
      max-width: 960px;
      width: 100%;
    }
    .header-bar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 24px;
      flex-wrap: wrap;
      gap: 12px;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .brand-logo {
      width: 40px;
      height: 40px;
      border-radius: 10px;
      background: linear-gradient(135deg, var(--primary), var(--primary-light));
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 22px;
      font-weight: 800;
      color: #fff;
      box-shadow: 0 4px 14px rgba(18, 163, 127, 0.4);
    }
    .brand-text h1 {
      font-size: 20px;
      margin: 0;
      font-weight: 700;
      letter-spacing: -0.5px;
    }
    .brand-text p {
      margin: 2px 0 0;
      font-size: 13px;
      color: var(--text-muted);
    }
    .badge-status {
      background: rgba(18, 163, 127, 0.15);
      border: 1px solid rgba(18, 163, 127, 0.4);
      color: var(--primary-light);
      padding: 6px 12px;
      border-radius: 20px;
      font-size: 12px;
      font-weight: 600;
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--primary-light);
      animation: pulse 2s infinite;
    }
    @keyframes pulse {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.4; }
    }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 14px;
      padding: 24px;
      margin-bottom: 24px;
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
    }
    .form-grid {
      display: grid;
      grid-template-columns: 2fr 1fr 1fr;
      gap: 14px;
      margin-bottom: 16px;
    }
    @media (max-width: 680px) {
      .form-grid { grid-template-columns: 1fr; }
    }
    label {
      display: block;
      margin-bottom: 6px;
      font-weight: 600;
      font-size: 13px;
      color: #cbd5e1;
    }
    input, select {
      width: 100%;
      padding: 12px 14px;
      border-radius: 9px;
      border: 1px solid var(--card-border);
      background: #0b1222;
      color: #fff;
      font-size: 14px;
      transition: border-color 0.2s;
    }
    input:focus, select:focus {
      outline: none;
      border-color: var(--primary-light);
      box-shadow: 0 0 0 3px rgba(18, 163, 127, 0.2);
    }
    .btn-audit {
      width: 100%;
      background: linear-gradient(135deg, var(--primary), var(--primary-light));
      color: white;
      border: none;
      border-radius: 9px;
      padding: 14px;
      font-size: 15px;
      font-weight: 700;
      cursor: pointer;
      transition: all 0.2s;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
    }
    .btn-audit:hover {
      opacity: 0.95;
      transform: translateY(-1px);
      box-shadow: 0 4px 16px rgba(18, 163, 127, 0.4);
    }
    .btn-audit:disabled {
      background: #334155;
      cursor: not-allowed;
      transform: none;
      box-shadow: none;
    }
    #resultContainer { display: none; }
    
    /* Executive Summary Banner */
    .exec-banner {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 20px 24px;
      background: linear-gradient(135deg, rgba(18, 163, 127, 0.15), rgba(30, 41, 59, 0.4));
      border: 1px solid rgba(18, 163, 127, 0.4);
      border-radius: 12px;
      margin-bottom: 20px;
      flex-wrap: wrap;
      gap: 16px;
    }
    .grade-circle {
      width: 72px;
      height: 72px;
      border-radius: 50%;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      background: #0b1222;
      border: 3px solid var(--primary);
      box-shadow: 0 0 16px rgba(18, 163, 127, 0.4);
    }
    .grade-val { font-size: 26px; font-weight: 800; line-height: 1; }
    .grade-sub { font-size: 10px; color: var(--text-muted); margin-top: 2px; }

    /* Action / Export Toolbar */
    .export-toolbar {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-bottom: 20px;
    }
    .btn-tool {
      background: #18233c;
      border: 1px solid var(--card-border);
      color: #e2e8f0;
      padding: 8px 14px;
      border-radius: 8px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 6px;
      transition: all 0.2s;
    }
    .btn-tool:hover {
      background: #233354;
      border-color: #3b82f6;
      color: #fff;
    }

    /* KPI Cards */
    .kpi-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 14px;
      margin-bottom: 24px;
    }
    .kpi-card {
      background: #0d1527;
      border: 1px solid var(--card-border);
      border-radius: 10px;
      padding: 16px;
    }
    .kpi-label { font-size: 12px; color: var(--text-muted); margin-bottom: 6px; }
    .kpi-val { font-size: 20px; font-weight: 700; color: #f1f5f9; }
    .kpi-sub { font-size: 12px; color: var(--primary-light); margin-top: 4px; }

    /* Category Cards */
    .cat-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 12px;
      margin-bottom: 24px;
    }
    .cat-card {
      background: #0d1527;
      border: 1px solid var(--card-border);
      border-radius: 10px;
      padding: 14px;
    }
    .cat-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 8px;
    }
    .cat-title { font-size: 13px; font-weight: 600; color: #e2e8f0; }
    .cat-score { font-size: 13px; font-weight: 700; }
    .progress-bg {
      background: #1e293b;
      height: 6px;
      border-radius: 3px;
      overflow: hidden;
    }
    .progress-bar { height: 100%; border-radius: 3px; transition: width 0.6s ease; }

    /* Issues Section */
    .issues-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 14px;
      flex-wrap: wrap;
      gap: 10px;
    }
    .filter-tabs {
      display: flex;
      gap: 6px;
      background: #0d1527;
      padding: 4px;
      border-radius: 8px;
      border: 1px solid var(--card-border);
    }
    .tab-btn {
      background: transparent;
      border: none;
      color: var(--text-muted);
      padding: 6px 12px;
      font-size: 12px;
      font-weight: 600;
      border-radius: 6px;
      cursor: pointer;
    }
    .tab-btn.active {
      background: var(--primary);
      color: #fff;
    }
    .search-input {
      padding: 8px 12px;
      font-size: 13px;
      border-radius: 8px;
      width: 220px;
    }
    .issue-item {
      background: #0d1527;
      border: 1px solid var(--card-border);
      border-radius: 10px;
      margin-bottom: 10px;
      overflow: hidden;
      transition: border-color 0.2s;
    }
    .issue-item:hover { border-color: #3b82f6; }
    .issue-summary {
      padding: 14px 18px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      cursor: pointer;
      gap: 12px;
    }
    .issue-left {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }
    .badge-sev {
      font-size: 10px;
      font-weight: 700;
      text-transform: uppercase;
      padding: 3px 8px;
      border-radius: 4px;
      letter-spacing: 0.5px;
    }
    .sev-critical { background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid #ef4444; }
    .sev-high { background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid #f59e0b; }
    .sev-medium { background: rgba(59, 130, 246, 0.2); color: #60a5fa; border: 1px solid #3b82f6; }
    .sev-low { background: rgba(148, 163, 184, 0.2); color: #cbd5e1; border: 1px solid #64748b; }
    .badge-cat {
      background: #1e293b;
      color: #94a3b8;
      font-size: 11px;
      padding: 3px 8px;
      border-radius: 4px;
    }
    .issue-title { font-size: 14px; font-weight: 600; color: #f1f5f9; }
    .issue-details {
      display: none;
      padding: 14px 18px;
      border-top: 1px solid var(--card-border);
      background: #080d1a;
      font-size: 13px;
      line-height: 1.6;
    }
    .fix-box {
      background: rgba(18, 163, 127, 0.1);
      border-left: 3px solid var(--primary);
      padding: 10px 14px;
      margin-top: 10px;
      border-radius: 0 6px 6px 0;
      color: #e2e8f0;
    }
    .footer-links {
      display: flex;
      gap: 16px;
      justify-content: center;
      margin-top: 24px;
      font-size: 13px;
    }
    .footer-links a { color: var(--primary-light); text-decoration: none; }
    .footer-links a:hover { text-decoration: underline; }
    
    @media print {
      body { background: #fff; color: #000; padding: 0; }
      .card { box-shadow: none; border: 1px solid #ccc; background: #fff; }
      .btn-audit, .export-toolbar, .header-bar, .form-grid, .footer-links { display: none !important; }
      .issue-details { display: block !important; }
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="header-bar">
      <div class="brand">
        <div class="brand-logo">S</div>
        <div class="brand-text">
          <h1>Spearmint Audit Agent</h1>
          <p>Autonomous Technical SEO, Core Web Vitals & Security Intelligence</p>
        </div>
      </div>
      <div class="badge-status">
        <div class="dot"></div>
        <span>Engine Active (v2.0)</span>
      </div>
    </div>

    <!-- Input Card -->
    <div class="card">
      <div class="form-grid">
        <div>
          <label for="urlInput">Target Domain or Website URL</label>
          <input type="text" id="urlInput" placeholder="https://example.com" value="https://example.com" />
        </div>
        <div>
          <label for="pagesInput">Pages to Crawl</label>
          <select id="pagesInput">
            <option value="1">1 Page (Instant, ~1s)</option>
            <option value="5" selected>5 Pages (Quick Scan, ~2s)</option>
            <option value="10">10 Pages (Standard, ~3s)</option>
            <option value="25">25 Pages (Deep Scan, ~5s)</option>
            <option value="50">50 Pages (Thorough Scan)</option>
            <option value="100">100 Pages (Enterprise Scan)</option>
          </select>
        </div>
        <div>
          <label for="clientInput">Client / Brand (Optional)</label>
          <input type="text" id="clientInput" placeholder="e.g. Acme Corp" />
        </div>
      </div>
      <button class="btn-audit" id="runBtn" onclick="startAudit()">
        <span>⚡ Start Website Audit</span>
      </button>
    </div>

    <!-- Results Section -->
    <div id="resultContainer">
      <!-- Executive Banner -->
      <div class="exec-banner">
        <div>
          <div style="font-size: 13px; color: var(--text-muted); margin-bottom: 4px;">Audit Completed for:</div>
          <div id="resTargetUrl" style="font-size: 20px; font-weight: 700; color: #fff;"></div>
          <div id="resTimestamp" style="font-size: 12px; color: var(--text-muted); margin-top: 4px;"></div>
        </div>
        <div style="display: flex; align-items: center; gap: 16px;">
          <div style="text-align: right;">
            <div style="font-size: 12px; color: var(--text-muted);">Overall Health</div>
            <div id="resGradeText" style="font-size: 16px; font-weight: 700; color: var(--primary-light);"></div>
          </div>
          <div class="grade-circle" id="gradeCircle">
            <span class="grade-val" id="resOverallNum">--</span>
            <span class="grade-sub">/ 100</span>
          </div>
        </div>
      </div>

      <!-- Export Toolbar -->
      <div class="export-toolbar">
        <button class="btn-tool" onclick="exportCSV()">
          <span>📊 Export Issues (CSV)</span>
        </button>
        <button class="btn-tool" onclick="exportJSON()">
          <span>📄 Export Full Report (JSON)</span>
        </button>
        <button class="btn-tool" onclick="window.print()">
          <span>🖨️ Print / Save as PDF</span>
        </button>
      </div>

      <!-- KPI Grid -->
      <div class="kpi-grid">
        <div class="kpi-card">
          <div class="kpi-label">Pages Crawled</div>
          <div class="kpi-val" id="kpiPages">0</div>
          <div class="kpi-sub" id="kpiSpeed">0ms avg latency</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Issues Detected</div>
          <div class="kpi-val" id="kpiIssues">0</div>
          <div class="kpi-sub" id="kpiIssuesSub">Across 68 checks</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Commercial Fix Quote</div>
          <div class="kpi-val" id="kpiCost">₹0</div>
          <div class="kpi-sub" id="kpiHours">0 hrs est. development</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Indexability Status</div>
          <div class="kpi-val" id="kpiIndexable">100%</div>
          <div class="kpi-sub" id="kpiCritical">0 critical blockers</div>
        </div>
      </div>

      <!-- Category Breakdown -->
      <div class="card">
        <div style="font-size: 16px; font-weight: 700; margin-bottom: 16px; color: #fff;">Audit Category Breakdown</div>
        <div class="cat-grid" id="catContainer"></div>
      </div>

      <!-- Detailed Issues Explorer -->
      <div class="card">
        <div class="issues-header">
          <div style="font-size: 16px; font-weight: 700; color: #fff;">Detailed Findings & Action Plan</div>
          <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
            <input type="text" class="search-input" id="searchIssues" placeholder="Search issues..." onkeyup="filterIssues()" />
            <div class="filter-tabs">
              <button class="tab-btn active" onclick="setFilter('all', this)">All</button>
              <button class="tab-btn" onclick="setFilter('critical', this)">Critical</button>
              <button class="tab-btn" onclick="setFilter('high', this)">High</button>
              <button class="tab-btn" onclick="setFilter('medium', this)">Medium</button>
              <button class="tab-btn" onclick="setFilter('low', this)">Low</button>
            </div>
          </div>
        </div>
        <div id="issuesList"></div>
      </div>
    </div>

    <!-- Footer Links -->
    <div class="footer-links">
      <a href="/docs" target="_blank">Swagger API Docs (/docs)</a>
      <a href="/health" target="_blank">Health Check (/health)</a>
      <a href="/debug" target="_blank">Environment Diagnostics (/debug)</a>
    </div>
  </div>

  <script>
    let currentAuditData = null;
    let currentFilter = 'all';

    async function startAudit() {
      const url = document.getElementById('urlInput').value.trim();
      const maxPages = document.getElementById('pagesInput').value;
      const client = document.getElementById('clientInput').value.trim();
      const btn = document.getElementById('runBtn');
      const resContainer = document.getElementById('resultContainer');

      if (!url) return alert('Please enter a target website URL.');

      btn.disabled = true;
      btn.innerHTML = '<span>⏳ Crawling ' + maxPages + ' pages and evaluating 68+ rules...</span>';
      resContainer.style.display = 'none';

      try {
        const query = `?url=${encodeURIComponent(url)}&max_pages=${maxPages}&client_name=${encodeURIComponent(client)}`;
        const resp = await fetch(query);
        const text = await resp.text();
        btn.disabled = false;
        btn.innerHTML = '<span>⚡ Start Website Audit</span>';

        let data;
        try {
          data = JSON.parse(text);
        } catch (e) {
          alert('Server returned an unexpected response (HTTP ' + resp.status + '):\\n' + text.slice(0, 300));
          return;
        }

        if (!resp.ok) {
          alert('Audit Error: ' + (data.detail || JSON.stringify(data)));
          return;
        }

        currentAuditData = data;
        renderAudit(data);
        resContainer.style.display = 'block';
        resContainer.scrollIntoView({ behavior: 'smooth' });

      } catch (err) {
        btn.disabled = false;
        btn.innerHTML = '<span>⚡ Start Website Audit</span>';
        alert('Network request failed: ' + err.message);
      }
    }

    function renderAudit(data) {
      document.getElementById('resTargetUrl').innerText = data.url;
      document.getElementById('resTimestamp').innerText = 'Audit ID: ' + data.audit_id;
      
      const score = data.score || {};
      const stats = data.stats || {};
      const estimate = data.estimate || {};
      const findings = data.findings || [];

      // Overall Score & Grade
      document.getElementById('resOverallNum').innerText = score.overall || 0;
      document.getElementById('resGradeText').innerText = 'Grade ' + (score.grade || 'N/A');

      // KPIs
      document.getElementById('kpiPages').innerText = stats.html_pages || stats.urls_crawled || 1;
      document.getElementById('kpiSpeed').innerText = (stats.avg_response_ms || 45) + 'ms avg latency';
      document.getElementById('kpiIssues').innerText = findings.length;
      document.getElementById('kpiCost').innerText = '₹' + (estimate.total_inr ? estimate.total_inr.toLocaleString() : '0');
      document.getElementById('kpiHours').innerText = (estimate.hours || 0) + ' hrs fix time';

      const bySev = stats.by_severity || {};
      document.getElementById('kpiCritical').innerText = (bySev.critical || 0) + ' critical blockers';

      // Categories
      const catContainer = document.getElementById('catContainer');
      catContainer.innerHTML = '';
      (score.categories || []).forEach(cat => {
        const color = cat.score >= 85 ? '#10b981' : cat.score >= 70 ? '#12a37f' : cat.score >= 50 ? '#f59e0b' : '#ef4444';
        const div = document.createElement('div');
        div.className = 'cat-card';
        div.innerHTML = `
          <div class="cat-header">
            <span class="cat-title">${cat.name}</span>
            <span class="cat-score" style="color: ${color};">${cat.score}% (${cat.grade})</span>
          </div>
          <div class="progress-bg">
            <div class="progress-bar" style="width: ${cat.score}%; background: ${color};"></div>
          </div>
        `;
        catContainer.appendChild(div);
      });

      // Render Issues
      renderIssuesList(findings);
    }

    function renderIssuesList(findings) {
      const container = document.getElementById('issuesList');
      container.innerHTML = '';

      if (!findings || findings.length === 0) {
        container.innerHTML = '<div style="padding: 24px; text-align: center; color: var(--text-muted);">No issues detected! Site passed all evaluated checks.</div>';
        return;
      }

      findings.forEach((item, idx) => {
        const sevClass = 'sev-' + (item.severity || 'low').toLowerCase();
        const div = document.createElement('div');
        div.className = 'issue-item';
        div.dataset.severity = (item.severity || 'low').toLowerCase();
        div.dataset.title = (item.title || '').toLowerCase();

        div.innerHTML = `
          <div class="issue-summary" onclick="toggleDetails(${idx})">
            <div class="issue-left">
              <span class="badge-sev ${sevClass}">${item.severity || 'low'}</span>
              <span class="badge-cat">${item.category || 'General'}</span>
              <span class="issue-title">${item.title}</span>
            </div>
            <span style="font-size: 13px; color: var(--text-muted);">▾</span>
          </div>
          <div class="issue-details" id="detail-${idx}">
            <p><strong>Why this matters:</strong> ${item.why || 'Affects technical performance and visibility.'}</p>
            <div class="fix-box">
              <strong>Recommended Fix:</strong><br/>
              ${item.fix || item.fix_steps || 'Review page configuration.'}
            </div>
            ${item.affected && item.affected.length > 0 ? `<p style="margin-top: 10px; color: var(--text-muted); font-size: 12px;"><strong>Affected pages (${item.affected.length}):</strong> ${item.affected.map(a => a.url).slice(0, 3).join(', ')}</p>` : ''}
          </div>
        `;
        container.appendChild(div);
      });
    }

    function toggleDetails(idx) {
      const el = document.getElementById('detail-' + idx);
      el.style.display = el.style.display === 'block' ? 'none' : 'block';
    }

    function setFilter(sev, btn) {
      currentFilter = sev;
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      filterIssues();
    }

    function filterIssues() {
      const q = document.getElementById('searchIssues').value.toLowerCase();
      const items = document.querySelectorAll('.issue-item');
      items.forEach(el => {
        const matchesSev = currentFilter === 'all' || el.dataset.severity === currentFilter;
        const matchesQuery = !q || el.dataset.title.includes(q);
        el.style.display = (matchesSev && matchesQuery) ? 'block' : 'none';
      });
    }

    // Export CSV
    function exportCSV() {
      if (!currentAuditData || !currentAuditData.findings) return alert('No audit data available to export.');
      const findings = currentAuditData.findings;
      const headers = ['Category', 'Severity', 'Title', 'Why It Matters', 'Recommended Fix'];
      const rows = findings.map(f => [
        `"${(f.category || '').replace(/"/g, '""')}"`,
        `"${(f.severity || '').replace(/"/g, '""')}"`,
        `"${(f.title || '').replace(/"/g, '""')}"`,
        `"${(f.why || '').replace(/"/g, '""')}"`,
        `"${(f.fix || f.fix_steps || '').replace(/"/g, '""')}"`
      ]);
      const csvContent = 'data:text/csv;charset=utf-8,' + [headers.join(','), ...rows.map(r => r.join(','))].join('\\n');
      const encodedUri = encodeURI(csvContent);
      const link = document.createElement('a');
      link.setAttribute('href', encodedUri);
      link.setAttribute('download', `audit-${currentAuditData.audit_id}-issues.csv`);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    }

    // Export JSON
    function exportJSON() {
      if (!currentAuditData) return alert('No audit data available to export.');
      const dataStr = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(currentAuditData, null, 2));
      const link = document.createElement('a');
      link.setAttribute('href', dataStr);
      link.setAttribute('download', `audit-${currentAuditData.audit_id}.json`);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    }
  </script>
</body>
</html>
"""


# Catch-all adaptive route: handles root, /api/audit, and any rewritten path seamlessly
@app.api_route("/{full_path:path}", methods=["GET", "POST"])
def adaptive_handler(request: Request, full_path: str = ""):
    qp = request.query_params

    # Check if this is an audit request (has ?url= or target path)
    if "url" in qp:
        try:
            pages = int(qp.get("max_pages", 5))
        except Exception:
            pages = 5
        return _execute_audit(qp["url"], max_pages=pages, client_name=qp.get("client_name"))

    if full_path in ("health", "api/health"):
        return health()

    if full_path in ("debug", "api/debug"):
        return debug()

    if _init_error is not None:
        return HTMLResponse(
            f"<h2>Engine Startup Error</h2><pre>{_init_error}</pre>",
            status_code=500
        )

    return HTMLResponse(DASHBOARD_HTML)
