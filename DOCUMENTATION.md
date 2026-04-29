# F1 Data Platform — Project Documentation

**Author:** clucas56
**Last Updated:** April 2026
**Repository:** github.com/clucas56/formula1-db

\---

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

\---

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

|Home Lab|Enterprise / Azure Equivalent|
|-|-|
|fetch\_data.py|Azure Data Factory Pipeline|
|incremental\_load.py|ADF Incremental Trigger|
|PostgreSQL|Azure SQL / Synapse Dedicated Pool|
|SSH tunnel|Azure Private Link / VNet Peering|
|cron schedule|ADF Scheduled Trigger|
|.env file|Azure Key Vault|
|GitHub|Azure DevOps|
|Python psycopg2|Synapse Linked Service|
|Flask + gunicorn|Azure App Service (Python)|
|Apache reverse proxy|Azure Application Gateway / Front Door|
|Cloudflare Tunnel|Azure Public IP + DNS|
|Database views|Azure SQL Views / Synapse Views|
|GitHub webhook|Azure DevOps CI/CD Pipeline|
|Dynamic routing|Azure API Management|

\---

## Infrastructure Overview

```
Windows Machine (pgAdmin, VSCode)
        ↓ SSH tunnel through RHEL host
RHEL IBM-BASEMENT (192.168.4.5) — Bare Metal Host
        ↓ KVM Hypervisor
        ├── Ubuntu VM — webster (192.168.4.7) — Web Server + Reverse Proxy
        ├── Debian VM — debian-db (192.168.122.236) — Database Server
        │                     └── PostgreSQL 17
        │                           └── f1\_data DB
        └── Debian VM — debian-app (192.168.122.100) — Flask App Server
                              └── gunicorn + Flask
                                    └── f1.charleslucas562.com
```

### Why Three VMs?

Separating the web server, app server, and database server is a fundamental
architecture pattern in enterprise systems. Benefits include:

* **Security** — database is not directly exposed to the internet
* **Separation of concerns** — each VM has one job
* **Blast radius** — if Flask crashes it does not affect the database or portfolio site
* **Scalability** — each layer can be scaled or replaced independently
* **Portfolio** — mirrors real production architecture patterns

\---

## IBM-BASEMENT — RHEL Host

### Specs

|Property|Value|
|-|-|
|OS|Red Hat Enterprise Linux Server 7.9 (Maipo)|
|Hostname|IBM-BASEMENT|
|IP|192.168.4.5|
|RAM|141 GB|
|Disk|3.7 TB|
|CPUs|16 cores|
|Hypervisor|KVM / libvirt|
|Package Manager|yum (RHEL 7 — dnf not available until RHEL 8)|

> \*\*Note:\*\* RHEL 7 reached end of life June 2024. Consider upgrading to
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

* A software defined network switch inside the server
* VMs on virbr0 get IPs in the 192.168.122.x range
* VMs can talk to each other freely
* Reaches internet via NAT through the physical NIC
* debian-db and debian-app use this network

**macvtap on eno2**

* Plugs directly into the physical network card
* VM gets a real IP from your home router (192.168.4.x)
* Can talk to any device on your home network
* Cannot talk directly to other macvtap VMs on the same host (Linux limitation)
* webster uses this network

> This is why we need SSH tunnels — the two network types cannot
> communicate directly. webster must tunnel through IBM-BASEMENT
> to reach anything on virbr0.

\---

## Debian DB Server Setup

### Specs

|Property|Value|
|-|-|
|OS|Debian 13.4 Trixie|
|Hostname|debian-db|
|IP|192.168.122.236 (static)|
|RAM|4 GB|
|Disk|50 GB|
|Network|virbr0 (KVM internal)|
|Purpose|PostgreSQL Database Server|

### Installation Process

#### 1\. Download ISO on RHEL Host

```bash
cd /var/lib/libvirt/images
wget https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/debian-13.4.0-amd64-netinst.iso
```

#### 2\. Create VM

```bash
virt-install \\
  --name debian-db \\
  --ram 4096 \\
  --vcpus 2 \\
  --disk path=/var/lib/libvirt/images/debian-db.qcow2,size=50 \\
  --os-variant debiantesting \\
  --network network=default \\
  --graphics none \\
  --console pty,target\_type=serial \\
  --location /var/lib/libvirt/images/debian-13.4.0-amd64-netinst.iso \\
  --extra-args 'console=ttyS0,115200n8'
```

> \*\*Note:\*\* Use `--os-variant debiantesting` — Debian 13 is not yet in the
> osinfo dictionary on RHEL 7. This is the correct fallback variant.

