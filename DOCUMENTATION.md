# F1 Data Platform — Project Documentation

**Author:** clucas56
**Last Updated:** April 2026
**Repository:** github.com/clucas56/formula1-db

---

## Table of Contents

1. [What You Built — The Big Picture](#what-you-built--the-big-picture)
2. [Infrastructure Overview](#infrastructure-overview)
3. [IBM-BASEMENT — RHEL Host](#ibm-basement--rhel-host)
4. [Debian DB Server Setup](#debian-db-server-setup)
5. [PostgreSQL Setup](#postgresql-setup)
6. [Ubuntu Web Server](#ubuntu-web-server)
7. [Flask App Server Setup](#flask-app-server-setup)
8. [SSH Tunnel Setup](#ssh-tunnel-setup)
9. [Python Pipeline](#python-pipeline)
10. [Database Schema](#database-schema)
11. [Database Views](#database-views)
12. [Web Dashboard](#web-dashboard)
13. [GitHub Webhook — Auto Deploy](#github-webhook--auto-deploy)
14. [Data Quality — Duplicate Prevention](#data-quality--duplicate-prevention)
15. [GitHub Version Control](#github-version-control)
16. [Firewall Rules](#firewall-rules)
17. [Network Topology](#network-topology)
18. [Incremental Load Pipeline](#incremental-load-pipeline)
19. [Cron Jobs](#cron-jobs)
20. [How It All Connects — End to End Flow](#how-it-all-connects--end-to-end-flow)
21. [Key Concepts Learned](#key-concepts-learned)
22. [Troubleshooting](#troubleshooting)
23. [Next Steps](#next-steps)
24. [Azure Equivalent Architecture](#azure-equivalent-architecture)

---

## What You Built — The Big Picture

This project is a full end to end F1 data platform built entirely on home lab
infrastructure. It pulls historical and live Formula 1 data from public APIs,
stores it in a relational database, and serves it through a live web dashboard
at f1.charleslucas562.com with an AI query layer planned next.

```
Public F1 APIs (Jolpica + OpenF1)
        ↓ Python pipeline fetches data
PostgreSQL Database (debian-db VM)
        ↓ stores 25,000+ race results from 1950-2026
Flask Web App (debian-app VM)
        ↓ queries database and serves HTML
Apache Reverse Proxy (webster VM)
        ↓ routes traffic to Flask
Cloudflare Tunnel
        ↓ exposes to public internet
f1.charleslucas562.com (live dashboard)
```

This maps directly to real enterprise data engineering:

| Home Lab | Enterprise / Azure Equivalent |
|---|---|
| fetch_data.py | Azure Data Factory Pipeline |
| incremental_load.py | ADF Incremental Trigger |
| PostgreSQL | Azure SQL / Synapse Dedicated Pool |
| SSH tunnel | Azure Private Link / VNet Peering |
| cron schedule | ADF Scheduled Trigger |
| .env file | Azure Key Vault |
| GitHub | Azure DevOps |
| Python psycopg2 | Synapse Linked Service |
| Flask + gunicorn | Azure App Service (Python) |
| Apache reverse proxy | Azure Application Gateway / Front Door |
| Cloudflare Tunnel | Azure Public IP + DNS |
| Database views | Azure SQL Views / Synapse Views |
| GitHub webhook | Azure DevOps CI/CD Pipeline |
| Dynamic routing | Azure API Management |

---

## Infrastructure Overview

```
Windows Machine (pgAdmin, VSCode)
        ↓ SSH tunnel through RHEL host
RHEL IBM-BASEMENT (192.168.4.5) — Bare Metal Host
        ↓ KVM Hypervisor
        ├── Ubuntu VM — webster (192.168.4.7) — Web Server + Reverse Proxy
        ├── Debian VM — debian-db (192.168.122.236) — Database Server
        │                     └── PostgreSQL 17
        │                           └── f1_data DB
        └── Debian VM — debian-app (192.168.122.100) — Flask App Server
                              └── gunicorn + Flask
                                    └── f1.charleslucas562.com
```

### Why Three VMs?

Separating the web server, app server, and database server is a fundamental
architecture pattern in enterprise systems. Benefits include:

- **Security** — database is not directly exposed to the internet
- **Separation of concerns** — each VM has one job
- **Blast radius** — if Flask crashes it does not affect the database or portfolio site
- **Scalability** — each layer can be scaled or replaced independently
- **Portfolio** — mirrors real production architecture patterns

---

## IBM-BASEMENT — RHEL Host

### Specs
| Property | Value |
|---|---|
| OS | Red Hat Enterprise Linux Server 7.9 (Maipo) |
| Hostname | IBM-BASEMENT |
| IP | 192.168.4.5 |
| RAM | 141 GB |
| Disk | 3.7 TB |
| CPUs | 16 cores |
| Hypervisor | KVM / libvirt |
| Package Manager | yum (RHEL 7 — dnf not available until RHEL 8) |

> **Note:** RHEL 7 reached end of life June 2024. Consider upgrading to
> Rocky Linux 8/9 (free RHEL clone) in the future.

### Key Commands
```bash
# List all VMs
virsh list --all

# Start a VM
virsh start <vm-name>

# Stop a VM gracefully
virsh shutdown <vm-name>

# Force stop a VM (like pulling the power)
virsh destroy <vm-name>

# Get VM IP address
virsh domifaddr <vm-name>

# Connect to VM console (emergency backdoor if SSH is locked)
virsh console <vm-name>

# Escape from console
Ctrl + ]

# Delete a VM definition (keeps disk unless deleted manually)
virsh undefine <vm-name>

# Delete VM disk
rm /var/lib/libvirt/images/<vm-name>.qcow2

# Check available osinfo variants for virt-install
osinfo-query os | grep debian
```

### KVM Network Explained
KVM creates two types of virtual networks:

**virbr0 (Virtual Bridge)**
- A software defined network switch inside the server
- VMs on virbr0 get IPs in the 192.168.122.x range
- VMs can talk to each other freely
- Reaches internet via NAT through the physical NIC
- debian-db and debian-app use this network

**macvtap on eno2**
- Plugs directly into the physical network card
- VM gets a real IP from your home router (192.168.4.x)
- Can talk to any device on your home network
- Cannot talk directly to other macvtap VMs on the same host (Linux limitation)
- webster uses this network

> This is why we need SSH tunnels — the two network types cannot
> communicate directly. webster must tunnel through IBM-BASEMENT
> to reach anything on virbr0.

---

## Debian DB Server Setup

### Specs
| Property | Value |
|---|---|
| OS | Debian 13.4 Trixie |
| Hostname | debian-db |
| IP | 192.168.122.236 (static) |
| RAM | 4 GB |
| Disk | 50 GB |
| Network | virbr0 (KVM internal) |
| Purpose | PostgreSQL Database Server |

### Why Debian?
- Rock solid stability — known for being bulletproof as a server OS
- Lightweight — no bloat, perfect for a VM
- Long support cycles
- Excellent PostgreSQL support
- Free forever — no subscription concerns

### Installation Process

#### 1. Download ISO on RHEL Host
```bash
cd /var/lib/libvirt/images
wget https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/debian-13.4.0-amd64-netinst.iso
```

#### 2. Create VM
```bash
virt-install \
  --name debian-db \
  --ram 4096 \
  --vcpus 2 \
  --disk path=/var/lib/libvirt/images/debian-db.qcow2,size=50 \
  --os-variant debiantesting \
  --network network=default \
  --graphics none \
  --console pty,target_type=serial \
  --location /var/lib/libvirt/images/debian-13.4.0-amd64-netinst.iso \
  --extra-args 'console=ttyS0,115200n8'
```

> **Note:** Use `--os-variant debiantesting` — Debian 13 is not yet in the
> osinfo dictionary on RHEL 7. This is the correct fallback variant.

#### 3. Installer Choices
- **Partitioning:** Separate /var and /srv
  - /var is where PostgreSQL stores its data — giving it a separate
    partition means a full OS disk will not corrupt the database
- **Mirror:** deb.debian.org — United States
- **Software:** SSH server + standard system utilities ONLY (no desktop)
- **GRUB:** Install to /dev/vda

#### 4. First Boot — Firewall FIRST (Critical Lesson Learned)
```bash
# ALWAYS do this before anything else
apt update && apt install -y ufw
ufw allow 22/tcp     # SSH — do this FIRST or you lock yourself out
ufw allow 5432/tcp   # PostgreSQL
ufw enable
```

> **Lesson learned the hard way:** If you enable ufw without allowing port 22
> first you will lock yourself out of SSH. ufw blocks everything by default
> when enabled. You must whitelist ports BEFORE enabling.
> Recovery: use `virsh console debian-db --force` as a backdoor.

#### 5. Install Packages
```bash
apt install -y postgresql postgresql-contrib fastfetch htop tmux fail2ban git curl
```

#### 6. Configure Hostname
```bash
hostnamectl set-hostname debian-db
nano /etc/hosts
# Change: 127.0.1.1  debian-db
```

#### 7. Set Static IP
```bash
nano /etc/network/interfaces
```
```
auto lo
iface lo inet loopback

auto ens3
iface ens3 inet static
    address 192.168.122.236
    netmask 255.255.255.0
    gateway 192.168.122.1
    dns-nameservers 8.8.8.8
```
```bash
systemctl restart networking
```

#### 8. Enable Root SSH Login
```bash
nano /etc/ssh/sshd_config
# Change: PermitRootLogin yes
systemctl restart sshd
```

> **Security note:** Root SSH is disabled by default for good reason.
> Fine for a home lab internal VM but never do this on a public server.

#### 9. Fastfetch on Login
```bash
nano ~/.bashrc
# Add at bottom:
fastfetch
```

#### 10. MOTD (Message of the Day)
```bash
nano /etc/motd
```
```
=========================================
  debian-db — F1 Database Server
  Debian 13 Trixie
  PostgreSQL 17
  Authorized access only
=========================================
```

---

## PostgreSQL Setup

### What is PostgreSQL?
PostgreSQL is a free open source relational database — the same type as
SQL Server at work just a different flavor. Your T-SQL knowledge transfers
well. It maps directly to Azure Database for PostgreSQL in the cloud.

### Version
PostgreSQL 17.9 (Debian 17.9-0+deb13u1)

### Installation
```bash
apt install -y postgresql postgresql-contrib
```

### Configuration

#### Create database and user
```bash
su - postgres
psql
```
```sql
\password postgres                           -- set superuser password
CREATE DATABASE f1_data;                     -- create our database
CREATE USER f1user WITH PASSWORD 'yourpw';   -- create app user
GRANT ALL PRIVILEGES ON DATABASE f1_data TO f1user;
\c f1_data                                   -- connect to f1_data
GRANT ALL ON SCHEMA public TO f1user;        -- grant schema access
\q
```
```bash
exit
```

#### Configure PostgreSQL to listen on all interfaces
```bash
nano /etc/postgresql/17/main/postgresql.conf
```
```
listen_addresses = '*'
```

#### Allow network connections (pg_hba.conf)
pg_hba.conf is PostgreSQL's access control file. It controls who can connect
from where and how they authenticate.
```bash
nano /etc/postgresql/17/main/pg_hba.conf
```
Add at the bottom:
```
host    all    all    192.168.122.0/24    md5
host    all    all    127.0.0.1/32        md5
```
- First line: allows connections from the KVM network
- Second line: allows tunnel connections (they arrive as localhost)

```bash
systemctl restart postgresql
```

### Verify PostgreSQL is Running
```bash
# Check cluster status
pg_lsclusters

# Check service status
systemctl status postgresql@17-main

# Check listening ports
ss -tlnp | grep 5432

# Check logs
tail -20 /var/log/postgresql/postgresql-17-main.log
```

### Connect to PostgreSQL
```bash
psql -h 127.0.0.1 -U f1user -d f1_data
```

### Inside psql
```sql
\l              -- list all databases
\dt             -- list all tables
\d table_name   -- describe a table structure
\c database     -- connect to a database
\q              -- quit
```

> **Important:** Every SQL statement in psql must end with a semicolon ;
> Without it psql waits for more input (prompt shows -# instead of =#)

---

## Ubuntu Web Server

### Specs
| Property | Value |
|---|---|
| OS | Ubuntu 20.04 |
| Hostname | webster |
| IP | 192.168.4.7 (macvtap on eno2) |
| Purpose | Reverse Proxy, Python Pipeline, Cloudflare Tunnel |
| Web Server | Apache |

### Apache Reverse Proxy Configuration

#### Enable Required Modules
```bash
sudo a2enmod proxy proxy_http
sudo systemctl restart apache2
```

#### Virtual Host for F1 Dashboard
```bash
sudo nano /etc/apache2/sites-available/f1-app.conf
```
```apache
<VirtualHost *:80>
    ServerName f1.charleslucas562.com

    ProxyPreserveHost On
    ProxyPass / http://localhost:5000/
    ProxyPassReverse / http://localhost:5000/

    ErrorLog ${APACHE_LOG_DIR}/f1-app-error.log
    CustomLog ${APACHE_LOG_DIR}/f1-app-access.log combined
</VirtualHost>
```
```bash
sudo a2ensite f1-app.conf
sudo systemctl reload apache2
```

> **Note:** ProxyPass points to localhost:5000 not directly to debian-app's IP.
> An SSH tunnel bridges port 5000 from localhost to debian-app.

### Cloudflare Tunnel Configuration

Config lives at `/etc/cloudflared/config.yml`:

```yaml
tunnel: personal-site
credentials-file: /root/.cloudflared/<tunnel-id>.json
ingress:
  - hostname: f1.charleslucas562.com
    service: http://localhost:80
  - hostname: charleslucas562.com
    service: http://localhost:80
  - service: http_status:404
```

> **Important:** More specific hostnames (subdomains) must come before the
> root domain. The final catch-all `http_status:404` is required.
> If you edit this file and introduce duplicate keys, cloudflared will fail
> to start — always verify with `cat` after editing.

```bash
sudo systemctl restart cloudflared
sudo systemctl status cloudflared
```

---

## Flask App Server Setup

### Specs
| Property | Value |
|---|---|
| OS | Debian 13.4 Trixie |
| Hostname | debian-app |
| IP | 192.168.122.100 (static) |
| RAM | 4 GB |
| Disk | 20 GB |
| Network | virbr0 (KVM internal) |
| Purpose | Flask Web Application Server |
| App URL | f1.charleslucas562.com |

### Why a Dedicated VM?
Running Flask on its own VM rather than on webster provides clean separation —
if Flask crashes, Apache and the portfolio site are unaffected. Mirrors real
production architecture where app servers and web servers are separate.

### VM Creation
```bash
virt-install \
  --name debian-app \
  --ram 4096 \
  --vcpus 2 \
  --disk path=/var/lib/libvirt/images/f1-app.qcow2,size=20 \
  --os-variant debiantesting \
  --network network=default \
  --graphics none \
  --console pty,target_type=serial \
  --location /var/lib/libvirt/images/debian-13.4.0-amd64-netinst.iso \
  --extra-args 'console=ttyS0,115200n8 serial'
```

### Static IP Setup
```bash
nano /etc/network/interfaces
```
```
auto lo
iface lo inet loopback

auto ens3
iface ens3 inet static
    address 192.168.122.100
    netmask 255.255.255.0
    gateway 192.168.122.1
    dns-nameservers 8.8.8.8 8.8.4.4
```
```bash
systemctl restart networking
```

### Python and Virtual Environment

#### Install Python
```bash
apt install -y python3 python3-pip python3-venv
```

#### What is a Virtual Environment?
A virtual environment is an isolated box for a project's Python packages.
Instead of installing Flask globally (which can cause version conflicts),
everything the app needs lives inside one folder.

#### Create the Virtual Environment
```bash
mkdir -p /var/www/f1-app
python3 -m venv /var/www/f1-app/venv
source /var/www/f1-app/venv/bin/activate
```

#### Install Packages
```bash
pip install flask gunicorn psycopg2-binary python-dotenv markdown
```

### App Structure
```
/var/www/formula1-db/          <- GitHub repo (cloned here)
├── web/
│   ├── app.py                 <- Flask application
│   └── templates/
│       ├── index.html         <- Main dashboard
│       ├── race.html          <- Race history page
│       └── docs.html          <- Documentation page
/var/www/f1-app/
├── .env                       <- database credentials (never commit)
└── venv/                      <- Python virtual environment
```

### .env on debian-app
```
DB_HOST=192.168.122.236
DB_PORT=5432
DB_NAME=f1_data
DB_USER=f1user
DB_PASSWORD=yourpassword
WEBHOOK_SECRET=yoursecret
```

```bash
chown f1app:f1app /var/www/f1-app/.env
chmod 600 /var/www/f1-app/.env
```

> **Critical:** Never commit .env to GitHub. It contains credentials.
> The WEBHOOK_SECRET should be a long random hex string generated with:
> `python3 -c "import secrets; print(secrets.token_hex(32))"`

### Dedicated Service Account
Running web apps as root is a security risk. A dedicated service account
limits the blast radius if the app is ever compromised.

```bash
# Create a system account with no login shell and no home directory
useradd --system --no-create-home --shell /usr/sbin/nologin f1app

# Create a home directory for git config
mkdir -p /home/f1app
chown f1app:f1app /home/f1app

# Give it ownership of the app directory
chown -R clucas:f1app /var/www/formula1-db
chmod -R 775 /var/www/formula1-db
```

### Git Shared Repository (Prevents Permission Issues)
```bash
cd /var/www/formula1-db
git config core.sharedRepository group
```

This ensures git always creates new objects with group write permissions
so the f1app user can always pull without permission errors during webhook deploys.

### gunicorn
gunicorn is a production WSGI server that runs multiple worker processes
concurrently. Flask's built-in dev server handles one request at a time —
gunicorn runs a restaurant kitchen with multiple cooks.

Test manually:
```bash
source /var/www/f1-app/venv/bin/activate
gunicorn --workers 3 --bind 0.0.0.0:5000 --chdir /var/www/formula1-db/web app:app
```

### systemd Service
systemd keeps gunicorn running automatically and restarts it if it crashes.

```bash
nano /etc/systemd/system/f1-app.service
```
```ini
[Unit]
Description=F1 Dashboard Flask App
After=network.target

[Service]
User=f1app
WorkingDirectory=/var/www/formula1-db/web
Environment="PATH=/var/www/f1-app/venv/bin"
ExecStart=/var/www/f1-app/venv/bin/gunicorn --workers 3 --bind 0.0.0.0:5000 app:app
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable f1-app
systemctl start f1-app
systemctl status f1-app
```

#### Service File Explained
- `After=network.target` — wait for network before starting
- `User=f1app` — run as dedicated service account, not root
- `Environment="PATH=..."` — use the virtual environment's Python
- `Restart=always` — auto-restart if the process crashes
- `WantedBy=multi-user.target` — start during normal system boot

### sudoers for f1app
```bash
nano /etc/sudoers.d/f1app
```
```
f1app ALL=(ALL) NOPASSWD: /bin/systemctl restart f1-app
```

This allows the webhook to restart the service without a password prompt.
Limited to only this one command — not broad sudo access.

### Key systemctl Commands
```bash
systemctl start f1-app      # start the service
systemctl stop f1-app       # stop the service
systemctl restart f1-app    # restart (use after code changes)
systemctl status f1-app     # check if running
systemctl enable f1-app     # start on boot
journalctl -u f1-app -n 50 --no-pager   # view logs
```

---

## SSH Tunnel Setup

### Why Do We Need Tunnels?
webster (macvtap, 192.168.4.x) cannot reach virbr0 VMs (192.168.122.x)
directly. SSH tunnels through IBM-BASEMENT bridge the gap.

### Tunnel 1 — webster to debian-db (PostgreSQL :5432)
```
webster (192.168.4.7)
    ↓ SSH to IBM-BASEMENT
IBM-BASEMENT (192.168.4.5)
    ↓ forwards through virbr0
debian-db (192.168.122.236:5432)
```
Python sees PostgreSQL as localhost:5432 — the tunnel is transparent.

### Tunnel 2 — webster to debian-app (Flask :5000)
```
webster (192.168.4.7)
    ↓ SSH to IBM-BASEMENT
IBM-BASEMENT (192.168.4.5)
    ↓ forwards through virbr0
debian-app (192.168.122.100:5000)
```
Apache proxies to localhost:5000 which the tunnel maps to debian-app.

### Persistent Tunnels (crontab on webster)
```bash
@reboot sleep 30 && autossh -M 0 -f -N -L 5432:192.168.122.236:5432 root@192.168.4.5
@reboot sleep 30 && autossh -M 0 -f -N -L 5000:192.168.122.100:5000 root@192.168.4.5
```

autossh monitors tunnels and automatically restarts them if they drop.
sleep 30 gives the network time to come up before connecting on reboot.

### SSH Keys (no password prompts)
```bash
ssh-keygen -t ed25519 -C "webster-to-rhel"
ssh-copy-id root@192.168.4.5
```

### Verify Tunnels are Running
```bash
ps aux | grep autossh
ss -tlnp | grep 5432
ss -tlnp | grep 5000
```

### Note on debian-app to debian-db
Both are on virbr0 so they reach each other directly — no tunnel needed.
Flask connects to PostgreSQL at 192.168.122.236 directly.

---

## Python Pipeline

### db_utils.py — Shared Utilities
- **get_connection()** — PostgreSQL connection from .env credentials
- **upsert()** — ON CONFLICT DO UPDATE — insert or update, never duplicate
- **setup_logging()** — logs to both file and console

### setup_db.py — Table Creation (run once)
```bash
cd ~/formula1-db
python3 pipeline/setup_db.py
```

### fetch_data.py — Full Historical Load (run once)
Loads all F1 data from 1950 to present. Takes 1-2 hours due to API rate
limiting (200 requests/hour max).

Load order matters — parent tables before child tables:
```
circuits → races → race_results
drivers → race_results
constructors → race_results
seasons → races → driver_standings
```

### incremental_load.py — Weekly Updates
Runs automatically every Monday at 6am. Pulls only the latest race.
Also supports manual backfill with season and round arguments:

```bash
# Load latest race automatically
python3 pipeline/incremental_load.py

# Backfill a specific race (e.g. Australia 2026)
python3 pipeline/incremental_load.py 2026 1
```

The manual override was added because the automated pipeline only fetches
the current latest race — any races missed before the pipeline was set up
require manual backfill.

---

## Database Schema

### Tables
| Table | Purpose | Key Columns |
|---|---|---|
| seasons | F1 seasons | season_year, total_rounds |
| circuits | Race tracks | circuit_id, name, country, lat, lng |
| drivers | Driver info | driver_id, first_name, last_name, nationality |
| constructors | Teams | constructor_id, name, nationality |
| races | Race calendar | race_id, season_year, round, circuit_id |
| race_results | Finishing positions | race_id, driver_id, finish_position, points |
| qualifying_results | Q1/Q2/Q3 times | race_id, driver_id, q1_time, q2_time, q3_time |
| sprint_results | Sprint races | race_id, driver_id, finish_position, points |
| driver_standings | Championship table | season_year, round, driver_id, points, position |
| constructor_standings | Team championship | season_year, round, constructor_id, points |
| lap_times | Individual laps | race_id, driver_id, lap_number, lap_time |
| pit_stops | Pit stop data | race_id, driver_id, stop_number, lap, duration |

### Unique Constraints
| Table | Unique Constraint |
|---|---|
| races | season_year, round |
| race_results | race_id, driver_id |
| qualifying_results | race_id, driver_id |
| sprint_results | race_id, driver_id |
| driver_standings | season_year, round, driver_id |
| constructor_standings | season_year, round, constructor_id |

### Data Sources
- **Jolpica API** (https://api.jolpi.ca/ergast/) — Historical + current. No API key required. Rate limit: 200 requests/hour.
- **OpenF1 API** (https://openf1.org/) — Live timing (planned)

### Data Loaded
- 76 seasons (1950-2026)
- 864+ drivers
- 211+ constructors
- 1,100+ races
- 25,873+ race results

---

## Database Views

Views are saved queries in PostgreSQL. Flask queries them with simple
SELECT statements — the database handles all the JOIN complexity.
This maps directly to Azure Synapse views and SQL Server views.

### current_standings
Current season driver championship at the latest round.
Uses EXTRACT(YEAR FROM CURRENT_DATE) — automatically reflects current season.

```sql
CREATE OR REPLACE VIEW current_standings AS
SELECT
    ds.position,
    d.first_name,
    d.last_name,
    ds.points,
    ds.wins
FROM driver_standings ds
JOIN drivers d ON ds.driver_id = d.driver_id
WHERE ds.season_year = EXTRACT(YEAR FROM CURRENT_DATE)
AND ds.round = (
    SELECT MAX(round) FROM driver_standings
    WHERE season_year = EXTRACT(YEAR FROM CURRENT_DATE)
)
ORDER BY ds.position;
```

### last_race_results
Full finishing order of the most recently completed race.

```sql
CREATE OR REPLACE VIEW last_race_results AS
SELECT
    r.race_name,
    r.date,
    d.first_name,
    d.last_name,
    rr.finish_position,
    rr.points
FROM race_results rr
JOIN drivers d ON rr.driver_id = d.driver_id
JOIN races r ON rr.race_id = r.race_id
WHERE r.race_id = (
    SELECT race_id FROM races
    WHERE season_year = EXTRACT(YEAR FROM CURRENT_DATE)
    ORDER BY round DESC LIMIT 1
)
ORDER BY rr.finish_position;
```

### current_constructor_standings
Current season constructor championship at the latest round.

```sql
CREATE OR REPLACE VIEW current_constructor_standings AS
SELECT
    cs.position,
    c.name,
    c.nationality,
    cs.points,
    cs.wins
FROM constructor_standings cs
JOIN constructors c ON cs.constructor_id = c.constructor_id
WHERE cs.season_year = EXTRACT(YEAR FROM CURRENT_DATE)
AND cs.round = (
    SELECT MAX(round) FROM constructor_standings
    WHERE season_year = EXTRACT(YEAR FROM CURRENT_DATE)
)
ORDER BY cs.position;
```

### race_results_detail
Full race results with driver, constructor, grid and finish position.
Used by the race history page.

```sql
CREATE OR REPLACE VIEW race_results_detail AS
SELECT
    r.season_year,
    r.round,
    r.race_name,
    r.date,
    ci.name as circuit_name,
    ci.country,
    d.first_name,
    d.last_name,
    c.name as constructor,
    rr.grid_position,
    rr.finish_position,
    rr.points,
    rr.status
FROM race_results rr
JOIN drivers d ON rr.driver_id = d.driver_id
JOIN constructors c ON rr.constructor_id = c.constructor_id
JOIN races r ON rr.race_id = r.race_id
JOIN circuits ci ON r.circuit_id = ci.circuit_id
ORDER BY rr.finish_position;
```

### season_races
All races in the current season for the race selector on the homepage.

```sql
CREATE OR REPLACE VIEW season_races AS
SELECT
    season_year,
    round,
    race_name,
    date
FROM races
WHERE season_year = EXTRACT(YEAR FROM CURRENT_DATE)
ORDER BY round;
```

---

## Web Dashboard

### Pages
| URL | Template | Purpose |
|---|---|---|
| / | index.html | Main dashboard — last race, standings, race selector |
| /race/<season>/<round> | race.html | Individual race results with grid vs finish |
| /docs | docs.html | Live project documentation rendered from markdown |

### Dashboard Section Order
1. ASCII F1 logo header
2. Last race results
3. Driver standings
4. Constructor standings
5. Season race selector (links to race history pages)
6. Footer

### Dynamic Routing
Flask captures URL segments as variables:

```python
@app.route('/race/<int:season>/<int:round_num>')
def race(season, round_num):
    # season and round_num come directly from the URL
    # /race/2026/3 sets season=2026, round_num=3
```

### Race History Page Features
- Full finishing order with points
- Grid position vs finish position with +/- places gained/lost (color coded)
- Constructor for each driver
- Race name, circuit, country, date header
- Back to dashboard link

### Markdown Documentation Page
The /docs route reads DOCUMENTATION.md from the repo root and renders it live.

```python
@app.route('/docs')
def docs():
    doc_path = Path(__file__).parent.parent / 'DOCUMENTATION.md'
    with open(doc_path, 'r') as f:
        content = f.read()
    html_content = markdown.markdown(content, extensions=['tables', 'fenced_code'])
    return render_template('docs.html', content=html_content)
```

### Dashboard Styling
Dark terminal aesthetic — black background (#111111), F1 red accents (#e10600),
monospace Courier New font throughout. ASCII art F1 logo in the header.

---

## GitHub Webhook — Auto Deploy

Every git push to GitHub automatically deploys to debian-app within seconds.

### How It Works
```
git push on Windows machine
        ↓
GitHub sends POST to f1.charleslucas562.com/webhook
        ↓
Flask verifies HMAC SHA-256 signature
        ↓
git pull on /var/www/formula1-db
        ↓
systemctl restart f1-app (background via Popen)
        ↓
New code is live
```

### Webhook Route in app.py
```python
@app.route('/webhook', methods=['POST'])
def webhook():
    secret = os.getenv("WEBHOOK_SECRET").encode()
    signature = request.headers.get("X-Hub-Signature-256", "")
    body = request.get_data()

    expected = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected, signature):
        abort(403)

    subprocess.run(["/usr/bin/git", "-C", "/var/www/formula1-db", "pull"], check=True)
    subprocess.Popen(["/usr/bin/sudo", "/bin/systemctl", "restart", "f1-app"])

    return "Deployed", 200
```

### Why Popen Instead of run for the Restart?
`subprocess.run` waits for the command to finish. `systemctl restart f1-app`
kills the very gunicorn worker running the webhook — so it would die before
returning a response. `subprocess.Popen` fires and forgets, letting Flask
return "Deployed 200" before the process restarts.

### Why Full Paths for git and sudo?
When f1app runs via gunicorn as a service, its PATH environment is minimal.
`git` and `sudo` are not in the PATH — you must use `/usr/bin/git` and
`/usr/bin/sudo` explicitly.

### Security Notes
- HMAC SHA-256 signature verification prevents unauthorized webhook calls
- WEBHOOK_SECRET stored in .env — never committed to GitHub
- git core.sharedRepository = group prevents permission issues on pull
- f1app sudoers rule limited to only `systemctl restart f1-app`
- Real attack surface: if WEBHOOK_SECRET is leaked, attacker can trigger deploys
- Mitigated by: secret is in .env with chmod 600, never in version control

### GitHub Configuration
Settings → Webhooks → Add webhook:
- **Payload URL:** https://f1.charleslucas562.com/webhook
- **Content type:** application/json
- **Secret:** your WEBHOOK_SECRET value
- **Events:** Just the push event

---

## Data Quality — Duplicate Prevention

### The Problem
Duplicate records were inserted because upsert checked conflict on SERIAL
primary keys (always unique) instead of business key combinations.

### Fix
```python
# Wrong — SERIAL id is always unique, never conflicts
upsert(conn, "race_results", {...}, "result_id")

# Correct — checks the real unique business combination
upsert(conn, "race_results", {...}, "race_id, driver_id")
```

### Cleaning Existing Duplicates
Child tables must be cleaned before parent tables (foreign key order):
```sql
BEGIN;
DELETE FROM race_results a
USING race_results b
WHERE a.result_id < b.result_id
AND a.race_id = b.race_id
AND a.driver_id = b.driver_id;
COMMIT;
```

### Duplicate Check Query
Run anytime to verify data quality:
```sql
SELECT 'race_results' as table_name, COUNT(*) as dupes
FROM race_results a
INNER JOIN race_results b ON a.race_id = b.race_id
AND a.driver_id = b.driver_id AND a.result_id < b.result_id
UNION ALL
SELECT 'qualifying_results', COUNT(*)
FROM qualifying_results a
INNER JOIN qualifying_results b ON a.race_id = b.race_id
AND a.driver_id = b.driver_id AND a.qualifying_id < b.qualifying_id
UNION ALL
SELECT 'sprint_results', COUNT(*)
FROM sprint_results a
INNER JOIN sprint_results b ON a.race_id = b.race_id
AND a.driver_id = b.driver_id AND a.sprint_id < b.sprint_id
UNION ALL
SELECT 'races', COUNT(*)
FROM races a
INNER JOIN races b ON a.season_year = b.season_year
AND a.round = b.round AND a.race_id < b.race_id;
```

---

## GitHub Version Control

### Repository
- **URL:** github.com/clucas56/formula1-db
- **Visibility:** Private (make public when ready as portfolio piece)

### Setup
```bash
git config --global user.email "your@email.com"
git config --global user.name "clucas56"
git config --global credential.helper store
git clone https://clucas56:<personal-access-token>@github.com/clucas56/formula1-db.git
```

> Use a Personal Access Token not your password. Generate at:
> github.com → Settings → Developer settings → Personal access tokens

### Daily Workflow
```bash
git add .
git commit -m "describe what you changed"
git push
```

### What .gitignore Excludes
```
.env        <- credentials — never commit
logs/       <- log files
__pycache__ <- Python compiled files
*.pyc
```

---

## Firewall Rules

### Critical Rule — Allow SSH Before Enabling
```bash
ufw allow 22/tcp     # SSH — ALWAYS first
ufw allow 5432/tcp   # PostgreSQL
ufw enable           # Now enable — SSH is already whitelisted
```

### Debian DB Server Rules
```bash
ufw allow 22/tcp
ufw allow 5432/tcp
ufw allow from 192.168.122.0/24 to any port 5432
ufw enable
```

### Verify
```bash
ufw status verbose
```

---

## Network Topology

```
Internet
    ↓
Cloudflare Network
    ↓ Cloudflare Tunnel
Home Router (192.168.4.1)
    ↓
IBM-BASEMENT RHEL Host (192.168.4.5)
    ├── Physical NIC: eno2 -> home network (192.168.4.x)
    │
    ├── KVM Hypervisor
    │     ├── virbr0 virtual bridge (192.168.122.x)
    │     │     ├── debian-db (192.168.122.236)
    │     │     │     └── PostgreSQL :5432
    │     │     └── debian-app (192.168.122.100)
    │     │           └── gunicorn + Flask :5000
    │     │
    │     └── macvtap on eno2
    │           └── webster (192.168.4.7)
    │                 ├── Apache :80 (reverse proxy)
    │                 ├── cloudflared (Cloudflare Tunnel)
    │                 ├── SSH tunnel -> debian-db :5432
    │                 └── SSH tunnel -> debian-app :5000
    │
    └── Tunnels bridge the macvtap/virbr0 network gap

Request flow for f1.charleslucas562.com:
Browser -> Cloudflare -> cloudflared -> Apache -> SSH tunnel -> Flask -> PostgreSQL
```

---

## Incremental Load Pipeline

### How it Works
```
1. Fetch latest completed race from Jolpica API
2. Check if race already exists in database
3. If new — insert race and season details
4. Load race results, qualifying, sprint, standings
5. All steps use upsert — idempotent and safe to rerun
```

### Idempotency
Running the script multiple times produces the same result — no duplicates.
If the script fails halfway through you can safely rerun it.

### Manual Backfill
```bash
python3 pipeline/incremental_load.py 2026 1
```

Pass season and round as command line arguments to load any specific race.
Used to backfill Australia 2026 Round 1 which was missed by the automated pipeline.

### Log Location
```
~/formula1-db/logs/incremental/incremental_load_YYYYMMDD_HHMMSS.log
```

---

## Cron Jobs

### Cron Schedule Syntax
```
* * * * * command
| | | | |
| | | | └── Day of week (0=Sunday, 6=Saturday)
| | | └──── Month (1-12)
| | └────── Day of month (1-31)
| └──────── Hour (0-23)
└────────── Minute (0-59)
```

### View and Edit
```bash
crontab -l    # view current jobs
crontab -e    # edit jobs
```

### Current Schedule (webster)
| Schedule | Command | Purpose |
|---|---|---|
| Every Monday 6am | python3 pipeline/incremental_load.py | Load latest race data |
| On reboot | autossh tunnel :5432 | Restart SSH tunnel to debian-db |
| On reboot | autossh tunnel :5000 | Restart SSH tunnel to debian-app |

```bash
@reboot sleep 30 && autossh -M 0 -f -N -L 5432:192.168.122.236:5432 root@192.168.4.5
@reboot sleep 30 && autossh -M 0 -f -N -L 5000:192.168.122.100:5000 root@192.168.4.5
0 6 * * 1 cd /home/clucas/formula1-db && python3 pipeline/incremental_load.py
```

> Monday at 6am — most F1 races happen Sunday, data is in the API within hours.

---

## How It All Connects — End to End Flow

### Web Request Flow
```
1. Browser requests f1.charleslucas562.com
2. Cloudflare receives and routes through tunnel
3. cloudflared on webster passes to Apache on localhost:80
4. Apache virtual host matches f1.charleslucas562.com
5. Apache proxies through SSH tunnel to localhost:5000
6. SSH tunnel forwards to gunicorn on debian-app:5000
7. gunicorn passes to Flask worker process
8. Flask queries PostgreSQL views on debian-db directly
9. PostgreSQL returns data
10. Flask renders HTML template
11. Response travels back through the chain to the browser
```

### Auto Deploy Flow
```
1. Code change made in VSCode on Windows
2. git push to GitHub
3. GitHub fires webhook POST to f1.charleslucas562.com/webhook
4. Flask verifies HMAC signature
5. git pull on /var/www/formula1-db
6. systemctl restart f1-app (background via Popen)
7. New code is live within seconds
```

### Weekly Data Flow (every Monday 6am)
```
1. Cron triggers incremental_load.py on webster
2. autossh keeps SSH tunnels alive
3. Python connects to PostgreSQL via tunnel (looks like localhost:5432)
4. Script fetches latest race from Jolpica API
5. Upserts race, results, qualifying, standings
6. Log written to logs/incremental/
```

---

## Key Concepts Learned

### Linux / Server Admin
- **KVM/libvirt** — Linux hypervisor for running virtual machines
- **virsh** — command line tool to manage KVM VMs
- **virbr0 vs macvtap** — two types of virtual networking with different tradeoffs
- **ufw** — Linux firewall whitelist based everything blocked by default
- **cron** — Linux task scheduler for automated jobs
- **systemctl** — manages Linux services (start, stop, status, enable)
- **systemd service files** — define how a service runs, who runs it, when it starts
- **Static IP** — prevents VM IP from changing on reboot
- **SSH keys** — passwordless authentication using public/private key pairs
- **autossh** — keeps SSH tunnels alive automatically
- **chmod 600** — file readable/writable by owner only, used for credential files
- **Service accounts** — dedicated non-login users for running services securely
- **git core.sharedRepository** — group write permissions on git objects

### Networking
- **SSH tunnel** — routes traffic through an intermediate server
- **Port forwarding** — `-L local_port:remote_host:remote_port`
- **NAT** — how virbr0 VMs reach the internet through the host
- **Firewall whitelist** — block everything allow only what you need
- **Reverse proxy** — Apache forwarding requests to Flask
- **Cloudflare Tunnel** — exposes local services to internet without open ports

### Web / Flask
- **Flask** — Python micro web framework, routes HTTP requests to functions
- **gunicorn** — production WSGI server, runs multiple Flask worker processes
- **WSGI** — standard interface between Python web apps and web servers
- **Virtual environment** — isolated Python package environment per project
- **Jinja2 templating** — Flask's HTML template engine with {{ }} syntax
- **Routes** — @app.route decorators map URLs to Python functions
- **Dynamic routing** — URL segments captured as variables e.g. /race/<int:season>/<int:round>
- **render_template** — passes data from Python to HTML templates
- **subprocess.Popen vs run** — Popen fires and forgets, run waits for completion
- **markdown library** — converts markdown files to HTML for the docs page

### Security / DevOps
- **HMAC SHA-256** — cryptographic signature verification for webhooks
- **Webhook secret** — shared secret between GitHub and Flask to verify requests
- **sudoers** — grants specific commands to specific users without full sudo
- **Service account** — minimal permission user for running services
- **Popen for self-restart** — fire and forget so Flask can respond before dying
- **git sharedRepository** — group permission setting prevents webhook pull failures

### PostgreSQL / Databases
- **Relational schema** — tables linked by foreign keys
- **Third normal form (3NF)** — store each fact once reference by ID
- **Unique constraint** — prevents duplicate combinations
- **pg_hba.conf** — PostgreSQL access control file
- **Transactions** — BEGIN/COMMIT/ROLLBACK for safe bulk operations
- **ON CONFLICT DO UPDATE** — upsert syntax in PostgreSQL
- **Views** — saved queries in the database, simplify application code
- **EXTRACT(YEAR FROM CURRENT_DATE)** — dynamic current year in SQL

### Python Data Engineering
- **psycopg2** — Python PostgreSQL connector
- **python-dotenv** — loads .env files into environment variables
- **ETL pattern** — Extract (API) Transform (clean/map) Load (database)
- **Upsert** — ON CONFLICT DO UPDATE — insert or update never duplicate
- **Idempotency** — running multiple times produces the same result
- **sys.argv** — command line arguments in Python scripts
- **subprocess** — running shell commands from Python

### Git / DevOps
- **Personal access token** — GitHub authentication not password
- **Webhook** — GitHub HTTP callback on push events
- **CI/CD pipeline** — automated deploy on every git push
- **.gitignore** — prevents sensitive files from being committed

---

## Troubleshooting

### SSH into VMs from RHEL Host
```bash
ssh root@192.168.122.236    # debian-db
ssh root@192.168.122.100    # debian-app
ssh clucas@192.168.4.7      # webster
```

### SSH locked out of VM
```bash
virsh console debian-db --force
# Hit Enter several times
ufw allow 22/tcp
ufw reload
```

### Flask service not starting
```bash
systemctl status f1-app
journalctl -u f1-app -n 50 --no-pager
```
Common causes:
- .env file not found or wrong permissions
- venv path wrong in service file
- Port 5000 already in use
- f1app user cannot access /var/www/formula1-db

### f1.charleslucas562.com not loading
Work through the chain:
```bash
systemctl status f1-app                                     # Flask running?
ps aux | grep autossh                                       # Tunnels alive?
ss -tlnp | grep 5000                                        # Port bound?
curl http://localhost:5000                                  # Tunnel works on webster?
curl -H "Host: f1.charleslucas562.com" http://localhost     # Apache proxying?
systemctl status cloudflared                                # Cloudflare tunnel up?
tail -50 /var/log/apache2/f1-app-error.log                  # Apache errors?
```

### Webhook deploy failing
```bash
sudo journalctl -u f1-app -n 30 --no-pager
```
Common causes and fixes:
- **Git permission error on .git/objects:**
  ```bash
  sudo chown -R clucas:f1app /var/www/formula1-db
  sudo chmod -R 775 /var/www/formula1-db
  git config core.sharedRepository group
  ```
- **FileNotFoundError for git or sudo:** Use full paths `/usr/bin/git` and `/usr/bin/sudo`
- **SIGTERM on restart:** Use `subprocess.Popen` not `subprocess.run` for systemctl restart
- **500 on signature check:** Verify WEBHOOK_SECRET matches what GitHub has configured

### cloudflared fails to start (YAML error)
```bash
cat /etc/cloudflared/config.yml   # check for duplicate keys
nano /etc/cloudflared/config.yml  # rewrite cleanly if needed
systemctl restart cloudflared
systemctl status cloudflared
```

### PostgreSQL not accepting connections
```bash
pg_lsclusters
systemctl status postgresql@17-main
ss -tlnp | grep 5432
tail -50 /var/log/postgresql/postgresql-17-main.log
cat /etc/postgresql/17/main/pg_hba.conf | tail -10
```

### SSH tunnel drops or port already in use
```bash
pkill -f "ssh -L 5432"
pkill -f "ssh -L 5000"
ss -tlnp | grep 5432
ss -tlnp | grep 5000
```

### VM has duplicate IPs
```bash
ip a show ens3
ip addr del <unwanted-ip>/24 dev ens3
# Set static IP in /etc/network/interfaces to prevent recurrence
```

### Git authentication failing (403)
```bash
git remote set-url origin https://clucas56:<token>@github.com/clucas56/formula1-db.git
git push -u origin main
```

---

## Next Steps

### Immediate
- [x] GitHub webhook for auto-deploy
- [x] Dashboard styling
- [x] Constructor standings
- [x] Race history page with dynamic routing
- [x] Documentation page at /docs
- [ ] Add pit stop data (endpoint needs investigation)

### AI Layer
- [ ] Build query_engine.py using Claude API
- [ ] Text-to-SQL — ask questions in plain English against the F1 database
- [ ] Migrate to Azure OpenAI once AZ-900 certified

### Data Enhancements
- [ ] Add lap times via OpenF1 API (live during race weekends)
- [ ] Historical data validation queries

### Infrastructure
- [ ] Make GitHub repo public as portfolio piece
- [ ] Consider upgrading RHEL 7 host to Rocky Linux 8/9

---

## Azure Equivalent Architecture

| Home Lab Component | Azure Service |
|---|---|
| Debian VM + PostgreSQL | Azure Database for PostgreSQL Flexible Server |
| debian-app + Flask + gunicorn | Azure App Service (Python) |
| Apache reverse proxy | Azure Application Gateway / Front Door |
| Cloudflare Tunnel | Azure Public IP + DNS Zone |
| Python pipeline scripts | Azure Data Factory Pipelines |
| Cron schedule | ADF Scheduled Trigger |
| SSH tunnel | Azure Private Link / VNet Peering |
| .env credentials | Azure Key Vault |
| GitHub repo + webhook | Azure DevOps / GitHub Actions |
| Logs folder | Azure Monitor / Log Analytics |
| Claude API query engine | Azure OpenAI Service |
| pgAdmin | Azure Data Studio |
| systemd service | Azure App Service always-on setting |
| Database views | Azure SQL Views / Synapse Views |
| f1app service account | Azure Managed Identity |
| HMAC webhook verification | Azure API Management + API Key |
| Dynamic Flask routes | Azure API Management routing |

This project is a proof of concept for a real Azure data platform.
Everything built here maps 1:1 to enterprise Azure architecture making it
a strong portfolio piece for DP-100, AI-102, and data engineering roles.