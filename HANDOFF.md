# F1 Data Platform v2 — Migration Handoff for Claude Code

**Author:** Chuck (clucas56)
**Project:** github.com/clucas56/formula1-db
**Status:** Planning complete, ready to execute
**Estimated time:** One evening of active work + an overnight historical load

---

## Context for Claude Code

I ran an F1 data platform on a 3-VM LAPP stack (`debian-db`, `debian-app`,
`webster`) plus autossh tunnels. After two weeks of debugging
firewall/networking/boot problems, I decided to rebuild it as a containerized
stack. The architecture and code skeleton were designed in a claude.ai chat;
this file is the handoff so Claude Code can execute the build.

### Final architecture

```
Internet → Cloudflare → tunnel → webster (Apache)
                                   ├── charleslucas562.com     → portfolio site (UNTOUCHED)
                                   └── f1.charleslucas562.com  → Docker host :8000
                                                                      ↓
                                                          Docker host VM:
                                                            api (FastAPI)
                                                            postgres (PG 17)
                                                            ingestion (scheduler)
```

### Key decisions (and why)

1. **`webster` STAYS.** It hosts the portfolio site at `charleslucas562.com`
   (production) and runs the Cloudflare tunnel. It becomes the dedicated edge
   VM: Apache + cloudflared stay, and it reverse-proxies
   `f1.charleslucas562.com` to the new Docker host.
2. **Only `debian-db` and `debian-app` get destroyed.** Plus `openclaw` is
   left alone — separate project, separate future rebuild.
