"""Keyed hashes that recognise a person across account deletion, and the email rules behind them.

Nothing here stores anything: callers keep only the hashes. The pepper is a server secret, so a leaked database
cannot be tested against a list of known emails or provider ids."""

import hashlib
import hmac

# A small list of well-known throwaway-mail domains. It raises the cost of farming trials, it does not stop a determined person.
DISPOSABLE_DOMAINS = frozenset({
    "mailinator.com", "guerrillamail.com", "guerrillamail.net", "guerrillamail.org", "guerrillamailblock.com", "sharklasers.com",
    "grr.la", "10minutemail.com", "10minutemail.net", "tempmail.com", "temp-mail.org", "temp-mail.io", "tempmailo.com",
    "throwawaymail.com", "yopmail.com", "yopmail.net", "trashmail.com", "trashmail.net", "getnada.com", "nada.email",
    "maildrop.cc", "dispostable.com", "fakeinbox.com", "mintemail.com", "mailnesia.com", "moakt.com", "emailondeck.com",
    "burnermail.io", "mohmal.com", "spamgourmet.com", "tmpmail.org", "tmpmail.net", "discard.email", "mailcatch.com",
    "inboxkitten.com", "anonaddy.me", "33mail.com", "fakemail.net", "emailfake.com", "tempinbox.com", "mytemp.email",
})  # fmt: skip
_GMAIL = {"gmail.com", "googlemail.com"}


def normalize_email(email: str) -> str | None:
    """Lowercase; the +tag dropped everywhere; dots dropped too for Gmail, where they do not change the mailbox.
    None when it does not look like an address."""
    local, sep, domain = email.strip().lower().rpartition("@")
    if not sep or not local or not domain or "@" in local or " " in email.strip():
        return None
    local = local.split("+", 1)[0]
    if domain in _GMAIL:
        local, domain = local.replace(".", ""), "gmail.com"
    return f"{local}@{domain}" if local else None


def is_disposable(normalized_email: str) -> bool:
    domain = normalized_email.rpartition("@")[2]
    return any(domain == d or domain.endswith("." + d) for d in DISPOSABLE_DOMAINS)


def anchor(pepper: str, kind: str, value: str) -> str:
    return hmac.new(pepper.encode(), f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()