#### 3\. Installer Choices

* **Partitioning:** Separate /var and /srv
* **Mirror:** deb.debian.org — United States
* **Software:** SSH server + standard system utilities ONLY (no desktop)
* **GRUB:** Install to /dev/vda

#### 4\. First Boot — Firewall FIRST (Critical Lesson Learned)

```bash
apt update \&\& apt install -y ufw
ufw allow 22/tcp     # SSH — do this FIRST or you lock yourself out
ufw allow 5432/tcp   # PostgreSQL
ufw enable
```

> \*\*Lesson learned the hard way:\*\* If you enable ufw without allowing port 22
> first you will lock yourself out of SSH. Always whitelist ports BEFORE enabling.
> Recovery: use `virsh console debian-db --force` as a backdoor.

#### 5\. Install Packages

```bash
apt install -y postgresql postgresql-contrib fastfetch htop tmux fail2ban git curl
```

#### 6\. Set Static IP

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

#### 7\. Fastfetch on Login

```bash
nano \~/.bashrc
# Add at bottom:
fastfetch
```

\---

## PostgreSQL Setup

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
\\password postgres
CREATE DATABASE f1\_data;
CREATE USER f1user WITH PASSWORD 'yourpw';
GRANT ALL PRIVILEGES ON DATABASE f1\_data TO f1user;
\\c f1\_data
GRANT ALL ON SCHEMA public TO f1user;
\\q
```

#### Configure PostgreSQL to listen on all interfaces

```bash
nano /etc/postgresql/17/main/postgresql.conf
```

```
listen\_addresses = '\*'
```

#### Allow network connections (pg\_hba.conf)

```bash
nano /etc/postgresql/17/main/pg\_hba.conf
```

Add at the bottom:

```
host    all    all    192.168.122.0/24    md5
host    all    all    127.0.0.1/32        md5
```

```bash
systemctl restart postgresql
```

### Connect to PostgreSQL

```bash
psql -h 127.0.0.1 -U f1user -d f1\_data
```

### Inside psql

```sql
\\l              -- list all databases
\\dt             -- list all tables
\\d table\_name   -- describe a table structure
\\c database     -- connect to a database
\\q              -- quit
```

\---

## Ubuntu Web Server

### Specs

|Property|Value|
|-|-|
|OS|Ubuntu 20.04|
|Hostname|webster|
|IP|192.168.4.7 (macvtap on eno2)|
|Purpose|Reverse Proxy, Python Pipeline, Cloudflare Tunnel|
|Web Server|Apache|

### Apache Reverse Proxy Configuration

#### Enable Required Modules

```bash
sudo a2enmod proxy proxy\_http
sudo systemctl restart apache2
```

#### Virtual Host for F1 Dashboard

```bash
sudo nano /etc/apache2/sites-available/f1-app.conf
```

```apache
<VirtualHost \*:80>
    ServerName f1.charleslucas562.com

    ProxyPreserveHost On
    ProxyPass / http://localhost:5000/
    ProxyPassReverse / http://localhost:5000/

    ErrorLog ${APACHE\_LOG\_DIR}/f1-app-error.log
    CustomLog ${APACHE\_LOG\_DIR}/f1-app-access.log combined
</VirtualHost>
```

```bash
sudo a2ensite f1-app.conf
sudo systemctl reload apache2
```

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
  - service: http\_status:404
```

> \*\*Important:\*\* More specific hostnames (subdomains) must come before the
> root domain. The final catch-all `http\_status:404` is required.

```bash
sudo systemctl restart cloudflared
sudo systemctl status cloudflared
```

\---

## Flask App Server Setup

### Specs

|Property|Value|
|-|-|
|OS|Debian 13.4 Trixie|
|Hostname|debian-app|
|IP|192.168.122.100 (static)|
|RAM|4 GB|
|Disk|20 GB|
|Network|virbr0 (KVM internal)|
|Purpose|Flask Web Application Server|
|App URL|f1.charleslucas562.com|

### VM Creation

```bash
virt-install \\
  --name debian-app \\
  --ram 4096 \\
  --vcpus 2 \\
  --disk path=/var/lib/libvirt/images/f1-app.qcow2,size=20 \\
  --os-variant debiantesting \\
  --network network=default \\
  --graphics none \\
  --console pty,target\_type=serial \\
  --location /var/lib/libvirt/images/debian-13.4.0-amd64-netinst.iso \\
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
DB\_HOST=192.168.122.236
DB\_PORT=5432
DB\_NAME=f1\_data
DB\_USER=f1user
DB\_PASSWORD=yourpassword
WEBHOOK\_SECRET=yoursecret
```

