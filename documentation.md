# F1 Data Platform — Project Documentation

**Author:** clucas56  
**Last Updated:** March 2026  
**Repository:** github.com/clucas56/formula1-db

---

## Table of Contents

1. [Infrastructure Overview](#infrastructure-overview)
2. [IBM-BASEMENT — RHEL Host](#ibm-basement--rhel-host)
3. [Debian DB Server Setup](#debian-db-server-setup)
4. [PostgreSQL Setup](#postgresql-setup)
5. [Ubuntu Web Server](#ubuntu-web-server)
6. [SSH Tunnel Setup](#ssh-tunnel-setup)
7. [Python Pipeline](#python-pipeline)
8. [Database Schema](#database-schema)
9. [GitHub Version Control](#github-version-control)
10. [Firewall Rules](#firewall-rules)
11. [Network Topology](#network-topology)
12. [Troubleshooting](#troubleshooting)
13. [Next Steps](#next-steps)

---

## Infrastructure Overview

```
Windows Machine (pgAdmin, VSCode)
        ↓ SSH tunnel
RHEL IBM-BASEMENT (192.168.4.5) — Bare Metal Host
        ↓ KVM Hypervisor
        ├── Ubuntu VM — webster (192.168.4.7) — Web Server
        └── Debian VM — debian-db (192.168.122.236) — Database Server
                              ↓
                        PostgreSQL 17
                              ↓
                          f1_data DB
```

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
| Package Manager | yum |

### Key Commands
```bash
# List all VMs
virsh list --all

# Start a VM
virsh start <vm-name>

# Stop a VM gracefully
virsh shutdown <vm-name>

# Force stop a VM
virsh destroy <vm-name>

# Get VM IP address
virsh domifaddr <vm-name>

# Connect to VM console
virsh console <vm-name>

# Escape from console
Ctrl + ]
```

### KVM Network
- **virbr0** — Internal virtual bridge (192.168.122.x) — VM to VM communication
- **eno2** — Physical NIC connected to home network (192.168.4.x)
- Debian DB uses virbr0 (192.168.122.236)
- Ubuntu Web Server uses macvtap on eno2 (192.168.4.7)

> **Note:** macvtap VMs cannot communicate directly with each other on the same host. This is why an SSH tunnel is used for Ubuntu → Debian communication.

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

### Installation Process

#### 1. Create VM on RHEL Host
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

#### 2. Installer Choices
- **Partitioning:** Separate /var and /srv (recommended for database server)
- **Mirror:** deb.debian.org — United States
- **Software:** SSH server + standard system utilities ONLY (no desktop environment)
- **GRUB:** Install to /dev/vda

#### 3. First Boot — Firewall First (CRITICAL)
```bash
# ALWAYS set up firewall before anything else
apt update && apt install -y ufw
ufw allow 22/tcp     # SSH — MUST do this first or you lock yourself out
ufw allow 5432/tcp   # PostgreSQL
ufw enable
```

#### 4. Install Packages
```bash
apt install -y postgresql postgresql-contrib fastfetch htop tmux fail2ban git curl
```

#### 5. Configure Hostname
```bash
hostnamectl set-hostname debian-db
nano /etc/hosts
# Change: 127.0.1.1  debian-db
```

#### 6. Set Static IP
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

#### 7. Enable Root SSH Login
```bash
nano /etc/ssh/sshd_config
# Change: PermitRootLogin yes
systemctl restart sshd
```

#### 8. Fastfetch on Login
```bash
nano ~/.bashrc
# Add at bottom: fastfetch
```

#### 9. MOTD
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

### Version
PostgreSQL 17.9 (Debian 17.9-0+deb13u1)

### Installation
```bash
apt install -y postgresql postgresql-contrib
```

### Configuration

#### Set postgres password and create F1 database
```bash
su - postgres
psql
```
```sql
\password postgres
CREATE DATABASE f1_data;
CREATE USER f1user WITH PASSWORD 'yourpassword';
GRANT ALL PRIVILEGES ON DATABASE f1_data TO f1user;
\c f1_data
GRANT ALL ON SCHEMA public TO f1user;
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

#### Allow network connections in pg_hba.conf
```bash
nano /etc/postgresql/17/main/pg_hba.conf
```
Add these lines at the bottom:
```
host    all             all             192.168.122.0/24        md5
host    all             all             127.0.0.1/32            md5
```

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

### Connect to PostgreSQL locally
```bash
psql -h 127.0.0.1 -U f1user -d f1_data
```

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
# Check Python version
python3 --version

# Install pip packages
pip3 install psycopg2-binary python-dotenv

# Install PostgreSQL client for testing
sudo apt install -y postgresql-client
```

### Project Location
```
/home/clucas/formula1-db/
├── .env                    ← credentials (hidden, never commit to git)
├── .gitignore
├── README.md
├── database/
│   └── schema.sql          ← table definitions
├── pipeline/
│   ├── setup_db.py         ← creates tables
│   └── fetch_data.py       ← pulls F1 API data (in progress)
├── web/
│   └── index.html          ← dashboard frontend
└── ai/
    └── query_engine.py     ← AI text-to-SQL layer (planned)
```

### .env File
```
DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=f1_data
DB_USER=f1user
DB_PASSWORD=yourpassword
```
> The `.env` file is hidden (starts with `.`). Use `ls -la` to see it.
> It is listed in `.gitignore` and should NEVER be committed to GitHub.

---

## SSH Tunnel Setup

Since the Ubuntu web server (macvtap/192.168.4.7) and Debian DB server (virbr0/192.168.122.236) are on different networks and macvtap VMs cannot communicate directly, an SSH tunnel through the RHEL host is used.

### How it Works
```
Ubuntu (192.168.4.7)
    ↓ SSH tunnel
RHEL IBM-BASEMENT (192.168.4.5)
    ↓ virbr0
Debian DB (192.168.122.236:5432)
```

### Start the Tunnel
```bash
ssh -L 5432:192.168.122.236:5432 root@192.168.4.5 -N -f
```

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

### Make Tunnel Persistent (auto-restart on reboot)
```bash
sudo apt install autossh
crontab -e
# Add: @reboot autossh -M 0 -f -N -L 5432:192.168.122.236:5432 root@192.168.4.5
```

> **Important:** The tunnel must be running before executing any Python scripts that connect to the database.

---

## Python Pipeline

### setup_db.py
Creates all database tables by executing schema.sql against PostgreSQL.

```python
import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

def setup_database():
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD")
    )
    cursor = conn.cursor()
    with open("database/schema.sql", "r") as f:
        cursor.execute(f.read())
    conn.commit()
    cursor.close()
    conn.close()
    print("Database schema created successfully!")

if __name__ == "__main__":
    setup_database()
```

### How to Run
```bash
# Make sure SSH tunnel is running first
ssh -L 5432:192.168.122.236:5432 root@192.168.4.5 -N -f

# Must run from project root
cd ~/formula1-db
python3 pipeline/setup_db.py
```

---

## Database Schema

### Tables
| Table | Purpose |
|---|---|
| seasons | F1 seasons (years) |
| circuits | Race tracks |
| drivers | Driver information |
| constructors | Team information |
| races | Race calendar |
| race_results | Race finishing positions and points |
| qualifying_results | Q1/Q2/Q3 times |
| sprint_results | Sprint race results |
| driver_standings | Championship standings per round |
| constructor_standings | Constructor championship per round |
| lap_times | Individual lap data (historical + live) |
| pit_stops | Pit stop data |

### Data Sources
- **Jolpica API** (https://api.jolpi.ca/ergast/) — Historical data, no API key required
- **OpenF1 API** (https://openf1.org/) — Live timing during race weekends, no API key required

---

## GitHub Version Control

### Repository
- **URL:** github.com/clucas56/formula1-db
- **Visibility:** Private (to be made public when ready)
- **Branch strategy:** main (stable) / dev (active development)

### Setup on Ubuntu Server
```bash
git config --global user.email "your@email.com"
git config --global user.name "clucas56"
git config --global credential.helper store
git clone https://clucas56:<token>@github.com/clucas56/formula1-db.git
```

### Daily Workflow
```bash
git add .
git commit -m "describe your changes"
git push
```

---

## Firewall Rules

### Debian DB Server (ufw)
```bash
ufw allow 22/tcp     # SSH
ufw allow 5432/tcp   # PostgreSQL
ufw allow from 192.168.122.0/24 to any port 5432  # KVM network
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
    ├── KVM Hypervisor
    │     ├── virbr0 (192.168.122.x internal)
    │     │     └── debian-db (192.168.122.236) — PostgreSQL
    │     └── macvtap → eno2
    │           └── webster/ubuntu20.04 (192.168.4.7) — Web Server
    └── SSH Tunnel bridges the two networks
```

---

## Troubleshooting

### SSH into Debian VM from RHEL Host
```bash
ssh root@192.168.122.236
```

### SSH locked out of VM (forgot to allow port 22 before enabling ufw)
```bash
# From RHEL host use virsh console as backdoor
virsh console debian-db --force
# Then fix firewall:
ufw allow 22/tcp
ufw reload
```

### PostgreSQL not accepting connections
```bash
# Check cluster is running
pg_lsclusters

# Check logs
tail -50 /var/log/postgresql/postgresql-17-main.log

# Check pg_hba.conf has correct entries
cat /etc/postgresql/17/main/pg_hba.conf | tail -10

# Restart PostgreSQL
systemctl restart postgresql@17-main
```

### SSH tunnel drops or port already in use
```bash
# Kill all tunnel processes
pkill -f "ssh -L 5432"

# Verify port is free
ss -tlnp | grep 5432

# Restart tunnel
ssh -L 5432:192.168.122.236:5432 root@192.168.4.5 -N -f
```

### VM has duplicate IPs
```bash
# Check IPs
ip a show ens3

# Remove stale IP
ip addr del 192.168.122.235/24 dev ens3

# Set static IP in /etc/network/interfaces to prevent recurrence
```

### Python script can't find .env file
```bash
# Always run from project root
cd ~/formula1-db
python3 pipeline/setup_db.py
```

---

## Next Steps

- [ ] Write `fetch_data.py` to pull F1 data from Jolpica API
- [ ] Load historical race data into PostgreSQL
- [ ] Set up cron job for scheduled data updates
- [ ] Build web dashboard (index.html + Flask backend)
- [ ] Implement AI text-to-SQL query layer using Claude API
- [ ] Set up GitHub webhook for auto-deploy to Ubuntu web server
- [ ] Make tunnel persistent with autossh
- [ ] Migrate to Azure (PostgreSQL → Azure DB, Pipeline → ADF, AI → Azure OpenAI)
- [ ] Make GitHub repo public as portfolio piece
