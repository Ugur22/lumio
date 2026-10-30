# Deploying Lumio on one EC2 instance

One Ubuntu instance: Caddy (HTTPS + basic auth) in front of uvicorn, which also serves the built frontend. Chats, profiles and keys live in `/var/lib/lumio`.

## AWS side (console)
1. EC2 in eu-north-1: Ubuntu 24.04 LTS, `t3.micro` (or whatever the free plan allows), 20 GB gp3. Under Advanced, set **Metadata version: V2 only** and **Metadata response hop limit: 1**.
2. Security group: 80 and 443 from anywhere, 22 from **your IP only**. Key-pair login only.
3. Allocate an **Elastic IP** and attach it, so the address and hostname survive a stop/start. The hostname is `<ip with dashes>.sslip.io` (Let's Encrypt refuses the `ec2-*.amazonaws.com` names).
4. Attach no IAM role.
5. Set a spend limit on every provider key you add later.

## Server setup (once)
```
sudo apt update && sudo apt install -y python3-venv rsync unattended-upgrades
sudo useradd --system --home /opt/lumio --shell /usr/sbin/nologin lumio
sudo mkdir -p /opt/lumio /var/lib/lumio/logs
sudo chown -R lumio:lumio /var/lib/lumio && sudo chmod 700 /var/lib/lumio
sudo chown "$USER" /opt/lumio

sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy
caddy hash-password          # paste the hash into deploy/Caddyfile
```
Use a long random password (20+ characters) from a password manager.

## Ship the code (from your laptop, each release)
The frontend is built locally, so the server needs no Node. The excludes keep your local secrets, saved chats and profiles off the server.
```
make build
rsync -a --delete --exclude .git --exclude .venv --exclude '.env*' --exclude '/data' --exclude logs \
  --exclude profiles.json --exclude .claude --exclude .agents --exclude __pycache__ \
  --exclude frontend/node_modules --exclude frontend/dist \
  ./ ubuntu@<hostname>:/opt/lumio/
rsync -a --delete frontend/dist/ ubuntu@<hostname>:/opt/lumio/frontend/dist/
```
Then on the server:
```
cd /opt/lumio && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
sudo cp deploy/lumio.service /etc/systemd/system/ && sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
sudo systemctl daemon-reload && sudo systemctl enable --now lumio && sudo systemctl reload caddy
```
Edit both files first (hostname, password hash). Open the hostname, log in, and add a provider and key in the Providers dialog. After later releases, `sudo systemctl restart lumio`.

## Backups and updates
- Snapshot the EBS volume daily (Data Lifecycle Manager or AWS Backup). The snapshots contain `secrets.json`, so treat them as sensitive.
- `unattended-upgrades` handles OS security patches; reboot now and then.

## Limits to know
- One shared password: everyone who has it sees all chats and can use and change all providers.
- If the host or password changes, update the Caddyfile and `DOLPHINLLM_PUBLIC_HOST` together.