```bash
chown f1app:f1app /var/www/f1-app/.env
chmod 600 /var/www/f1-app/.env
```

### Dedicated Service Account

```bash
useradd --system --no-create-home --shell /usr/sbin/nologin f1app
mkdir -p /home/f1app
chown f1app:f1app /home/f1app
chown -R clucas:f1app /var/www/formula1-db
chmod -R 775 /var/www/formula1-db
```

### Git Shared Repository (Prevents Permission Issues)

```bash
cd /var/www/formula1-db
git config core.sharedRepository group
```

This ensures git always creates new objects with group write permissions
so the f1app user can always pull without permission errors.

### gunicorn

Test manually:

```bash
source /var/www/f1-app/venv/bin/activate
gunicorn --workers 3 --bind 0.0.0.0:5000 --chdir /var/www/formula1-db/web app:app
```

### systemd Service

```bash
nano /etc/systemd/system/f1-app.service
```

```ini
\[Unit]
Description=F1 Dashboard Flask App
After=network.target

\[Service]
User=f1app
WorkingDirectory=/var/www/formula1-db/web
Environment="PATH=/var/www/f1-app/venv/bin"
ExecStart=/var/www/f1-app/venv/bin/gunicorn --workers 3 --bind 0.0.0.0:5000 app:app
Restart=always

\[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable f1-app
systemctl start f1-app
systemctl status f1-app
```

### sudoers for f1app

```bash
nano /etc/sudoers.d/f1app
```

```
f1app ALL=(ALL) NOPASSWD: /bin/systemctl restart f1-app
```

\---

## SSH Tunnel Setup

### Why Do We Need Tunnels?

webster (macvtap, 192.168.4.x) cannot reach virbr0 VMs (192.168.122.x)
directly. SSH tunnels through IBM-BASEMENT bridge the gap.

### Tunnel 1 — webster to debian-db (PostgreSQL :5432)

### Tunnel 2 — webster to debian-app (Flask :5000)

### Persistent Tunnels — systemd Services (on webster)

Tunnels are managed as systemd services — **not crontab @reboot entries**.
systemd provides `Restart=always` so tunnels automatically recover from
drops, failed connections, or race conditions on boot.

> **Why not crontab?** `@reboot sleep 30 && autossh ...` runs once at boot
> and gives up if the target VM isn't ready yet. A systemd service with
> `Restart=always` and `RestartSec=10` keeps retrying indefinitely — much
> more resilient after a power outage when VMs may take varying time to boot.

#### Service File — Flask Tunnel

Location: `/etc/systemd/system/autossh-f1-flask.service`

```ini
[Unit]
Description=autossh tunnel — webster to debian-app (Flask :5000)
After=network-online.target
Wants=network-online.target

[Service]
User=clucas
Environment="AUTOSSH_GATETIME=0"
ExecStart=/usr/lib/autossh/autossh -M 0 -N \
    -o "ServerAliveInterval=30" \
    -o "ServerAliveCountMax=3" \
    -o "StrictHostKeyChecking=no" \
    -o "ExitOnForwardFailure=yes" \
    -L 5000:192.168.122.100:5000 root@192.168.4.5
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

#### Service File — PostgreSQL Tunnel

Location: `/etc/systemd/system/autossh-f1-postgres.service`

```ini
[Unit]
Description=autossh tunnel — webster to debian-db (PostgreSQL :5432)
After=network-online.target
Wants=network-online.target

[Service]
User=clucas
Environment="AUTOSSH_GATETIME=0"
ExecStart=/usr/lib/autossh/autossh -M 0 -N \
    -o "ServerAliveInterval=30" \
    -o "ServerAliveCountMax=3" \
    -o "StrictHostKeyChecking=no" \
    -o "ExitOnForwardFailure=yes" \
    -L 5432:192.168.122.236:5432 root@192.168.4.5
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

#### Deploy on webster

```bash
# Copy service files
sudo cp autossh-f1-flask.service /etc/systemd/system/
sudo cp autossh-f1-postgres.service /etc/systemd/system/

# Reload systemd and enable + start both
sudo systemctl daemon-reload
sudo systemctl enable --now autossh-f1-flask
sudo systemctl enable --now autossh-f1-postgres

# Verify
sudo systemctl status autossh-f1-flask
sudo systemctl status autossh-f1-postgres
curl http://localhost:5000   # should return F1 HTML

# Remove old crontab entries — keep only the incremental_load line
crontab -e
```

