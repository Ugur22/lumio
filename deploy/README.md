# Deploying Lumio on one EC2 instance

One Ubuntu instance: Caddy terminates HTTPS and proxies to uvicorn on `127.0.0.1:8000`; uvicorn serves the built frontend and handles sign-in itself (invite-only accounts, no `basic_auth` in Caddy). Releases replace `/opt/lumio`; all data lives in `/var/lib/lumio`.

- [Routine release](#routine-release)
- [First-time setup](#first-time-setup)
- [Accounts](#accounts)
- [Configuration and storage](#configuration-and-storage)
- [Backups and the master key](#backups-and-the-master-key)
- [Rolling back](#rolling-back)
- [Limits to know](#limits-to-know)

## Routine release

From the repo root, on `main` with no uncommitted changes to tracked files:

```sh
make deploy
```

It runs `make check` and `make build`, refuses to continue unless you are on `main` with a clean tracked tree and the key file exists, then rsyncs the tree and `frontend/dist` to `/opt/lumio`, runs `pip install -r requirements.txt`, restarts the `lumio` service and prints `systemctl is-active`. The restart interrupts replies that are streaming at that moment.

Overrides (the defaults are `~/Downloads/lumio-keypair.pem` and `ubuntu@16-192-71-141.sslip.io`):

```sh
make deploy DEPLOY_KEY=/path/to/key.pem DEPLOY_HOST=ubuntu@<host>
```

Both are plain Make variables, so exporting them in your shell works too.

Don't run the `rsync` by hand: it uses `--delete`, so a wrong folder would wipe `/opt/lumio`. It excludes `.git`, `.venv`, `.env*`, `/data`, `logs`, `profiles.json`, `.claude`, `.agents`, `__pycache__`, `frontend/node_modules` and `frontend/dist` (the last is synced separately), so the virtualenv is kept.

### When the service file or Caddyfile changes

`make deploy` copies `deploy/lumio.service` and `deploy/Caddyfile` to `/opt/lumio/deploy/` but does not install them. After such a release, on the server:

```sh
cd /opt/lumio
admin=$(grep -oP '(?<=DOLPHINLLM_ADMIN_USER=).*' /etc/systemd/system/lumio.service)   # keep the current value
sudo cp deploy/lumio.service /etc/systemd/system/lumio.service
sudo sed -i "s/CHANGE_ME/$admin/" /etc/systemd/system/lumio.service
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sudo systemctl daemon-reload && sudo systemctl restart lumio && sudo systemctl reload caddy
```

If the new release needs a setting that only the new unit file has, `make deploy`'s own restart still runs with the old unit, and the app may refuse to start until you finish the steps above.

## First-time setup

### 1. AWS

1. EC2 in eu-north-1: Ubuntu 24.04 LTS, `t3.micro`, 20 GB gp3. Under Advanced, set **Metadata version: V2 only** and **Metadata response hop limit: 1**.
2. Security group: ports 80 and 443 from anywhere, 22 from **your IP only**. Key-pair login only.
3. Attach an **Elastic IP** so the address survives a stop/start. The hostname is `<ip with dashes>.sslip.io`; Let's Encrypt refuses `ec2-*.amazonaws.com`.
4. Attach no IAM role. Set a spend limit on every provider key you add.

### 2. Hostname

If the hostname is not the committed one (`16-192-71-141.sslip.io`), change it in `deploy/lumio.service` (`DOLPHINLLM_PUBLIC_HOST`), `deploy/Caddyfile` and the `DEPLOY_HOST` default in the `Makefile`, and merge to `main`. The service and Caddyfile must agree.

### 3. Prepare the server

Run on the server (SSH in with your key):

```sh
sudo apt update && sudo apt install -y python3-venv rsync sqlite3 unattended-upgrades openssl
sudo useradd --system --home /opt/lumio --shell /usr/sbin/nologin lumio
sudo mkdir -p /opt/lumio /var/lib/lumio/logs /etc/lumio
sudo chown -R lumio:lumio /var/lib/lumio /etc/lumio && sudo chmod 700 /var/lib/lumio /etc/lumio
sudo chown "$USER" /opt/lumio

sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy

python3 -m venv /opt/lumio/.venv
```

The empty virtualenv matters: `make deploy` runs `/opt/lumio/.venv/bin/pip` and would fail without it.

Create the master key. A Fernet key is 32 random bytes in URL-safe base64, which this produces:

```sh
openssl rand -base64 32 | tr '+/' '-_' | sudo tee /etc/lumio/secret.key > /dev/null
sudo chown lumio:lumio /etc/lumio/secret.key && sudo chmod 400 /etc/lumio/secret.key
sudo cat /etc/lumio/secret.key
```

Store that key in a password manager: without it the saved API keys cannot be decrypted. (`python -m secret_store new-key` makes an equivalent key, but needs the dependencies, which aren't installed yet.)

### 4. Install the service and Caddyfile

From your laptop, in the repo root (pick the admin username now; it is stored in the unit file):

```sh
export DEPLOY_KEY=~/Downloads/lumio-keypair.pem DEPLOY_HOST=ubuntu@<host>
scp -i "$DEPLOY_KEY" deploy/lumio.service deploy/Caddyfile "$DEPLOY_HOST":/tmp/
```

On the server:

```sh
sudo cp /tmp/lumio.service /etc/systemd/system/lumio.service
sudo sed -i 's/CHANGE_ME/<admin name>/' /etc/systemd/system/lumio.service
sudo cp /tmp/Caddyfile /etc/caddy/Caddyfile
sudo systemctl daemon-reload && sudo systemctl enable lumio && sudo systemctl reload caddy
```

### 5. First release

From your laptop:

```sh
make deploy
```

The service now exists, the virtualenv and master key are in place, so this should end with `active`. A fresh database has no chats to assign, so the app starts without any account yet. (`DOLPHINLLM_ADMIN_USER` must name an existing account only when chats or profiles from before accounts exist; see [UPGRADING.md](UPGRADING.md).)

### 6. First account

On the server, define the helper (explained under [Accounts](#accounts)), then create the admin with the same name you put in the unit file:

```sh
lumio() { (cd /opt/lumio && sudo -u lumio env $(systemctl show lumio -p Environment --value) .venv/bin/python -m "$@"); }
lumio accounts create-user <admin name> --admin
```

Open `https://<host>`, sign in, and add a provider and key in **Providers**.

## Accounts

Nobody can register without an invite code. All commands run on the server through the `lumio` helper defined in first-time step 6 (define it again in each new shell). It runs a Python module as the service user with the service's `Environment=` values, so it sees the same database, secrets file and master key.

- **Create an account:** `lumio accounts create-user <name> [--admin]` prompts for a password (10–128 characters; names are 3–32 letters, digits, `_` or `-`). The `--admin` flag matters for the account named in `DOLPHINLLM_ADMIN_USER`, which inherits pre-accounts chats and profiles; no other use of the admin flag was found in the backend.
- **Invite someone:** `lumio accounts invite` prints a single-use code, valid 7 days (`--days N`). It is shown once. They choose **Create account** and enter it.
- **Forgot a password:** `lumio accounts set-password <name>` signs that account out everywhere. There is no reset email.
- **Remove access:** `lumio accounts disable <name>` disables the account and ends its sessions.

## Configuration and storage

Settings are `Environment=` lines in `deploy/lumio.service`:

| Variable | Value | Purpose |
| --- | --- | --- |
| `DOLPHINLLM_PUBLIC_HOST` | the hostname | Turns on deployed mode (accounts, origin checks, public-address-only provider URLs). Must match the Caddyfile |
| `DOLPHINLLM_ADMIN_USER` | admin username | Owner of chats and profiles from before accounts; also keeps the legacy `.env` key. Needed to exist only while such data exists |
| `DOLPHINLLM_DATA_DIR` | `/var/lib/lumio/chats` | Chat images |
| `DOLPHINLLM_DB_FILE` | `/var/lib/lumio/lumio.db` | SQLite database: chats, accounts, sessions, invites |
| `DOLPHINLLM_PROFILES_FILE` | `/var/lib/lumio/profiles.json` | Its directory also holds per-account `profiles/<id>.json`; the file itself is the pre-accounts global list |
| `DOLPHINLLM_SECRETS_FILE` | `/var/lib/lumio/secrets.json` | Encrypted provider and Tavily keys |
| `DOLPHINLLM_SECRET_KEY_FILE` | `/etc/lumio/secret.key` | Master key(s) for the secrets file |
| `DOLPHINLLM_LOG_FILE` | `/var/lib/lumio/logs/app.jsonl` | Metadata-only log |

Optional: `DOLPHINLLM_IMAGE_RETENTION_DAYS` (default 30), and `DOLPHINLLM_SECRET_KEY`, which takes precedence over the key file when set. The service is sandboxed with `ProtectSystem=strict`: it can write only `/var/lib/lumio` and read `/etc/lumio`. After editing the unit, run `sudo systemctl daemon-reload && sudo systemctl restart lumio`.

The app exits at startup, with a message in `journalctl -u lumio`, if the secrets file is set but no usable master key exists, if a server-only setting is present without `DOLPHINLLM_PUBLIC_HOST`, or if pre-accounts chats exist and `DOLPHINLLM_ADMIN_USER` is unset or has no account.

## Backups and the master key

**What to back up** (all in `/var/lib/lumio` unless noted): `lumio.db` (chats and accounts), `secrets.json` (keys), `profiles/` (each account's providers), optionally `chats/images/` (kept only 30 days), and `/etc/lumio/secret.key`. A database backup alone does not restore providers or keys.

Daily file-level backup on the instance (run after the first provider is saved, so `secrets.json` and `profiles/` exist):

```sh
d=/var/lib/lumio/backup/$(date +%F)
sudo -u lumio mkdir -p "$d"
sudo -u lumio sqlite3 /var/lib/lumio/lumio.db ".backup '$d/lumio.db'"
sudo -u lumio cp -a /var/lib/lumio/secrets.json /var/lib/lumio/profiles "$d"/
```

`.backup` is safe while the app runs; never copy `lumio.db-wal` or `-shm` by themselves. Nothing prunes `backup/`, and it sits on the same disk, so it does not protect against losing the volume.

**EBS snapshots.** Snapshot the volume daily (Data Lifecycle Manager or AWS Backup); that is the copy that survives losing the instance. `/etc/lumio` and `/var/lib/lumio` are on the same volume, so **a snapshot contains both `secrets.json` and the master key, and anyone who can restore or share the snapshot can decrypt the provider keys.** Treat snapshots as sensitive: restrict who may create volumes from or share them, and consider EBS encryption (not configured by anything in this repository). Putting the key on a separate volume would be needed to keep it out of snapshots; this setup doesn't.

**What the encryption does protect:** copies of `secrets.json` or of `/var/lib/lumio` taken without `/etc/lumio` (for example an off-box file backup), and plaintext keys at rest in a file. It does not protect chats, which are plain text in the database.

**Keep a separate copy of the master key** (password manager). If the key is lost, the encrypted keys are unrecoverable and each person must re-enter their provider keys.

**Rotating the master key.** Run on the server, using the `lumio` helper so the command runs as the service user with the configured `DOLPHINLLM_SECRETS_FILE` and key file (running `python -m secret_store rotate` as your own user cannot read `/etc/lumio` and has no secrets file configured):

```sh
old=$(sudo cat /etc/lumio/secret.key)
new=$(openssl rand -base64 32 | tr '+/' '-_')
printf '%s,%s\n' "$new" "$old" | sudo tee /etc/lumio/secret.key > /dev/null
lumio secret_store rotate          # re-encrypts every entry with the first key; changes nothing if any entry fails to decrypt
printf '%s\n' "$new" | sudo tee /etc/lumio/secret.key > /dev/null
```

Save the new key in your password manager and back up `secrets.json` again. By the code, the key file is re-read on every use, so the running service picks up each change without a restart. A restart (after `daemon-reload`) is required only if the key is supplied through `DOLPHINLLM_SECRET_KEY` in the unit file, because that is read from the process environment at start. If you want certainty, `sudo systemctl restart lumio` afterwards is harmless. This procedure has not been run against a live server from here.

`unattended-upgrades` patches the OS; reboot now and then.

## Rolling back

**Ordinary rollback.** Revert the bad change on `main` through a pull request, then run `make deploy` (it only ships `main`). This is safe when the releases share the database schema and the secrets and sign-in design. Check the schema the database is stamped with against the older release's `SCHEMA_VERSION` in `storage.py`:

```sh
sudo -u lumio sqlite3 /var/lib/lumio/lumio.db 'PRAGMA user_version'
```

An older build refuses to open a database with a newer version (on purpose). Deploying it then fails at startup instead of serving data it doesn't understand.

**Rollback across an incompatible database or authentication change.** Deploying old code onto the new data won't work, and shouldn't be forced. The accounts release stamped the database schema 2; the release before it has no per-user scoping and no sign-in, so without Caddy's `basic_auth` it would show every chat to anyone. To go back past it:

1. `sudo systemctl stop lumio`, then restore a database backup taken before the upgrade (with the `secrets.json` and `profiles.json` from the same time) and delete any leftover `lumio.db-wal` and `lumio.db-shm`. Chats and keys created since are not in it.
2. Restore the `basic_auth` block in the Caddyfile (a `basic_auth { <user> <hash from caddy hash-password> }` inside the site block) and reload Caddy **before** the old release is reachable.
3. Revert on `main` and `make deploy`.

[UPGRADING.md](UPGRADING.md) lists what each past upgrade changed.

## Limits to know

- The generation lease uses the server's wall clock: a large clock jump while a reply streams could let a second send start in that chat.
- uvicorn must stay on 127.0.0.1 behind Caddy: the app takes the client address from the proxy for rate limiting.
- Five failed sign-ins lock a username for 15 minutes, so a stranger who knows a username can keep its owner out. Accepted: the alternative is no limit on guessing.
- Provider URLs on a server must resolve to public addresses, so a local Ollama can't be used there.
- Not verifiable from the repository: the EC2, Caddy-install and EBS steps, the Let's Encrypt/sslip.io behavior, and the first-time order end to end. It was checked against the Makefile and code, not executed.
