# F1 Data Platform v2 — Documentation

**Author:** clucas56
**Last Updated:** May 2026
**Repository:** github.com/clucas56/formula1-db

> **Note:** This documents the v2 containerized stack. For the original
> v1 LAPP architecture see `DOCUMENTATION.md`.

---

## Table of Contents

1. [What Changed from v1 to v2](#what-changed-from-v1-to-v2)
2. [Architecture Overview](#architecture-overview)
3. [Infrastructure](#infrastructure)
4. [Docker — The Core Concept](#docker--the-core-concept)
5. [The Three Services](#the-three-services)
6. [FastAPI vs Flask](#fastapi-vs-flask)
7. [Database Schema and Views](#database-schema-and-views)
8. [The Ingestion Pipeline](#the-ingestion-pipeline)
9. [Webster — Edge VM](#webster--edge-vm)
10. [Environment Variables and Secrets](#environment-variables-and-secrets)
11. [Daily Backups](#daily-backups)
12. [How It All Connects — End to End Flow](#how-it-all-connects--end-to-end-flow)
13. [Key Commands Reference](#key-commands-reference)
14. [Troubleshooting](#troubleshooting)
15. [Azure Equivalent Architecture](#azure-equivalent-architecture)

---

## What Changed from v1 to v2

v1 ran on three separate VMs — a database server, an app server, and a web
server — connected by SSH tunnels. It worked, but firewall/networking issues
caused two weeks of lockout problems and made it fragile.

v2 solves this by collapsing the database and app into a single Docker host.
Docker handles the networking between services internally, eliminating the
SSH tunnel complexity entirely.

| v1 | v2 |
|---|---|
| 3 VMs (debian-db, debian-app, webster) | 2 VMs (docker host, webster) |
| Flask web framework | FastAPI web framework |
| gunicorn process manager | uvicorn (built into FastAPI) |
| SSH tunnels between VMs | Docker internal networking |
| cron on webster for ingestion | In-container scheduler |
| Manual schema setup | Auto-runs on first container start |
| Private GitHub repo | Public portfolio repo |

**What stayed the same:**
- PostgreSQL 17
- The original ingestion scripts (fetch_data.py, incremental_load.py)
- Webster as the edge VM (Apache + Cloudflare tunnel)
- The Jolpica API as the data source
- Dark F1 dashboard aesthetic

---

## Architecture Overview

```
Internet
    ↓ HTTPS
Cloudflare (terminates SSL)
    ↓ Cloudflare Tunnel
webster VM (192.168.4.7)
    Apache reverse proxy
    ↓ HTTP proxied to 192.168.4.9:8000
Docker Host VM (192.168.4.9, Debian 13)
    ├── f1-api container (FastAPI :8000)
    │       ↓ reads from
    ├── f1-postgres container (PostgreSQL :5432)
    └── f1-ingestion container (scheduler)
            ↓ writes to
        f1-postgres container
```

All three Docker containers share one internal network (`f1net`) and talk
to each other by service name (`postgres`, `api`). Nothing on the internet
can reach postgres directly — only the api and ingestion containers can.

---

## Infrastructure

### RHEL KVM Host (IBM-BASEMENT)
The physical machine running all the VMs. Unchanged from v1.

| Property | Value |
|---|---|
| OS | RHEL 7.9 |
| IP | 192.168.4.5 |
| RAM | 141 GB |
| Hypervisor | KVM / libvirt |

### Docker Host VM
New VM created for v2. Runs the entire F1 stack as Docker containers.

| Property | Value |
|---|---|
| OS | Debian 13 (Trixie) |
| IP | 192.168.4.9 (static, eno2 network) |
| RAM | 4 GB |
| Disk | 40 GB |
| Network | eno2 (same LAN as webster) |
| Purpose | Runs Docker stack |

### Webster VM
Unchanged from v1. Still the public-facing edge VM.

| Property | Value |
|---|---|
| OS | Ubuntu 20.04 |
| IP | 192.168.4.7 |
| Purpose | Apache reverse proxy + Cloudflare tunnel |

---

## Docker — The Core Concept

### What is Docker?
Docker lets you package an application and everything it needs (Python,
libraries, config) into a single portable unit called a **container**.
A container runs identically on any machine that has Docker installed.

Think of it like a shipping container — the contents are packed the same
way regardless of which ship carries it.

### Key Terms

**Image** — A blueprint for a container. Like a class in Python. Built from
a `Dockerfile`. You build an image once, then run it many times.

**Container** — A running instance of an image. Like an object created from
a class. You can have many containers from the same image.

**Volume** — Persistent storage that survives container restarts. This is
how postgres keeps data even if the container is destroyed and recreated.

**Network** — A virtual network that containers share. Containers on the
same network can talk to each other by service name instead of IP address.

### docker-compose.yml
Instead of running containers manually with long docker commands,
`docker-compose.yml` defines all three services, their config, and how
they connect — then you bring everything up with one command.

```bash
docker compose up -d       # start all services in the background
docker compose down        # stop all services
docker compose ps          # check what's running
docker compose logs api    # view logs for the api service
docker compose restart api # restart one service
```

### Why Docker over separate VMs?
- **No SSH tunnels** — containers on the same Docker network talk directly
- **Reproducible** — git clone + docker compose up and it's running
- **Isolated** — if ingestion crashes it doesn't touch the API or database
- **Portable** — the exact same setup could run on any VM or cloud provider

---

## The Three Services

### postgres
Runs PostgreSQL 17. Identical to the old debian-db VM but containerized.

- Data persists in a named volume (`postgres_data`) — destroying the
  container does NOT delete your data
- The init script (`postgres/init/01-schema.sql`) runs automatically
  the very first time the container starts when the data volume is empty
- No ports exposed to the outside — only `api` and `ingestion` can reach it
- Has a healthcheck so other services wait for it to be ready before starting

### api
Runs the FastAPI application. Replaces the old Flask app on debian-app.

- Built from `api/Dockerfile` using `python:3.12-slim`
- Runs as a non-root user (`apiuser`) for security
- Exposes port 8000 to the Docker host — this is what Webster proxies to
- Serves both JSON API endpoints and the HTML frontend

### ingestion
Runs the data pipeline scheduler. Replaces the old cron job on webster.

- Runs `scheduler.py` which sleeps until the next scheduled time
  (default: Monday 6am, controlled by `INGESTION_CRON` env var)
- Then calls `incremental_load.main()` to pull the latest race data
- `fetch_data.py` is NOT run by this service — that's a one-time manual step

---

## FastAPI vs Flask

FastAPI replaced Flask in v2. Both are Python web frameworks but FastAPI
has several advantages relevant to the career path.

### How FastAPI works
You define functions and decorate them with `@router.get(...)` or
`@router.post(...)` to tell FastAPI which URL triggers each function.

```python
@router.get("/drivers", response_model=list[DriverStanding])
def get_driver_standings():
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM current_standings ORDER BY position;")
            rows = cur.fetchall()
    return rows
```

FastAPI automatically:
- Validates the returned data matches `list[DriverStanding]`
- Converts it to JSON
- Documents it at `/docs` (auto-generated interactive API docs)

### Key differences from Flask

| Flask | FastAPI |
|---|---|
| `@app.route("/path")` | `@router.get("/path")` |
| Returns dict directly | Uses Pydantic models for validation |
| No built-in type hints | Type hints are first-class |
| No auto-generated docs | Interactive docs at `/docs` |
| gunicorn for production | uvicorn built in |

### Pydantic Models (models.py)
Pydantic validates data shape. If a database row is missing a field or
has the wrong type FastAPI returns a 422 error automatically — you do not
have to write manual validation code.

```python
class DriverStanding(BaseModel):
    position: int
    driver_name: str
    constructor_name: str | None = None
    points: Decimal
    wins: int
```

### Connection Pooling (db.py)
The API uses a connection pool rather than opening a new database connection
for every request. A pool keeps a set of connections open and reuses them.
This is standard production practice — opening a new connection for every
request is slow and wastes resources.

### Jinja2 HTML Frontend
The HTML pages (`/` homepage and `/race/{season}/{round}`) are served by
FastAPI using Jinja2 templates — the same templating engine Flask used.
Templates live in `api/templates/` and use `{{ variable }}` syntax to
inject data from Python into HTML.

---

## Database Schema and Views

### Schema
12 tables auto-created by `postgres/init/01-schema.sql` on first container
start. Same structure as v1 with one bug fix (fastest_lap column syntax).

| Table | Purpose |
|---|---|
| seasons | F1 seasons (year, total rounds) |
| circuits | Race tracks |
| drivers | Driver info |
| constructors | Teams |
| races | Race calendar |
| race_results | Finishing positions, points, status |
| qualifying_results | Q1/Q2/Q3 times |
| sprint_results | Sprint race results |
| driver_standings | Championship standings per round |
| constructor_standings | Team championship per round |
| lap_times | Individual lap data |
| pit_stops | Pit stop data |

### Data Loaded
~25,784 race results, 1,149 races, 879 drivers covering 1950–2025.

### Views
Two views built manually as a SQL exercise in Phase 4.

**current_standings** — Driver championship standings for the latest round
of the most recent season. Uses a `DISTINCT ON` subquery to find each
driver's constructor from their most recent race (handles mid-season team
changes correctly).

```sql
CREATE OR REPLACE VIEW current_standings AS
SELECT
    ds.position,
    d.first_name || ' ' || d.last_name AS driver_name,
    c.name AS constructor_name,
    ds.points,
    ds.wins
FROM driver_standings ds
JOIN drivers d ON d.driver_id = ds.driver_id
JOIN (
    SELECT DISTINCT ON (rr.driver_id)
        rr.driver_id,
        rr.constructor_id
    FROM race_results rr
    JOIN races r ON r.race_id = rr.race_id
    WHERE r.season_year = (SELECT MAX(season_year) FROM races)
    ORDER BY rr.driver_id, r.round DESC
) latest_constructor ON latest_constructor.driver_id = ds.driver_id
JOIN constructors c ON c.constructor_id = latest_constructor.constructor_id
WHERE ds.season_year = (SELECT MAX(season_year) FROM driver_standings)
  AND ds.round = (
      SELECT MAX(round) FROM driver_standings ds2
      WHERE ds2.season_year = ds.season_year
  )
ORDER BY ds.position;
```

**last_race_results** — Full finishing order of the most recently completed
race, using `date <= CURRENT_DATE` to handle future races in the calendar.

---

## The Ingestion Pipeline

### fetch_data.py — One Time Bootstrap
Loads all historical F1 data from 1950 to present. Runs for 1–2 hours
due to Jolpica API rate limiting (~200 requests/hour). Run once with:

```bash
docker compose run --rm ingestion python fetch_data.py
```

`run --rm` starts a one-shot container that deletes itself when done.
Do NOT use `exec` here — the scheduler isn't the right place for this.

### incremental_load.py — Weekly Updates
Loads only the latest completed race. Runs in under 10 seconds.
Triggered automatically by the scheduler every Monday at 6am.

### scheduler.py — The Timer
Runs forever inside the ingestion container. Reads the `INGESTION_CRON`
env var, sleeps until the next scheduled time, then calls `incremental_load.main()`.

**Important:** `incremental_load.py` calls `sys.exit(1)` on failure.
The scheduler intentionally catches `SystemExit` so a failed run does not
kill the whole scheduler — it logs the error and keeps waiting for the next
scheduled time.

---

## Webster — Edge VM

Webster's role did not change in v2 — it is still the public-facing edge VM.
What changed is the Apache vhost now points directly to the Docker host IP
instead of through a local SSH tunnel.

### Apache Virtual Host (f1.charleslucas562.com)

```apache
<VirtualHost *:80>
    ServerName f1.charleslucas562.com
    ProxyPreserveHost On
    ProxyPass        / http://192.168.4.9:8000/
    ProxyPassReverse / http://192.168.4.9:8000/
    RequestHeader set X-Forwarded-Proto "https"
    ProxyTimeout 60
    ErrorLog  ${APACHE_LOG_DIR}/f1_error.log
    CustomLog ${APACHE_LOG_DIR}/f1_access.log combined
</VirtualHost>
```

### Key Rules for Webster
- **Always `apache2ctl configtest` before reloading Apache.** If the config
  has a syntax error and you reload, Apache stops serving the portfolio site.
- The portfolio site (`charleslucas562.com`) is in a **separate vhost file**.
  Never edit it. After any Apache change, curl the portfolio site to confirm
  it still works.
- After every Apache config change run:
  ```bash
  sudo apache2ctl configtest   # must say Syntax OK
  sudo systemctl reload apache2
  curl https://charleslucas562.com   # confirm portfolio still works
  ```

---

## Environment Variables and Secrets

All secrets live in `.env` on the Docker host. Never committed to GitHub
(`.env` is in `.gitignore`). `.env.example` is in the repo and shows the
required variables without real values.

```
DB_NAME=f1_data
DB_USER=f1user
DB_PASSWORD=<strong password>
INGESTION_CRON=0 6 * * 1
```

### How docker-compose passes them to containers
`docker-compose.yml` uses `${VARIABLE}` syntax to read from `.env` and
pass values into each container's environment. The containers then read
them with `os.getenv("VARIABLE")`.

### Read-Only Postgres Role (f1reader)
Created in Phase 6 for the API's database connection. Has SELECT only —
cannot INSERT, UPDATE, or DELETE. Provides defense-in-depth for the API.

```sql
CREATE ROLE f1reader WITH LOGIN PASSWORD '<password>';
GRANT CONNECT ON DATABASE f1_data TO f1reader;
GRANT USAGE ON SCHEMA public TO f1reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO f1reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO f1reader;
```

---

## Daily Backups

Configured as a cron job on the Docker host. Runs at 2am daily.

```bash
0 2 * * * docker compose -f /home/clucas/formula1-db/docker-compose.yml exec -T postgres pg_dump -U f1user -d f1_data -F c > /backups/f1_data_$(date +\%F).dump && find /backups -name 'f1_data_*.dump' -mtime +14 -delete
```

- `-F c` — custom format, more efficient than plain SQL
- Backups stored in `/backups/` on the Docker host
- Files older than 14 days are deleted automatically

### Manual backup
```bash
docker compose exec -T postgres pg_dump -U f1user -d f1_data -F c > /backups/f1_data_manual.dump
```

### Verify backup exists
```bash
ls -lh /backups/
```

---

## How It All Connects — End to End Flow

### Web Request (f1.charleslucas562.com)
```
1. Browser requests f1.charleslucas562.com
2. Cloudflare terminates HTTPS and routes through tunnel
3. cloudflared on webster passes to Apache on localhost:80
4. Apache vhost matches f1.charleslucas562.com
5. Apache proxies to 192.168.4.9:8000 (Docker host)
6. FastAPI api container receives request
7. pages.py queries postgres container via f1net Docker network
8. postgres returns data from current_standings / last_race_results views
9. FastAPI renders Jinja2 HTML template with data
10. Response returns through Apache → Cloudflare → browser
```

### Weekly Ingestion (Monday 6am)
```
1. scheduler.py wakes up — INGESTION_CRON timer fires
2. Calls incremental_load.main()
3. Connects to postgres container via Docker network (hostname: postgres)
4. Fetches latest race from Jolpica API
5. Checks if race already exists in database
6. If new — upserts race, results, standings
7. Commits to PostgreSQL
8. scheduler.py goes back to sleep until next Monday
```

### Code Deploy
```
1. Edit code on local machine
2. git push to github.com/clucas56/formula1-db
3. SSH into Docker host
4. git pull
5. docker compose up -d --build api   (rebuilds only the changed service)
6. Test at https://f1.charleslucas562.com
```

---

## Key Commands Reference

### On the Docker Host

```bash
# Start all services
docker compose up -d

# Check service status
docker compose ps

# View logs
docker compose logs api
docker compose logs postgres
docker compose logs ingestion

# Rebuild and restart one service after a code change
docker compose up -d --build api

# Open a postgres shell
docker compose exec postgres psql -U f1user -d f1_data

# Run the one-time historical load
docker compose run --rm ingestion python fetch_data.py

# Check row counts
docker compose exec postgres psql -U f1user -d f1_data -c "
  SELECT 'race_results', COUNT(*) FROM race_results UNION ALL
  SELECT 'races',        COUNT(*) FROM races UNION ALL
  SELECT 'drivers',      COUNT(*) FROM drivers;
"

# Manual backup
docker compose exec -T postgres pg_dump -U f1user -d f1_data -F c > /backups/manual.dump
```

### On Webster

```bash
# Test config before reloading (always do this first)
sudo apache2ctl configtest

# Reload Apache after config changes
sudo systemctl reload apache2

# Check Apache status
sudo systemctl status apache2

# Check Apache error logs
sudo tail -50 /var/log/apache2/f1_error.log

# Verify both sites work
curl https://f1.charleslucas562.com/health
curl https://charleslucas562.com
```

---

## Troubleshooting

### API container keeps restarting
```bash
docker compose logs api
# Most common causes:
# - DB credentials wrong in .env
# - postgres not healthy yet (it starts slower than api)
# - Python import error in the code
```

### Site returns 502 Bad Gateway
Webster can reach the Docker host but the API isn't responding.
```bash
# On Docker host
docker compose ps                    # is f1-api running?
curl http://localhost:8000/health   # does API respond locally?
docker compose logs api             # any errors?
```

### Site times out completely
Webster can't reach the Docker host at all.
```bash
# On webster
curl http://192.168.4.9:8000/health   # can webster reach Docker host?
# On Docker host
sudo ufw status                        # is port 8000 allowed?
docker compose ps                      # are containers running?
```

### postgres data gone after container restart
This should NOT happen if you are using docker compose — postgres data
is in the named volume `postgres_data` which persists. If you ran
`docker compose down -v` (note the `-v` flag) that deletes volumes.
Without `-v` the data is safe.

### Ingestion stopped running
```bash
docker compose logs ingestion
# Check if scheduler.py is still alive
docker compose ps
# Restart if needed
docker compose restart ingestion
```

### Apache breaks the portfolio site after an edit
```bash
# Check config immediately
sudo apache2ctl configtest
# If errors found, fix them before proceeding
# If Apache is already down
sudo systemctl status apache2
sudo journalctl -u apache2 -n 50 --no-pager
```

---

## Azure Equivalent Architecture

This stack maps directly to real Azure services. Every component here
has a direct enterprise equivalent.

| v2 Component | Azure Equivalent |
|---|---|
| Docker host VM | Azure Container Apps / ACI |
| docker-compose.yml | Azure Container Apps environment |
| postgres container | Azure Database for PostgreSQL Flexible Server |
| api container (FastAPI) | Azure Container Apps (or App Service) |
| ingestion container | Azure Container Apps Job (scheduled) |
| Named volume (postgres_data) | Azure Managed Disk / Azure Storage |
| .env file | Azure Key Vault |
| webster Apache proxy | Azure Application Gateway / Front Door |
| Cloudflare Tunnel | Azure Public IP + DNS Zone |
| Daily pg_dump cron | Azure Backup for PostgreSQL |
| GitHub repo | Azure DevOps / GitHub Actions |
| Jolpica API → fetch_data.py | Azure Data Factory Pipeline |
| Weekly incremental_load | ADF Scheduled Trigger |
| FastAPI /docs endpoint | Azure API Management |
| f1reader read-only role | Azure Managed Identity (least privilege) |

The containerized approach is particularly valuable for Azure — the same
`docker-compose.yml` logic translates almost directly to Azure Container
Apps configurations, making this a natural stepping stone toward AZ-104
and AZ-305 work.
