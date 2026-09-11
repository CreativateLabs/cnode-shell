"""Cloud-API-Schlüssel (Service-Tokens) für programmatischen Zugriff auf cNode.

Neben Magic-Link-Cookie + Bearer-JWT (für interaktive Nutzer) akzeptiert die Cloud-
Variante langlebige **API-Keys** — so kann der Client-SDK die API ohne Login ansprechen.

Keys kommen NUR als Umgebungs-Referenz (env/ssm/vault), nie inline im Code/Repo:

    CNODE_API_KEYS="label:secret[:role], …"

  • label   — sprechender Name (erscheint als Identität `apikey:<label>`, für Audit/Provenienz)
  • secret  — der eigentliche Schlüssel (constant-time verglichen)
  • role    — optional; Default `member` (ask + graph:read + artifacts:*). owner/admin für mehr.

Der Tenant ist bei dediziertem Deployment IMMER die Instanz-Org (TENANT_ID) — ein API-Key
kann also nie über seinen Tenant hinausgreifen.
"""
from __future__ import annotations

import hmac
import os

_VALID_ROLES = {"owner", "admin", "member", "viewer", "super_admin"}


def _registry() -> dict[str, dict]:
    """secret → {label, role}. Bei jedem Aufruf frisch aus der Env (erlaubt Rotation ohne Rebuild)."""
    out: dict[str, dict] = {}
    for part in (os.getenv("CNODE_API_KEYS", "") or "").split(","):
        part = part.strip()
        if not part:
            continue
        bits = [b.strip() for b in part.split(":")]
        if len(bits) < 2 or not bits[0] or not bits[1]:
            continue
        label, secret = bits[0], bits[1]
        role = bits[2] if len(bits) > 2 and bits[2] in _VALID_ROLES else "member"
        out[secret] = {"label": label, "role": role}
    return out


def resolve_api_key(token: str) -> dict | None:
    """→ {label, role} bei gültigem Key, sonst None. Constant-time-Vergleich (kein Timing-Leak)."""
    if not token:
        return None
    for secret, meta in _registry().items():
        if hmac.compare_digest(token, secret):
            return meta
    return None


def enabled() -> bool:
    return bool(_registry())
