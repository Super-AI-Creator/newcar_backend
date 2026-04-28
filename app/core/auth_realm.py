"""Split carscu.com vs newcarsuperstore.com accounts that share one `users` table."""

from __future__ import annotations

AUTH_REALM_CARSCU = "carscu"
AUTH_REALM_NEWCAR_SUPERSTORE = "newcar_superstore"
ALLOWED_AUTH_REALMS = frozenset({AUTH_REALM_CARSCU, AUTH_REALM_NEWCAR_SUPERSTORE})


def normalize_auth_realm(value: str | None) -> str | None:
    if value is None:
        return None
    s = value.strip()
    return s or None


def parse_required_auth_realm(value: str | None) -> str:
    """Realm required on registration / OTP start (explicit site)."""
    r = normalize_auth_realm(value)
    if not r or r not in ALLOWED_AUTH_REALMS:
        raise ValueError(
            "auth_realm must be one of: carscu, newcar_superstore",
        )
    return r


def login_realm_allows(user_auth_realm: str | None, requested: str | None, legacy_default: str) -> bool:
    """
    Whether a password/Otp/Google login may proceed for this user + client-declared realm.

    - Legacy users (auth_realm NULL): only the configured legacy_default site may sign them in
      (default: newcar_superstore — pre-migration rows are treated as marketplace accounts, not carscu).
    - Users with a stored realm: missing client realm is allowed only if stored == legacy_default;
      otherwise the client must send the matching realm.
    """
    if legacy_default not in ALLOWED_AUTH_REALMS:
        return False
    r = normalize_auth_realm(requested)
    stored = normalize_auth_realm(user_auth_realm)

    if stored is None:
        effective = r if r else legacy_default
        return effective == legacy_default

    if not r:
        return stored == legacy_default
    return r == stored
