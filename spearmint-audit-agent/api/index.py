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

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(
    title="Spearmint Audit Agent",
    description="Serverless Website & SEO Audit Agent API",
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


@app.get("/api/audit")
@app.post("/api/audit")
@app.get("/audit")
@app.post("/audit")
def run_audit(
    url: str = Query(..., description="Website URL to audit"),
    max_pages: int = Query(1, ge=1, le=5, description="Pages to crawl (recommended 1-3 on Vercel)"),
    client_name: Optional[str] = Query(None, description="Client or brand name"),
):
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

    try:
        result = execute(
            clean_url,
            audit_id=audit_id,
            store=store,
            max_pages=max_pages,
            max_depth=2,
            timeout=5,            # Short timeout to fit in serverless function
            pagespeed=False,      # Disabled for speed and quota safety
            render=False,         # No browser in serverless
            out=str(REPORTS_DIR),
            open_browser=False,
            log=lambda *a, **k: None,
            client_name=client_name,
        )

        return {
            "status": "completed",
            "audit_id": audit_id,
            "url": clean_url,
            "score": result.get("score"),
            "stats": result.get("stats"),
            "estimate": result.get("estimate"),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Audit failed: {str(exc)[:400]}")


@app.get("/api/findings")
@app.get("/findings")
def list_findings(audit_id: str, limit: int = 50, offset: int = 0):
    store = get_store()
    if store is None:
        raise HTTPException(status_code=500, detail="Store is not initialized")
    return store.list_findings(audit_id, limit=limit, offset=offset)


@app.get("/", response_class=HTMLResponse)
@app.get("/index", response_class=HTMLResponse)
def index():
    if _init_error is not None:
        return f"""<!DOCTYPE html>
<html>
<head><title>Initialization Error - Spearmint</title></head>
<body style="font-family:sans-serif;background:#0f172a;color:#f8fafc;padding:30px;">
  <h2 style="color:#ef4444;">Engine Startup Error</h2>
  <p>The Python serverless function started, but failed to load the engine:</p>
  <pre style="background:#1e293b;padding:16px;border-radius:8px;overflow:auto;color:#fca5a5;">{_init_error}</pre>
  <p><a href="/debug" style="color:#12a37f;">View Debug Environment (/debug)</a></p>
</body>
</html>"""

    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Spearmint Audit Agent</title>
  <style>
    :root {
      --primary: #12a37f;
      --primary-dark: #0e8063;
      --bg: #0f172a;
      --card-bg: #1e293b;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --border: #334155;
    }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      margin: 0;
      padding: 40px 20px;
      display: flex;
      justify-content: center;
    }
    .container {
      max-width: 720px;
      width: 100%;
    }
    .badge {
      display: inline-block;
      background: rgba(18, 163, 127, 0.2);
      color: var(--primary);
      padding: 4px 10px;
      border-radius: 9999px;
      font-size: 13px;
      font-weight: 600;
      margin-bottom: 12px;
    }
    h1 {
      margin: 0 0 8px 0;
      font-size: 28px;
    }
    p.desc {
      color: var(--text-muted);
      margin-top: 0;
      margin-bottom: 24px;
    }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 24px;
      margin-bottom: 24px;
    }
    .form-group {
      margin-bottom: 16px;
    }
    label {
      display: block;
      margin-bottom: 6px;
      font-weight: 500;
      font-size: 14px;
    }
    input, select {
      width: 100%;
      padding: 12px;
      border-radius: 8px;
      border: 1px solid var(--border);
      background: #0f172a;
      color: #fff;
      font-size: 15px;
      box-sizing: border-box;
    }
    input:focus, select:focus {
      outline: none;
      border-color: var(--primary);
    }
    button {
      width: 100%;
      background: var(--primary);
      color: white;
      border: none;
      border-radius: 8px;
      padding: 14px;
      font-size: 16px;
      font-weight: 600;
      cursor: pointer;
      transition: background 0.2s;
    }
    button:hover {
      background: var(--primary-dark);
    }
    button:disabled {
      background: var(--border);
      cursor: not-allowed;
    }
    #result {
      margin-top: 20px;
      display: none;
    }
    .score-banner {
      display: flex;
      align-items: center;
      justify-content: space-between;
      background: rgba(18, 163, 127, 0.15);
      border: 1px solid var(--primary);
      border-radius: 8px;
      padding: 16px;
      margin-bottom: 16px;
    }
    .score-circle {
      font-size: 36px;
      font-weight: 800;
      color: var(--primary);
    }
    .cat-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      margin-bottom: 16px;
    }
    .cat-item {
      background: #0f172a;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 10px 14px;
      display: flex;
      justify-content: space-between;
    }
    pre {
      background: #090d16;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 12px;
      overflow-x: auto;
      font-size: 13px;
      color: #cbd5e1;
    }
    .links {
      display: flex;
      gap: 16px;
      font-size: 14px;
    }
    .links a {
      color: var(--primary);
      text-decoration: none;
    }
    .links a:hover {
      text-decoration: underline;
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="badge">Vercel Deployment Active</div>
    <h1>Spearmint Audit Agent</h1>
    <p class="desc">Enter a domain or URL below to run an instant serverless SEO audit.</p>

    <div class="card">
      <div class="form-group">
        <label for="url">Target URL</label>
        <input type="text" id="url" placeholder="https://example.com" value="https://example.com" />
      </div>
      <div class="form-group">
        <label for="max_pages">Pages to Crawl</label>
        <select id="max_pages">
          <option value="1" selected>1 Page (Fast, ~1s)</option>
          <option value="2">2 Pages</option>
          <option value="3">3 Pages</option>
        </select>
      </div>
      <button id="auditBtn" onclick="runAudit()">Run Audit</button>

      <div id="result">
        <div class="score-banner">
          <div>
            <div style="font-size: 13px; color: var(--text-muted);">Overall Score</div>
            <div id="scoreGrade" style="font-size: 18px; font-weight: bold;"></div>
          </div>
          <div id="scoreNum" class="score-circle">--</div>
        </div>
        <div class="cat-grid" id="catGrid"></div>
        <pre id="rawJson"></pre>
      </div>
    </div>

    <div class="links">
      <a href="/docs" target="_blank">Interactive API Docs (/docs)</a>
      <a href="/api/health" target="_blank">Health Check (/api/health)</a>
      <a href="/debug" target="_blank">Debug (/debug)</a>
    </div>
  </div>

  <script>
    async function runAudit() {
      const url = document.getElementById('url').value.trim();
      const maxPages = document.getElementById('max_pages').value;
      const btn = document.getElementById('auditBtn');
      const resultDiv = document.getElementById('result');
      const rawJson = document.getElementById('rawJson');
      const scoreNum = document.getElementById('scoreNum');
      const scoreGrade = document.getElementById('scoreGrade');
      const catGrid = document.getElementById('catGrid');

      if (!url) return alert('Please enter a URL');

      btn.disabled = true;
      btn.innerText = 'Crawling and Scoring...';
      resultDiv.style.display = 'none';

      try {
        const resp = await fetch(`/api/audit?url=${encodeURIComponent(url)}&max_pages=${maxPages}`);
        const text = await resp.text();
        btn.disabled = false;
        btn.innerText = 'Run Audit';

        let data;
        try {
          data = JSON.parse(text);
        } catch (jsonErr) {
          alert('Server returned non-JSON response (HTTP ' + resp.status + '):\\n' + text.slice(0, 300));
          return;
        }

        if (!resp.ok) {
          alert('Audit failed: ' + (data.detail || JSON.stringify(data)));
          return;
        }

        resultDiv.style.display = 'block';
        scoreNum.innerText = data.score.overall;
        scoreGrade.innerText = 'Grade ' + data.score.grade;

        catGrid.innerHTML = '';
        (data.score.categories || []).forEach(c => {
          const div = document.createElement('div');
          div.className = 'cat-item';
          div.innerHTML = `<span>${c.name}</span><strong>${c.score} (${c.grade})</strong>`;
          catGrid.appendChild(div);
        });

        rawJson.innerText = JSON.stringify(data, null, 2);
      } catch (err) {
        btn.disabled = false;
        btn.innerText = 'Run Audit';
        alert('Network error: ' + err.message);
      }
    }
  </script>
</body>
</html>
"""