#### Day-to-day tunnel management

```bash
# Check status
sudo systemctl status autossh-f1-flask
sudo systemctl status autossh-f1-postgres

# Restart a tunnel manually
sudo systemctl restart autossh-f1-flask

# View logs
journalctl -u autossh-f1-flask -n 30 --no-pager
journalctl -u autossh-f1-postgres -n 30 --no-pager
```

### Note on debian-app to debian-db

Both are on virbr0 so they reach each other directly — no tunnel needed.
Flask connects to PostgreSQL at 192.168.122.236 directly.

\---

## Python Pipeline

### db\_utils.py — Shared Utilities

* **get\_connection()** — PostgreSQL connection from .env credentials
* **upsert()** — ON CONFLICT DO UPDATE — insert or update, never duplicate
* **setup\_logging()** — logs to file and console

### setup\_db.py — Table Creation (run once)

```bash
cd \~/formula1-db
python3 pipeline/setup\_db.py
```

### fetch\_data.py — Full Historical Load (run once)

Loads all F1 data from 1950 to present. Takes 1-2 hours due to rate limiting.

### incremental\_load.py — Weekly Updates

Runs automatically every Monday at 6am. Pulls only the latest race.
Also supports manual backfill with season and round arguments:

```bash
# Load latest race automatically
python3 pipeline/incremental\_load.py

# Backfill a specific race
python3 pipeline/incremental\_load.py 2026 1
```

The manual override was added to backfill missing races (e.g. Australia 2026
Round 1 which was not loaded by the automated pipeline).

\---

## Database Schema

### Tables

|Table|Purpose|Key Columns|
|-|-|-|
|seasons|F1 seasons|season\_year, total\_rounds|
|circuits|Race tracks|circuit\_id, name, country, lat, lng|
|drivers|Driver info|driver\_id, first\_name, last\_name, nationality|
|constructors|Teams|constructor\_id, name, nationality|
|races|Race calendar|race\_id, season\_year, round, circuit\_id|
|race\_results|Finishing positions|race\_id, driver\_id, finish\_position, points|
|qualifying\_results|Q1/Q2/Q3 times|race\_id, driver\_id, q1\_time, q2\_time, q3\_time|
|sprint\_results|Sprint races|race\_id, driver\_id, finish\_position, points|
|driver\_standings|Championship table|season\_year, round, driver\_id, points, position|
|constructor\_standings|Team championship|season\_year, round, constructor\_id, points|
|lap\_times|Individual laps|race\_id, driver\_id, lap\_number, lap\_time|
|pit\_stops|Pit stop data|race\_id, driver\_id, stop\_number, lap, duration|

### Data Sources

