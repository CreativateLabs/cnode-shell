"""Rate-Limit / Nutzungs-Cap für die öffentliche Sandbox (PUBLIC_DEMO).

Schützt die Gemini-gestützte Web-Sandbox vor Missbrauch/Kosten-Explosion: pro Client-IP
ein Minuten-Fenster (Burst-Schutz) + ein Tages-Cap (Kosten-Deckel) auf den teuren
LLM-Pfaden (/ask, /route, /graph/capture, /forms/*/submit). In-Process (eine Instanz),
zero-dependency. Nur aktiv, wenn PUBLIC_DEMO gesetzt ist — echte Tenants sind nie limitiert.

Tiered Caps (Monetarisierung): free = enge Caps; bezahlte Tiers (pro/team/enterprise)
weiter bzw. aus. Der Aufrufer löst das Entitlement je Tenant auf und reicht die passenden
Caps als `caps=` durch. Ohne `caps` gelten die Env-Defaults (Free-Sandbox).

Env (Free-Default):
  PUBLIC_DEMO           an/aus (wie in engine)
  RL_PER_MIN            Requests je IP/Minute       (Default 20)
  RL_PER_DAY            Requests je IP/Tag          (Default 200)
  RL_TOKENS_PER_DAY     Token-Budget je IP/Tag      (Default 150000)
  RL_EST_TOKENS_PER_REQ Schätzung Tokens je Anfrage (Default 1500) — konservativer Kosten-Deckel
                        ohne Body-Parsing (streaming-sicher). Echte Gemini-usageMetadata
                        wird über add_tokens() nachgezogen.
"""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict

PUBLIC_DEMO = os.getenv("PUBLIC_DEMO", "").strip().lower() in ("1", "true", "yes", "on")
RL_PER_MIN = int(os.getenv("RL_PER_MIN", "20"))
RL_PER_DAY = int(os.getenv("RL_PER_DAY", "200"))
RL_TOKENS_PER_DAY = int(os.getenv("RL_TOKENS_PER_DAY", "150000"))
RL_EST_TOKENS_PER_REQ = int(os.getenv("RL_EST_TOKENS_PER_REQ", "1500"))

# GLOBALER Tages-Deckel (alle IPs zusammen) — harte Kosten-Obergrenze für die offene
# Sandbox: verhindert Kostenexplosion durch viele Sign-ups, die je einzeln unter dem
# per-IP-Limit bleiben. 0 = aus (Default). Gilt in PUBLIC_DEMO tier-unabhängig.
RL_GLOBAL_PER_DAY = int(os.getenv("RL_GLOBAL_PER_DAY", "0"))
RL_GLOBAL_TOKENS_PER_DAY = int(os.getenv("RL_GLOBAL_TOKENS_PER_DAY", "0"))

# Tier → Caps. 0 (bzw. None) = unbegrenzt. Free spiegelt die Env-Defaults.
# Bezahlte Tiers weiten die Deckel; enterprise ist effektiv aus.
TIERS: dict[str, dict] = {
    "free":       {"per_min": RL_PER_MIN, "per_day": RL_PER_DAY, "tokens_per_day": RL_TOKENS_PER_DAY},
    "pro":        {"per_min": 60,  "per_day": 2000,  "tokens_per_day": 2_000_000},
    "team":       {"per_min": 120, "per_day": 6000,  "tokens_per_day": 8_000_000},
    "enterprise": {"per_min": 0,   "per_day": 0,     "tokens_per_day": 0},
}


def caps_for_tier(tier: str | None) -> dict:
    """Caps-Dict für einen Tier-Namen (Fallback free)."""
    return TIERS.get((tier or "free").strip().lower(), TIERS["free"])


# Teure Pfade (LLM/Gemini). POST-only.
_COST_EXACT = {"/route", "/graph/capture"}
_COST_PREFIX = ("/ask",)  # /ask, /ask/stream

_lock = threading.Lock()
_minute: dict[str, list[float]] = defaultdict(list)   # ip -> Timestamps < 60s
_day: dict[str, tuple[int, float]] = {}               # ip -> (request_count, reset_ts)
_tokens: dict[str, tuple[int, float]] = {}            # ip -> (token_sum, reset_ts)
# Globaler Tages-Bucket (alle IPs): (count/tokens, reset_ts). In _lock mutiert.
_g: dict[str, tuple[int, float]] = {"day": (0, 0.0), "tokens": (0, 0.0)}


def is_cost_path(method: str, path: str) -> bool:
    if method != "POST":
        return False
    if path in _COST_EXACT or any(path.startswith(p) for p in _COST_PREFIX):
        return True
    return path.startswith("/forms/") and path.endswith("/submit")


