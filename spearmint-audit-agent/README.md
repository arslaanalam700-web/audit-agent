# Spearmint audit agent

The engine crawls a site and scores it. Hermes agents read those results over MCP and talk to each other over A2A. They do not invent the score.

## Run an audit from this folder

```powershell
pip install -r requirements.txt
python -m engine.site_audit https://example.com --client-name "Acme" --no-pagespeed --no-open
```

From the Spearmint folder the old command still works: `python -m site_audit https://example.com`.

Reports land in `reports\<domain>-<timestamp>\` (HTML, pitch, fix pack, CSV). The same run is stored in `data\audits.db`.

Useful flags: `--max-pages 2000`, `--render`, `--axe`, `--check-external`, `--psi-samples 3`, `--ai`.

## Start the MCP server

```powershell
$env:AUDIT_MCP_TOKEN = "a-long-random-string"
python -m mcp_server.server
```

Tools are on `http://127.0.0.1:8800/mcp`. Callers must send `Authorization: Bearer <token>`.

## Hermes team

```powershell
powershell -ExecutionPolicy Bypass -File hermes\bootstrap.ps1
```

That writes ten profiles (nine in the core team, plus an optional WordPress fixer). On Windows it copies them into `%LOCALAPPDATA%\hermes\profiles`. Each profile already has its own A2A port (9900 for the lead through 9909) and its own bearer token. The lead fans work out with `a2a_orchestrate` on the capability `audit_specialist`.

The model is set to OpenRouter in each `config.yaml`. Add `OPENROUTER_API_KEY` to the profile `.env` files (one key is enough to copy into all ten), or run `hermes -p lead model` if you use Nous Portal instead. Then:

```powershell
hermes -p lead gateway start
```

Nothing is emailed to a client. `queue_delivery` writes `data\outbox\` and waits for `approve_delivery`.

## Tests

```powershell
python -m unittest tests.test_audit -v
$env:AUDIT_LIVE = "1"
python -m unittest tests.test_audit.LiveSitesTest -v
```

## Server

On a Linux VPS, from `deploy\`:

```sh
cp ../.env.example ../.env
docker compose up -d --build
sh install-profiles.sh
```

Caddy publishes only the lead agent (`:9900`). Schedule a nightly backup:

```sh
0 2 * * * /opt/spearmint/audit-agent/deploy/backup.sh
```

`deploy/healthcheck.sh` checks the engine and the lead agent card. Engine logs are `docker compose logs -f audit-engine`. Hermes logs and token cost are `docker logs hermes` and `docker exec hermes hermes insights`. The audit engine makes no model calls, so its cost is zero.

Optional keys in `.env.example`: PageSpeed, DataForSEO, Search Console, GA4, WordPress. WordPress changes stay off until someone runs:

```powershell
python -m engine.wordpress approve <audit_id> --reviewer "Your Name"
```
