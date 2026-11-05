# Upgrading data from older releases

Only needed for an instance that ran a release before these changes. A new install can skip this. Run commands through the `lumio` helper from [README.md](README.md#6-first-account) and take a [backup](README.md#backups-and-the-master-key) first.

## Chats as JSON files to SQLite

Older releases stored one `<id>.json` per chat in the data directory. On the first start with a database, the app imports them once (recorded in the database, so a chat deleted later never comes back). The files are only read, never deleted or changed.

To preview or run the import by hand:

```sh
lumio chat_migration import            # dry run, reads the data directory, prints a report
lumio chat_migration import --apply    # writes to the database and verifies each chat after import
```

The import does not delete the JSON files. `lumio chat_migration export --to <empty dir>` writes every chat back as JSON, for going back to a release that reads JSON.

## Before accounts to accounts

The accounts release changed three things on first start:

- The database is stamped schema version 2 (accounts, sessions, invites, login attempts and a chat owner column). Older builds refuse to open it.
- Chats without an owner are given to the account named in `DOLPHINLLM_ADMIN_USER`. That account must already exist, or the app exits with a message. Create it first: `lumio accounts create-user <name> --admin`.
- The global `profiles.json` and the keys saved before accounts are moved to that admin account, once. If the move fails, the originals stay where they are and the next start tries again.

Sign-in moved from Caddy's `basic_auth` to the app, so the Caddyfile no longer carries it.

## Free trial (schema 3)

The free-trial release changes the following on first start:

- The database is stamped schema version 3 (new tables `identities`, `trial_anchors`, `trials`, `trial_usage`). Builds from before it refuse the file, so `make rollback` to an older image fails at startup. Take a [backup](README.md#backups-and-the-master-key) before deploying; rolling back means restoring that backup. The change is additive and runs by itself: nothing to migrate by hand.
- New optional environment variables (all unset means no change in behaviour): `DOLPHINLLM_OPEN_SIGNUP`, `DOLPHINLLM_TRIAL_API_KEY`, `DOLPHINLLM_TRIAL_BASE_URL`, `DOLPHINLLM_TRIAL_MODEL`, `DOLPHINLLM_TRIAL_CALLS`, `DOLPHINLLM_TRIAL_DAILY_CALLS`, `DOLPHINLLM_OAUTH_PEPPER`, `DOLPHINLLM_OAUTH_GOOGLE_CLIENT_ID`, `DOLPHINLLM_OAUTH_GOOGLE_CLIENT_SECRET`, `DOLPHINLLM_OAUTH_GITHUB_CLIENT_ID`, `DOLPHINLLM_OAUTH_GITHUB_CLIENT_SECRET`, `DOLPHINLLM_PUBLIC_BASE_URL`. With `DOLPHINLLM_OPEN_SIGNUP=true` the app refuses to start unless the rest is configured. Steps: [Free trial](README.md#free-trial-optional-off-by-default).
- Redirect URLs to register with the identity providers: `https://<host>/api/auth/oauth/google/callback` and `https://<host>/api/auth/oauth/github/callback`.
- Check `FORWARDED_ALLOW_IPS` before turning sign-up on: the per-address sign-up limit uses the address uvicorn resolves from the proxy.
- **Security fix, act before deploying.** The account named by `DOLPHINLLM_ADMIN_USER` inherited the operator's legacy key by name alone. It now also needs the admin flag, and `admin`, `root`, `support`, `local`, `system` and the admin's name are refused at invite registration. If the admin account was created without `--admin`, the legacy key and profiles stop being inherited after this release; fix it before deploying by running `UPDATE users SET is_admin=1 WHERE username='<name>'` against the database (`sqlite3`, after a backup), or re-create the account with `--admin`.

## Plaintext to encrypted secrets file

A `secrets.json` from before encryption is re-encrypted at startup, after the new file is verified, when a master key is configured. Without a master key the app refuses to start. Create the key as in [first-time step 3](README.md#3-prepare-the-server). An older build cannot read the encrypted file, so roll back secrets together with the matching backup.

For rollback across these changes see [Rolling back](README.md#rolling-back).