def client_ip(headers, client_host: str | None) -> str:
    """Hinter Caddy: erste IP aus X-Forwarded-For; sonst Peer."""
    xff = headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return client_host or "unknown"


def check(ip: str, caps: dict | None = None) -> tuple[bool, int]:
    """→ (erlaubt, retry_after_sekunden). Zählt bei Erlaubnis einen Request.

    caps: {per_min, per_day, tokens_per_day} je aufgelöstem Tier. Ohne caps gelten
    die Free-Env-Defaults. Ein Cap-Wert von 0 (oder <=0) bedeutet unbegrenzt.
    """
    if not PUBLIC_DEMO:
        return True, 0
    c = caps or TIERS["free"]
    lim_min = int(c.get("per_min", RL_PER_MIN) or 0)
    lim_day = int(c.get("per_day", RL_PER_DAY) or 0)
    lim_tok = int(c.get("tokens_per_day", RL_TOKENS_PER_DAY) or 0)
    per_ip_off = lim_min <= 0 and lim_day <= 0 and lim_tok <= 0
    global_on = RL_GLOBAL_PER_DAY > 0 or RL_GLOBAL_TOKENS_PER_DAY > 0
    # Weder per-IP-Deckel noch globaler Deckel → unbegrenzt (bezahlter/enterprise Tier).
    if per_ip_off and not global_on:
        return True, 0
    now = time.time()
    with _lock:
        # 1) GLOBALER Tages-Deckel (alle IPs, tier-unabhängig) — harte Kosten-Obergrenze.
        gcnt, greset = _g["day"]
        if now >= greset:
            gcnt, greset = 0, now + 86400.0
        gtok, gtreset = _g["tokens"]
        if now >= gtreset:
            gtok, gtreset = 0, now + 86400.0
        if RL_GLOBAL_PER_DAY > 0 and gcnt >= RL_GLOBAL_PER_DAY:
            _g["day"] = (gcnt, greset)
            return False, int(greset - now)
        if RL_GLOBAL_TOKENS_PER_DAY > 0 and gtok >= RL_GLOBAL_TOKENS_PER_DAY:
            _g["tokens"] = (gtok, gtreset)
            return False, int(gtreset - now)
        # 2) per-IP-Deckel (Burst + Tag + Token) — nur wenn für den Tier aktiv.
        if not per_ip_off:
            q = [t for t in _minute[ip] if now - t < 60.0]
            _minute[ip] = q
            if lim_min > 0 and len(q) >= lim_min:
                return False, max(1, int(60 - (now - q[0])))
            cnt, reset = _day.get(ip, (0, now + 86400.0))
            if now >= reset:
                cnt, reset = 0, now + 86400.0
            if lim_day > 0 and cnt >= lim_day:
                return False, int(reset - now)
            # Token-Budget (Kosten-Deckel): konservative Schätzung je Anfrage.
            tok, treset = _tokens.get(ip, (0, now + 86400.0))
            if now >= treset:
                tok, treset = 0, now + 86400.0
            if lim_tok > 0 and tok >= lim_tok:
                return False, int(treset - now)
            q.append(now)
            _day[ip] = (cnt + 1, reset)
            _tokens[ip] = (tok + RL_EST_TOKENS_PER_REQ, treset)
        # 3) globalen Bucket hochzählen (Schätzung; add_tokens() korrigiert auf Ist).
        if global_on:
            _g["day"] = (gcnt + 1, greset)
            _g["tokens"] = (gtok + RL_EST_TOKENS_PER_REQ, gtreset)
        return True, 0


def add_tokens(ip: str, actual: int) -> None:
    """Reale Token-Nutzung nachtragen (z.B. Gemini usageMetadata), korrigiert die Schätzung.
    Optional — der Cap greift bereits über die Schätzung in check()."""
    if not PUBLIC_DEMO or actual <= 0:
        return
    now = time.time()
    with _lock:
        tok, treset = _tokens.get(ip, (0, now + 86400.0))
        if now >= treset:
            tok, treset = 0, now + 86400.0
        # Schätzung durch Ist ersetzen (Schätzwert dieser Anfrage abziehen, Ist addieren).
        _tokens[ip] = (max(0, tok - RL_EST_TOKENS_PER_REQ) + actual, treset)
        # Gleiche Korrektur im globalen Bucket.
        if RL_GLOBAL_TOKENS_PER_DAY > 0:
            gtok, gtreset = _g["tokens"]
            if now >= gtreset:
                gtok, gtreset = 0, now + 86400.0
            _g["tokens"] = (max(0, gtok - RL_EST_TOKENS_PER_REQ) + actual, gtreset)