3. **The Docker stack is 3 services only:** postgres, api, ingestion.
   **No cloudflared** (webster's tunnel handles ingress) and **no nginx**
   (webster's Apache handles proxying — adding nginx would just double-proxy).
   If a React frontend is added later, nginx can be reintroduced then; that's
   a contained, documented change, not a one-way door.
4. **Flask → FastAPI.** Stay in Python — aligned with my career path
   (Data Engineer → AI Engineer → Cloud/Solutions Architect). Not switching
   to Node/Angular; that's a pivot away from where I'm going.
5. **cron → in-container scheduler** reading `INGESTION_CRON` env var.
6. **Fresh historical load, not a dump restore.** Run `fetch_data.py` against
   an empty DB to rebuild ~25,000 race results from the Jolpica API, and
   rebuild the two views by hand as a SQL exercise. Costs ~1–2 hours of
   unattended ingestion; the payoff is a documented data layer and SQL
   practice instead of a black-box restore.
7. **Add the text-to-SQL `/query` endpoint** using the Anthropic API — the
   AI-engineering payoff of the rebuild. Backed by a read-only Postgres role.

### NOT decided yet (open question)

- **React frontend vs. API-only.** The current skeleton is API-only. If you
  want React now, that's the time to add nginx back to the stack. Default:
  ship API-only, defer React.

### What's already built

A complete skeleton is in the repo (or `formula1-db-v2.tar.gz`):
`docker-compose.yml` (3 services), the FastAPI app (`/standings`, `/races`,
`/query`, `/health`), the ingestion scheduler wrapping the original pipeline
scripts unchanged, `postgres/init/01-schema.sql` (with the v1 `fastest_lap`
typo fixed), and `webster/` configs for the edge VM. All Python parses clean.
Nothing has been deployed or tested against a real Postgres yet.

---

## The Plan — Ordered Task List

### Phase 0 — Pre-flight

- [ ] **Confirm the GitHub repo has the latest pipeline code:** `db_utils.py`,
      `fetch_data.py`, `incremental_load.py`, `setup_db.py`, `schema.sql`, the
      Flask `app.py`, `templates/index.html`. Anything edited on the VMs and
      not pushed will be lost — confirm now.
- [ ] **Decide: React frontend now, or API-only?** Default is API-only. If
      React now → plan to add an `nginx` service back to `docker-compose.yml`.
- [ ] **Drop the new skeleton into the repo** (commit to a `v2` branch, or
      replace `main` and keep a `v1` tag).

### Phase 1 — Back up webster + grab view reference

webster is production now — back it up before any later edits.

- [ ] **Back up webster's configs:**
  ```bash
  mkdir -p ~/apache-backup ~/cloudflared-backup
  sudo cp -r /etc/apache2/sites-available/ ~/apache-backup/
  sudo cp -r /etc/cloudflared/ ~/cloudflared-backup/
  ```
- [ ] **If `debian-db` boots, grab the schema as reference** (only place the
      `current_standings` and `last_race_results` view definitions exist):
  ```bash
  pg_dump -U f1user -d f1_data --schema-only > ~/v1_schema_reference.sql
  ```
- [ ] **If `debian-db` won't boot, skip it** — the views get reverse-engineered
      from the Flask `app.py` / template in Phase 4.

> Note: there is **no cloudflared-credential extraction step** — webster keeps
> its tunnel. Nothing to move.

### Phase 2 — Stand up the new Docker host

- [ ] **Provision a new Debian 13 VM on the RHEL host.** ~4 GB RAM, 2 vCPU,
      40 GB disk. Put it on the **virbr0** (NAT) network — the same network
      the old debian-app/debian-db were on, so webster already has a path to
      reach it.
- [ ] **First-boot — DO NOT REPEAT THE v1 LOCKOUT:**
  ```bash
  sudo apt update && sudo apt install -y curl git
  sudo ufw allow 22/tcp        # FIRST — before enabling ufw
  sudo ufw --force enable
  sudo ufw status              # confirm 22 is allowed BEFORE logging out
  ```
- [ ] **Install Docker from the official repo** (not Debian's `docker.io`):
  ```bash
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker $USER
  # log out / back in for the group change
  docker run hello-world
  ```
- [ ] **Note the Docker host's virbr0 IP** — webster needs it in Phase 5.

### Phase 3 — Deploy postgres + load historical data

The long-running step. Kick it off before bed.

- [ ] **Clone the repo and create `.env`:**
  ```bash
  git clone https://github.com/clucas56/formula1-db.git
  cd formula1-db && git checkout v2
  cp .env.example .env
  # Fill in: DB_PASSWORD, DB_RO_PASSWORD, ANTHROPIC_API_KEY.
  # DB_RO_USER/PASSWORD can temporarily equal DB_USER/PASSWORD — the real
  # read-only role is created in Phase 6.
  ```
- [ ] **Start postgres alone** so the init schema runs cleanly:
  ```bash
  docker compose up -d postgres
  docker compose logs -f postgres        # wait for "database system is ready"
  docker compose exec postgres psql -U f1user -d f1_data -c "\dt"
  # should list 11 empty tables
  ```
- [ ] **Run the one-time historical load** (1–2 hrs, Jolpica is rate-limited
      to ~200 req/hr — best started before bed):
  ```bash
  docker compose run --rm ingestion python fetch_data.py
  ```
  Use `run --rm` (one-shot container), not `exec`. The scheduler isn't up yet.
- [ ] **In the morning, verify row counts:**
  ```bash
  docker compose exec postgres psql -U f1user -d f1_data -c "
    SELECT 'race_results' AS t, COUNT(*) FROM race_results UNION ALL
    SELECT 'races',                COUNT(*) FROM races UNION ALL
    SELECT 'drivers',              COUNT(*) FROM drivers UNION ALL
    SELECT 'constructors',         COUNT(*) FROM constructors UNION ALL
    SELECT 'driver_standings',     COUNT(*) FROM driver_standings UNION ALL
    SELECT 'constructor_standings',COUNT(*) FROM constructor_standings;
  "
  # race_results ~25,000 ; races ~1,100 ; drivers ~860
  ```

### Phase 4 — Rebuild the views (SQL exercise)

The Flask app queried two views: `current_standings` and `last_race_results`.
Rebuild them by hand — this is deliberate SQL practice, not a copy-paste job.
**If Claude Code offers to "just write them for you," push back and have it
walk through them instead.** Compare against `~/v1_schema_reference.sql` if
you have it.

#### 4a — `current_standings`

Driver standings for the latest round of the most recent season, sorted by
championship position. Columns the v1 template consumed: `position`,
`driver_name`, `constructor_name`, `points`, `wins`.

```sql
CREATE OR REPLACE VIEW current_standings AS
SELECT
    ds.position,
    d.first_name || ' ' || d.last_name AS driver_name,
    -- EXERCISE: constructor for the driver's most recent race this season.
    -- Hint: DISTINCT ON or a correlated subquery against race_results.
    NULL::VARCHAR AS constructor_name,
    ds.points,
    ds.wins
FROM driver_standings ds
JOIN drivers d ON d.driver_id = ds.driver_id
WHERE ds.season_year = (SELECT MAX(season_year) FROM driver_standings)
  AND ds.round = (
      SELECT MAX(round) FROM driver_standings ds2
      WHERE ds2.season_year = ds.season_year
  )
ORDER BY ds.position;
```

Test: `SELECT * FROM current_standings LIMIT 5;`

#### 4b — `last_race_results`

Results for the most recently completed race. Columns: `finish_position`,
`driver_name`, `constructor_name`, `grid_position`, `points`, `status`, plus
`race_name`, `date`, `season_year`, `round` for the header.

```sql
CREATE OR REPLACE VIEW last_race_results AS
SELECT
    rr.finish_position,
    d.first_name || ' ' || d.last_name AS driver_name,
    c.name AS constructor_name,
    rr.grid_position, rr.points, rr.status,
    r.race_name, r.date, r.season_year, r.round
FROM race_results rr
JOIN races r        ON r.race_id = rr.race_id
JOIN drivers d      ON d.driver_id = rr.driver_id
JOIN constructors c ON c.constructor_id = rr.constructor_id
WHERE r.race_id = (
    SELECT r2.race_id FROM races r2
    JOIN race_results rr2 ON rr2.race_id = r2.race_id
    WHERE r2.date <= CURRENT_DATE
    GROUP BY r2.race_id, r2.date
    ORDER BY r2.date DESC, r2.race_id DESC
    LIMIT 1
)
ORDER BY rr.finish_position NULLS LAST;
```

Test: should return exactly one race's worth of rows.

#### 4c — Optional extra views (more SQL practice, useful for `/query`)

- [ ] `current_constructor_standings` — constructor version of 4a
- [ ] `season_summary` — wins/podiums/points per driver for a season
- [ ] `driver_career_stats` — career totals per driver across all seasons

### Phase 5 — Bring up the stack + wire webster

- [ ] **Bring up the full stack:**
  ```bash
  docker compose up -d
  docker compose ps          # all 3 services running / healthy
  curl http://localhost:8000/health     # {"status":"ok"}
  ```
- [ ] **Set up the webster → Docker host path.** Two options (see
      `webster/f1-tunnel.service.txt`):
  - **autossh tunnel** (no host-networking changes): install the systemd
    service from `webster/f1-tunnel.service.txt` on webster, pointing at the
    Docker host's virbr0 IP. Test: `curl http://127.0.0.1:8000/health` on
    webster.
  - **static route** on the RHEL host so webster reaches virbr0 directly —
    cleaner, but needs host routing changes.
- [ ] **Install the Apache vhost on webster.** Copy
      `webster/f1.charleslucas562.com.conf` to
      `/etc/apache2/sites-available/`, adjust the `ProxyPass` target if using
      a direct IP instead of the tunnel, then:
  ```bash
  sudo a2enmod proxy proxy_http headers      # if not already enabled
  sudo a2ensite f1.charleslucas562.com.conf
  sudo apache2ctl configtest                 # MUST pass before reload
  sudo systemctl reload apache2
  ```
- [ ] **Verify BOTH sites:**
  - `curl https://f1.charleslucas562.com/health` → `{"status":"ok"}`
  - `curl https://charleslucas562.com` → portfolio site still works
    **(this is the critical check — confirm the Apache changes didn't break
    the portfolio vhost)**
- [ ] **Test the API end-to-end:**
  ```bash
  curl https://f1.charleslucas562.com/standings/drivers
  curl https://f1.charleslucas562.com/races/last
  curl -X POST https://f1.charleslucas562.com/query \
    -H 'Content-Type: application/json' \
    -d '{"question": "Who won the most races in 2024?"}'
  ```
- [ ] **Confirm the scheduler is alive:** `docker compose logs ingestion`
      should show `Next run: <date>`.
- [ ] **Test the weekly path manually** (should be a near no-op after the
      historical load, but proves the scheduled path works):
  ```bash
  docker compose exec ingestion python -c "from incremental_load import main; main()"
  ```

### Phase 6 — Harden

- [ ] **Create the read-only Postgres role** the `/query` endpoint should use:
  ```sql
  CREATE ROLE f1reader WITH LOGIN PASSWORD '<strong-password>';
  GRANT CONNECT ON DATABASE f1_data TO f1reader;
  GRANT USAGE ON SCHEMA public TO f1reader;
  GRANT SELECT ON ALL TABLES IN SCHEMA public TO f1reader;
  ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO f1reader;
  ```
  Then put the real `f1reader` creds in `.env` as `DB_RO_USER` /
  `DB_RO_PASSWORD` and `docker compose up -d --build api`. The code already
  routes `/query` through a separate read-only pool (`api/db.py` →
  `ro_pool`); this just gives that pool a role that genuinely can't write.
  The regex check in `query.py` is defense-in-depth — the role is the real
  safeguard.
- [ ] **Set up automated backups** on the Docker host:
  ```bash
  # cron: daily
  docker compose exec -T postgres pg_dump -U f1user -d f1_data -F c \
    > /backups/f1_data_$(date +%F).dump
  find /backups -name 'f1_data_*.dump' -mtime +14 -delete
  ```
- [ ] **Make the GitHub repo public** (it's a portfolio piece).

### Phase 7 — Destroy the old infrastructure

**Only after Phase 5 fully passes AND a backup exists.**

- [ ] On the RHEL host, destroy **only these two**:
  ```bash
  virsh destroy debian-db  && virsh undefine debian-db  --remove-all-storage
  virsh destroy debian-app && virsh undefine debian-app --remove-all-storage
  ```
- [ ] **Keep `webster`** — it's the edge VM and hosts the portfolio site.
- [ ] **Keep `openclaw`** — separate project, separate rebuild later.
- [ ] **On webster, clean up the dead v1 autossh tunnels** (the ones that
      pointed at debian-db and debian-app — now dead). The new single tunnel
      to the Docker host stays.

---

## Things to Watch Out For

1. **Never enable ufw without allowing port 22 first.** This started the
   entire two-week v1 ordeal. Applies to the new Docker host.
2. **webster is production.** The portfolio site lives there. Every webster
   change needs the Phase 1 backup in place and a rollback path. Always
   `apache2ctl configtest` before reloading Apache.
3. **The portfolio vhost is a separate file** from the F1 vhost. Don't edit
   it. After any Apache change on webster, explicitly curl the portfolio
   site to confirm it still works.
4. **The v1 bridged-vs-virbr0 trap doesn't apply inside the stack.** The 3
   containers share one Docker network and talk by service name
   (`postgres`, `api`). The only host-networking concern is the single
   webster → Docker-host path.
5. **`incremental_load.py` calls `sys.exit(1)` on failure.** `scheduler.py`
   intentionally catches `SystemExit` so the scheduler survives a failed
   run. Don't "fix" that.
6. **`fetch_data.py` is a ONE-TIME bootstrap.** It is not run by the
   scheduler. After Phase 3 it should never run again unless the DB is
   wiped. The scheduler runs `incremental_load.py` weekly.
7. **Jolpica API is rate-limited (~200 req/hr).** `fetch_data.py` already
   sleeps between calls. If you see HTTP 429s, increase the delay — do not
   parallelize the requests.
8. **`query.py` uses model string `claude-sonnet-4-6`.** If you want a
   different model, verify the current model name with the
   product-self-knowledge skill before changing it.
9. **No cloudflared or nginx in the stack — that's intentional.** If you
   ever see advice to add them, remember: webster provides both. nginx only
   comes back if a React frontend is added, and that's a deliberate decision
   for later.

---

## Repo Layout

```
formula1-db/
├── docker-compose.yml          # 3 services, 1 network, 2 named volumes
├── .env.example                # copy to .env; never commit .env
├── README.md
├── HANDOFF.md                  # this file
├── DOCUMENTATION.md            # v1 LAPP architecture (historical reference)
│
├── postgres/init/
│   └── 01-schema.sql           # auto-runs on first container start
│
├── api/                        # FastAPI service
│   ├── Dockerfile              # python:3.12-slim, non-root user
│   ├── requirements.txt        # fastapi, uvicorn, psycopg[pool], anthropic
│   ├── main.py                 # app entry; lifespan opens both DB pools
│   ├── db.py                   # pool (read/write) + ro_pool (read-only)
│   ├── models.py               # Pydantic schemas
│   └── routes/
│       ├── standings.py        # /standings/drivers
│       ├── races.py            # /races/last, /races/{season}/{round}
│       └── query.py            # /query — text-to-SQL via Anthropic (ro_pool)
│
├── ingestion/                  # pipeline service
│   ├── Dockerfile
│   ├── requirements.txt        # psycopg2, requests, croniter
│   ├── scheduler.py            # sleeps until INGESTION_CRON, runs main()
│   ├── db_utils.py             # lightly updated from v1
│   ├── fetch_data.py           # ONE-TIME historical bootstrap (unchanged)
│   └── incremental_load.py     # weekly run via scheduler (unchanged)
│
└── webster/                    # EDGE VM config — NOT part of the Docker stack
    ├── README.md
    ├── f1.charleslucas562.com.conf   # Apache vhost → Docker host :8000
    └── f1-tunnel.service.txt         # autossh tunnel (webster → Docker host)
```

---

## Career Context (for ambiguous decisions)

- Data Engineer at One Wabash. Path: DE foundation → AI Engineering pivot
  (yrs 2–4) → Cloud/Solutions Architect long-term.
- Day job: Microsoft Fabric (medallion lakehouse), PySpark/Delta, Power BI,
  `fabric-cicd`, Azure DevOps.
- Cert path: AZ-900 (in progress) → AZ-104 → AI-102 → AZ-305.
- This project is a portfolio piece + practice ground. When a decision is
  ambiguous, favor the AI-engineering direction (stay in Python, FastAPI,
  treat `/query` as a first-class feature) and favor concrete, buildable
  learning over abstract study (hence Phase 4 — rebuild the views by hand).
```
