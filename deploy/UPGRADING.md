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

## Plaintext to encrypted secrets file

A `secrets.json` from before encryption is re-encrypted at startup, after the new file is verified, when a master key is configured. Without a master key the app refuses to start. Create the key as in [first-time step 3](README.md#3-prepare-the-server). An older build cannot read the encrypted file, so roll back secrets together with the matching backup.

For rollback across these changes see [Rolling back](README.md#rolling-back).
