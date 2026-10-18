# Self-hosting DealScour

One container runs the API and the web app. Caddy sits in front for HTTPS. The data is a single SQLite file on a Docker volume.
You bring your own keys (ADR-022), and any feature whose key is empty stays off.

## 1. Requirements
- A machine that's always on: a ₹300–500/month VPS, a home mini-PC or Raspberry Pi 4/5, or a free-tier VM.
- Docker with the Compose plugin.
- For access from phones outside your home: either a domain pointing at the machine (ports 80/443 open), or
  [Tailscale](https://tailscale.com) / Cloudflare Tunnel (no open ports).

## 2. Configure
```bash
git clone https://github.com/NaikDeepak/deal-scour.git && cd deal-scour
cp .env.example .env
# Edit .env:
#   DEALSCOUR_SECRET_KEY   → output of: python3 -c "import secrets; print(secrets.token_urlsafe(32))"
#   DEALSCOUR_OWNER_EMAIL  → your email (you'll be the household owner)
#   SMTP_*                 → any SMTP provider, used to email sign-in codes
#   DEALSCOUR_DOMAIN       → deals.example.com (omit for http://localhost)
#   everything else is optional; leave empty to keep that feature off
```

## 3. Run
```bash
docker compose up -d --build
docker compose logs -f app        # migrations run automatically on start
```
Open `https://<your domain>` (or `http://localhost`) and sign in with `DEALSCOUR_OWNER_EMAIL`. Invite family from the **Family** tab.
On a phone, use **Add to Home Screen** to install it like an app.

## 4. Back up (do this)
The database lives in the `dealscour-data` volume. Add a nightly backup on the host:
```bash
crontab -e
# 0 3 * * *  cd /path/to/deal-scour && docker compose exec -T app python scripts/backup.py --keep 14
```
Backups go to `/data/backups` in the volume. To copy them off the machine, add a second cron line with `docker compose cp` or `rclone`.

## 5. Update
```bash
git pull && docker compose up -d --build
```

## 6. Restore
```bash
docker compose stop app
docker compose cp ./dealscour-YYYYMMDD-HHMMSS.db app:/data/dealscour.db
docker compose start app
```
