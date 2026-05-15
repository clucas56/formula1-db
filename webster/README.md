# webster/ — Edge VM configuration

**These files do NOT deploy with the Docker stack.** They are configuration
for the **webster VM**, which stays in service as the edge / ingress host.

## Why webster stays

webster hosts the portfolio site at `charleslucas562.com` (production) and
runs the Cloudflare tunnel. Rather than move that, the F1 rebuild keeps
webster as the edge VM and slots the new Docker host in behind it.

```
Internet → Cloudflare → tunnel → webster (Apache)
                                   ├── charleslucas562.com      → portfolio (untouched)
                                   └── f1.charleslucas562.com   → Docker host :8000
                                                                       ↓
                                                              api → postgres
                                                              ingestion
```

## Files

| File | Goes where on webster | Purpose |
|---|---|---|
| `f1.charleslucas562.com.conf` | `/etc/apache2/sites-available/` | Apache vhost — reverse proxies the F1 subdomain to the Docker host |
| `f1-tunnel.service.txt` | `/etc/systemd/system/f1-tunnel.service` | autossh tunnel (webster → Docker host:8000), if not using a static route |

## What changes on webster (and what doesn't)

**Changes:**
- One new/replaced Apache vhost for `f1.charleslucas562.com`
- One autossh tunnel (replacing the old two tunnels to debian-db + debian-app)

**Does NOT change:**
- The portfolio vhost for `charleslucas562.com`
- The Cloudflare tunnel config / credentials
- Anything else on webster

## Pre-flight (do before touching webster)

webster is production now. Back up before editing:

```bash
mkdir -p ~/apache-backup ~/cloudflared-backup
sudo cp -r /etc/apache2/sites-available/ ~/apache-backup/
sudo cp -r /etc/cloudflared/ ~/cloudflared-backup/
```

The old F1 vhost and the two old autossh tunnels (to debian-db and
debian-app) can be removed once the new path is verified — those VMs are
destroyed in HANDOFF Phase 7, so the old tunnels die anyway.
