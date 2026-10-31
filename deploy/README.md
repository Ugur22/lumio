# Deploying Lumio on one EC2 instance

One Ubuntu instance: Caddy (HTTPS) in front of uvicorn, which also serves the built frontend and handles sign-in itself (accounts, registration by invite code only). Chats (SQLite), profiles and keys live in `/var/lib/lumio`, each owned by one account; a release only ever replaces `/opt/lumio`.

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
sudo mkdir -p /etc/lumio && sudo chown lumio:lumio /etc/lumio && sudo chmod 700 /etc/lumio
```
There is no password in the Caddyfile any more: people sign in to the app. The first account is created on the server (see Accounts).

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
Edit both files first (hostname, `DOLPHINLLM_ADMIN_USER`), and create the master key and the first account before the first start (see Accounts). Open the hostname, sign in, and add a provider and key in the Providers dialog. After later releases, `sudo systemctl restart lumio`.

## Accounts
Everyone has their own account, chats, providers and keys. Nobody can register without an invite code, and only you can make one. All commands run on the server from `/opt/lumio` as the `lumio` user, with the same environment as the service. Define this once per shell (the service's values contain no spaces):
```
cd /opt/lumio
lumio() { sudo -u lumio env $(systemctl show lumio -p Environment --value) .venv/bin/python -m "$@"; }
```
- **First account (an admin):** `lumio accounts create-user <name> --admin` (asks for the password). Do this before the first start of a release with accounts; then set `DOLPHINLLM_ADMIN_USER` in `lumio.service` to the same name.
- **Invite someone:** `lumio accounts invite` prints a single-use code, valid 7 days (`--days N`). It is shown once and stored hashed. They open the site, choose Create account and enter it.
- **Forgot a password:** `lumio accounts set-password <name>` (this also signs that account out everywhere). **Remove access:** `lumio accounts disable <name>`.
- Sign-in is rate limited (5 failures per 15 minutes per name and per address).

### Upgrading an existing single-password deployment
Chats, profiles and keys from before accounts become the admin's, once, at the first start.
```
# 1. Backup first: EBS snapshot, then
sudo systemctl stop lumio
sudo -u lumio sqlite3 /var/lib/lumio/lumio.db ".backup '/var/lib/lumio/backup/pre-accounts.db'"
sudo cp -a /var/lib/lumio/secrets.json /var/lib/lumio/secrets.json.pre-accounts
sudo cp -a /var/lib/lumio/profiles.json /var/lib/lumio/profiles.json.pre-accounts

# 2. Ship the release, pip install -r requirements.txt, create the master key (see Backups), then the admin account (above)
# 3. Set DOLPHINLLM_ADMIN_USER in lumio.service, copy the unit, daemon-reload, and replace deploy/Caddyfile (no basic_auth)
sudo systemctl start lumio && sudo systemctl reload caddy
```
At that start the app assigns the unowned chats to the admin, encrypts `secrets.json`, and moves the old profiles and keys to the admin's own files. The old global `profiles.json` is removed once its contents are in the admin's files, so the `.pre-accounts` copies are the only leftovers: check that the admin sees everything, then delete them (the plain `secrets.json.pre-accounts` holds the keys unencrypted). If the admin account or the master key is missing the app refuses to start and tells you which. It also refuses to start when `DOLPHINLLM_SECRETS_FILE`, a master key or `DOLPHINLLM_ADMIN_USER` is set without `DOLPHINLLM_PUBLIC_HOST` (a missing or misspelt host would otherwise run the app without any login), and the `/docs`, `/redoc` and `/openapi.json` pages are off on a server.

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
- **Do not roll back past the accounts release by just deploying the old code.** This release stamps the database as schema version 2, so the previous release refuses to open it, on purpose: that release has no per-user scoping and, without the Caddy `basic_auth` block, would show every user's chats to anyone. To go back that far, restore the pre-accounts database backup (`pre-accounts.db`, and the `.pre-accounts` copies of `secrets.json` and `profiles.json`), put the `basic_auth` block back in the Caddyfile and reload Caddy first, then deploy the old release. Chats made after the cutover are not in that backup.
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
- `secrets.json` holds the API keys encrypted (Fernet). The master key is in `/etc/lumio/secret.key` (`sudo sh -c 'umask 077; .venv/bin/python -m secret_store new-key > /etc/lumio/secret.key'`, owned by `lumio`), not under `/var/lib/lumio`, so snapshots do not carry both. Back the key up separately: without it the keys must be re-entered. To rotate, put the new key first and the old after it, comma-separated, in that file, restart, run `python -m secret_store rotate`, then drop the old key. The app refuses to start when the secrets file is configured and no key is.
- `unattended-upgrades` handles OS security patches; reboot now and then.

## Limits to know
- The generation lease uses the server's wall clock: a large clock jump while a reply streams could let a second send start in that chat.
- Accounts are separate: nobody sees another account's chats, providers or keys. The admin flag is only a marker for now; it gives no access to other people's data.
- Sign-in lives in the app, so uvicorn must stay on 127.0.0.1 behind Caddy: the app takes the client address from the proxy for rate limiting.
- A password reset is a command on the server (`set-password`); there is no email.
- Five failed sign-ins for a username lock that username for 15 minutes, so a stranger who knows a username can keep its owner out of signing in. This is accepted: the alternative is no limit on guessing.
- Provider URLs on a server must resolve to public addresses (checked when saved and on every request); a provider on the server's own network, such as a local Ollama, cannot be used there.
- If the host or password changes, update the Caddyfile and `DOLPHINLLM_PUBLIC_HOST` together.
