"""HTTP MCP server. Tools call the audit engine; they do not invent scores."""
import os

from engine.service import AuditService

TOKEN = os.environ.get("AUDIT_MCP_TOKEN", "dev-token")
HOST = os.environ.get("AUDIT_HOST", "127.0.0.1")
PORT = int(os.environ.get("AUDIT_PORT", "8800"))
SERVICE = AuditService(os.environ.get("AUDIT_DB"))


def _tools():
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("spearmint-audit", host=HOST, port=PORT)

    @mcp.tool()
    def start_audit(url: str, client_name: str = "", max_pages: int = 2000, render: bool = False,
                    pagespeed: bool = True, check_external: bool = False) -> dict:
        """Start a website audit. Returns immediately with an audit_id. Default crawl cap is 2000 pages."""
        return SERVICE.start_audit(url, client_name, max_pages, check_external=check_external,
                                    pagespeed=pagespeed, render=render)

    @mcp.tool()
    def wait_for_audit(audit_id: str, timeout_s: int = 600) -> dict:
        """Block until the audit finishes or timeout_s elapses (maximum 600). Call again if it is still running."""
        return SERVICE.wait_for_audit(audit_id, timeout_s)

    @mcp.tool()
    def get_site_overview(audit_id: str) -> dict:
        """Score, issue counts, templates, and report paths for one audit."""
        return SERVICE.get_site_overview(audit_id)

    @mcp.tool()
    def list_findings(audit_id: str, status: str = "", severity: str = "", limit: int = 50, offset: int = 0) -> dict:
        """Paginated findings. Filter by status (open, verified, rejected, fixed) and severity."""
        return SERVICE.list_findings(audit_id, status, severity, limit, offset)

    @mcp.tool()
    def query_pages(audit_id: str, template: str = "", limit: int = 25, offset: int = 0) -> dict:
        """Paginated page list. Pass a template from list_templates to sample that group."""
        return SERVICE.query_pages(audit_id, template, limit, offset)

    @mcp.tool()
    def get_page(audit_id: str, url: str) -> dict:
        """One crawled page, including the evidence payload."""
        return SERVICE.get_page(audit_id, url)

    @mcp.tool()
    def list_templates(audit_id: str) -> dict:
        """URL templates and how many crawled pages belong to each."""
        return SERVICE.list_templates(audit_id)

    @mcp.tool()
    def render_page(url: str) -> dict:
        """Render a URL in a headless browser and compare word counts with the raw HTML."""
        return SERVICE.render_page(url)

    @mcp.tool()
    def run_lighthouse(url: str, strategy: str = "mobile") -> dict:
        """PageSpeed Insights lab data and Chrome UX Report field data for one URL."""
        return SERVICE.run_lighthouse(url, strategy)

    @mcp.tool()
    def run_axe(url: str) -> dict:
        """axe-core WCAG scan of one rendered URL."""
        return SERVICE.run_axe(url)

    @mcp.tool()
    def check_structured_data(audit_id: str, url: str) -> dict:
        """Schema types and schema findings already stored for one page."""
        return SERVICE.check_structured_data(audit_id, url)

    @mcp.tool()
    def check_tls(host: str) -> dict:
        """Certificate validity and days until expiry. Passive check."""
        return SERVICE.check_tls(host)

    @mcp.tool()
    def dns_email_auth(domain: str) -> dict:
        """SPF and DMARC TXT records for a domain."""
        return SERVICE.dns_email_auth(domain)

    @mcp.tool()
    def submit_findings(audit_id: str, findings: list, agent: str) -> dict:
        """Save agent findings. Each one needs a severity and evidence. Findings without evidence are rejected."""
        return SERVICE.submit_findings(audit_id, findings, agent)

    @mcp.tool()
    def update_finding(finding_id: int, status: str = "", severity: str = "", note: str = "") -> dict:
        """QA tool. Set status to verified or rejected, and optionally change severity."""
        return SERVICE.update_finding(finding_id, status, severity, note)

    @mcp.tool()
    def create_fix_tickets(audit_id: str) -> dict:
        """Create tickets for verified findings that do not have one yet, plus the rupee estimate."""
        return SERVICE.create_fix_tickets(audit_id)

    @mcp.tool()
    def build_report(audit_id: str) -> dict:
        """Write the verified-findings summary into the audit folder and export tickets."""
        return SERVICE.build_report(audit_id)

    @mcp.tool()
    def export_tickets(audit_id: str, path: str = "") -> dict:
        """Write tickets.csv."""
        return SERVICE.export_tickets(audit_id, path)

    @mcp.tool()
    def diff_audits(old_audit_id: str, new_audit_id: str) -> dict:
        """Compare two audits. Returns fixed, still_open, and new issue rows."""
        return SERVICE.diff_audits(old_audit_id, new_audit_id)

    @mcp.tool()
    def queue_delivery(audit_id: str, channel: str = "internal", note: str = "") -> dict:
        """Hold the report for Spearmint review. Does not email the client."""
        return SERVICE.queue_delivery(audit_id, channel, note)

    @mcp.tool()
    def approve_delivery(delivery_id: int) -> dict:
        """Mark an internal review as approved. Sending still happens outside this tool."""
        return SERVICE.approve_delivery(delivery_id)

    @mcp.tool()
    def offpage_summary(domain: str) -> dict:
        """Backlinks and ranking keywords from DataForSEO. Unavailable until API keys are set."""
        return SERVICE.offpage_summary(domain)

    @mcp.tool()
    def search_console(site_url: str) -> dict:
        """Search Console queries for a client who has granted access."""
        return SERVICE.search_console(site_url)

    @mcp.tool()
    def ga4_overview(property_id: str) -> dict:
        """GA4 channel report for a client who has granted access."""
        return SERVICE.ga4_overview(property_id)

    @mcp.tool()
    def wordpress_propose(audit_id: str) -> dict:
        """List title fixes that could be written to WordPress. Does not change the site."""
        return SERVICE.wordpress_propose(audit_id)

    @mcp.tool()
    def wordpress_apply(audit_id: str, site: str) -> dict:
        """Apply approved title fixes. Refuses to run until a human has approved this audit id."""
        return SERVICE.wordpress_apply(audit_id, site)

    return mcp


def main():
    if TOKEN == "dev-token":
        print("AUDIT_MCP_TOKEN is not set. Using dev-token, which is only for this machine.")
    try:
        mcp = _tools()
    except ImportError as exc:
        raise SystemExit(f"The mcp package is required ({exc}). pip install -r requirements.txt") from exc
    app = mcp.streamable_http_app() if hasattr(mcp, "streamable_http_app") else mcp.http_app()
    app.add_middleware(_bearer())
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)


def _bearer():
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    class BearerMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            if request.url.path in ("/health",):
                return JSONResponse({"status": "ok"})
            header = request.headers.get("authorization", "")
            if header != f"Bearer {TOKEN}":
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            return await call_next(request)

    return BearerMiddleware


if __name__ == "__main__":
    main()
