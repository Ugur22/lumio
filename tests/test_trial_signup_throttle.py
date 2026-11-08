# ruff: noqa: F401, F811  (fixtures are imported from trial_support and re-declared as test arguments)
"""Free trial: the open-signup throttle, the daily cap on signups and the clustering log line."""

import logging

import pytest

from app import routes_oauth, runtime
from trial_support import clean, error_of, idp, net, sign_in, trial_on


# --- signup throttle -----------------------------------------------------------------------------------------------


def test_one_open_signup_per_address_then_throttled_and_successes_are_not_credited(idp, net):
    net.ip = "203.0.113.9"
    _, res = sign_in(idp, "c0", sub="s0", email="p0@example.com")
    assert res.headers["location"] == "/"

    _, res = sign_in(idp, "c1", sub="s1", email="p1@example.com")

    assert error_of(res) == "throttled"
    net.ip = "203.0.113.10"  # another address is its own bucket
    assert sign_in(idp, "c2", sub="s2", email="p2@example.com")[1].headers["location"] == "/"
    with runtime.db._read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2


def test_refused_attempts_do_not_use_up_the_signup_allowance(idp, net):
    net.ip = "203.0.113.20"
    for n in range(5):
        assert error_of(sign_in(idp, f"d{n}", sub=f"d{n}", email=f"x{n}@mailinator.com")[1]) == "disposable"

    assert sign_in(idp, "ok", sub="ok", email="ok@example.com")[1].headers["location"] == "/"


def test_existing_accounts_signing_in_are_not_counted_as_signups(idp, net):
    net.ip = "203.0.113.30"
    sign_in(idp, "c1")
    for _ in range(6):
        assert sign_in(idp, "c1")[1].headers["location"] == "/"


def test_ipv6_addresses_share_a_bucket_per_64(idp, net):
    net.ip = "2001:db8:1:2::1"
    assert sign_in(idp, "c0", sub="s0", email="p0@example.com")[1].headers["location"] == "/"

    net.ip = "2001:db8:1:2:ffff::1"  # same /64, different address
    assert error_of(sign_in(idp, "c3", sub="s3", email="p3@example.com")[1]) == "throttled"
    net.ip = "2001:db8:1:3::1"  # next /64
    assert sign_in(idp, "c4", sub="s4", email="p4@example.com")[1].headers["location"] == "/"


@pytest.mark.parametrize(
    "ip,key",
    [
        ("198.51.100.7", "signup:ip:198.51.100.7"),
        ("2001:db8:aaaa:bbbb:1:2:3:4", "signup:ip:2001:db8:aaaa:bbbb::/64"),
        ("::ffff:198.51.100.7", "signup:ip:198.51.100.7"),
    ],
)
def test_signup_ip_keys(ip, key):
    assert routes_oauth.signup_ip_key(ip) == key


def test_a_global_daily_cap_on_open_signups(idp, monkeypatch):
    monkeypatch.setattr(runtime.settings, "trial_daily_calls", 20)
    monkeypatch.setattr(runtime.settings, "trial_reserved_share", 0.5)
    assert runtime.settings.open_signup_limit == 2
    assert sign_in(idp, "c0", sub="s0", email="p0@example.com")[1].headers["location"] == "/"
    assert sign_in(idp, "c1", sub="s1", email="p1@example.com")[1].headers["location"] == "/"

    assert error_of(sign_in(idp, "c2", sub="s2", email="p2@example.com")[1]) == "open_full"


def test_login_attempt_limits_take_their_own_window(idp):
    db = runtime.db
    assert db.take_login_attempt(["w"], limit=2, window=1000)[0] == 0
    assert db.take_login_attempt(["w"], limit=2, window=1000)[0] == 0
    wait, ids = db.take_login_attempt(["w"], limit=2, window=1000)
    assert 0 < wait <= 1001 and ids == []
    # A signup row (a day long) survives the 15-minute purge that login failures get.
    db.record_login_failure(["signup:keep"], now=0)
    db.take_login_attempt(["other"], now=3600)
    with db._read() as conn:
        assert conn.execute("SELECT COUNT(*) FROM login_attempts WHERE key='signup:keep'").fetchone()[0] == 1


def test_open_signups_clustering_on_a_network_are_logged_once_per_window(caplog):
    routes_oauth._cluster_seen.clear()
    routes_oauth._cluster_alerted.clear()
    caplog.set_level(logging.WARNING, logger="dolphinllm")

    for n, ip in enumerate(["198.51.100.1", "198.51.100.2", "198.51.100.3", "198.51.100.4", "198.51.100.5"]):
        routes_oauth.note_open_signup(routes_oauth.signup_ip_key(ip), now=1000.0 + n * 10)
    routes_oauth.note_open_signup(routes_oauth.signup_ip_key("198.51.101.1"), now=1050.0)  # another /24
    lines = [r.getMessage() for r in caplog.records if "clustered" in r.getMessage()]
    assert len(lines) == 1 and "198.51.100.0/24" in lines[0]

    later = 1000.0 + routes_oauth.CLUSTER_SECONDS + 100
    for n in range(3):
        routes_oauth.note_open_signup(routes_oauth.signup_ip_key(f"198.51.100.{n + 10}"), now=later + n)
    assert len([r for r in caplog.records if "clustered" in r.getMessage()]) == 2  # the window passed, so it is news again
    routes_oauth._cluster_seen.clear()
    routes_oauth._cluster_alerted.clear()


def test_signups_spread_over_a_window_do_not_cluster(caplog):
    routes_oauth._cluster_seen.clear()
    routes_oauth._cluster_alerted.clear()
    caplog.set_level(logging.WARNING, logger="dolphinllm")

    for n in range(6):
        routes_oauth.note_open_signup("signup:ip:198.51.100.7", now=1000.0 + n * 300)

    assert not [r for r in caplog.records if "clustered" in r.getMessage()]
    routes_oauth._cluster_seen.clear()


@pytest.mark.parametrize(
    "ip,network",
    [("198.51.100.7", "198.51.100.0/24"), ("2001:db8:aaaa:bbbb:1:2:3:4", "2001:db8:aaaa::/48"), ("::ffff:198.51.100.7", "198.51.100.0/24")],
)
def test_the_cluster_network_is_a_24_or_a_48(ip, network):
    assert routes_oauth.signup_network(routes_oauth.signup_ip_key(ip)) == network
    assert routes_oauth.signup_network("signup:ip:not-an-ip") is None
