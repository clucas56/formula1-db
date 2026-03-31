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
7. [Flask App Server Setup](#flask-app-server-setup)
8. [SSH Tunnel Setup](#ssh-tunnel-setup)
9. [Python Pipeline](#python-pipeline)
10. [Database Schema](#database-schema)
11. [Database Views](#database-views)
12. [Data Quality — Duplicate Prevention](#data-quality--duplicate-prevention)
13. [GitHub Version Control](#github-version-control)
14. [Firewall Rules](#firewall-rules)
15. [Network Topology](#network-topology)
16. [Incremental Load Pipeline](#incremental-load-pipeline)
17. [Cron Jobs](#cron-jobs)
18. [How It All Connects — End to End Flow](#how-it-all-connects--end-to-end-flow)
19. [Key Concepts Learned](#key-concepts-learned)
20. [Troubleshooting](#troubleshooting)
21. [Next Steps](#next-steps)
22. [Azure Equivalent Architecture](#azure-equivalent-architecture)

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
| Purpose | Reverse Proxy, Python Pipeline, Cloudflare Tunnel |
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

### Apache Reverse Proxy Configuration

Apache on webster acts as a reverse proxy — it receives incoming web traffic
and forwards it to the appropriate backend service. This keeps one consistent
entry point for all web traffic.

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
> This is because webster cannot reach virbr0 VMs directly — an SSH tunnel
> bridges port 5000 from localhost to debian-app.

### Cloudflare Tunnel Configuration

The Cloudflare Tunnel config lives at `/etc/cloudflared/config.yml`.
It routes incoming Cloudflare traffic to Apache on localhost.

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

> **Important:** Ingress rules are evaluated top to bottom. More specific
> hostnames (subdomains) must come before the root domain. The final
> catch-all `http_status:404` is required.

```bash
# Restart after any config change
sudo systemctl restart cloudflared

# Check status
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
Running Flask on its own VM rather than on webster provides:
- Clean separation — web server does one thing, app server does another
- If Flask crashes, Apache and the portfolio site are unaffected
- Mirrors real production architecture (App Service separate from Front Door)
- Easier to snapshot, rebuild, or replace the app layer independently

### VM Creation
```bash
# On IBM-BASEMENT
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
everything the app needs lives inside one folder. Standard professional practice.

#### Create the Virtual Environment
```bash
mkdir -p /var/www/f1-app
python3 -m venv /var/www/f1-app/venv
```

#### Activate the Virtual Environment
```bash
source /var/www/f1-app/venv/bin/activate
# Prompt changes to (venv) — you are now inside the isolated environment
```

#### Install Packages
```bash
pip install flask gunicorn psycopg2-binary python-dotenv
```

### App Structure
```
/var/www/f1-app/
├── .env                  <- database credentials (never commit)
├── app.py                <- Flask application
├── venv/                 <- Python virtual environment
└── templates/
    └── index.html        <- HTML dashboard template
```

### app.py
```python
import os
import psycopg2
from flask import Flask, render_template
from dotenv import load_dotenv
from pathlib import Path

# ------------------------------------------------
# Configuration
# ------------------------------------------------

load_dotenv(Path(__file__).parent / '.env')

app = Flask(__name__)

# ------------------------------------------------
# Database connection
# ------------------------------------------------

def get_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )

# ------------------------------------------------
# Routes
# ------------------------------------------------

@app.route('/')
def index():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM current_standings;")
    standings = cursor.fetchall()

    cursor.execute("SELECT * FROM last_race_results;")
    last_race = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('index.html', standings=standings, last_race=last_race)

# ------------------------------------------------
# Entry point
# ------------------------------------------------

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
```

### .env on debian-app
Same structure as webster but DB_HOST points directly to debian-db
since both VMs are on virbr0 and can reach each other natively.
```
DB_HOST=192.168.122.236
DB_PORT=5432
DB_NAME=f1_data
DB_USER=f1user
DB_PASSWORD=yourpassword
```

Secure the file:
```bash
chown f1app:f1app /var/www/f1-app/.env
chmod 600 /var/www/f1-app/.env
```

### Dedicated Service Account
Running web apps as root is a security risk. A dedicated service account
limits the blast radius if the app is ever compromised.

```bash
# Create a system account with no login shell and no home directory
useradd --system --no-create-home --shell /usr/sbin/nologin f1app

# Give it ownership of the app directory
chown -R f1app:f1app /var/www/f1-app
```

### gunicorn
Flask's built-in dev server handles one request at a time. gunicorn is a
production WSGI server that runs multiple worker processes concurrently.

Think of Flask's dev server as a food truck run by one person, and gunicorn
as a restaurant kitchen with multiple cooks.

Test manually:
```bash
source /var/www/f1-app/venv/bin/activate
gunicorn --workers 3 --bind 0.0.0.0:5000 --chdir /var/www/f1-app app:app
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
WorkingDirectory=/var/www/f1-app
Environment="PATH=/var/www/f1-app/venv/bin"
ExecStart=/var/www/f1-app/venv/bin/gunicorn --workers 3 --bind 0.0.0.0:5000 app:app
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable f1-app    # start on boot
systemctl start f1-app     # start now
systemctl status f1-app    # verify running
```

#### systemd Service File Explained
- `After=network.target` — wait for network before starting
- `User=f1app` — run as the dedicated service account, not root
- `Environment="PATH=..."` — use the virtual environment's Python, not system Python
- `Restart=always` — auto-restart if the process crashes
- `WantedBy=multi-user.target` — start during normal system boot

### Key systemctl Commands
```bash
systemctl start f1-app      # start the service
systemctl stop f1-app       # stop the service
systemctl restart f1-app    # restart (use after code changes)
systemctl status f1-app     # check if running
systemctl enable f1-app     # start on boot
systemctl disable f1-app    # do not start on boot
```

---

## SSH Tunnel Setup

### Why Do We Need Tunnels?
The Ubuntu web server (192.168.4.7) and the virbr0 VMs (192.168.122.x) are
on different networks. macvtap VMs cannot communicate directly with virbr0
VMs on the same host — it is a Linux networking limitation by design.

The solution is SSH tunnels through the RHEL host which can reach both networks.

### Tunnel 1 — webster to debian-db (PostgreSQL)
Used by the Python pipeline to reach the database.

```
webster (192.168.4.7)
    ↓ opens SSH connection to IBM-BASEMENT
IBM-BASEMENT (192.168.4.5)
    ↓ forwards traffic through virbr0
debian-db (192.168.122.236:5432)
```

From Python's perspective PostgreSQL looks like it is running locally
on webster at 127.0.0.1:5432.

### Tunnel 2 — webster to debian-app (Flask)
Used by Apache to forward web traffic to the Flask app.

```
webster (192.168.4.7)
    ↓ opens SSH connection to IBM-BASEMENT
IBM-BASEMENT (192.168.4.5)
    ↓ forwards traffic through virbr0
debian-app (192.168.122.100:5000)
```

Apache proxies to localhost:5000 which the tunnel maps to debian-app.

### Persistent Tunnels (crontab on webster)
```bash
crontab -e
```
```
@reboot sleep 30 && autossh -M 0 -f -N -L 5432:192.168.122.236:5432 root@192.168.4.5
@reboot sleep 30 && autossh -M 0 -f -N -L 5000:192.168.122.100:5000 root@192.168.4.5
```

autossh monitors tunnels and automatically restarts them if they drop.
sleep 30 gives the network time to come up before connecting on reboot.

### Verify Tunnels are Running
```bash
ps aux | grep autossh
ss -tlnp | grep 5432
ss -tlnp | grep 5000
```

### SSH Keys (no password prompts)
```bash
ssh-keygen -t ed25519 -C "webster-to-rhel"
ssh-copy-id root@192.168.4.5
```

Required for autossh to work automatically on reboot.

### Note on debian-app to debian-db
debian-app and debian-db are both on virbr0 (192.168.122.x) so they can
reach each other directly — no tunnel needed between them. Flask connects
to PostgreSQL at 192.168.122.236 directly.

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

## Database Views

### What is a View?
A view is a saved query that lives in PostgreSQL. Instead of writing long
JOIN queries in Flask every time, the view is defined once in the database
and queried with a simple SELECT. This separates concerns — the database
handles data shaping, Python handles application logic.

This maps directly to Azure Synapse views and SQL Server views used in
enterprise BI and reporting pipelines.

### current_standings
Returns the current season driver championship standings at the latest round.
Uses EXTRACT(YEAR FROM CURRENT_DATE) so it automatically reflects the
current season without hardcoding a year.

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
Returns the full finishing order of the most recently completed race
in the current season.

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

### Querying Views in Flask
```python
cursor.execute("SELECT * FROM current_standings;")
cursor.execute("SELECT * FROM last_race_results;")
```

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

### Key Lessons
- Always use meaningful business columns as conflict columns in upsert
- Never use SERIAL auto-increment IDs as upsert conflict targets
- Clean child tables before parent tables (foreign key dependency order)
- Use BEGIN/COMMIT transactions when making bulk changes
- Always verify fixes with a duplicate check query after cleanup

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

### Current Schedule (Ubuntu Web Server / webster)
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

> Monday at 6am was chosen because most F1 races happen on Sunday.
> Race data is available in the Jolpica API within hours of finishing.

---

## How It All Connects — End to End Flow

### Initial Setup (done once)
```
1. Debian DB VM created on RHEL host
2. PostgreSQL installed and configured on debian-db
3. Ubuntu web server (webster) set up with Python, Apache, Cloudflare Tunnel
4. SSH tunnel configured webster -> IBM-BASEMENT -> debian-db
5. GitHub repo cloned to webster
6. setup_db.py run -> creates all 12 tables
7. fetch_data.py run -> loads 1950-2026 historical data
8. Debian App VM (debian-app) created on RHEL host
9. Flask + gunicorn installed on debian-app
10. systemd service configured to run Flask on boot
11. SSH tunnel configured webster -> IBM-BASEMENT -> debian-app
12. Apache reverse proxy configured on webster
13. Cloudflare Tunnel config updated for f1.charleslucas562.com
14. Database views created in PostgreSQL
15. f1.charleslucas562.com live
```

### Weekly Automated Flow (every Monday 6am)
```
1. Cron triggers incremental_load.py on webster
2. autossh keeps the SSH tunnels alive
3. Python connects to PostgreSQL via tunnel (looks like localhost:5432)
4. Script asks Jolpica API: what was the last race?
5. API returns latest race details
6. Script checks database: do we already have this race?
7. If no -> insert race record
8. Fetch and upsert: results, qualifying, sprint, standings
9. Commit to PostgreSQL
10. Log written to logs/incremental/
```

### Web Request Flow (f1.charleslucas562.com)
```
1. Browser requests f1.charleslucas562.com
2. Cloudflare receives request and routes through tunnel
3. cloudflared on webster passes to Apache on localhost:80
4. Apache virtual host matches f1.charleslucas562.com
5. Apache proxies request through SSH tunnel to localhost:5000
6. SSH tunnel forwards to gunicorn on debian-app:5000
7. gunicorn passes to Flask worker process
8. Flask queries PostgreSQL views on debian-db directly (same network)
9. PostgreSQL returns standings and race results
10. Flask renders index.html template with data
11. Response travels back through the chain to the browser
```

### Manual Development Flow
```
1. Write code in VSCode on Windows
2. git push to GitHub
3. SSH into debian-app
4. git pull (future: webhook auto-deploys)
5. sudo systemctl restart f1-app
6. Test at f1.charleslucas562.com
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
- **Hidden files** — files starting with . are hidden use `ls -la` to see them
- **chmod 600** — file readable/writable by owner only, used for credential files
- **Service accounts** — dedicated non-login users for running services securely

### Networking
- **SSH tunnel** — routes traffic through an intermediate server
- **Port forwarding** — `-L local_port:remote_host:remote_port`
- **NAT** — how virbr0 VMs reach the internet through the host
- **Firewall whitelist** — block everything allow only what you need
- **Reverse proxy** — Apache sitting in front of Flask forwarding requests
- **Cloudflare Tunnel** — exposes local services to internet without open ports

### Web / Flask
- **Flask** — Python micro web framework, routes HTTP requests to functions
- **gunicorn** — production WSGI server, runs multiple Flask worker processes
- **WSGI** — standard interface between Python web apps and web servers
- **Virtual environment** — isolated Python package environment per project
- **Jinja2 templating** — Flask's HTML template engine with {{ }} syntax
- **Routes** — @app.route decorators map URLs to Python functions
- **render_template** — passes data from Python to HTML templates
- **Reverse proxy** — Apache forwards requests to Flask, Flask never exposed directly

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
- **Views** — saved queries in the database, simplify application code
- **EXTRACT(YEAR FROM CURRENT_DATE)** — dynamic current year in SQL

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

### Git / DevOps
- **Personal access token** — GitHub authentication not password
- **credential.helper store** — saves token so you do not retype it
- **.gitignore** — prevents sensitive files from being committed
- **Commit messages** — describe what changed and why

---

## Troubleshooting

### SSH into VMs from RHEL Host
```bash
ssh root@192.168.122.236    # debian-db
ssh root@192.168.122.100    # debian-app
ssh clucas@192.168.4.7      # webster
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

### Flask service not starting
```bash
# Check service status
systemctl status f1-app

# Check detailed logs
journalctl -u f1-app -n 50 --no-pager

# Common causes:
# - .env file not found or wrong permissions
# - venv path wrong in service file
# - Port 5000 already in use
# - f1app user does not own /var/www/f1-app
```

### f1.charleslucas562.com not loading
Work through the chain:
```bash
# 1. Is Flask running on debian-app?
systemctl status f1-app

# 2. Is the SSH tunnel from webster to debian-app alive?
ps aux | grep autossh
ss -tlnp | grep 5000

# 3. Can webster reach Flask through the tunnel?
curl http://localhost:5000

# 4. Is Apache proxying correctly?
curl -H "Host: f1.charleslucas562.com" http://localhost

# 5. Is cloudflared running?
systemctl status cloudflared

# 6. Check Apache error logs
tail -50 /var/log/apache2/f1-app-error.log
```

### cloudflared fails to start (YAML error)
```bash
# Check for duplicate keys in config
cat /etc/cloudflared/config.yml

# If duplicated, rewrite the file cleanly
nano /etc/cloudflared/config.yml

# Restart
systemctl restart cloudflared
systemctl status cloudflared
```

### PostgreSQL not accepting connections
```bash
pg_lsclusters
systemctl status postgresql@17-main
ss -tlnp | grep 5432
tail -50 /var/log/postgresql/postgresql-17-main.log
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
- [ ] GitHub webhook for auto-deploy to debian-app
- [ ] Improve dashboard styling
- [ ] Add constructor standings page
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
- [ ] Document webhook setup when implemented

---

## Azure Equivalent Architecture

When ready to move this to Azure here is how each component maps:

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
| GitHub repo | Azure DevOps / GitHub Actions |
| Logs folder | Azure Monitor / Log Analytics |
| Claude API query engine | Azure OpenAI Service |
| pgAdmin | Azure Data Studio |
| systemd service | Azure App Service always-on setting |
| Database views | Azure SQL Views / Synapse Views |
| f1app service account | Azure Managed Identity |

This project is a proof of concept for a real Azure data platform.
Everything built here maps 1:1 to enterprise Azure architecture making it
a strong portfolio piece for DP-100, AI-102, and data engineering roles.
