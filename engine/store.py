"""SQLite store shared by the crawler, the MCP tools, and the Hermes agents."""
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


SCHEMA = """
CREATE TABLE IF NOT EXISTS audits (
  id TEXT PRIMARY KEY,
  url TEXT,
  client_name TEXT,
  status TEXT,
  started_at TEXT,
  finished_at TEXT,
  score_json TEXT,
  stats_json TEXT,
  psi_json TEXT,
  error TEXT,
  report_dir TEXT,
  consent_probe INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS pages (
  audit_id TEXT,
  url TEXT,
  final_url TEXT,
  status INTEGER,
  depth INTEGER,
  template TEXT,
  title TEXT,
  word_count INTEGER,
  noindex INTEGER,
  simhash TEXT,
  pagerank REAL,
  payload TEXT,
  PRIMARY KEY (audit_id, url)
);
CREATE TABLE IF NOT EXISTS links (
  audit_id TEXT,
  source TEXT,
  target TEXT,
  internal INTEGER
);
CREATE TABLE IF NOT EXISTS evidence (
  id TEXT PRIMARY KEY,
  audit_id TEXT,
  kind TEXT,
  url TEXT,
  detail TEXT
);
CREATE TABLE IF NOT EXISTS findings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  audit_id TEXT,
  rule_id TEXT,
  category TEXT,
  severity TEXT,
  title TEXT,
  why TEXT,
  fix TEXT,
  scope TEXT,
  affected TEXT,
  evidence_ids TEXT,
  business_impact TEXT,
  fix_steps TEXT,
  platform_fixes TEXT,
  acceptance_check TEXT,
  confidence REAL,
  agent TEXT,
  status TEXT
);
CREATE TABLE IF NOT EXISTS tickets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  audit_id TEXT,
  finding_id INTEGER,
  title TEXT,
  owner TEXT,
  effort_hours REAL,
  steps TEXT,
  code TEXT,
  acceptance TEXT,
  status TEXT,
  platform_fixes TEXT
);
CREATE TABLE IF NOT EXISTS artifacts (
  audit_id TEXT,
  name TEXT,
  path TEXT
);
CREATE TABLE IF NOT EXISTS deliveries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  audit_id TEXT,
  channel TEXT,
  payload TEXT,
  status TEXT,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS wp_approvals (
  audit_id TEXT PRIMARY KEY,
  reviewer TEXT,
  created_at TEXT
);
"""


class AuditStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)

    def close(self):
        self._db.close()

    def create_audit(self, audit_id: str, url: str, client_name: str = "", consent_probe: bool = False) -> str:
        with self._lock:
            self._db.execute(
                "INSERT INTO audits (id, url, client_name, status, started_at, consent_probe) VALUES (?,?,?,?,?,?)",
                (audit_id, url, client_name, "running", _now(), int(consent_probe)),
            )
            self._db.commit()
        return audit_id

    def update_audit(self, audit_id: str, **fields):
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        with self._lock:
            self._db.execute(f"UPDATE audits SET {cols} WHERE id=?", (*fields.values(), audit_id))
            self._db.commit()

    def get_audit(self, audit_id: str) -> dict | None:
        row = self._db.execute("SELECT * FROM audits WHERE id=?", (audit_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        for key in ("score_json", "stats_json", "psi_json"):
            data[key[:-5]] = json.loads(data.pop(key) or "null")
        return data

    def save_page(self, audit_id: str, page: dict):
        with self._lock:
            self._db.execute(
                """INSERT OR REPLACE INTO pages
                   (audit_id, url, final_url, status, depth, template, title, word_count, noindex, simhash, pagerank, payload)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (audit_id, page["url"], page.get("final_url"), page.get("status"), page.get("depth"),
                 page.get("template"), page.get("title"), page.get("word_count"), int(page.get("noindex") or 0),
                 page.get("simhash"), page.get("pagerank"), json.dumps(page.get("payload") or {}, default=str)),
            )
            self._db.commit()

    def save_graph(self, audit_id: str, pages: list[dict], links: list[tuple]):
        with self._lock:
            self._db.executemany(
                """INSERT OR REPLACE INTO pages
                   (audit_id, url, final_url, status, depth, template, title, word_count, noindex, simhash, pagerank, payload)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                [(audit_id, p["url"], p.get("final_url"), p.get("status"), p.get("depth"), p.get("template"),
                  p.get("title"), p.get("word_count"), int(p.get("noindex") or 0), p.get("simhash"),
                  p.get("pagerank"), json.dumps(p.get("payload") or {}, default=str)) for p in pages],
            )
            self._db.executemany(
                "INSERT INTO links (audit_id, source, target, internal) VALUES (?,?,?,?)",
                [(audit_id, src, dst, int(internal)) for src, dst, internal in links],
            )
            self._db.commit()

    def add_evidence(self, audit_id: str, kind: str, url: str, detail: str) -> str:
        eid = "ev_" + uuid.uuid4().hex[:12]
        with self._lock:
            self._db.execute(
                "INSERT INTO evidence (id, audit_id, kind, url, detail) VALUES (?,?,?,?,?)",
                (eid, audit_id, kind, url, detail),
            )
            self._db.commit()
        return eid

    def evidence_exists(self, audit_id: str, evidence_id: str) -> bool:
        row = self._db.execute(
            "SELECT 1 FROM evidence WHERE audit_id=? AND id=?", (audit_id, evidence_id)
        ).fetchone()
        return row is not None

    def insert_finding(self, audit_id: str, finding: dict) -> int:
        with self._lock:
            cur = self._db.execute(
                """INSERT INTO findings
                   (audit_id, rule_id, category, severity, title, why, fix, scope, affected, evidence_ids,
                    business_impact, fix_steps, platform_fixes, acceptance_check, confidence, agent, status)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (audit_id, finding["rule_id"], finding.get("category"), finding.get("severity"),
                 finding.get("title"), finding.get("why"), finding.get("fix"), finding.get("scope", "page"),
                 json.dumps(finding.get("affected") or []), json.dumps(finding.get("evidence_ids") or []),
                 finding.get("business_impact", ""), finding.get("fix_steps", ""),
                 json.dumps(finding.get("platform_fixes") or {}), finding.get("acceptance_check", ""),
                 finding.get("confidence", 1.0), finding.get("agent", "engine"), finding.get("status", "open")),
            )
            self._db.commit()
            return int(cur.lastrowid)

    def update_finding(self, finding_id: int, **fields) -> bool:
        allowed = {"severity", "status", "business_impact", "fix_steps", "confidence"}
        fields = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not fields:
            return False
        cols = ", ".join(f"{k}=?" for k in fields)
        with self._lock:
            cur = self._db.execute(f"UPDATE findings SET {cols} WHERE id=?", (*fields.values(), finding_id))
            self._db.commit()
        return cur.rowcount > 0

    def list_findings(self, audit_id: str, status: str | None = None, severity: str | None = None,
                      limit: int = 100, offset: int = 0) -> list[dict]:
        sql = "SELECT * FROM findings WHERE audit_id=?"
        args: list = [audit_id]
        if status:
            sql += " AND status=?"
            args.append(status)
        if severity:
            sql += " AND severity=?"
            args.append(severity)
        sql += " ORDER BY id LIMIT ? OFFSET ?"
        args.extend([limit, offset])
        return [_finding(row) for row in self._db.execute(sql, args)]

    def get_finding(self, finding_id: int) -> dict | None:
        row = self._db.execute("SELECT * FROM findings WHERE id=?", (finding_id,)).fetchone()
        return _finding(row) if row else None

    def query_pages(self, audit_id: str, template: str | None = None, limit: int = 25, offset: int = 0) -> dict:
        sql = "SELECT url, final_url, status, depth, template, title, word_count, noindex, pagerank FROM pages WHERE audit_id=?"
        args: list = [audit_id]
        if template:
            sql += " AND template=?"
            args.append(template)
        total = self._db.execute(
            "SELECT COUNT(*) FROM pages WHERE audit_id=?" + (" AND template=?" if template else ""),
            args,
        ).fetchone()[0]
        rows = self._db.execute(sql + " ORDER BY depth, url LIMIT ? OFFSET ?", (*args, limit, offset)).fetchall()
        return {"total": total, "limit": limit, "offset": offset, "pages": [dict(r) for r in rows]}

    def get_page(self, audit_id: str, url: str) -> dict | None:
        row = self._db.execute(
            "SELECT * FROM pages WHERE audit_id=? AND (url=? OR final_url=?)", (audit_id, url, url)
        ).fetchone()
        if not row:
            return None
        data = dict(row)
        data["payload"] = json.loads(data.pop("payload") or "{}")
        return data

    def list_templates(self, audit_id: str) -> list[dict]:
        rows = self._db.execute(
            """SELECT template, COUNT(*) AS pages FROM pages
               WHERE audit_id=? GROUP BY template ORDER BY pages DESC""",
            (audit_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def pageranks(self, audit_id: str) -> dict[str, float]:
        rows = self._db.execute(
            "SELECT url, pagerank FROM pages WHERE audit_id=? AND pagerank IS NOT NULL", (audit_id,)
        )
        return {r["url"]: r["pagerank"] for r in rows}

    def add_ticket(self, audit_id: str, ticket: dict) -> int:
        with self._lock:
            cur = self._db.execute(
                """INSERT INTO tickets
                   (audit_id, finding_id, title, owner, effort_hours, steps, code, acceptance, status, platform_fixes)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (audit_id, ticket.get("finding_id"), ticket["title"], ticket.get("owner"),
                 ticket.get("effort_hours"), ticket.get("steps"), ticket.get("code", ""),
                 ticket.get("acceptance", ""), ticket.get("status", "open"),
                 json.dumps(ticket.get("platform_fixes") or {})),
            )
            self._db.commit()
            return int(cur.lastrowid)

    def list_tickets(self, audit_id: str) -> list[dict]:
        rows = self._db.execute("SELECT * FROM tickets WHERE audit_id=? ORDER BY id", (audit_id,))
        out = []
        for row in rows:
            data = dict(row)
            data["platform_fixes"] = json.loads(data.pop("platform_fixes") or "{}")
            out.append(data)
        return out

    def add_artifact(self, audit_id: str, name: str, path: str):
        with self._lock:
            self._db.execute("INSERT INTO artifacts (audit_id, name, path) VALUES (?,?,?)", (audit_id, name, path))
            self._db.commit()

    def artifacts(self, audit_id: str) -> list[dict]:
        return [dict(r) for r in self._db.execute("SELECT name, path FROM artifacts WHERE audit_id=?", (audit_id,))]

    def queue_delivery(self, audit_id: str, channel: str, payload: dict) -> int:
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO deliveries (audit_id, channel, payload, status, created_at) VALUES (?,?,?,?,?)",
                (audit_id, channel, json.dumps(payload), "pending_review", _now()),
            )
            self._db.commit()
            return int(cur.lastrowid)

    def set_delivery_status(self, delivery_id: int, status: str) -> bool:
        with self._lock:
            cur = self._db.execute("UPDATE deliveries SET status=? WHERE id=?", (status, delivery_id))
            self._db.commit()
        return cur.rowcount > 0

    def approve_wordpress(self, audit_id: str, reviewer: str):
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO wp_approvals (audit_id, reviewer, created_at) VALUES (?,?,?)",
                (audit_id, reviewer, _now()),
            )
            self._db.commit()

    def wordpress_approved(self, audit_id: str) -> bool:
        return self._db.execute("SELECT 1 FROM wp_approvals WHERE audit_id=?", (audit_id,)).fetchone() is not None

    def get_delivery(self, delivery_id: int) -> dict | None:
        row = self._db.execute("SELECT * FROM deliveries WHERE id=?", (delivery_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        data["payload"] = json.loads(data.pop("payload") or "{}")
        return data


def _finding(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["affected"] = json.loads(data.pop("affected") or "[]")
    data["evidence_ids"] = json.loads(data.pop("evidence_ids") or "[]")
    data["platform_fixes"] = json.loads(data.pop("platform_fixes") or "{}")
    return data
