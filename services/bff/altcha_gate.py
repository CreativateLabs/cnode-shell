"""Altcha — selbst-gehosteter Proof-of-Work-Bot-Schutz (kein Dritt-Dienst sieht den Besucher).

Portiert das Schema von altcha-lib (wie forms.creativate.tech): der Server stellt eine
Challenge (SHA-256 über salt+number, mit HMAC signiert), das Widget löst den PoW, der Server
verifiziert die Lösung + verhindert Wiederverwendung (Replay-Guard). Gleicher HMAC-Key wie das
Deployment (ALTCHA_HMAC_KEY, sonst AUTH_SECRET) — kein zusätzliches Secret nötig.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

MAX_NUMBER = int(os.getenv("ALTCHA_MAX_NUMBER", "50000"))


def _key() -> str:
    return os.getenv("ALTCHA_HMAC_KEY") or os.getenv("AUTH_SECRET") or "dev-insecure-change-me"


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _hmac_hex(msg: str) -> str:
    return hmac.new(_key().encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()


def create_challenge() -> dict:
    """Frische PoW-Challenge fürs Widget (altcha-lib-kompatibel)."""
    salt = secrets.token_hex(12)
    number = secrets.randbelow(MAX_NUMBER + 1)
    challenge = _sha256_hex(salt + str(number))
    return {"algorithm": "SHA-256", "challenge": challenge,
            "maxnumber": MAX_NUMBER, "salt": salt, "signature": _hmac_hex(challenge)}


# Replay-Guard: eine gelöste Signatur ist nur EINMAL gültig (TTL 15 min, in-process).
_spent: dict[str, float] = {}
_TTL = 15 * 60.0


def _consume(sig: str) -> bool:
    now = time.time()
    if len(_spent) > 10_000:
        for k, exp in list(_spent.items()):
            if exp <= now:
                _spent.pop(k, None)
    if _spent.get(sig, 0) > now:
        return False
    _spent[sig] = now + _TTL
    return True


def verify(payload_b64: str | None) -> bool:
    """Verifiziert die Widget-Lösung: PoW korrekt + gültige HMAC-Signatur + noch nicht benutzt."""
    if not payload_b64:
        return False
    try:
        data = json.loads(base64.b64decode(payload_b64).decode("utf-8"))
        salt, number = data["salt"], data["number"]
        challenge, sig = data["challenge"], data["signature"]
        if data.get("algorithm") != "SHA-256":
            return False
        if _sha256_hex(f"{salt}{number}") != challenge:            # PoW stimmt?
            return False
        if not hmac.compare_digest(_hmac_hex(challenge), sig):      # von uns signiert?
            return False
        return _consume(sig)                                       # kein Replay
    except Exception:  # noqa: BLE001
        return False
