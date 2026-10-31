"""The server's secrets file is encrypted at rest (Fernet); the keychain backend is untouched. Offline."""

import json
import logging
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

import secret_store

ROOT = Path(__file__).resolve().parent.parent
SECRET = "sk-super-secret-value-1234567890"
A, B = "profile:a", "profile:b"


def new_key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture
def key(monkeypatch):
    k = new_key()
    monkeypatch.setenv(secret_store.SECRET_KEY_ENV, k)
    return k


@pytest.fixture
def path(tmp_path, monkeypatch, key):
    p = tmp_path / "secrets.json"
    monkeypatch.setenv(secret_store.SECRETS_FILE_ENV, str(p))
    return p


def stored(path):
    return json.loads(path.read_text())["secrets"]


def test_roundtrip_and_delete(path):
    secret_store.set_key(SECRET, A)
    secret_store.set_key("other", B)

    assert secret_store.get_key(A) == SECRET and secret_store.get_key(B) == "other"
    secret_store.delete_key(A)
    assert secret_store.get_key(A) is None and secret_store.get_key(B) == "other"


def test_file_bytes_hold_no_plaintext_but_keep_account_names(path):
    secret_store.set_key(SECRET, A)

    raw = path.read_bytes()
    assert SECRET.encode() not in raw
    assert json.loads(raw)["v"] == 2 and list(stored(path)) == [A]


def test_file_mode_is_0600_and_no_tmp_is_left(path):
    secret_store.set_key(SECRET, A)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert sorted(p.name for p in path.parent.iterdir()) == sorted([path.name, path.name + ".lock"])  # no tmp left
    assert stat.S_IMODE((path.parent / (path.name + ".lock")).stat().st_mode) == 0o600


def test_v1_plaintext_file_is_read_then_encrypted_by_startup_migration(path):
    path.write_text(json.dumps({A: SECRET, B: "other"}))

    assert secret_store.get_key(A) == SECRET  # readable before any rewrite
    secret_store.migrate_to_encrypted()

    assert SECRET.encode() not in path.read_bytes() and b"other" not in path.read_bytes()
    assert (secret_store.get_key(A), secret_store.get_key(B)) == (SECRET, "other")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_v1_file_is_encrypted_by_the_next_write(path):
    path.write_text(json.dumps({A: SECRET}))

    secret_store.set_key("other", B)

    assert SECRET.encode() not in path.read_bytes()
    assert (secret_store.get_key(A), secret_store.get_key(B)) == (SECRET, "other")


def test_migration_is_idempotent(path):
    path.write_text(json.dumps({A: SECRET}))
    secret_store.migrate_to_encrypted()
    first = path.read_bytes()

    secret_store.migrate_to_encrypted()

    assert path.read_bytes() == first


def test_migration_crash_before_replace_keeps_the_original_and_retries(path, monkeypatch):
    original = json.dumps({A: SECRET})
    path.write_text(original)
    with monkeypatch.context() as m:
        m.setattr(Path, "replace", lambda self, target: (_ for _ in ()).throw(OSError("crash")))
        with pytest.raises(OSError):
            secret_store.migrate_to_encrypted()

    assert path.read_text() == original and secret_store.get_key(A) == SECRET
    secret_store.migrate_to_encrypted()
    assert SECRET.encode() not in path.read_bytes() and secret_store.get_key(A) == SECRET


def test_a_tmp_that_fails_verification_is_never_put_in_place(path, monkeypatch):
    original = json.dumps({A: SECRET})
    path.write_text(original)
    real = secret_store.MultiFernet.decrypt
    monkeypatch.setattr(secret_store.MultiFernet, "decrypt", lambda self, token, *a, **k: b"corrupted")

    with pytest.raises(secret_store.SecretStoreError):
        secret_store.migrate_to_encrypted()

    monkeypatch.setattr(secret_store.MultiFernet, "decrypt", real)
    assert path.read_text() == original and not list(path.parent.glob("*.tmp"))


def test_wrong_key_returns_none_and_warns_without_the_secret(path, monkeypatch, caplog):
    secret_store.set_key(SECRET, A)
    token = stored(path)[A]
    wrong = new_key()
    monkeypatch.setenv(secret_store.SECRET_KEY_ENV, wrong)

    with caplog.at_level(logging.WARNING, logger="dolphinllm"):
        assert secret_store.get_key(A) is None

    (record,) = caplog.records
    assert record.account == A
    dumped = repr(record.__dict__) + record.getMessage()
    assert SECRET not in dumped and token not in dumped and wrong not in dumped


def test_other_entries_keep_working_when_one_is_foreign(path, key, monkeypatch):
    secret_store.set_key(SECRET, A)
    foreign = Fernet(new_key().encode()).encrypt(b"x").decode()
    doc = json.loads(path.read_text())
    doc["secrets"][B] = foreign
    path.write_text(json.dumps(doc))

    assert secret_store.get_key(B) is None
    assert secret_store.get_key(A) == SECRET


