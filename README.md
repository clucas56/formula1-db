# F1 Data Platform — v2 (Containerized)

Replaces the v1 LAPP stack's `debian-db` and `debian-app` VMs with a single
Docker host running three containers. `webster` is **kept** as the edge VM.

## Architecture

```
Internet → Cloudflare → tunnel → webster (Apache)
                                   ├── charleslucas562.com     → portfolio site (untouched)
                                   └── f1.charleslucas562.com  → Docker host :8000
                                                                      ↓
                                                          ┌─────────────────────┐
                                                          │  Docker host VM     │
                                                          │  ┌───────────────┐  │
                                                          │  │ api (FastAPI) │  │
                                                          │  └───────┬───────┘  │
                                                          │  ┌───────┴───────┐  │
                                                          │  │   postgres    │  │
                                                          │  └───────┬───────┘  │
                                                          │  ┌───────┴───────┐  │
                                                          │  │  ingestion    │  │
                                                          │  └───────────────┘  │
                                                          └─────────────────────┘
```

- **postgres** — PostgreSQL 17, persistent named volume
- **api** — FastAPI (replaces Flask + gunicorn), exposes port 8000
- **ingestion** — scheduler running `incremental_load.py` weekly (replaces host cron)

There is **no cloudflared and no nginx** in this stack — `webster` already
provides public ingress (Cloudflare tunnel) and reverse proxying (Apache).

The v1 architecture is preserved in `DOCUMENTATION.md` for reference.
**`HANDOFF.md` is the build runbook** — start there.

## Quick reference

```bash
# First-time bring-up (see HANDOFF.md for the full sequence)
cp .env.example .env          # then fill in real values
docker compose up -d postgres # schema auto-loads on first start
docker compose run --rm ingestion python fetch_data.py   # one-time historical load
docker compose up -d          # bring up api + ingestion

# Day-2 operations
docker compose ps
docker compose logs -f api
docker compose logs -f ingestion
docker compose up -d --build api          # redeploy after a code change
docker compose down                       # stop (data persists)
docker compose down -v                    # stop AND delete data (destructive)

# Trigger an immediate incremental run (don't wait for the schedule)
docker compose exec ingestion python -c "from incremental_load import main; main()"

# Backup
docker compose exec -T postgres pg_dump -U f1user -d f1_data -F c \
  > backups/f1_data_$(date +%F).dump
```

## Directory layout

```
formula1-db/
├── docker-compose.yml      # 3 services, 1 network, 2 named volumes
├── .env.example            # copy to .env, fill in, never commit .env
├── HANDOFF.md              # ← the build runbook
├── DOCUMENTATION.md         # v1 LAPP architecture (historical reference)
│
├── postgres/init/          # 01-schema.sql — auto-runs on first container start
├── api/                    # FastAPI service
│   └── routes/             # standings, races, query (text-to-SQL)
├── ingestion/              # scheduler + the original pipeline scripts
└── webster/                # config for the EDGE VM (not part of the stack)
    ├── f1.charleslucas562.com.conf   # Apache vhost
    └── f1-tunnel.service.txt         # autossh tunnel (webster → Docker host)
```

## What changed from v1

| v1 | v2 |
|---|---|
| debian-db + debian-app VMs | One Docker host, 3 containers |
| webster: Apache + cloudflared + autossh ×2 | webster: Apache + cloudflared + autossh ×1 |
| autossh tunnels into virbr0 (×2, flaky) | One tunnel to one stable Docker host |
| Flask + gunicorn + systemd | FastAPI + uvicorn + container restart policy |
| Host cron `0 6 * * 1` | ingestion container reading `INGESTION_CRON` |
| psycopg2 (sync) | psycopg 3 with connection pools |
| No text-to-SQL | `/query` endpoint backed by the Anthropic API |
| Manual deploy: ssh + git pull + systemctl | `docker compose up -d --build api` |
```
