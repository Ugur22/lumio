# Deploying Lumio on one EC2 instance

One Ubuntu instance: Caddy (HTTPS + basic auth) in front of uvicorn, which also serves the built frontend. Chats (SQLite), profiles and keys live in `/var/lib/lumio`; a release only ever replaces `/opt/lumio`.

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

## Chat database (SQLite)
Chats are rows in `/var/lib/lumio/lumio.db` (`DOLPHINLLM_DB_FILE`). Images stay as files under `/var/lib/lumio/chats/images`. The database runs in WAL mode, so next to it you will see `lumio.db-wal` and `lumio.db-shm`: they belong to it, so never copy or delete them separately. Several uvicorn workers may share the file. A reply in a chat takes a lease row, so a second send to that chat gets `409` while other chats carry on; a lease whose process died expires after 60 s.

### Migrating from JSON chat files (once, when first deploying this version)
The release never changes or deletes the old `/var/lib/lumio/chats/*.json` files. On its first start with a database the app imports them itself (once; deleting a chat later does not bring it back from its leftover file). Running the import by hand first, as below, lets you read the report before anything goes live.
```
# 1. Backup: EBS snapshot first, then a copy of the originals
sudo systemctl stop lumio
sudo cp -a /var/lib/lumio/chats /var/lib/lumio/chats.bak-$(date +%F)

# 2. Ship the release (see above) but do not start it yet, then look before writing
cd /opt/lumio
sudo -u lumio env DOLPHINLLM_DATA_DIR=/var/lib/lumio/chats DOLPHINLLM_DB_FILE=/var/lib/lumio/lumio.db .venv/bin/python -m chat_migration import

# 3. Import. Exit status 1 means some files were skipped or differed on read-back: read the messages before going on
sudo -u lumio env DOLPHINLLM_DATA_DIR=/var/lib/lumio/chats DOLPHINLLM_DB_FILE=/var/lib/lumio/lumio.db .venv/bin/python -m chat_migration import --apply

# 4. Start and check the chat list in the browser (the import in step 3 also tells the app not to repeat it)
sudo systemctl start lumio
```
The import is safe to repeat: chats already in the database are skipped and never overwritten.

### Rolling back
- **Nothing was written after the cutover** (or you do not need those chats): stop the service, deploy the previous release, start it. The original JSON files are still there.
- **You want the chats made or changed since the cutover**: export them before going back.
```
sudo systemctl stop lumio
sudo mv /var/lib/lumio/chats /var/lib/lumio/chats.before-rollback   # keeps the originals and the images
sudo mkdir /var/lib/lumio/chats && sudo chown lumio:lumio /var/lib/lumio/chats && sudo chmod 700 /var/lib/lumio/chats
cd /opt/lumio && sudo -u lumio env DOLPHINLLM_DB_FILE=/var/lib/lumio/lumio.db .venv/bin/python -m chat_migration export --to /var/lib/lumio/chats
sudo mv /var/lib/lumio/chats.before-rollback/images /var/lib/lumio/chats/images
# deploy the previous release, then: sudo systemctl start lumio
```
`export` refuses to write over existing files unless `--force`. Keep `lumio.db` until you are sure; none of this deletes it.

## Backups and updates
- The database is one live file, so do not copy it while the app runs. Back it up with `sudo -u lumio sqlite3 /var/lib/lumio/lumio.db ".backup '/var/lib/lumio/backup/lumio-$(date +%F).db'"` (safe while running; create the `backup` directory first), or rely on the EBS snapshot, which is crash-consistent in WAL mode.
- Snapshot the EBS volume daily (Data Lifecycle Manager or AWS Backup). The snapshots contain `secrets.json`, so treat them as sensitive.
- `unattended-upgrades` handles OS security patches; reboot now and then.

## Limits to know
- The generation lease uses the server's wall clock: a large clock jump while a reply streams could let a second send start in that chat.
- One shared password: everyone who has it sees all chats and can use and change all providers.
- If the host or password changes, update the Caddyfile and `DOLPHINLLM_PUBLIC_HOST` together.