def test_write_with_the_wrong_key_preserves_entries_it_cannot_read(path, monkeypatch):
    secret_store.set_key(SECRET, A)
    before = stored(path)[A]
    new = new_key()
    monkeypatch.setenv(secret_store.SECRET_KEY_ENV, new)

    secret_store.set_key("other", B)
    assert stored(path)[A] == before
    secret_store.delete_key(B)
    assert stored(path)[A] == before


def test_tampered_token_reads_as_missing(path, caplog):
    secret_store.set_key(SECRET, A)
    secret_store.set_key("other", B)
    doc = json.loads(path.read_text())
    t = doc["secrets"][A]
    doc["secrets"][A] = t[:-6] + ("AAAAAA" if not t.endswith("AAAAAA") else "BBBBBB")
    path.write_text(json.dumps(doc))

    with caplog.at_level(logging.WARNING, logger="dolphinllm"):
        assert secret_store.get_key(A) is None
    assert secret_store.get_key(B) == "other"
    assert SECRET not in caplog.text


def test_rotation_reads_with_the_old_key_and_rotate_reencrypts(path, monkeypatch, capsys):
    old = os.environ[secret_store.SECRET_KEY_ENV]
    secret_store.set_key(SECRET, A)
    old_token = stored(path)[A]
    new = new_key()

    monkeypatch.setenv(secret_store.SECRET_KEY_ENV, f"{new},{old}")
    assert secret_store.get_key(A) == SECRET  # old key still decrypts
    secret_store.set_key("other", B)
    assert Fernet(new.encode()).decrypt(stored(path)[B].encode()) == b"other"  # first key encrypts

    assert secret_store.main(["rotate"]) == 0
    assert stored(path)[A] != old_token
    assert Fernet(new.encode()).decrypt(stored(path)[A].encode()).decode() == SECRET

    monkeypatch.setenv(secret_store.SECRET_KEY_ENV, new)  # old key no longer needed
    assert (secret_store.get_key(A), secret_store.get_key(B)) == (SECRET, "other")


def test_rotate_changes_nothing_when_an_entry_cannot_be_decrypted(path, capsys):
    secret_store.set_key(SECRET, A)
    doc = json.loads(path.read_text())
    doc["secrets"][B] = Fernet(new_key().encode()).encrypt(b"x").decode()
    path.write_text(json.dumps(doc))
    before = path.read_bytes()

    assert secret_store.main(["rotate"]) == 1

    assert path.read_bytes() == before
    assert B in capsys.readouterr().err


def test_new_key_prints_a_usable_key(capsys):
    assert secret_store.main(["new-key"]) == 0
    Fernet(capsys.readouterr().out.strip().encode())


def run_server_import(tmp_path, **env):
    full = {
        **os.environ,
        "DOLPHINLLM_DATA_DIR": str(tmp_path / "chats"),
        "DOLPHINLLM_PROFILES_FILE": str(tmp_path / "profiles.json"),
        "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
        "DOLPHINLLM_PUBLIC_HOST": "lumio.example.com",  # the secrets setup only counts on a server; a missing host is refused (test_ownership)
    }
    for name in (secret_store.SECRET_KEY_ENV, secret_store.SECRET_KEY_FILE_ENV):
        full.pop(name, None)
    full.update(env)
    return subprocess.run([sys.executable, "-c", "import server"], cwd=ROOT, env=full, capture_output=True, text=True, timeout=60)


def test_server_refuses_to_start_without_a_master_key_and_never_falls_back_to_plaintext(tmp_path):
    secrets = tmp_path / "secrets.json"
    secrets.write_text(json.dumps({A: SECRET}))

    res = run_server_import(tmp_path, DOLPHINLLM_SECRETS_FILE=str(secrets))

    assert res.returncode != 0
    assert secret_store.SECRET_KEY_ENV in res.stderr and secret_store.SECRET_KEY_FILE_ENV in res.stderr
    assert json.loads(secrets.read_text()) == {A: SECRET}  # untouched


def test_server_starts_with_a_key_and_encrypts_the_old_file_once(tmp_path):
    secrets = tmp_path / "secrets.json"
    secrets.write_text(json.dumps({A: SECRET}))

    res = run_server_import(tmp_path, DOLPHINLLM_SECRETS_FILE=str(secrets), DOLPHINLLM_SECRET_KEY=new_key())

    assert res.returncode == 0, res.stderr
    assert SECRET.encode() not in secrets.read_bytes()


def test_server_ignores_the_secrets_setup_for_the_keychain_backend(tmp_path):
    assert run_server_import(tmp_path).returncode == 0


def test_an_invalid_key_is_rejected_without_echoing_it(tmp_path):
    secrets = tmp_path / "secrets.json"
    res = run_server_import(tmp_path, DOLPHINLLM_SECRETS_FILE=str(secrets), DOLPHINLLM_SECRET_KEY="not-a-valid-key-zzz")

    assert res.returncode != 0 and "not-a-valid-key-zzz" not in res.stderr + res.stdout


