# Deploying Lumio on one EC2 instance

One Ubuntu instance: Caddy (HTTPS) in front of uvicorn, which serves the built frontend and handles sign-in itself (invite-only accounts). Chats, profiles and keys live in `/var/lib/lumio`, each owned by one account; a release only replaces `/opt/lumio`.

## AWS side (console)
1. EC2 in eu-north-1: Ubuntu 24.04 LTS, `t3.micro`, 20 GB gp3. Under Advanced, set **Metadata version: V2 only** and **Metadata response hop limit: 1**.
2. Security group: 80 and 443 from anywhere, 22 from **your IP only**. Key-pair login only.
3. Attach an **Elastic IP**, so the address survives a stop/start. The hostname is `<ip with dashes>.sslip.io` (Let's Encrypt refuses `ec2-*.amazonaws.com`).
4. Attach no IAM role. Set a spend limit on every provider key you add.

## Server setup (once)
```
sudo apt update && sudo apt install -y python3-venv rsync sqlite3 unattended-upgrades
sudo useradd --system --home /opt/lumio --shell /usr/sbin/nologin lumio
sudo mkdir -p /opt/lumio /var/lib/lumio/logs /etc/lumio
sudo chown -R lumio:lumio /var/lib/lumio /etc/lumio && sudo chmod 700 /var/lib/lumio /etc/lumio
sudo chown "$USER" /opt/lumio

sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy
```

## Deploy (every release)
From the repo root, on `main` with everything committed:
```
make deploy
```
It runs `make check` and `make build`, copies the code and `frontend/dist` to `/opt/lumio`, installs `requirements.txt`, restarts the service and prints whether it is active. The key and host default to `~/Downloads/lumio-keypair.pem` and `ubuntu@16-192-71-141.sslip.io`; override with `make deploy DEPLOY_KEY=... DEPLOY_HOST=...`.

Don't type the `rsync` by hand: it uses `--delete`, so an empty or wrong folder would wipe `/opt/lumio`.

When a release changes `deploy/lumio.service` or the Caddyfile, copy them again on the server, redo the `sed` from the first-deploy step 3 (the copy brings `CHANGE_ME` back), then `sudo systemctl daemon-reload && sudo systemctl restart lumio && sudo systemctl reload caddy`.

## First deploy (once)
1. Make sure the hostname in `deploy/lumio.service` (`DOLPHINLLM_PUBLIC_HOST`) and `deploy/Caddyfile` is yours and merged to `main`, then run `make deploy`. It copies the files, then fails at the restart because the service isn't installed yet. That is expected.
2. On the server, install the dependencies and create the master key:
```
cd /opt/lumio && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m secret_store new-key | sudo tee /etc/lumio/secret.key > /dev/null
sudo chown lumio:lumio /etc/lumio/secret.key && sudo chmod 400 /etc/lumio/secret.key
sudo cat /etc/lumio/secret.key
```
Put that key in a password manager: without it the saved API keys can't be decrypted.
3. Install the units, set the admin's name, and create the first account (the `lumio` helper is defined under Accounts):
```
sudo cp deploy/lumio.service /etc/systemd/system/ && sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
sudo sed -i 's/CHANGE_ME/<name>/' /etc/systemd/system/lumio.service && sudo systemctl daemon-reload
lumio accounts create-user <name> --admin
sudo systemctl enable --now lumio && sudo systemctl reload caddy
```
4. Open the hostname, sign in, and add a provider and key in the Providers dialog. The app refuses to start, and says why, if the admin account, the master key or `DOLPHINLLM_PUBLIC_HOST` is missing.

## Accounts
Everyone has their own chats, providers and keys. Nobody can register without an invite code. Run these on the server from `/opt/lumio`; define the helper once per shell:
```
cd /opt/lumio
lumio() { sudo -u lumio env $(systemctl show lumio -p Environment --value) .venv/bin/python -m "$@"; }
```
- **Invite someone:** `lumio accounts invite` prints a single-use code, valid 7 days (`--days N`). It is shown once. They choose Create account and enter it.
- **Forgot a password:** `lumio accounts set-password <name>` (signs that account out everywhere).
- **Remove access:** `lumio accounts disable <name>`.

## Backups
- Database: `sudo -u lumio mkdir -p /var/lib/lumio/backup && sudo -u lumio sqlite3 /var/lib/lumio/lumio.db ".backup '/var/lib/lumio/backup/lumio-$(date +%F).db'"`. Safe while the app runs. Never copy `lumio.db-wal` or `-shm` on their own.
- Snapshot the EBS volume daily (Data Lifecycle Manager or AWS Backup). `secrets.json` in it is encrypted, but treat snapshots as sensitive.
- The master key lives in `/etc/lumio/secret.key`, outside `/var/lib/lumio`, so a snapshot doesn't carry both. Keep a separate copy. To rotate: put the new key first and the old one after it, comma-separated, in that file, restart, run `python -m secret_store rotate`, then drop the old key.
- `unattended-upgrades` patches the OS; reboot now and then.

## Rolling back
- **Past the accounts release:** don't just deploy the old code. The database is stamped schema version 2, so the old release refuses to open it, on purpose: it has no per-user scoping and, without Caddy's `basic_auth`, would show every chat to anyone. Restore a backup taken before the accounts release, put the `basic_auth` block back in the Caddyfile and reload Caddy, then deploy the old release. Chats made after the upgrade aren't in that backup.
- **Anything else:** revert the change on `main` and run `make deploy`.

## Limits to know
- The generation lease uses the server's wall clock: a large clock jump while a reply streams could let a second send start in that chat.
- uvicorn must stay on 127.0.0.1 behind Caddy: the app takes the client address from the proxy for rate limiting.
- Five failed sign-ins lock a username for 15 minutes, so a stranger who knows a username can keep its owner out. Accepted: the alternative is no limit on guessing.
- There is no password-reset email; use `set-password`.
- Provider URLs on a server must resolve to public addresses, so a local Ollama can't be used there.
- If the host changes, update the Caddyfile and `DOLPHINLLM_PUBLIC_HOST` together.