* **Jolpica API** (https://api.jolpi.ca/ergast/) — Historical + current
* **OpenF1 API** (https://openf1.org/) — Live timing (planned)

### Data Loaded

* 76 seasons (1950-2026)
* 864+ drivers
* 211+ constructors
* 1,100+ races
* 25,873+ race results

\---

## Database Views

Views are saved queries in PostgreSQL. Flask queries them with simple
SELECT statements — the database handles the JOIN complexity.

### current\_standings

Current season driver championship at the latest round.
Uses EXTRACT(YEAR FROM CURRENT\_DATE) — automatically reflects current season.

```sql
CREATE OR REPLACE VIEW current\_standings AS
SELECT
    ds.position,
    d.first\_name,
    d.last\_name,
    ds.points,
    ds.wins
FROM driver\_standings ds
JOIN drivers d ON ds.driver\_id = d.driver\_id
WHERE ds.season\_year = EXTRACT(YEAR FROM CURRENT\_DATE)
AND ds.round = (
    SELECT MAX(round) FROM driver\_standings
    WHERE season\_year = EXTRACT(YEAR FROM CURRENT\_DATE)
)
ORDER BY ds.position;
```

### last\_race\_results

Full finishing order of the most recently completed race.

```sql
CREATE OR REPLACE VIEW last\_race\_results AS
SELECT
    r.race\_name,
    r.date,
    d.first\_name,
    d.last\_name,
    rr.finish\_position,
    rr.points
FROM race\_results rr
JOIN drivers d ON rr.driver\_id = d.driver\_id
JOIN races r ON rr.race\_id = r.race\_id
WHERE r.race\_id = (
    SELECT race\_id FROM races
    WHERE season\_year = EXTRACT(YEAR FROM CURRENT\_DATE)
    ORDER BY round DESC LIMIT 1
)
ORDER BY rr.finish\_position;
```

### current\_constructor\_standings

Current season constructor championship at the latest round.

```sql
CREATE OR REPLACE VIEW current\_constructor\_standings AS
SELECT
    cs.position,
    c.name,
    c.nationality,
    cs.points,
    cs.wins
FROM constructor\_standings cs
JOIN constructors c ON cs.constructor\_id = c.constructor\_id
WHERE cs.season\_year = EXTRACT(YEAR FROM CURRENT\_DATE)
AND cs.round = (
    SELECT MAX(round) FROM constructor\_standings
    WHERE season\_year = EXTRACT(YEAR FROM CURRENT\_DATE)
)
ORDER BY cs.position;
```

### race\_results\_detail

Full race results with driver, constructor, grid and finish position.
Used by the race history page.

```sql
CREATE OR REPLACE VIEW race\_results\_detail AS
SELECT
    r.season\_year,
    r.round,
    r.race\_name,
    r.date,
    ci.name as circuit\_name,
    ci.country,
    d.first\_name,
    d.last\_name,
    c.name as constructor,
    rr.grid\_position,
    rr.finish\_position,
    rr.points,
    rr.status
FROM race\_results rr
JOIN drivers d ON rr.driver\_id = d.driver\_id
JOIN constructors c ON rr.constructor\_id = c.constructor\_id
JOIN races r ON rr.race\_id = r.race\_id
JOIN circuits ci ON r.circuit\_id = ci.circuit\_id
ORDER BY rr.finish\_position;
```

### season\_races

All races in the current season for the race selector on the homepage.

```sql
CREATE OR REPLACE VIEW season\_races AS
SELECT
    season\_year,
    round,
    race\_name,
    date
FROM races
WHERE season\_year = EXTRACT(YEAR FROM CURRENT\_DATE)
ORDER BY round;
```

\---

## Web Dashboard

### Pages

|URL|Template|Purpose|
|-|-|-|
|/|index.html|Main dashboard — standings, last race, race selector|
|/race/<season>/<round>|race.html|Individual race results with grid vs finish|
|/docs|docs.html|Live project documentation rendered from markdown|

### Dynamic Routing

Flask captures URL segments as variables:

```python
@app.route('/race/<int:season>/<int:round\_num>')
def race(season, round\_num):
    # season and round\_num come directly from the URL
    # e.g. /race/2026/3 sets season=2026, round\_num=3
```

### Markdown Documentation Page

The /docs route reads DOCUMENTATION.md from the repo root, converts it
to HTML using the markdown library, and renders it in docs.html.

```python
@app.route('/docs')
def docs():
    doc\_path = Path(\_\_file\_\_).parent.parent / 'DOCUMENTATION.md'
    with open(doc\_path, 'r') as f:
        content = f.read()
    html\_content = markdown.markdown(content, extensions=\['tables', 'fenced\_code'])
    return render\_template('docs.html', content=html\_content)
```

### Dashboard Styling

Dark terminal aesthetic throughout — black background, F1 red accents,
monospace Courier New font. Includes an ASCII art F1 logo in the header.

### Race History Page Features

* Full finishing order with points
* Grid position vs finish position with +/- places gained/lost
* Constructor for each driver
* Race name, circuit, country, date at the top
* Color coded positions gained (green) and lost (red)

\---

## GitHub Webhook — Auto Deploy

Every git push to GitHub automatically deploys to debian-app.

### How It Works

```
git push on Windows machine
        ↓
GitHub sends POST request to f1.charleslucas562.com/webhook
        ↓
Flask verifies HMAC signature (prevents unauthorized deploys)
        ↓
git pull on /var/www/formula1-db
        ↓
systemctl restart f1-app (runs in background via Popen)
        ↓
New code is live
```

### Webhook Route in app.py

```python
@app.route('/webhook', methods=\['POST'])
def webhook():
    secret = os.getenv("WEBHOOK\_SECRET").encode()
    signature = request.headers.get("X-Hub-Signature-256", "")
    body = request.get\_data()

    expected = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()

    if not hmac.compare\_digest(expected, signature):
        abort(403)

    subprocess.run(\["/usr/bin/git", "-C", "/var/www/formula1-db", "pull"], check=True)
    subprocess.Popen(\["/usr/bin/sudo", "/bin/systemctl", "restart", "f1-app"])

    return "Deployed", 200
```

### Security Notes

* HMAC SHA-256 signature verification prevents unauthorized webhook calls
* WEBHOOK\_SECRET stored in .env — never committed to GitHub
* Uses Popen (not run) for restart so Flask can return 200 before dying
* git core.sharedRepository = group prevents permission issues on pull
* f1app sudoers limited to only `systemctl restart f1-app`

### GitHub Configuration

Settings → Webhooks → Add webhook:

* **Payload URL:** https://f1.charleslucas562.com/webhook
* **Content type:** application/json
* **Secret:** your WEBHOOK\_SECRET value
* **Events:** Just the push event

\---

## Data Quality — Duplicate Prevention

### Root Cause

Upsert was checking conflict on SERIAL primary keys (always unique)
instead of business key combinations.

### Fix

```python
# Wrong
upsert(conn, "race\_results", {...}, "result\_id")

# Correct
upsert(conn, "race\_results", {...}, "race\_id, driver\_id")
```

### Unique Constraints

|Table|Unique Constraint|
|-|-|
|races|season\_year, round|
|race\_results|race\_id, driver\_id|
|qualifying\_results|race\_id, driver\_id|
|sprint\_results|race\_id, driver\_id|
|driver\_standings|season\_year, round, driver\_id|
|constructor\_standings|season\_year, round, constructor\_id|

\---

## GitHub Version Control

### Repository

* **URL:** github.com/clucas56/formula1-db
* **Visibility:** Private (make public when ready as portfolio piece)

### Setup

```bash
git config --global user.email "your@email.com"
git config --global user.name "clucas56"
git config --global credential.helper store
git clone https://clucas56:<personal-access-token>@github.com/clucas56/formula1-db.git
```

### What .gitignore Excludes

```
.env        <- credentials — never commit
logs/       <- log files
\_\_pycache\_\_ <- Python compiled files
\*.pyc
```

\---

## Firewall Rules

### Critical Rule — Allow SSH Before Enabling

```bash
ufw allow 22/tcp     # SSH — ALWAYS first
ufw allow 5432/tcp   # PostgreSQL
ufw enable
```

\---

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

\---

## Incremental Load Pipeline

### How it Works

```
1. Fetch latest completed race from Jolpica API
2. Check if race already exists in database
3. If new — insert race and season details
4. Load race results, qualifying, sprint, standings
5. All steps use upsert — idempotent and safe to rerun
```

### Manual Backfill

```bash
python3 pipeline/incremental\_load.py 2026 1
```

Pass season and round as arguments to load any specific race.
Used to backfill Australia 2026 Round 1 which was missed by the
automated pipeline.

\---

## Cron Jobs

### Current Schedule (webster)

```bash
0 6 * * 1 cd /home/clucas/formula1-db && python3 pipeline/incremental_load.py
```

> **Note:** autossh tunnels were previously managed via `@reboot` crontab entries.
> They are now managed as systemd services (`autossh-f1-flask` and
> `autossh-f1-postgres`) with `Restart=always` for better reliability after
> power outages. See the SSH Tunnel Setup section for details.

\---

## How It All Connects — End to End Flow

### Web Request Flow (f1.charleslucas562.com)

```
1. Browser requests f1.charleslucas562.com
2. Cloudflare receives request and routes through tunnel
3. cloudflared on webster passes to Apache on localhost:80
4. Apache virtual host matches f1.charleslucas562.com
5. Apache proxies through SSH tunnel to localhost:5000
6. SSH tunnel forwards to gunicorn on debian-app:5000
7. gunicorn passes to Flask worker process
8. Flask queries PostgreSQL views on debian-db directly
9. PostgreSQL returns data
10. Flask renders HTML template with data
11. Response travels back through the chain to the browser
```

### Auto Deploy Flow

```
1. Code change made in VSCode on Windows
2. git push to GitHub
3. GitHub fires webhook POST to f1.charleslucas562.com/webhook
4. Flask verifies HMAC signature
5. git pull on /var/www/formula1-db
6. systemctl restart f1-app (background)
7. New code is live within seconds
```

### Weekly Data Flow (every Monday 6am)

```
1. Cron triggers incremental\_load.py on webster
2. autossh keeps SSH tunnels alive
3. Python connects to PostgreSQL via tunnel
4. Script fetches latest race from Jolpica API
5. Upserts race, results, qualifying, standings
6. Log written to logs/incremental/
```

\---

## Key Concepts Learned

### Linux / Server Admin

* **KVM/libvirt** — Linux hypervisor for running virtual machines
* **virsh** — command line tool to manage KVM VMs
* **virbr0 vs macvtap** — two types of virtual networking with different tradeoffs
* **ufw** — Linux firewall whitelist based everything blocked by default
* **cron** — Linux task scheduler for automated jobs
* **systemctl** — manages Linux services (start, stop, status, enable)
* **systemd service files** — define how a service runs, who runs it, when it starts
* **Static IP** — prevents VM IP from changing on reboot
* **SSH keys** — passwordless authentication using public/private key pairs
* **autossh** — keeps SSH tunnels alive automatically
* **chmod 600** — file readable/writable by owner only, used for credential files
* **Service accounts** — dedicated non-login users for running services securely
* **git core.sharedRepository** — ensures group write permissions on git objects

### Networking

* **SSH tunnel** — routes traffic through an intermediate server
* **Port forwarding** — `-L local\_port:remote\_host:remote\_port`
* **NAT** — how virbr0 VMs reach the internet through the host
* **Firewall whitelist** — block everything allow only what you need
* **Reverse proxy** — Apache sitting in front of Flask forwarding requests
* **Cloudflare Tunnel** — exposes local services to internet without open ports

### Web / Flask

* **Flask** — Python micro web framework, routes HTTP requests to functions
* **gunicorn** — production WSGI server, runs multiple Flask worker processes
* **WSGI** — standard interface between Python web apps and web servers
* **Virtual environment** — isolated Python package environment per project
* **Jinja2 templating** — Flask's HTML template engine with {{ }} syntax
* **Routes** — @app.route decorators map URLs to Python functions
* **Dynamic routing** — URL segments captured as variables e.g. /race/[int:season](int:season)/[int:round](int:round)
* **render\_template** — passes data from Python to HTML templates
* **subprocess.Popen vs run** — Popen fires and forgets, run waits for completion
* **markdown library** — converts markdown files to HTML for the docs page

### Security / DevOps

* **HMAC SHA-256** — cryptographic signature verification for webhooks
* **Webhook secret** — shared secret between GitHub and Flask to verify requests
* **sudoers** — grants specific commands to specific users without full sudo
* **Service account** — minimal permission user for running services
* **Popen for self-restart** — fire and forget so Flask can respond before dying
* **git sharedRepository** — group permission setting prevents webhook pull failures

### PostgreSQL / Databases

* **Relational schema** — tables linked by foreign keys
* **Third normal form (3NF)** — store each fact once reference by ID
* **Unique constraint** — prevents duplicate combinations
* **pg\_hba.conf** — PostgreSQL access control file
* **Transactions** — BEGIN/COMMIT/ROLLBACK for safe bulk operations
* **ON CONFLICT DO UPDATE** — upsert syntax in PostgreSQL
* **Views** — saved queries in the database, simplify application code
* **EXTRACT(YEAR FROM CURRENT\_DATE)** — dynamic current year in SQL

### Python Data Engineering

* **psycopg2** — Python PostgreSQL connector
* **python-dotenv** — loads .env files into environment variables
* **ETL pattern** — Extract (API) Transform (clean/map) Load (database)
* **Upsert** — ON CONFLICT DO UPDATE — insert or update never duplicate
* **Idempotency** — running multiple times produces the same result
* **sys.argv** — command line arguments in Python scripts
* **subprocess** — running shell commands from Python

### Git / DevOps

* **Personal access token** — GitHub authentication not password
* **Webhook** — GitHub HTTP callback on push events
* **CI/CD pipeline** — automated deploy on every git push
* **.gitignore** — prevents sensitive files from being committed

\---

---

## Power Outage Recovery — Full Boot Checklist

After a full power loss, everything should come back automatically if the
following is configured. Run this checklist once to verify all autostart
settings are in place.

### On IBM-BASEMENT (run once to configure)

```bash
# Enable all VMs to autostart on host boot
virsh autostart debian-db
virsh autostart debian-app
virsh autostart clawmachine

# Verify — Autostart column should show 'yes' for all three
virsh list --all
```

### On debian-db

```bash
systemctl enable postgresql
```

### On debian-app

```bash
systemctl enable f1-app
```

### On clawmachine

```bash
sudo systemctl enable ollama
systemctl --user enable openclaw-gateway.service
sudo loginctl enable-linger clucas
loginctl show-user clucas | grep Linger   # verify: Linger=yes
```

### On webster

```bash
sudo systemctl enable apache2
sudo systemctl enable cloudflared
sudo systemctl enable autossh-f1-flask
sudo systemctl enable autossh-f1-postgres
```

### Expected boot order after power restoration

```
1. IBM-BASEMENT powers on (RHEL host)
2. libvirtd starts → VMs autostart (debian-db, debian-app, clawmachine)
3. webster boots (macvtap, already on home network)
4. debian-db: PostgreSQL comes up
5. debian-app: f1-app (gunicorn/Flask) comes up — connects to debian-db directly
6. clawmachine: ollama + openclaw-gateway come up
7. webster: apache2, cloudflared, autossh-f1-flask, autossh-f1-postgres come up
8. autossh services retry every 10s until debian-app and debian-db are reachable
9. f1.charleslucas562.com is live — no manual intervention needed
```

\---
## Troubleshooting

### SSH into VMs from RHEL Host

```bash
ssh root@192.168.122.236    # debian-db
ssh root@192.168.122.100    # debian-app
ssh clucas@192.168.4.7      # webster
```

### Flask service not starting

```bash
systemctl status f1-app
journalctl -u f1-app -n 50 --no-pager
```

Common causes:

* .env file not found or wrong permissions
* venv path wrong in service file
* Port 5000 already in use
* f1app user does not own /var/www/formula1-db

### f1.charleslucas562.com not loading

Work through the chain:

```bash
systemctl status f1-app                          # Flask running?
ps aux | grep autossh                            # Tunnels alive?
curl http://localhost:5000                       # Tunnel works on webster?
curl -H "Host: f1.charleslucas562.com" http://localhost  # Apache proxying?
systemctl status cloudflared                     # Cloudflare tunnel up?
tail -50 /var/log/apache2/f1-app-error.log       # Apache errors?
```

### Webhook deploy failing

```bash
sudo journalctl -u f1-app -n 30 --no-pager
```

Common causes:

* Git permission error on .git/objects — run:
`sudo chown -R clucas:f1app /var/www/formula1-db \&\& sudo chmod -R 775 /var/www/formula1-db`
Then set: `git config core.sharedRepository group`
* Full path required for git/sudo in subprocess — use /usr/bin/git, /usr/bin/sudo
* systemctl restart kills the worker — use Popen not run

### cloudflared fails to start (YAML error)

```bash
cat /etc/cloudflared/config.yml   # check for duplicate keys
nano /etc/cloudflared/config.yml  # rewrite cleanly
systemctl restart cloudflared
```

### PostgreSQL not accepting connections

```bash
pg\_lsclusters
systemctl status postgresql@17-main
ss -tlnp | grep 5432
tail -50 /var/log/postgresql/postgresql-17-main.log
```

### SSH tunnel drops

```bash
pkill -f "ssh -L 5432"
pkill -f "ssh -L 5000"
```

### Git authentication failing (403)

```bash
git remote set-url origin https://clucas56:<token>@github.com/clucas56/formula1-db.git
```

\---

## Next Steps

### Immediate

* \[x] GitHub webhook for auto-deploy
* \[x] Dashboard styling
* \[x] Constructor standings
* \[x] Race history page with dynamic routing
* \[x] Documentation page
* \[ ] Add pit stop data (endpoint needs investigation)

### AI Layer

* \[ ] Build query\_engine.py using Claude API
* \[ ] Text-to-SQL — ask questions in plain English against the F1 database
* \[ ] Migrate to Azure OpenAI once AZ-900 certified

### Data Enhancements

* \[ ] Add lap times via OpenF1 API (live during race weekends)
* \[ ] Historical data validation queries

### Infrastructure

* \[ ] Make GitHub repo public as portfolio piece
* \[ ] Consider upgrading RHEL 7 host to Rocky Linux 8/9

\---

## Azure Equivalent Architecture

|Home Lab Component|Azure Service|
|-|-|
|Debian VM + PostgreSQL|Azure Database for PostgreSQL Flexible Server|
|debian-app + Flask + gunicorn|Azure App Service (Python)|
|Apache reverse proxy|Azure Application Gateway / Front Door|
|Cloudflare Tunnel|Azure Public IP + DNS Zone|
|Python pipeline scripts|Azure Data Factory Pipelines|
|Cron schedule|ADF Scheduled Trigger|
|SSH tunnel|Azure Private Link / VNet Peering|
|.env credentials|Azure Key Vault|
|GitHub repo + webhook|Azure DevOps / GitHub Actions|
|Logs folder|Azure Monitor / Log Analytics|
|Claude API query engine|Azure OpenAI Service|
|pgAdmin|Azure Data Studio|
|systemd service|Azure App Service always-on setting|
|Database views|Azure SQL Views / Synapse Views|
|f1app service account|Azure Managed Identity|
|HMAC webhook verification|Azure API Management + API Key|
|Dynamic Flask routes|Azure API Management routing|

This project is a proof of concept for a real Azure data platform.
Everything built here maps 1:1 to enterprise Azure architecture making it
a strong portfolio piece for DP-100, AI-102, and data engineering roles.