def test_key_file_variant(tmp_path, monkeypatch):
    keyfile = tmp_path / "master.key"
    keyfile.write_text(f"  {new_key()}\n")
    monkeypatch.delenv(secret_store.SECRET_KEY_ENV, raising=False)
    monkeypatch.setenv(secret_store.SECRET_KEY_FILE_ENV, str(keyfile))
    monkeypatch.setenv(secret_store.SECRETS_FILE_ENV, str(tmp_path / "secrets.json"))

    secret_store.set_key(SECRET, A)

    assert secret_store.get_key(A) == SECRET
    assert SECRET.encode() not in (tmp_path / "secrets.json").read_bytes()


def test_env_key_wins_over_the_key_file(tmp_path, monkeypatch, key):
    keyfile = tmp_path / "master.key"
    keyfile.write_text(new_key())
    monkeypatch.setenv(secret_store.SECRET_KEY_FILE_ENV, str(keyfile))
    monkeypatch.setenv(secret_store.SECRETS_FILE_ENV, str(tmp_path / "secrets.json"))

    secret_store.set_key(SECRET, A)

    assert Fernet(key.encode()).decrypt(stored(tmp_path / "secrets.json")[A].encode()).decode() == SECRET


def test_missing_key_fails_closed_on_every_operation(tmp_path, monkeypatch):
    monkeypatch.delenv(secret_store.SECRET_KEY_ENV, raising=False)
    monkeypatch.setenv(secret_store.SECRETS_FILE_ENV, str(tmp_path / "secrets.json"))

    for op in (lambda: secret_store.get_key(A), lambda: secret_store.set_key(SECRET, A), lambda: secret_store.delete_key(A)):
        with pytest.raises(secret_store.SecretStoreError):
            op()
    assert not (tmp_path / "secrets.json").exists()


def test_keychain_backend_is_untouched(memory_keyring, monkeypatch):
    monkeypatch.delenv(secret_store.SECRET_KEY_ENV, raising=False)
    monkeypatch.delenv(secret_store.SECRETS_FILE_ENV, raising=False)

    secret_store.set_key(SECRET, A)
    secret_store.migrate_to_encrypted()

    assert memory_keyring.store[(secret_store.SERVICE, A)] == SECRET
    assert secret_store.get_key(A) == SECRET


# --- concurrent writers --------------------------------------------------------------------


def test_concurrent_set_key_from_threads_loses_no_key(path):
    import threading

    names = [f"u:{i:032x}:tavily" for i in range(40)]
    errors = []

    def put(name):
        try:
            secret_store.set_key(f"value-of-{name}", name)
        except Exception as e:  # a shared tmp name used to make the loser fail here
            errors.append(e)

    threads = [threading.Thread(target=put, args=(n,)) for n in names]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)

    assert errors == []
    assert {n: secret_store.get_key(n) for n in names} == {n: f"value-of-{n}" for n in names}
    assert not list(path.parent.glob("*.tmp"))


def test_concurrent_set_and_delete_from_threads_keep_the_others(path):
    import threading

    keep = [f"keep{i}" for i in range(15)]
    for n in keep:
        secret_store.set_key("v-" + n, n)
    drop = [f"drop{i}" for i in range(15)]
    for n in drop:
        secret_store.set_key("x", n)
    add = [f"add{i}" for i in range(15)]
    jobs = [lambda n=n: secret_store.delete_key(n) for n in drop] + [lambda n=n: secret_store.set_key("v-" + n, n) for n in add]
    threads = [threading.Thread(target=j) for j in jobs]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)

    assert {n: secret_store.get_key(n) for n in keep + add} == {n: "v-" + n for n in keep + add}
    assert all(secret_store.get_key(n) is None for n in drop)


def _put_in_process(args):
    secrets_path, master, name = args
    os.environ[secret_store.SECRETS_FILE_ENV] = secrets_path
    os.environ[secret_store.SECRET_KEY_ENV] = master
    secret_store.set_key(f"value-of-{name}", name)


def test_concurrent_set_key_from_processes_loses_no_key(path, key):
    import multiprocessing

    names = [f"proc{i}" for i in range(16)]
    with multiprocessing.get_context("spawn").Pool(4) as pool:
        pool.map(_put_in_process, [(str(path), key, n) for n in names])

    assert {n: secret_store.get_key(n) for n in names} == {n: f"value-of-{n}" for n in names}


def test_each_writer_gets_its_own_tmp_file(tmp_path):
    first, a = secret_store.atomic_tmp(tmp_path / "f.json")
    second, b = secret_store.atomic_tmp(tmp_path / "f.json")
    os.close(first), os.close(second)

    assert a != b and a.parent == b.parent == tmp_path
    assert stat.S_IMODE(a.stat().st_mode) == 0o600
