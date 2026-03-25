# F1 Data Platform — Project Documentation

**Author:** clucas56  
**Last Updated:** March 2026  
**Repository:** github.com/clucas56/formula1-db

---

## Table of Contents

1. [What You Built — The Big Picture](#what-you-built--the-big-picture)
2. [Infrastructure Overview](#infrastructure-overview)
3. [IBM-BASEMENT — RHEL Host](#ibm-basement--rhel-host)
4. [Debian DB Server Setup](#debian-db-server-setup)
5. [PostgreSQL Setup](#postgresql-setup)
6. [Ubuntu Web Server](#ubuntu-web-server)
7. [SSH Tunnel Setup](#ssh-tunnel-setup)
8. [Python Pipeline](#python-pipeline)
9. [Database Schema](#database-schema)
10. [Data Quality — Duplicate Prevention](#data-quality--duplicate-prevention)
11. [GitHub Version Control](#github-version-control)
12. [Firewall Rules](#firewall-rules)
13. [Network Topology](#network-topology)
14. [Incremental Load Pipeline](#incremental-load-pipeline)
15. [Cron Jobs](#cron-jobs)
16. [How It All Connects — End to End Flow](#how-it-all-connects--end-to-end-flow)
17. [Key Concepts Learned](#key-concepts-learned)
18. [Troubleshooting](#troubleshooting)
19. [Next Steps](#next-steps)
20. [Azure Equivalent Architecture](#azure-equivalent-architecture)

---

## What You Built — The Big Picture

This project is a full end to end F1 data platform built entirely on home lab
infrastructure. It pulls historical and live Formula 1 data from public APIs,
stores it in a relational database, and will eventually serve it through a web
dashboard with an AI query layer.

```
Public F1 APIs (Jolpica + OpenF1)
        ↓ Python pipeline fetches data
PostgreSQL Database (debian-db VM)
        ↓ stores 25,000+ race results from 1950-2026
Ubuntu Web Server (webster VM)
        ↓ will serve dashboard and AI query layer
Your Browser (pgAdmin, future web dashboard)
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

---

## Infrastructure Overview

```
Windows Machine (pgAdmin, VSCode)
        ↓ SSH tunnel through RHEL host
RHEL IBM-BASEMENT (192.168.4.5) — Bare Metal Host
        ↓ KVM Hypervisor
        ├── Ubuntu VM — webster (192.168.4.7) — Web Server
        └── Debian VM — debian-db (192.168.122.236) — Database Server
                              ↓
                        PostgreSQL 17
                              ↓
                          f1_data DB
```

### Why Two VMs?

Separating the web server and database server is a fundamental architecture
pattern in enterprise systems. Benefits include:

- **Security** — database is not directly exposed to the internet
- **Performance** — each server can be tuned for its specific workload
- **Scalability** — you can scale them independently
- **Stability** — a web server crash does not affect the database

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
```

### KVM Network Explained
KVM creates two types of virtual networks:

**virbr0 (Virtual Bridge)**
- A software defined network switch inside the server
- VMs on virbr0 get IPs in the 192.168.122.x range
- VMs can talk to each other freely
- Reaches internet via NAT through the physical NIC
- debian-db uses this network

**macvtap on eno2**
- Plugs directly into the physical network card
- VM gets a real IP from your home router (192.168.4.x)
- Can talk to any device on your home network
- Cannot talk directly to other macvtap VMs on the same host (Linux limitation)
- ubuntu/webster uses this network

> This is why we need an SSH tunnel — the two VMs are on different network
> types and cannot communicate directly.

---

## Debian DB Server Setup

### Specs
| Property | Value |
|---|---|
| OS | Debian 13.3 Trixie |
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
wget https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/debian-13.3.0-amd64-netinst.iso
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
  --location /var/lib/libvirt/images/debian-13.3.0-amd64-netinst.iso \
  --extra-args 'console=ttyS0,115200n8'
```

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
Why static? DHCP assigns IPs dynamically — your VM could get a different IP
after a reboot breaking all your connection strings and tunnel configs.
Static IP means it is always the same.

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
Shown every time you SSH in — good for identifying which server you are on.
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
well. It is the industry standard for Python data projects and maps directly
to Azure Database for PostgreSQL in the cloud.

### Version
PostgreSQL 17.9 (Debian 17.9-0+deb13u1)

### Installation
```bash
apt install -y postgresql postgresql-contrib
```

### Configuration

#### Create database and user
```bash
su - postgres    # switch to the postgres system user
psql             # open the PostgreSQL shell
```
```sql
\password postgres                           -- set superuser password
CREATE DATABASE f1_data;                     -- create our database
CREATE USER f1user WITH PASSWORD 'yourpw';   -- create app user
GRANT ALL PRIVILEGES ON DATABASE f1_data TO f1user;
\c f1_data                                   -- connect to f1_data
GRANT ALL ON SCHEMA public TO f1user;        -- grant schema access
\q                                           -- quit psql
```
```bash
exit    -- return to root
```

#### Configure PostgreSQL to listen on all interfaces
By default PostgreSQL only listens on localhost — nothing outside the VM
can connect. This opens it up to the network.
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

#### Restart PostgreSQL
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
| Purpose | Web Server, Python Pipeline |
| Web Server | Apache |

### Python Environment
```bash
pip3 install psycopg2-binary python-dotenv requests
sudo apt install -y postgresql-client
```

### Project Location
```
/home/clucas/formula1-db/
├── .env                         <- credentials (hidden, never commit)
├── .gitignore
├── README.md
├── DOCUMENTATION.md
├── database/
│   └── schema.sql               <- table definitions
├── pipeline/
│   ├── db_utils.py              <- shared DB connection and logging
│   ├── setup_db.py              <- creates tables (run once)
│   ├── fetch_data.py            <- full historical load (run once)
│   ├── incremental_load.py      <- weekly race updates (automated)
│   └── test_fetch.py            <- connection and API tests
├── logs/
│   ├── fetch/                   <- logs from fetch_data.py
│   └── incremental/             <- logs from incremental_load.py
├── web/
│   └── index.html               <- dashboard frontend (planned)
└── ai/
    └── query_engine.py          <- AI text-to-SQL layer (planned)
```

### .env File
The .env file stores sensitive credentials. It starts with a dot making it
a hidden file in Linux. Use `ls -la` to see hidden files.

```
DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=f1_data
DB_USER=f1user
DB_PASSWORD=yourpassword
```

> **Critical:** .env is listed in .gitignore and must NEVER be committed
> to GitHub. Credentials in a public repo is a serious security issue.
> Always use environment variables or a secrets manager for credentials.

---

## SSH Tunnel Setup

### Why Do We Need a Tunnel?
The Ubuntu web server (192.168.4.7) and Debian database server (192.168.122.236)
are on different networks. macvtap VMs cannot communicate directly with each
other on the same host — it is a Linux networking limitation by design.

The solution is an SSH tunnel through the RHEL host which can reach both networks.

### How it Works
```
Ubuntu (192.168.4.7)
    ↓ opens SSH connection to RHEL
RHEL IBM-BASEMENT (192.168.4.5)
    ↓ forwards traffic through virbr0
Debian DB (192.168.122.236:5432)
```

From Python's perspective it looks like PostgreSQL is running locally on
Ubuntu at 127.0.0.1:5432 — the tunnel handles the routing transparently.

### Start the Tunnel Manually
```bash
ssh -L 5432:192.168.122.236:5432 root@192.168.4.5 -N -f
```
- `-L 5432` — listen on local port 5432
- `192.168.122.236:5432` — forward to Debian PostgreSQL
- `root@192.168.4.5` — through the RHEL host
- `-N` — no command just tunnel
- `-f` — run in background

### Verify Tunnel is Running
```bash
ps aux | grep ssh
ss -tlnp | grep 5432
```

### Kill the Tunnel
```bash
pkill -f "ssh -L 5432"
```

### Test the Tunnel
```bash
psql -h 127.0.0.1 -p 5432 -U f1user -d f1_data
```

### Persistent Tunnel (auto-restart on reboot)
```bash
sudo apt install autossh
crontab -e
# Add: @reboot sleep 30 && autossh -M 0 -f -N -L 5432:192.168.122.236:5432 root@192.168.4.5
```

autossh monitors the tunnel and automatically restarts it if it drops.
The sleep 30 gives the network time to come up before connecting.

### SSH Keys (no password prompts)
```bash
ssh-keygen -t ed25519 -C "webster-to-rhel"
ssh-copy-id root@192.168.4.5
```

After this Ubuntu can SSH to RHEL without a password — required for
autossh to work automatically on reboot.

---

## Python Pipeline

### db_utils.py — Shared Utilities
Every pipeline script imports from this file. It provides:

**get_connection()** — Creates a PostgreSQL connection using credentials
from the .env file. Centralizing this means if you ever change the database
location you only update one file.

**upsert()** — Insert a record update if it already exists.
Uses PostgreSQL ON CONFLICT DO UPDATE syntax. This is what makes the
pipeline idempotent — safe to run multiple times without creating dupes.

**setup_logging()** — Creates a logger that writes to both the console
and a log file. Routes logs to logs/fetch/ or logs/incremental/ based
on which script is running.

### setup_db.py — Table Creation
Run once to create all database tables by executing schema.sql.
```bash
cd ~/formula1-db
python3 pipeline/setup_db.py
```

### fetch_data.py — Full Historical Load
Run once to bootstrap the database with all F1 data from 1950 to 2025.
Takes 1-2 hours due to API rate limiting (200 requests/hour max).

Load order matters — you must load parent tables before child tables
because of foreign key constraints:
```
circuits      -> needed by races
drivers       -> needed by race_results
constructors  -> needed by race_results
seasons       -> needed by races
races         -> needed by race_results, qualifying, sprint
race_results
qualifying_results
sprint_results
driver_standings
constructor_standings
```

### incremental_load.py — Weekly Updates
Runs automatically every Monday at 6am via cron.
Pulls only the latest completed race — runs in under 10 seconds.

```bash
cd ~/formula1-db
python3 pipeline/incremental_load.py
```

### Running Scripts
```bash
# Make sure SSH tunnel is running first
ps aux | grep ssh

# Always run from project root so .env is found
cd ~/formula1-db
python3 pipeline/<script>.py
```

---

## Database Schema

### Why This Schema Design?
The schema follows third normal form (3NF) — a database design standard
that eliminates redundancy by storing each piece of information exactly once
and referencing it by ID everywhere else.

For example Hamilton's nationality is stored once in the drivers table.
Every race result just stores driver_id = 'hamilton' — not his full name
nationality date of birth etc repeated thousands of times.

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

### Table Relationships
```
seasons
  └──< races >── circuits
         ├──< race_results >── drivers
         │                 └── constructors
         ├──< qualifying_results
         ├──< sprint_results
         ├──< lap_times
         └──< pit_stops

drivers ──< driver_standings
constructors ──< constructor_standings
```

### Unique Constraints
Every table has a unique constraint on its natural business key to prevent
duplicate data and make upsert work correctly:

| Table | Unique Constraint |
|---|---|
| races | season_year, round |
| race_results | race_id, driver_id |
| qualifying_results | race_id, driver_id |
| sprint_results | race_id, driver_id |
| driver_standings | season_year, round, driver_id |
| constructor_standings | season_year, round, constructor_id |

### Data Sources
- **Jolpica API** (https://api.jolpi.ca/ergast/) — Historical + current
  - No API key required
  - Rate limit: 200 requests/hour
  - Successor to the deprecated Ergast API
- **OpenF1 API** (https://openf1.org/) — Live timing (planned)
  - No API key required
  - Real-time lap times and positions during race weekends

### Data Loaded
- 76 seasons (1950-2026)
- 77+ circuits
- 864+ drivers
- 211+ constructors
- 1,100+ races
- 25,873 race results
- Qualifying data from 1994 onwards
- Sprint results from 2021 onwards
- Driver and constructor standings throughout

---

## Data Quality — Duplicate Prevention

### The Problem
On initial load duplicate records were inserted into several tables because
the upsert function was checking conflict on SERIAL (auto-increment) primary
keys which are always unique by definition. Every insert succeeded even when
the same logical record already existed.

### Root Cause
```python
# Wrong - SERIAL id is always unique, never conflicts
upsert(conn, "race_results", {...}, "result_id")

# Correct - checks the real unique business combination
upsert(conn, "race_results", {...}, "race_id, driver_id")
```

### Fix Applied

**Step 1 — Clean existing duplicates**

Child tables must be cleaned before parent tables due to foreign key constraints.
Order: race_results, qualifying_results, sprint_results, then races.

```sql
BEGIN;

DELETE FROM race_results a
USING race_results b
WHERE a.result_id < b.result_id
AND a.race_id = b.race_id
AND a.driver_id = b.driver_id;

COMMIT;
```

**Step 2 — Add unique constraints**
```sql
ALTER TABLE race_results
ADD CONSTRAINT uq_race_results
UNIQUE (race_id, driver_id);
```

**Step 3 — Update upsert conflict columns in Python**

**Step 4 — Update schema.sql to reflect constraints**

### Unique Constraints Added
| Table | Unique Constraint |
|---|---|
| races | season_year, round |
| race_results | race_id, driver_id |
| qualifying_results | race_id, driver_id |
| sprint_results | race_id, driver_id |
| driver_standings | season_year, round, driver_id |
| constructor_standings | season_year, round, constructor_id |

### Key Lessons
- Always use meaningful business columns as conflict columns in upsert
- Never use SERIAL auto-increment IDs as upsert conflict targets
- Clean child tables before parent tables (foreign key dependency order)
- Use BEGIN/COMMIT transactions when making bulk changes
- Always verify fixes with a duplicate check query after cleanup
- session_replication_role = replica requires superuser — run as postgres

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
- **Branch strategy:** main (stable) / dev (active development)

### Setup on Ubuntu Server
```bash
git config --global user.email "your@email.com"
git config --global user.name "clucas56"
git config --global credential.helper store
git clone https://clucas56:<personal-access-token>@github.com/clucas56/formula1-db.git
```

> Use a Personal Access Token not your password. Generate at:
> github.com -> Settings -> Developer settings -> Personal access tokens
> Make sure to check the repo scope with read/write access.

### Daily Workflow
```bash
git add .
git commit -m "describe what you changed"
git push
```

### What .gitignore Excludes
```
.env        <- credentials — never commit
logs/       <- log files — no need to version control
__pycache__ <- Python compiled files
*.pyc       <- Python compiled files
```

---

## Firewall Rules

### Why Firewalls Matter
A firewall controls what network traffic is allowed in and out of a server.
ufw on Debian uses a whitelist approach — everything is blocked by default
you explicitly allow what you need.

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
Home Router (192.168.4.1)
    ↓
IBM-BASEMENT RHEL Host (192.168.4.5)
    ├── Physical NIC: eno2 -> home network (192.168.4.x)
    │
    ├── KVM Hypervisor
    │     ├── virbr0 virtual bridge (192.168.122.x)
    │     │     └── debian-db (192.168.122.236)
    │     │           └── PostgreSQL :5432
    │     │
    │     └── macvtap on eno2
    │           └── webster/ubuntu (192.168.4.7)
    │                 └── Apache, Python pipeline
    │
    └── SSH Tunnel: ubuntu -> RHEL -> debian-db
          bridges the two networks for DB connectivity

Windows Machine (192.168.4.x)
    ├── pgAdmin -> SSH tunnel -> PostgreSQL
    └── VSCode -> git push -> GitHub -> future webhook -> ubuntu
```

---

## Incremental Load Pipeline

### Overview
After the full historical load new race data is loaded incrementally after
each race weekend. Runs in under 10 seconds vs 1-2 hours for the full load.

### How it Works
```
1. Fetch latest completed race from Jolpica (/current/last/results.json)
2. Check if race already exists in database
3. If new — insert race and season details
4. Load race results (also upserts any new drivers/constructors)
5. Load qualifying results
6. Load sprint results (if sprint weekend)
7. Load driver and constructor standings
8. All steps use upsert — idempotent and safe to rerun
```

### Idempotency
Running the script multiple times produces the same result — no duplicates.
This is a critical property of a well designed data pipeline. If the script
fails halfway through you can simply rerun it safely.

### Key Differences from fetch_data.py
| | fetch_data.py | incremental_load.py |
|---|---|---|
| Purpose | One time bootstrap | Run after each race |
| Data range | 1950 to present | Latest race only |
| Runtime | 1-2 hours | Under 10 seconds |
| Rate limiting | 20 second delays | Standard 0.5s delay |
| Driver/constructor upsert | Separate functions | Inline with results |

### Manual Run
```bash
cd ~/formula1-db
python3 pipeline/incremental_load.py
```

### Log Location
```
~/formula1-db/logs/incremental/incremental_load_YYYYMMDD_HHMMSS.log
```

---

## Cron Jobs

### What is Cron?
Cron is Linux's built in task scheduler. You define a schedule and a command
and Linux runs it automatically at that time even if you are not logged in.
Think of it like Windows Task Scheduler.

### Cron Schedule Syntax
```
* * * * * command
| | | | |
| | | | └── Day of week (0=Sunday, 1=Monday...6=Saturday)
| | | └──── Month (1-12)
| | └────── Day of month (1-31)
| └──────── Hour (0-23)
└────────── Minute (0-59)
```

### View and Edit Cron Jobs
```bash
crontab -l    # view current jobs
crontab -e    # edit jobs
```

### Current Schedule (Ubuntu Web Server)
| Schedule | Command | Purpose |
|---|---|---|
| Every Monday 6am | python3 pipeline/incremental_load.py | Load latest race data |
| On reboot | autossh tunnel | Restart SSH tunnel to Debian VM |

```bash
@reboot sleep 30 && autossh -M 0 -f -N -L 5432:192.168.122.236:5432 root@192.168.4.5
0 6 * * 1 cd /home/clucas/formula1-db && python3 pipeline/incremental_load.py
```

> Monday at 6am was chosen because most F1 races happen on Sunday.
> Race data is available in the Jolpica API within hours of finishing.

---

## How It All Connects — End to End Flow

### Initial Setup (done once)
```
1. Debian VM created on RHEL host
2. PostgreSQL installed and configured on Debian
3. Ubuntu web server set up with Python and git
4. SSH tunnel configured Ubuntu -> RHEL -> Debian
5. GitHub repo cloned to Ubuntu
6. setup_db.py run -> creates all 12 tables
7. fetch_data.py run -> loads 1950-2025 historical data
```

### Weekly Automated Flow (every Monday 6am)
```
1. Cron triggers incremental_load.py on Ubuntu
2. autossh keeps the SSH tunnel alive
3. Python connects to PostgreSQL via tunnel (looks like localhost:5432)
4. Script asks Jolpica API: what was the last race?
5. API returns latest race details
6. Script checks database: do we already have this race?
7. If no -> insert race record
8. Fetch and upsert: results, qualifying, sprint, standings
9. Commit to PostgreSQL
10. Log written to logs/incremental/
```

### Manual Development Flow
```
1. Write code in VSCode on Windows
2. git push to GitHub
3. SSH into Ubuntu web server
4. git pull to get latest code
5. Test and run scripts
6. Push any fixes back to GitHub
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
- **Static IP** — prevents VM IP from changing on reboot
- **SSH keys** — passwordless authentication using public/private key pairs
- **autossh** — keeps SSH tunnels alive automatically
- **Hidden files** — files starting with . are hidden use `ls -la` to see them

### Networking
- **SSH tunnel** — routes traffic through an intermediate server
- **Port forwarding** — `-L local_port:remote_host:remote_port`
- **NAT** — how virbr0 VMs reach the internet through the host
- **Firewall whitelist** — block everything allow only what you need

### PostgreSQL / Databases
- **Relational schema** — tables linked by foreign keys
- **Third normal form (3NF)** — store each fact once reference by ID
- **SERIAL** — auto-increment primary key
- **Unique constraint** — prevents duplicate combinations
- **pg_hba.conf** — PostgreSQL access control file
- **psql commands** — \l \dt \d \c \q
- **Semicolons** — every SQL statement must end with ; in psql
- **Transactions** — BEGIN/COMMIT/ROLLBACK for safe bulk operations
- **Foreign key dependency order** — clean/delete children before parents
- **ON CONFLICT DO UPDATE** — upsert syntax in PostgreSQL

### Python Data Engineering
- **psycopg2** — Python PostgreSQL connector
- **python-dotenv** — loads .env files into environment variables
- **requests** — HTTP library for calling APIs
- **ETL pattern** — Extract (API) Transform (clean/map) Load (database)
- **Upsert** — ON CONFLICT DO UPDATE — insert or update never duplicate
- **Idempotency** — running multiple times produces the same result
- **Rate limiting** — respecting API request limits with time.sleep()
- **Pagination** — fetching all results when API limits per-page records
- **Logging** — structured logs for monitoring pipeline runs
- **Error handling** — try/except/finally for robust pipelines
- **.get() vs []** — use .get() for optional fields to avoid crashes on missing data

### Data Quality
- **Duplicate detection** — GROUP BY ... HAVING COUNT(*) > 1
- **Self join delete** — removing dupes while keeping one copy
- **Idempotent upsert** — conflict on business key not surrogate key
- **Data quality checks** — verify after every major operation

### Git / DevOps
- **Personal access token** — GitHub authentication not password
- **credential.helper store** — saves token so you do not retype it
- **.gitignore** — prevents sensitive files from being committed
- **Commit messages** — describe what changed and why

---

## Troubleshooting

### SSH into Debian VM from RHEL Host
```bash
ssh root@192.168.122.236
```

### SSH locked out of VM
Happened when ufw was enabled without allowing port 22 first.
```bash
# From RHEL host — virsh console bypasses SSH entirely
virsh console debian-db --force
# Hit Enter several times to wake up the console
ufw allow 22/tcp
ufw reload
```

### PostgreSQL not accepting connections
```bash
# Check cluster is actually running
pg_lsclusters
systemctl status postgresql@17-main

# Check what it is listening on
ss -tlnp | grep 5432

# Check recent errors
tail -50 /var/log/postgresql/postgresql-17-main.log

# Check pg_hba.conf
cat /etc/postgresql/17/main/pg_hba.conf | tail -10

# Restart
systemctl restart postgresql@17-main
```

### SSH tunnel drops or port already in use
```bash
# Find and kill stale tunnel processes
pkill -f "ssh -L 5432"

# Check nothing is holding port 5432
ss -tlnp | grep 5432
sudo lsof -i :5432

# Kill specific PID if needed
kill -9 <pid>

# Start fresh tunnel
ssh -L 5432:192.168.122.236:5432 root@192.168.4.5 -N -f
```

### Python script connection timeout
```bash
# Check tunnel is running
ps aux | grep ssh

# Test connection directly
psql -h 127.0.0.1 -p 5432 -U f1user -d f1_data

# Check .env has correct values
cat ~/formula1-db/.env

# Always run from project root
cd ~/formula1-db
python3 pipeline/script.py
```

### VM has duplicate IPs
Happened after multiple rebuilds — DHCP assigned two leases.
```bash
ip a show ens3
ip addr del 192.168.122.235/24 dev ens3
# Set static IP in /etc/network/interfaces to prevent recurrence
```

### Permission denied for session_replication_role
Requires superuser. Run as postgres user not f1user:
```bash
ssh root@192.168.122.236
su - postgres
psql -d f1_data
```

### Git authentication failing (403)
```bash
git remote set-url origin https://clucas56:<token>@github.com/clucas56/formula1-db.git
git push -u origin main
```

---

## Next Steps

### Immediate
- [ ] Build web dashboard (index.html + Flask backend)
- [ ] Set up GitHub webhook for auto-deploy to Ubuntu
- [ ] Add pit stop data (endpoint needs investigation)

### AI Layer
- [ ] Build query_engine.py using Claude API
- [ ] Text-to-SQL — ask questions in plain English
- [ ] Migrate to Azure OpenAI once AZ-900 certified

### Data Enhancements
- [ ] Add lap times via OpenF1 API (live during race weekends)
- [ ] Historical data validation queries
- [ ] Add 2026 season data as it comes in

### Infrastructure
- [ ] Make GitHub repo public as portfolio piece
- [ ] Set up Royal TS for organized server connection management
- [ ] Consider upgrading RHEL 7 host to Rocky Linux 8/9
- [ ] Document webhook setup when implemented

---

## Azure Equivalent Architecture

When ready to move this to Azure here is how each component maps:

| Home Lab Component | Azure Service |
|---|---|
| Debian VM + PostgreSQL | Azure Database for PostgreSQL Flexible Server |
| Ubuntu Web Server | Azure App Service |
| Python pipeline scripts | Azure Data Factory Pipelines |
| Cron schedule | ADF Scheduled Trigger |
| SSH tunnel | Azure Private Link / VNet Peering |
| .env credentials | Azure Key Vault |
| GitHub repo | Azure DevOps / GitHub Actions |
| Logs folder | Azure Monitor / Log Analytics |
| Claude API query engine | Azure OpenAI Service |
| pgAdmin | Azure Data Studio |

This project is a proof of concept for a real Azure data platform.
Everything built here maps 1:1 to enterprise Azure architecture making it
a strong portfolio piece for DP-100 AI-102 and data engineering roles.
