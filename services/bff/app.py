"""bff — Middleware / BFF für die c:node Assistant Shell (SCOPE v1 + v2).

Einziger Auth-Boundary der Shell (Port 8080). Nimmt Natural-Language via
POST /ask, klassifiziert die Absicht über die engine, routet an engine
(cNode+NEN) oder assets (LeadScout/Förder) und antwortet IMMER im selben
Envelope (SCOPE §2.1).

Governance (SCOPE v2): Multi-Tenant-Auth über Magic-Link + JWT. Tenant-Kontext
und Rolle stammen AUSSCHLIESSLICH aus dem verifizierten JWT — nie aus dem
Request-Body. Downstream (engine/assets) bekommt client_id serverseitig aus dem
Kontext gesetzt. Persistenz in Postgres (RLS als Defense-in-Depth).

Robust by design: sind engine/assets nicht erreichbar, liefert die BFF ein
sauberes *degraded*-Envelope statt eines 500ers — die Demo bleibt stabil.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import asyncio
import os
import re
import secrets
import time

from urllib.parse import urlencode

import httpx
import jwt
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field

import agents
import altcha_gate
import domain_agents
import auth
import db
import ratelimit
from auth import (Identity, current_identity, has_perm as auth_has_permission,
                  require_permission, require_super_admin)

log = logging.getLogger("bff")

ENGINE_URL = os.getenv("ENGINE_URL", "http://engine:8020").rstrip("/")
ASSETS_URL = os.getenv("ASSETS_URL", "http://assets:8030").rstrip("/")
# Öffentliche Demo (c:node): IP-Abriegelung — die Agenten-Routen Förderung/Leads greifen auf
# market-Ebenen-IP (Förder-Katalog, LeadScout) zu und werden hier unterdrückt; die Anfrage
# fällt dann auf den ohnehin abgeriegelten Wissens-/Chat-Pfad (nur eigene Ebene) zurück.
PUBLIC_DEMO = os.getenv("PUBLIC_DEMO", "").strip().lower() in ("1", "true", "yes", "on")
# In der Demo blockierte Intents (market-IP); ingest/graph bleiben (eigene Ebene).
_PUBLIC_BLOCKED_INTENTS = {"leads", "foerderung"}
VOICE_URL = os.getenv("VOICE_URL", "http://voice:8060").rstrip("/")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8080").rstrip("/")
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "cNode <noreply@localhost>")

# Dediziertes Deployment (Sandbox/Cloud): diese Instanz bedient GENAU eine Org.
DEPLOYMENT_TENANT = os.getenv("TENANT_ID", "").strip() or "cnode"

# --- Entitlement (Monetarisierung): NENA-Intel + Token-Tier je Tenant --------
# Kurzer TTL-Cache, damit nicht jede LLM-Anfrage die App-DB trifft.
_ENT_TTL = 30.0
_ent_cache: dict[str, tuple[dict, float]] = {}


def _real_tenant(x: str) -> str:
    """Normalisiert einen Graph-Namespace (`ws:<tenant>~<user>`) zurück auf den echten Tenant.
    Entitlement/Tier gelten je ECHTEM Tenant, nicht je Sandbox-Workspace."""
    x = x or ""
    return x[3:].split("~", 1)[0] if x.startswith("ws:") else x


def _entitlement(tenant_id: str) -> dict:
    """{intel, tier, stripe_customer} je Tenant, 30s gecacht. Default free/kein Intel.
    Akzeptiert auch einen ws:-Workspace-Namespace (→ echter Tenant)."""
    import time as _t
    tenant_id = _real_tenant(tenant_id)
    now = _t.time()
    hit = _ent_cache.get(tenant_id)
    if hit and now - hit[1] < _ENT_TTL:
        return hit[0]
    try:
        ent = db.get_entitlement(tenant_id)
    except Exception:  # noqa: BLE001 — DB-Ausfall darf den Chat nicht blocken
        ent = {"intel": False, "tier": "free", "stripe_customer": None}
    _ent_cache[tenant_id] = (ent, now)
    return ent


def _intel_flag(tenant_id: str) -> bool | None:
    """NENA-Flag, das die Engine als `intel` erhält. Nur in der Public-Sandbox relevant —
    echte Tenants entscheiden strukturell über SHARED_LAYERS (None = Default-Regel)."""
    if not PUBLIC_DEMO:
        return None
    return bool(_entitlement(tenant_id).get("intel"))


def _tier_caps(tenant_id: str) -> dict:
    """Rate-Limit-Caps für den aufgelösten Tier des Tenants (Free-Default)."""
    return ratelimit.caps_for_tier(_entitlement(tenant_id).get("tier"))


def _graph_client(identity) -> str:
    """Graph-/Gedächtnis-Namespace für DIESE Anfrage. In der öffentlichen Sandbox
    (PUBLIC_DEMO) pro-User isoliert (`ws:<tenant>~<user>` → eigener graph-group, RLS-getrennt);
    sonst tenant-weit (dediziert/geteilt). Lokal (PUBLIC_DEMO aus) unverändert = tenant_id."""
    if PUBLIC_DEMO:
        uid = (getattr(identity, "user_id", "") or "anon").replace(":", "-")
        return f"ws:{identity.tenant_id}~{uid}"
    return identity.tenant_id


_CHAT_GREET = ("hallo", "hi", "hey", "danke", "ok", "okay", "alles klar", "guten morgen",
               "guten tag", "guten abend", "servus", "moin", "tschüss", "test", "na", "yo")


def _chat_substantive(text: str, answer: str) -> bool:
    """Lohnt der Turn fürs Gedächtnis? Kein Smalltalk/Gruß, echte Substanz auf beiden Seiten."""
    t = (text or "").strip().lower().rstrip("?!. ")
    if len(t) < 12 or len((answer or "").strip()) < 120:
        return False
    if t in _CHAT_GREET or (len(t) < 30 and any(t.startswith(g + " ") for g in _CHAT_GREET)):
        return False
    return True


async def _learn_chat_bg(gclient: str, identity: "Identity", text: str, answer: str,
                         thread_id: str | None) -> None:
    """Fire-and-forget: substanziellen Chat-Turn als Gedächtnis-Knoten in den per-User-Graph
    schreiben (Frage+Antwort eingebettet → später abrufbar). Blockt die Antwort nie; Fehler
    sind bewusst geschluckt. So lernt der Graph auch aus Chats (neben Files/Artefakten/Connectoren)."""
    if not _chat_substantive(text, answer):
        return
    try:
        async with httpx.AsyncClient(timeout=30.0) as c:
            await c.post(f"{ENGINE_URL}/ingest", json={
                "label": ("Chat: " + text.strip())[:120], "type": "ChatMemory",
                "props": {"kind": "chat", "quelle": f"chat:{thread_id or 'na'}",
                          "frage": text[:600], "inhalt": answer[:1400],
                          "erstellt_von": getattr(identity, "email", ""),
                          "mandant": _real_tenant(identity.tenant_id),
                          "erstellt_am": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                "content": text.strip() + "\n\n" + answer[:1400],
                "links": [], "client_id": gclient, "levels": ["client"]})
    except Exception:  # noqa: BLE001
        pass


def _send_email(to: str, subject: str, html: str) -> bool:
    """Best-effort Mailversand via Resend. Ohne RESEND_API_KEY → False (Dev: Link im Log)."""
    if not RESEND_API_KEY:
        return False
    try:
        r = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
            json={"from": EMAIL_FROM, "to": [to], "subject": subject, "html": html},
            timeout=10.0,
        )
        return r.status_code < 300
    except Exception:  # noqa: BLE001
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "ollama")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "qwen2.5:7b")


def _effective_provider(p: str | None) -> str:
    """Öffentliche Sandbox (PUBLIC_DEMO): erzwingt Gemini für ALLE engine-gebundenen
    Pfade und ignoriert jeden vom Client gelieferten Provider. Echte Tenants nutzen
    weiter ihre Wahl (bzw. den Server-Default)."""
    return "gemini" if PUBLIC_DEMO else (p or DEFAULT_PROVIDER)

# SCOPE v3 — Google connector (Stub, live-ready once creds are set).
# Akzeptiert auch das Claudio/Memosorter-Namensschema (GMAIL_CLIENT_ID/SECRET) als Alias,
# damit dieselben Google-OAuth-Credentials wiederverwendet werden können.
GOOGLE_OAUTH_CLIENT_ID = (
    os.getenv("GOOGLE_OAUTH_CLIENT_ID") or os.getenv("GMAIL_CLIENT_ID") or ""
).strip()
GOOGLE_OAUTH_CLIENT_SECRET = (
    os.getenv("GOOGLE_OAUTH_CLIENT_SECRET") or os.getenv("GMAIL_CLIENT_SECRET") or ""
).strip()
GOOGLE_OAUTH_REDIRECT_URI = os.getenv(
    "GOOGLE_OAUTH_REDIRECT_URI",
    f"{PUBLIC_BASE_URL}/integrations/google/oauth/callback",
).strip()
GOOGLE_OAUTH_SCOPES = os.getenv(
    "GOOGLE_OAUTH_SCOPES",
    "https://www.googleapis.com/auth/gmail.readonly "
    "https://www.googleapis.com/auth/gmail.compose "
    "https://www.googleapis.com/auth/drive "
    "https://www.googleapis.com/auth/calendar.events",
).strip()


def _google_configured() -> bool:
    return bool(GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET)


# --- Microsoft / Outlook (Graph) OAuth — Code-komplett; braucht nur Azure-App-Env ---
MICROSOFT_CLIENT_ID = (os.getenv("MICROSOFT_CLIENT_ID") or os.getenv("MS_CLIENT_ID") or "").strip()
MICROSOFT_CLIENT_SECRET = (os.getenv("MICROSOFT_CLIENT_SECRET") or os.getenv("MS_CLIENT_SECRET") or "").strip()
MICROSOFT_TENANT = (os.getenv("MICROSOFT_TENANT") or "common").strip()
MICROSOFT_REDIRECT_URI = os.getenv(
    "MICROSOFT_REDIRECT_URI",
    f"{PUBLIC_BASE_URL}/integrations/microsoft/oauth/callback",
).strip()
MICROSOFT_SCOPES = os.getenv(
    "MICROSOFT_SCOPES",
    "offline_access User.Read Mail.ReadWrite Mail.Send Calendars.ReadWrite",
).strip()
_MS_AUTH_URL = f"https://login.microsoftonline.com/{MICROSOFT_TENANT}/oauth2/v2.0/authorize"
_MS_TOKEN_URL = f"https://login.microsoftonline.com/{MICROSOFT_TENANT}/oauth2/v2.0/token"


def _ms_configured() -> bool:
    return bool(MICROSOFT_CLIENT_ID and MICROSOFT_CLIENT_SECRET)


# Escalation target: the next-higher role that can approve a data-request.
_ESCALATION = {"viewer": "admin", "member": "admin", "admin": "super_admin"}

# short for probes/classify, long for LLM answers/artifacts
T_SHORT = float(os.getenv("BFF_TIMEOUT_SHORT", "5.0"))
T_LONG = float(os.getenv("BFF_TIMEOUT_LONG", "140.0"))

# Keyword → Artifact-Kind.
ARTIFACT_KEYWORDS = [
    ("protokoll", "dialog_protocol"),
    ("protocol", "dialog_protocol"),
    ("dialog", "dialog_protocol"),
    ("gesprächsprotokoll", "dialog_protocol"),
    ("memo", "memo"),
    ("proposal", "proposal"),
    ("angebot", "proposal"),
    ("one-pager", "one_pager"),
    ("onepager", "one_pager"),
    ("one pager", "one_pager"),
    ("spezifikation", "one_pager"),
    ("spezi", "one_pager"),
    ("steckbrief", "one_pager"),
    ("factsheet", "one_pager"),
    ("fact sheet", "one_pager"),
]

app = FastAPI(title="bff", version="2.0.0")

# --- Tenant-Layer + Plugin-Framework (config-driven; optional zur Laufzeit) ---
# Werden über PYTHONPATH (compose-Overlay) bereitgestellt. Fällt etwas weg, bleibt
# der BFF funktionsfähig — die Endpoints liefern dann neutrale Defaults.
try:
    from tenant_core import load_default as _load_tenant
    TENANT_CTX = _load_tenant()
except Exception:  # noqa: BLE001
    TENANT_CTX = None
try:
    from cnode_platform import registry as _plugin_registry
except Exception:  # noqa: BLE001
    _plugin_registry = None


_CONFIG_DIR = os.path.dirname(os.getenv("TENANT_CONFIG", "/config/tenant.yaml")) or "/config"


def _tenant_logo_svg() -> str:
    """Rohes Tenant-Logo-SVG (falls vorhanden) für Auth + Header. Tenant-scoped:
    liest <config>/brand/logo.svg (Cap 200 KB). Kein File → "" (Fallback: Initial-Icon)."""
    for rel in ("brand/logo.svg", "logo.svg"):
        p = os.path.join(_CONFIG_DIR, rel)
        try:
            if os.path.isfile(p) and os.path.getsize(p) <= 200_000:
                with open(p, encoding="utf-8") as f:
                    svg = f.read()
                if "<svg" in svg.lower():
                    return svg
        except Exception:  # noqa: BLE001
            continue
    return ""


@app.get("/tenant/context")
def tenant_context():
    """Identität + Branding + aktive Module des laufenden Tenants (für die Shell)."""
    if TENANT_CTX is None:
        return {"id": "cnode", "name": "cNode", "mode": "dedicated",
                "brand": {}, "modules": {}}
    s = TENANT_CTX.spec
    brand = s.brand.model_dump()
    logo_svg = _tenant_logo_svg()
    if logo_svg:
        brand["logo_svg"] = logo_svg          # echtes Marken-Logo (nur wenn hinterlegt)
    return {"id": TENANT_CTX.id, "name": TENANT_CTX.name, "mode": TENANT_CTX.mode,
            "locale": s.tenant.locale, "brand": brand,
            "modules": s.modules.model_dump()}


@app.get("/forms")
def forms_list():
    """Tenant-scoped interaktive Formulare (FraBö). Summary für NL-Trigger + „/"-Menü."""
    try:
        from tenant_core.forms import load_forms
        specs = load_forms(_CONFIG_DIR)
    except Exception:  # noqa: BLE001
        return {"forms": []}
    return {"forms": [
        {"id": s.id, "title": s.title, "kind": s.kind, "description": s.description,
         "triggers": s.triggers, "subject_prompt": s.subject_prompt,
         "sections": len(s.sections),
         "questions": sum(len(sec.questions) + len(sec.fields) for sec in s.sections)}
        for s in specs
    ]}


@app.get("/forms/{form_id}")
def form_detail(form_id: str):
    """Vollständige Form-Spec (Sektionen/Fragen/Skala/Scoring) für den Chat-Runner."""
    try:
        from tenant_core.forms import load_forms
        specs = load_forms(_CONFIG_DIR)
    except Exception:  # noqa: BLE001
        specs = []
    for s in specs:
        if s.id == form_id:
            return s.model_dump()
    raise HTTPException(status_code=404, detail="form_not_found")


@app.get("/plugins")
def plugins():
    """Plugin-Katalog dieses Tenants (Connectoren/Formate/Agenten/Systeme) für die Bibliothek."""
    if _plugin_registry is None:
        return {"plugins": []}
    try:
        return {"plugins": _plugin_registry().catalog(TENANT_CTX)}
    except Exception:  # noqa: BLE001
        return {"plugins": []}


@app.get("/connectors/catalog")
def connectors_catalog():
    """Connector-Bibliothek: alle recherchierten Stack-Integrationen mit API-Metadaten
    (Base-URL, Auth-Modell, Docs, Kategorie) + je Tenant, ob aktiviert. Grundlage für die
    „Verfügbare Connectoren"-Ansicht, aus der ein Admin sie in tenant.yaml freischaltet.
    Secrets bleiben Refs — es werden nur Referenzen/Booleans, nie Werte ausgeliefert."""
    try:
        from cnode_platform.connectors_catalog import CATALOG
    except Exception:  # noqa: BLE001
        return {"connectors": []}
    active = {}
    if TENANT_CTX is not None and getattr(TENANT_CTX, "spec", None):
        active = TENANT_CTX.spec.connectors or {}
    out = []
    for c in CATALOG:
        conf = active.get(c.id)
        out.append({
            "id": c.id, "name": c.name, "category": c.category,
            "api_base": c.api_base, "docs_url": c.docs_url,
            "auth": c.auth.kind, "capabilities": c.capabilities,
            "region_aware": c.region_aware, "note": c.note,
            "description": c.description,
            "secret_ref": c.auth.secret_ref,
            "enabled": bool(getattr(conf, "enabled", False)) if conf else False,
        })
    out.sort(key=lambda x: (x["category"], x["name"]))
    return {"connectors": out, "count": len(out)}
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3010").split(","),
    allow_credentials=True,  # cookies must be allowed across origins
    allow_methods=["*"],
    allow_headers=["*"],
)

# G7 — Observability: /metrics (Prometheus, zero-dep) + HTTP-Zähler.
_REQS: dict[tuple, int] = {}


@app.middleware("http")
async def _rate_limit(request: Request, call_next):
    """Öffentliche Sandbox (PUBLIC_DEMO): teure LLM-Pfade je IP limitieren (Burst + Tages-Cap).
    Echte Tenants (PUBLIC_DEMO aus) sind nie betroffen."""
    if ratelimit.PUBLIC_DEMO and ratelimit.is_cost_path(request.method, request.url.path):
        ip = ratelimit.client_ip(request.headers, request.client.host if request.client else None)
        # Caps je Tier des Deployment-Tenants (free eng, bezahlt weiter/aus).
        ok, retry = ratelimit.check(ip, _tier_caps(DEPLOYMENT_TENANT))
        if not ok:
            ent = _entitlement(DEPLOYMENT_TENANT)
            return JSONResponse(
                {"detail": "rate_limited",
                 "message": "Sandbox-Limit erreicht — bitte kurz warten oder auf einen höheren Plan upgraden.",
                 "retry_after": retry, "tier": ent.get("tier", "free"), "upgrade": True},
                status_code=429, headers={"Retry-After": str(retry)})
    return await call_next(request)


@app.middleware("http")
async def _count_requests(request: Request, call_next):
    resp = await call_next(request)
    try:
        _REQS[(request.method, resp.status_code)] = _REQS.get((request.method, resp.status_code), 0) + 1
    except Exception:  # noqa: BLE001
        pass
    return resp


@app.get("/metrics")
def metrics():
    lines = ["# TYPE cnode_up gauge", 'cnode_up{service="bff"} 1',
             "# HELP cnode_http_requests_total HTTP-Requests nach Methode/Status.",
             "# TYPE cnode_http_requests_total counter"]
    for (method, status), n in _REQS.items():
        m = str(method).replace('"', '')
        lines.append(f'cnode_http_requests_total{{service="bff",method="{m}",status="{status}"}} {n}')
    return Response("\n".join(lines) + "\n", media_type="text/plain")


@app.on_event("startup")
def _startup() -> None:
    db.init()


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------
class AskReq(BaseModel):
    text: str
    thread_id: str | None = None
    provider: str = DEFAULT_PROVIDER
    # SCOPE v2: ingest-Ebene. ["client"] default; ["client","market"] nur Super-Admin.
    levels: list[str] | None = None


class ArtifactReq(BaseModel):
    kind: str = "memo"
    title: str = ""
    markdown: str = ""
    thread_id: str = ""


class ShareReq(BaseModel):
    role: str = "viewer"


class RequestLinkReq(BaseModel):
    email: str


class VerifyReq(BaseModel):
    token: str


class VerifyCodeReq(BaseModel):
    email: str
    code: str


class SignupReq(BaseModel):
    email: str
    password: str
    name: str | None = None
    company: str | None = None
    altcha: str | None = None   # PoW-Bot-Schutz (Pflicht in der öffentlichen Sandbox)


class SignupDemoReq(BaseModel):
    """Passwortloser Sandbox-Signup — erfasst Profil, Login danach via OTP."""
    email: str
    name: str | None = None
    company: str | None = None


class LoginReq(BaseModel):
    email: str
    password: str


class TenantReq(BaseModel):
    id: str | None = None
    label: str | None = None


class AdminReq(BaseModel):
    email: str


class MemberReq(BaseModel):
    email: str
    role: str = "member"


class SettingsReq(BaseModel):
    settings: dict = {}


class PromotionReq(BaseModel):
    source_id: str
    note: str | None = None


# --- SCOPE v3 -------------------------------------------------------------
class FolderReq(BaseModel):
    name: str


class ThreadPatchReq(BaseModel):
    title: str | None = None
    folder_id: str | None = None
    visibility: str | None = None
    members: list[str] | None = None
    team_id: str | None = None          # Team-Zuordnung (mit visibility='team')
    set_team: bool = False              # true → team_id anwenden (auch null zum Lösen)


class DataRequestReq(BaseModel):
    scope: str
    note: str | None = None
    connector: str | None = None


class GoogleQueryReq(BaseModel):
    q: str = ""
    max: int = 10


class DriveListReq(BaseModel):
    q: str = ""
    max: int = 20


class GoogleSyncReq(BaseModel):
    max_gmail: int = 8
    max_drive: int = 8


class DrivePutReq(BaseModel):
    name: str
    content: str = ""
    mime: str | None = None


class ActionExecuteReq(BaseModel):
    type: str
    params: dict = {}


class ArtifactSaveReq(BaseModel):
    id: str = ""
    kind: str = "memo"
    title: str = ""
    markdown: str = ""
    thread_id: str = ""


class AgentRunReq(BaseModel):
    goal: str
    thread_id: str | None = None
    provider: str = DEFAULT_PROVIDER


# --------------------------------------------------------------------------
# Envelope helper (SCOPE §2.1) — identische Form für ALLE Routen
# --------------------------------------------------------------------------
def envelope(intent: str, route: str, result_text: str, **extra) -> dict:
    base = {
        "intent": intent,
        "route": route,
        "result_text": result_text,
        "sources": [],
        "artifact": None,
        "graph_delta": {"nodes": [], "edges": []},
        "highlight": [],
        "trace": [],
        "provider": DEFAULT_PROVIDER,
        "model": DEFAULT_MODEL,
    }
    base.update(extra)
    return base


def _norm_sources(raw: list) -> list[dict]:
    out: list[dict] = []
    for i, s in enumerate(raw or []):
        if not isinstance(s, dict):
            s = {"label": str(s)}
        sid = str(s.get("id") or s.get("name") or f"src_{i}")
        out.append(
            {
                "id": sid,
                "label": s.get("label") or s.get("name") or sid,
                "type": s.get("type", ""),
                "props": s.get("props") or {
                    k: v for k, v in s.items()
                    if k not in ("id", "label", "name", "type", "props", "provenance")
                },
                "provenance": s.get("provenance", ""),
            }
        )
    return out


def _detect_artifact_kind(text: str) -> str | None:
    low = text.lower()
    for kw, kind in ARTIFACT_KEYWORDS:
        if kw in low:
            return kind
    return None


def _can_access_thread(thread: dict, identity: Identity) -> bool:
    """SCOPE v3 privacy rule.

    private  → owner only (+ tenant admin / super-admin)
    team     → owner + members (+ tenant admin / super-admin)
    Legacy threads without an owner (created_by IS NULL) stay tenant-visible for
    backward compatibility.
    """
    if not thread:
        return False
    # super-admin (and act-as) already passed tenant scoping in the caller.
    if identity.is_super:
        return True
    # cross-tenant is never allowed for non-super users.
    if thread.get("tenant_id") and thread["tenant_id"] != identity.tenant_id:
        return False
    # PUBLIC_DEMO: der cnode-Tenant ist GETEILT (jeder Sandbox-User) → strikte per-USER-
    # Isolation, NUR der Ersteller sieht seinen Thread. Keine Tenant-Admin-/Legacy-/org-/team-
    # Sichtbarkeit (die würde im geteilten Tenant fremde Chats offenlegen).
    if PUBLIC_DEMO:
        return (thread.get("created_by") or "").lower() == (identity.email or "").lower()
    # tenant admins see everything inside their tenant.
    if identity.role == "admin":
        return True
    owner = (thread.get("created_by") or "").lower()
    email = (identity.email or "").lower()
    if not owner:  # legacy thread — keep visible to the tenant
        return True
    if email == owner:
        return True
    vis = thread.get("visibility")
    if vis == "org":
        return True  # org-weit sichtbar für alle Mitglieder des Tenants
    if vis == "team":
        members = [str(m).lower() for m in (thread.get("members") or [])]
        if email in members:
            return True
        # Team-Zuordnung: Mitglieder des zugeordneten Teams sehen den Thread.
        tid = thread.get("team_id")
        if tid and db.user_team_role(tid, identity.user_id, identity.tenant_id,
                                     is_super=identity.is_super):
            return True
    return False


def _is_thread_owner(thread: dict, identity: Identity) -> bool:
    """Owner or admin/super — allowed to mutate/delete a thread."""
    if identity.is_super:
        return True
    # PUBLIC_DEMO: geteilter Tenant → nur der Ersteller darf mutieren/löschen (kein Tenant-Admin,
    # keine Legacy-Ownerless-Adoption — sonst griffe man auf fremde Sandbox-Threads zu).
    if PUBLIC_DEMO:
        return (thread.get("created_by") or "").lower() == (identity.email or "").lower()
    if identity.role == "admin":
        return True
    owner = (thread.get("created_by") or "").lower()
    # legacy owner-less threads: any member of the tenant may adopt/manage them.
    return not owner or owner == (identity.email or "").lower()


def _demo_owned(rows: list[dict], identity: Identity) -> list[dict]:
    """PUBLIC_DEMO: im geteilten cnode-Tenant nur die eigenen Records (created_by == email)
    zurückgeben — schützt Artefakte/Läufe vor Cross-User-Sicht. Sonst (echter Tenant) unverändert."""
    if not PUBLIC_DEMO or identity.is_super:
        return rows
    email = (identity.email or "").lower()
    return [r for r in rows if (r.get("created_by") or "").lower() == email]


# --------------------------------------------------------------------------
# Health (unauthenticated)
# --------------------------------------------------------------------------
@app.get("/health")
async def health():
    deps = {}
    async with httpx.AsyncClient(timeout=T_SHORT) as c:
        for name, url in (("engine", ENGINE_URL), ("assets", ASSETS_URL)):
            try:
                r = await c.get(f"{url}/health")
                deps[name] = r.json().get("status", "ok") if r.status_code == 200 else "unreachable"
            except Exception:
                deps[name] = "unreachable"
    # DB probe
    try:
        db.list_tenants()
        deps["db"] = "ok"
    except Exception:
        deps["db"] = "unreachable"
    ok = all(v != "unreachable" for v in deps.values())
    return {"status": "ok" if ok else "degraded", "service": "bff", "deps": deps}


# --------------------------------------------------------------------------
# Auth (Magic-Link + JWT)
# --------------------------------------------------------------------------
_ROLE_ORDER = {"super_admin": 0, "admin": 1, "member": 2, "viewer": 3}


def _best_membership(memberships: list[dict]) -> dict | None:
    """Pick the highest-privilege membership (super_admin > admin > member > viewer)."""
    if not memberships:
        return None
    return sorted(memberships, key=lambda m: _ROLE_ORDER.get(m["role"], 9))[0]


def _slug(value: str) -> str:
    """Tenant-id slug from a company name / email local-part."""
    s = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return s or db.new_id("tn")


def _login_payload(response: Response, user: dict, membership: dict) -> dict:
    """Issue the session cookie + JWT and build the standard login response."""
    jwt_token = auth.issue_jwt(
        user["id"], user["email"], membership["tenant_id"], membership["role"]
    )
    auth.set_session_cookie(response, jwt_token)
    tenant = db.get_tenant(membership["tenant_id"])
    return {
        "user": {"id": user["id"], "email": user["email"],
                 "name": user.get("name"), "company": user.get("company")},
        "tenant": tenant,
        "role": membership["role"],
        "token": jwt_token,  # convenience for non-cookie API clients / tests
    }


# Self-Service-Signup: in der öffentlichen Sandbox (PUBLIC_DEMO) bekommt jede verifizierte
# E-Mail sofort einen Zugang im Deployment-Tenant (member). Sonst nur eingeladene User.
SELF_SERVICE_SIGNUP = (
    os.getenv("SELF_SERVICE_SIGNUP", "").strip().lower() in ("1", "true", "yes", "on")
    or PUBLIC_DEMO
)


def _resolve_login(email: str) -> tuple[dict, dict] | None:
    """Return (user, membership) to log in as, or None if no access.

    Reihenfolge: bestehender User → Super-Admin-Bootstrap → Self-Service-Signup (Sandbox)."""
    email = email.lower().strip()
    if not email or "@" not in email:
        return None
    user = db.get_user_by_email(email)
    # Bootstrap the configured super-admin on first login.
    if user is None and email == os.getenv("SUPERADMIN_EMAIL", "").strip().lower():
        db.upsert_tenant("platform", "Platform")
        user = db.upsert_user(email)
        db.add_membership(user["id"], "platform", "super_admin")
    if user is not None:
        membership = _best_membership(db.list_memberships_for_user(user["id"]))
        if membership:
            return user, membership
    # Self-Service: neuen User im Sandbox-Tenant anlegen (nur wenn aktiviert).
    if SELF_SERVICE_SIGNUP:
        db.upsert_tenant(DEPLOYMENT_TENANT, DEPLOYMENT_TENANT)
        user = user or db.upsert_user(email)
        membership = db.add_membership(user["id"], DEPLOYMENT_TENANT, "member")
        return user, membership
    return None


def _otp_email_html(code: str, link: str) -> str:
    """Light-Brand OTP-Mail: großer Code + klickbarer Magic-Link als Fallback."""
    return (
        f'<div style="font-family:Inter,system-ui,sans-serif;max-width:440px;margin:0 auto;'
        f'color:#181B26">'
        f'<h2 style="font-family:\'Bricolage Grotesque\',system-ui;color:#181B26">c:node — dein Login-Code</h2>'
        f'<p style="color:#5C6273">Gib diesen Code in der App ein (10 Minuten gültig):</p>'
        f'<div style="font-size:34px;font-weight:800;letter-spacing:8px;color:#4B6EF5;'
        f'background:#F1F3F9;border-radius:12px;padding:16px 0;text-align:center;margin:16px 0">{code}</div>'
        f'<p style="color:#5C6273">Oder klick einfach hier:</p>'
        f'<p><a href="{link}" style="background:#4B6EF5;color:#fff;text-decoration:none;'
        f'padding:10px 18px;border-radius:9px;font-weight:600;display:inline-block">Anmelden →</a></p>'
        f'<p style="color:#868D9E;font-size:12px;margin-top:20px">Nicht angefordert? Ignoriere diese Mail.</p>'
        f'</div>'
    )


def _gen_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


@app.get("/auth/altcha/challenge")
def altcha_challenge():
    """PoW-Challenge fürs „Ich bin kein Roboter"-Widget (self-hosted, kein Dritt-Dienst)."""
    return altcha_gate.create_challenge()


@app.get("/auth/exists")
def auth_exists(email: str):
    """Prüft, ob zu einer E-Mail bereits ein Konto existiert (für Login/Signup-Hinweise).
    Gibt bewusst nur das Nötigste zurück."""
    u = db.get_user_by_email((email or "").lower().strip())
    return {"exists": bool(u), "has_password": bool(u and u.get("password_hash"))}


@app.post("/auth/request-code")
def request_code(req: RequestLinkReq):
    """Login-Code — NUR für bestehende Konten (neue Nutzer registrieren sich via Signup)."""
    email = req.email.lower().strip()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="valid email required")
    if not db.get_user_by_email(email):
        raise HTTPException(status_code=404, detail="no_account")
    code = _gen_otp()
    db.set_auth_code(email, code)
    tok = db.create_magic_token(email)               # derselbe Login, als klickbarer Fallback
    link = f"{PUBLIC_BASE_URL}/auth/verify?token={tok['token']}"
    sent = _send_email(email, "Dein c:node Login-Code", _otp_email_html(code, link))
    if not sent:
        log.warning("OTP for %s → code=%s · link=%s", email, code, link)
    out = {"sent": sent, "email": email}
    # Kein Secret-Leak: Code/Link NUR im lokalen Dev zeigen (kein RESEND UND keine öffentliche
    # Instanz). In der öffentlichen Sandbox (PUBLIC_DEMO) NIE — sonst wäre der Login offen.
    if not RESEND_API_KEY and not PUBLIC_DEMO:
        out["dev_code"] = code
        out["dev_link"] = link
    return out


@app.post("/auth/signup-demo")
def signup_demo(req: SignupDemoReq):
    """Passwortloser Sandbox-Signup: erfasst Profil (Name/Firma) für späteres Onboarding,
    legt den User in der DB an (Mitglied im Sandbox-Tenant, Model A: shared tenant +
    per-User-Workspace) und schickt denselben OTP-Code wie beim Login. Danach schließt
    /auth/verify-code den Login ab."""
    email = req.email.lower().strip()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="valid email required")
    name = (req.name or "").strip() or None
    company = (req.company or "").strip() or None
    # Profil persistieren (idempotent; bei bestehendem User werden Name/Firma ergänzt).
    user = db.upsert_user(email, name=name, company=company)
    # Zugang sicherstellen: Sandbox → Mitglied im Deployment-Tenant; sonst frischer Tenant.
    membership = _best_membership(db.list_memberships_for_user(user["id"]))
    if membership is None:
        if SELF_SERVICE_SIGNUP:
            db.upsert_tenant(DEPLOYMENT_TENANT, DEPLOYMENT_TENANT)
            db.add_membership(user["id"], DEPLOYMENT_TENANT, "member")
        else:
            tenant_id = _slug(company or email.split("@", 1)[0])
            db.upsert_tenant(tenant_id, (company or email).strip())
            db.add_membership(user["id"], tenant_id, "admin")
    # OTP verschicken (identisch zum Login-Pfad).
    code = _gen_otp()
    db.set_auth_code(email, code)
    tok = db.create_magic_token(email)
    link = f"{PUBLIC_BASE_URL}/auth/verify?token={tok['token']}"
    sent = _send_email(email, "Willkommen bei c:node — dein Login-Code",
                       _otp_email_html(code, link))
    if not sent:
        log.warning("SIGNUP OTP for %s → code=%s · link=%s", email, code, link)
    out = {"sent": sent, "email": email, "signup": True}
    if not RESEND_API_KEY and not PUBLIC_DEMO:
        out["dev_code"] = code
        out["dev_link"] = link
    return out


@app.post("/auth/verify-code")
def verify_code(req: "VerifyCodeReq", response: Response):
    email = (req.email or "").lower().strip()
    if not db.verify_auth_code(email, req.code or ""):
        raise HTTPException(status_code=400, detail="invalid or expired code")
    resolved = _resolve_login(email)
    if not resolved:
        raise HTTPException(status_code=403, detail="no access for this email")
    user, membership = resolved
    return _login_payload(response, user, membership)


@app.post("/auth/request-link")
def request_link(req: RequestLinkReq):
    email = req.email.lower().strip()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="valid email required")
    if not db.get_user_by_email(email):   # Magic-Link nur für bestehende Konten
        raise HTTPException(status_code=404, detail="no_account")
    tok = db.create_magic_token(email)
    link = f"{PUBLIC_BASE_URL}/auth/verify?token={tok['token']}"
    sent = _send_email(email, "Dein c:node Login-Link",
                       _otp_email_html("— (nutze den Button)", link)) if RESEND_API_KEY else False
    if not sent:
        log.warning("MAGIC-LINK for %s → %s", email, link)
    out = {"sent": sent, "email": email, "expires_at": tok["expires_at"]}
    if not RESEND_API_KEY and not PUBLIC_DEMO:   # nur lokales Dev, nie in der öffentlichen Sandbox
        out["dev_token"] = tok["token"]
        out["dev_link"] = link
    return out


def _do_verify(token: str, response: Response) -> dict:
    row = db.consume_magic_token(token)
    if not row:
        raise HTTPException(status_code=400, detail="invalid or expired token")
    resolved = _resolve_login(row["email"])
    if not resolved:
        raise HTTPException(
            status_code=403,
            detail="no tenant access for this email — ask an admin to invite you",
        )
    user, membership = resolved
    jwt_token = auth.issue_jwt(
        user["id"], user["email"], membership["tenant_id"], membership["role"]
    )
    auth.set_session_cookie(response, jwt_token)
    tenant = db.get_tenant(membership["tenant_id"])
    return {
        "user": {"id": user["id"], "email": user["email"],
                 "name": user.get("name"), "company": user.get("company")},
        "tenant": tenant,
        "role": membership["role"],
        "token": jwt_token,  # convenience for non-cookie API clients / tests
    }


@app.post("/auth/verify")
def verify_post(req: VerifyReq, response: Response):
    return _do_verify(req.token, response)


@app.get("/auth/verify")
def verify_get(response: Response, token: str = Query(...)):
    # Convenience for clicking the magic link directly in a browser.
    return _do_verify(token, response)


# --- Google SSO ("Mit Google anmelden") — Login, getrennt vom Workspace-Connect ----------
def _sso_redirect_uri() -> str:
    return f"{PUBLIC_BASE_URL}/auth/sso/google/callback"


@app.get("/auth/sso/google/login")
def sso_google_login():
    """Startet den Google-SSO-Login (scope openid email profile)."""
    if not _google_configured():
        raise HTTPException(status_code=503, detail="google sso not configured")
    now = int(time.time())
    state = jwt.encode({"sso": True, "iat": now, "exp": now + _GOOGLE_STATE_TTL},
                       auth.AUTH_SECRET, algorithm=auth.JWT_ALG)
    params = {
        "client_id": GOOGLE_OAUTH_CLIENT_ID,
        "redirect_uri": _sso_redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "prompt": "select_account",
        "state": state,
    }
    return RedirectResponse(_GOOGLE_AUTH_URL + "?" + urlencode(params), status_code=302)


@app.get("/auth/sso/google/callback")
async def sso_google_callback(code: str | None = Query(None),
                              state: str | None = Query(None),
                              error: str | None = Query(None)):
    """Callback: Code→Token→verifizierte E-Mail→Session (Self-Service-Signup greift)."""
    origin = _frontend_origin()
    fail = RedirectResponse(f"{origin}/?login=error", status_code=302)
    if error or not code or not state:
        return fail
    try:
        claims = jwt.decode(state, auth.AUTH_SECRET, algorithms=[auth.JWT_ALG])
        if not claims.get("sso"):
            return fail
    except jwt.PyJWTError:
        return fail
    try:
        async with httpx.AsyncClient(timeout=T_SHORT) as c:
            tok = await c.post(_GOOGLE_TOKEN_URL, data={
                "code": code, "client_id": GOOGLE_OAUTH_CLIENT_ID,
                "client_secret": GOOGLE_OAUTH_CLIENT_SECRET,
                "redirect_uri": _sso_redirect_uri(), "grant_type": "authorization_code"})
            access = tok.json().get("access_token")
            if not access:
                return fail
            ui = await c.get("https://openidconnect.googleapis.com/v1/userinfo",
                             headers={"Authorization": f"Bearer {access}"})
            info = ui.json()
    except Exception:  # noqa: BLE001
        return fail
    email = (info.get("email") or "").lower().strip()
    if not email or info.get("email_verified") is False:
        return fail
    resolved = _resolve_login(email)
    if not resolved:
        return RedirectResponse(f"{origin}/?login=noaccess", status_code=302)
    user, membership = resolved
    jwt_token = auth.issue_jwt(user["id"], user["email"],
                               membership["tenant_id"], membership["role"])
    redirect = RedirectResponse(f"{origin}/?login=ok", status_code=302)
    auth.set_session_cookie(redirect, jwt_token)
    return redirect


@app.get("/auth/accept-invite")
def accept_invite(response: Response, token: str = Query(...)):
    """Invite-Link annehmen: User anlegen/finden, Org-Mitgliedschaft (+ optional Team)
    setzen, Einladung als angenommen markieren und Session ausstellen."""
    inv = db.get_invite_by_token(_token_hash(token))
    if not inv:
        raise HTTPException(status_code=400, detail="invalid or expired invite")
    user = db.upsert_user(inv["email"])
    if not db.get_membership(user["id"], inv["tenant_id"]):
        db.add_membership(user["id"], inv["tenant_id"], inv["org_role"])
    if inv.get("team_id"):
        db.add_team_member(inv["team_id"], user["id"], inv["tenant_id"],
                           inv.get("team_role") or "member", is_super=True)
    db.accept_invite(inv["id"], inv["tenant_id"])
    m = db.get_membership(user["id"], inv["tenant_id"])
    jwt_token = auth.issue_jwt(user["id"], user["email"], inv["tenant_id"],
                              (m or {}).get("role", inv["org_role"]))
    auth.set_session_cookie(response, jwt_token)
    tenant = db.get_tenant(inv["tenant_id"])
    return {"ok": True, "user": {"id": user["id"], "email": user["email"]},
            "tenant": tenant, "role": (m or {}).get("role", inv["org_role"]),
            "team_id": inv.get("team_id"), "token": jwt_token}


@app.post("/auth/logout")
def logout(response: Response):
    auth.clear_session_cookie(response)
    return {"ok": True}


# --------------------------------------------------------------------------
# Auth (Password: primary) — Magic-Link above stays available as an option
# --------------------------------------------------------------------------
@app.post("/auth/signup")
def signup(req: SignupReq, response: Response):
    email = req.email.lower().strip()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="valid email required")
    if not req.password or len(req.password) < 8:
        raise HTTPException(status_code=400, detail="password must be at least 8 characters")
    # Bot-Schutz auf der öffentlichen Sandbox: Altcha-PoW muss verifizieren.
    if PUBLIC_DEMO and not altcha_gate.verify(req.altcha):
        raise HTTPException(status_code=400, detail="altcha_failed")

    existing = db.get_user_by_email(email)
    # Already fully registered (has a password) → conflict.
    if existing and existing.get("password_hash"):
        raise HTTPException(status_code=409, detail="user already exists")

    pw_hash = auth.hash_password(req.password)
    if existing:  # invited stub (membership exists, no password yet) → set password
        user = db.set_user_password(existing["id"], pw_hash) or existing
    else:
        user = db.upsert_user(email, password_hash=pw_hash)

    # Persist the signup profile (name/company) for later onboarding.
    if req.name or req.company:
        user = db.upsert_user(email, name=req.name, company=req.company) or user
    # Join an existing tenant/role if invited; else:
    #  - PUBLIC_DEMO → member of the shared deployment tenant (Model A: shared tenant +
    #    per-user workspace). No fresh tenant per signup on the public sandbox.
    #  - otherwise → a fresh tenant owned by this signup as admin.
    membership = _best_membership(db.list_memberships_for_user(user["id"]))
    if membership is None:
        if PUBLIC_DEMO:
            db.upsert_tenant(DEPLOYMENT_TENANT, DEPLOYMENT_TENANT)
            membership = db.add_membership(user["id"], DEPLOYMENT_TENANT, "member")
        else:
            tenant_id = _slug(req.company or email.split("@", 1)[0])
            label = (req.company or email).strip()
            db.upsert_tenant(tenant_id, label)
            membership = db.add_membership(user["id"], tenant_id, "admin")

    return _login_payload(response, user, membership)


@app.post("/auth/login")
def login(req: LoginReq, response: Response):
    email = req.email.lower().strip()
    user = db.get_user_by_email(email)
    if not user:
        raise HTTPException(status_code=401, detail="invalid email or password")
    if not user.get("password_hash"):
        raise HTTPException(
            status_code=400,
            detail="no password set for this account — bitte Magic-Link nutzen",
        )
    if not auth.verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="invalid email or password")
    membership = _best_membership(db.list_memberships_for_user(user["id"]))
    if membership is None:
        raise HTTPException(
            status_code=403,
            detail="no tenant access for this email — ask an admin to invite you",
        )
    return _login_payload(response, user, membership)


@app.get("/auth/demo-accounts")
def demo_accounts():
    """Dev-only: list the seeded demo accounts incl. cleartext password."""
    # Öffentliche Sandbox: NIE Demo-Zugänge preisgeben (kein passwortloser Public-Zugang).
    if PUBLIC_DEMO or os.getenv("EXPOSE_DEMO_ACCOUNTS", "true").lower() != "true":
        raise HTTPException(status_code=404, detail="not found")
    out = []
    for email, role, tenant in db.DEMO_ACCOUNTS:
        t = db.get_tenant(tenant)
        out.append({
            "email": email,
            "password": db.DEMO_PASSWORD,
            "role": role,
            "tenant": tenant,
            "label": t["label"] if t else tenant,
        })
    return out


@app.post("/voice/transcribe")
async def voice_transcribe(
    file: UploadFile = File(...),
    identity: Identity = Depends(current_identity),
):
    """Auth-gated proxy → lokaler Voice-Service (faster-whisper). Transkript geht danach
    im Frontend durch das normale /ask-Routing."""
    data = await file.read()
    try:
        async with httpx.AsyncClient(timeout=T_LONG) as c:
            r = await c.post(
                f"{VOICE_URL}/transcribe",
                files={"file": (file.filename or "audio.webm", data, file.content_type or "audio/webm")},
            )
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"voice service unreachable: {e}")


@app.get("/me")
def me(identity: Identity = Depends(current_identity)):
    tenant = db.get_tenant(identity.tenant_id)
    return {
        "user": {"id": identity.user_id, "email": identity.email},
        "tenant": tenant or {"id": identity.tenant_id},
        "role": identity.role,
        "permissions": auth.permissions_for(identity.role),
        "acting_as": identity.acting_as,
        "home_tenant_id": identity.home_tenant_id,
    }


# --------------------------------------------------------------------------
# Clients / Tenants (auth-gated, tenant-scoped)
# --------------------------------------------------------------------------
@app.get("/clients")
def get_clients(identity: Identity = Depends(current_identity)):
    if identity.is_super:
        rows = db.list_tenants()
    else:
        t = db.get_tenant(identity.tenant_id)
        rows = [t] if t else []
    return {"clients": [{"id": r["id"], "label": r["label"],
                         "created_at": r.get("created_at")} for r in rows]}


@app.post("/clients")
def post_client(req: TenantReq,
                identity: Identity = Depends(require_permission("tenants:manage"))):
    return db.upsert_tenant(req.id or "", req.label)


@app.get("/clients/{client_id}/threads")
def get_client_threads(client_id: str, identity: Identity = Depends(current_identity)):
    if client_id != identity.tenant_id and not identity.is_super:
        raise HTTPException(status_code=403, detail="tenant scope violation")
    rows = db.list_threads(client_id, is_super=identity.is_super)
    visible = [t for t in rows if _can_access_thread(t, identity)]
    return {"client_id": client_id, "threads": visible}


# --------------------------------------------------------------------------
# Threads / Share
# --------------------------------------------------------------------------
@app.post("/threads/{thread_id}/share")
def share_thread(thread_id: str, req: ShareReq,
                 identity: Identity = Depends(require_permission("artifacts:write"))):
    thread = db.get_thread(thread_id, identity.tenant_id, is_super=identity.is_super)
    if not thread:
        raise HTTPException(status_code=404, detail="thread not found")
    share = db.create_share(thread_id, identity.tenant_id, req.role,
                            is_super=identity.is_super)
    return {"url": f"{PUBLIC_BASE_URL}/shared/{share['token']}", "role": share["role"]}


@app.get("/shared/{token}")
def open_share(token: str):
    # Public: possession of the share token is the authorization.
    share = db.resolve_share(token)
    if not share:
        raise HTTPException(status_code=404, detail="share not found")
    tid = share["tenant_id"]
    thread = db.get_thread(share["thread_id"], tid, is_super=True)
    return {
        "role": share["role"],
        "thread": thread,
        "messages": db.get_history(share["thread_id"], tid, limit=200, is_super=True),
        "artifacts": db.list_artifacts(tid, thread_id=share["thread_id"], is_super=True),
    }


# --------------------------------------------------------------------------
# Artifacts (SCOPE §2.3) — tenant-scoped from JWT
# --------------------------------------------------------------------------
@app.get("/artifacts")
def get_artifacts(thread_id: str | None = Query(None),
                  identity: Identity = Depends(require_permission("artifacts:read"))):
    rows = db.list_artifacts(identity.tenant_id, thread_id, is_super=identity.is_super)
    return {"artifacts": _demo_owned(rows, identity)}


@app.post("/artifacts")
def post_artifact(req: ArtifactReq,
                  identity: Identity = Depends(require_permission("artifacts:write"))):
    return db.save_artifact(req.model_dump(), identity.tenant_id,
                            is_super=identity.is_super, created_by=identity.email)


@app.post("/artifacts/save")
async def save_artifact_to_library(
    req: ArtifactSaveReq,
    identity: Identity = Depends(require_permission("artifacts:write")),
):
    """Speichert ein Session-Artefakt dauerhaft in der Bibliothek UND nimmt es in den
    Gedächtnis auf. Ohne diesen Aufruf bleibt ein Artefakt nur für die Session
    (Download/Export)."""
    # DB ist die Grundlage (Source-of-Truth, audit-fest) — zuerst persistieren.
    art = req.model_dump()
    saved = db.save_artifact(art, identity.tenant_id, is_super=identity.is_super,
                             created_by=identity.email)
    # Der Graph ist die lesbare, audit-sichere Projektion der DB: klarer Knoten-Label
    # (Titel) + Provenienz (Quelle/Autor/Zeitpunkt) + Inhalt für Mensch & LLM.
    graph_nodes = 0
    try:
        async with httpx.AsyncClient(timeout=T_LONG) as c:
            r = await c.post(
                f"{ENGINE_URL}/ingest",
                json={
                    "label": saved.get("title") or "Artefakt",
                    "type": "Document",
                    "props": {
                        "kind": saved.get("kind", "memo"),
                        "quelle": f"artefakt:{saved.get('id', '')}",  # Rück-Verweis auf DB-Record
                        "erstellt_von": identity.email,
                        "erstellt_am": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "mandant": identity.tenant_id,
                        "inhalt": (saved.get("markdown") or "")[:1800],
                    },
                    "links": [],
                    "client_id": _graph_client(identity),  # pro-User-Graph = Chat-Graph
                    "levels": ["client"],
                },
            )
            graph_nodes = len((r.json().get("graph_delta", {}) or {}).get("nodes", []))
    except Exception as e:  # noqa: BLE001
        log.warning("artifact graph ingest failed: %s", e)
    saved["saved"] = True
    return {"ok": True, "artifact": saved, "graph_nodes": graph_nodes}


# --------------------------------------------------------------------------
# Proxies to engine (tenant from JWT)
# --------------------------------------------------------------------------
@app.get("/queue")
async def queue(identity: Identity = Depends(current_identity)):
    """NEN-Verarbeitungs-Queue-Snapshot (für die UI-Sichtbarkeit der Ingest-Latenz)."""
    try:
        async with httpx.AsyncClient(timeout=T_SHORT) as c:
            r = await c.get(f"{ENGINE_URL}/queue")
            return r.json()
    except Exception:
        return {"nen": None}


@app.get("/graph")
async def graph(identity: Identity = Depends(require_permission("graph:read"))):
    try:
        # In der Free-Sandbox (PUBLIC_DEMO, kein Intel) auch die kuratierte NENA-Vorschau-Scheibe
        # einblenden — der Chat belegt daraus, also muss sie im Graph sichtbar sein.
        show_preview = PUBLIC_DEMO and not _entitlement(identity.tenant_id).get("intel")
        async with httpx.AsyncClient(timeout=T_LONG) as c:
            r = await c.get(f"{ENGINE_URL}/graph",
                            # hoher Node-Cap: ALLE gefütterten Knoten sichtbar (nicht nur 80).
                            # include_base: die immer-mitgelesene Basis-/Demo-Ebene einblenden,
                            # damit die Graph-Ansicht deckungsgleich mit den zitierten Quellen ist
                            # (Chat belegt aus Basis → Basis muss auch im Graph sichtbar sein).
                            params={"client_id": _graph_client(identity), "limit": 1000,
                                    "include_base": "true",
                                    "include_preview": "true" if show_preview else "false"})
            return r.json()
    except Exception:
        return {"nodes": [], "edges": [], "status": "degraded"}


@app.post("/route")
async def route_proxy(req: Request, identity: Identity = Depends(current_identity)):
    """Tenant-Orchestrator: entscheidet den Pfad EINER Nachricht. Die BFF reichert die
    Engine-Anfrage um die tenant-eigenen Formulare (FraBö) an — so bleibt das Routing
    tenant-bewusst, ohne dass die Engine Tenant-Config kennt."""
    body = await req.json()
    text = (body or {}).get("text", "")
    forms_payload: list[dict] = []
    try:
        from tenant_core.forms import load_forms
        for s in load_forms(_CONFIG_DIR):
            forms_payload.append({"id": s.id, "title": s.title, "kind": s.kind,
                                  "triggers": list(s.triggers or [])})
    except Exception:  # noqa: BLE001
        forms_payload = []
    payload = {"text": text, "client_id": _graph_client(identity),
               "forms": forms_payload, "history": (body or {}).get("history", [])}
    try:
        async with httpx.AsyncClient(timeout=T_SHORT) as c:
            r = await c.post(f"{ENGINE_URL}/route", json=payload)
            return r.json()
    except Exception:  # noqa: BLE001
        # Degradiert: Engine nicht erreichbar → Chat/Knowledge im Frontend entscheiden lassen.
        return {"route": "knowledge", "method": "degraded", "trace": []}


@app.post("/graph/capture")
async def graph_capture_proxy(req: Request, identity: Identity = Depends(current_identity)):
    """Chat-basierte Knoten-Aufnahme (Orchestrator-Route graph_ingest). client_id + Provenienz
    serverseitig aus dem JWT-Tenant/-User."""
    body = await req.json()
    body["client_id"] = _graph_client(identity)   # pro-User-Graph in der Sandbox
    body["contributed_by"] = identity.email
    try:
        async with httpx.AsyncClient(timeout=T_LONG) as c:
            r = await c.post(f"{ENGINE_URL}/graph/capture", json=body)
            data = r.json()
        # Echte Token-Nutzung in den Sandbox-Cap eintragen (ersetzt die Schätzung).
        ip = ratelimit.client_ip(req.headers, req.client.host if req.client else None)
        ratelimit.add_tokens(ip, int(data.get("tokens", 0) or 0))
        return data
    except Exception:  # noqa: BLE001
        return {"ok": False, "reason": "engine_unreachable", "added": []}


@app.post("/forms/{form_id}/submit")
async def form_submit_proxy(form_id: str, req: Request,
                            identity: Identity = Depends(current_identity)):
    """Interaktives Formular scoren + persistieren (Engine). client_id aus dem JWT-Tenant."""
    body = await req.json()
    body["client_id"] = identity.tenant_id
    body["contributed_by"] = identity.email  # O2 — Provenienz je Beitrag
    try:
        async with httpx.AsyncClient(timeout=T_LONG) as c:
            r = await c.post(f"{ENGINE_URL}/forms/{form_id}/submit", json=body)
            return r.json()
    except Exception:
        return {"ok": False, "reason": "engine_unreachable"}


@app.post("/forms/{form_id}/pdf")
async def form_pdf_proxy(form_id: str, req: Request,
                         identity: Identity = Depends(current_identity)):
    """PDF-Export eines Formular-Ergebnisses (Engine rendert; bff reicht binär durch)."""
    body = await req.json()
    try:
        async with httpx.AsyncClient(timeout=T_LONG) as c:
            r = await c.post(f"{ENGINE_URL}/forms/{form_id}/pdf", json=body)
    except Exception:
        raise HTTPException(status_code=502, detail="pdf_unreachable")
    ct = r.headers.get("content-type", "")
    if "application/pdf" not in ct:
        return Response(content=r.content, media_type=ct or "application/json", status_code=r.status_code)
    return Response(
        content=r.content, media_type="application/pdf",
        headers={"Content-Disposition": r.headers.get("content-disposition", f'attachment; filename="{form_id}.pdf"')},
    )


@app.get("/models")
async def models(identity: Identity = Depends(current_identity)):
    try:
        async with httpx.AsyncClient(timeout=T_SHORT) as c:
            r = await c.get(f"{ENGINE_URL}/models")
            return r.json()
    except Exception:
        return {"models": [{"id": DEFAULT_MODEL, "provider": DEFAULT_PROVIDER}],
                "status": "degraded"}


# --------------------------------------------------------------------------
# Admin — Super-Admin: tenants + tenant-admins
# --------------------------------------------------------------------------
@app.get("/admin/tenants")
def admin_list_tenants(identity: Identity = Depends(require_super_admin)):
    return {"tenants": db.list_tenants()}


@app.post("/admin/tenants")
def admin_create_tenant(req: TenantReq,
                        identity: Identity = Depends(require_super_admin)):
    t = db.upsert_tenant(req.id or "", req.label)
    # O7: neue Org bekommt sofort ein Default-Team („General").
    try:
        db.ensure_default_team(t["id"] if isinstance(t, dict) and t.get("id") else (req.id or ""))
    except Exception:  # noqa: BLE001
        pass
    return t


@app.delete("/admin/tenants/{tenant_id}")
def admin_delete_tenant(tenant_id: str,
                        identity: Identity = Depends(require_super_admin)):
    if tenant_id == "platform":
        raise HTTPException(status_code=400, detail="cannot delete platform tenant")
    ok = db.delete_tenant(tenant_id)
    if not ok:
        raise HTTPException(status_code=404, detail="tenant not found")
    return {"ok": True, "deleted": tenant_id}


@app.post("/admin/tenants/{tenant_id}/admins")
def admin_add_tenant_admin(tenant_id: str, req: AdminReq,
                           identity: Identity = Depends(require_super_admin)):
    if not db.get_tenant(tenant_id):
        raise HTTPException(status_code=404, detail="tenant not found")
    user = db.upsert_user(req.email)
    m = db.add_membership(user["id"], tenant_id, "admin")
    return {"user": {"id": user["id"], "email": user["email"]}, "membership": m}


# --------------------------------------------------------------------------
# Tenant — Admin: members + settings (scoped to own tenant)
# --------------------------------------------------------------------------
@app.get("/tenant/members")
def tenant_members(identity: Identity = Depends(require_permission("members:manage"))):
    return {"tenant_id": identity.tenant_id,
            "members": db.list_members_for_tenant(identity.tenant_id)}


@app.post("/tenant/members")
def tenant_add_member(req: MemberReq,
                      identity: Identity = Depends(require_permission("members:manage"))):
    # Only super-admin may mint further super-admins; admins cannot.
    if req.role == "super_admin":
        raise HTTPException(status_code=403, detail="cannot assign super_admin here")
    role = req.role if req.role in ("admin", "member", "viewer") else "member"
    user = db.upsert_user(req.email)
    m = db.add_membership(user["id"], identity.tenant_id, role)
    return {"user": {"id": user["id"], "email": user["email"]}, "membership": m}


@app.delete("/tenant/members/{membership_id}")
def tenant_remove_member(membership_id: str,
                         identity: Identity = Depends(require_permission("members:manage"))):
    ok = db.delete_membership(membership_id, identity.tenant_id)
    if not ok:
        raise HTTPException(status_code=404, detail="member not found in tenant")
    return {"ok": True, "deleted": membership_id}


class TenantSetupReq(BaseModel):
    """Owner-Org-Setup (Launch-Wizard): Name + Beschreibung + Quellen + Fortschritt."""
    org_name: str = ""
    org_profile: str = ""
    sources: list[dict] = Field(default_factory=list)  # [{kind:'url'|'text', value, status?}]
    completed: bool = False


@app.get("/tenant/setup")
def tenant_setup_get(identity: Identity = Depends(current_identity)):
    """Setup-State (für den Owner-Launch-Wizard). Sandbox: je User-Workspace; dediziert: je Tenant.
    In der Sandbox darf jeder seinen EIGENEN Workspace einrichten (can_edit=True)."""
    ws = _graph_client(identity)
    can_edit = True if PUBLIC_DEMO else auth_has_permission(identity.role, "members:manage")
    return {"tenant_id": identity.tenant_id, "can_edit": can_edit,
            **db.get_tenant_setup(identity.tenant_id, is_super=identity.is_super, workspace=ws)}


@app.put("/tenant/setup")
def tenant_setup_put(req: TenantSetupReq, identity: Identity = Depends(current_identity)):
    """Setup speichern. Sandbox (PUBLIC_DEMO): jeder speichert seinen EIGENEN Workspace-Setup.
    Dediziert: nur owner/admin (members:manage) für den tenant-weiten Setup."""
    if not PUBLIC_DEMO and not auth_has_permission(identity.role, "members:manage"):
        raise HTTPException(status_code=403, detail="owner/admin only")
    saved = db.save_tenant_setup(
        identity.tenant_id, org_name=req.org_name, org_profile=req.org_profile,
        sources=req.sources, completed=req.completed, updated_by=identity.email,
        is_super=identity.is_super, workspace=_graph_client(identity))
    return {"tenant_id": identity.tenant_id, "ok": True, **saved}


# --------------------------------------------------------------------------
# Monetarisierung: Entitlement (NENA-Intel + Token-Tier) + Billing-Webhook
# --------------------------------------------------------------------------
@app.get("/tenant/entitlement")
def tenant_entitlement(identity: Identity = Depends(current_identity)):
    """Was dieser Tenant freigeschaltet hat — steuert Upsell-Banner + Feature-Gates im Frontend.
    Liefert Tier, NENA-Flag und die geltenden Sandbox-Caps (nur in PUBLIC_DEMO relevant)."""
    ent = _entitlement(identity.tenant_id)
    caps = ratelimit.caps_for_tier(ent.get("tier"))
    return {
        "tenant_id": identity.tenant_id,
        "tier": ent.get("tier", "free"),
        "intel": bool(ent.get("intel")),
        "public_demo": PUBLIC_DEMO,
        "caps": caps,
        # Upsell-Ziele (Env-konfiguriert; leer → Frontend zeigt Sales-/Kontakt-Fallback).
        "upgrade": {
            "pro": os.getenv("STRIPE_LINK_PRO", ""),
            "team": os.getenv("STRIPE_LINK_TEAM", ""),
            "enterprise": os.getenv("SALES_CONTACT_URL", ""),
            "whitelabel": os.getenv("SALES_CONTACT_URL", ""),
        },
    }


# Tier je Stripe-Price/Product (Metadata product_tier bevorzugt, sonst Price-ID-Map).
def _tier_from_stripe(obj: dict) -> str:
    md = (obj.get("metadata") or {})
    t = (md.get("product_tier") or md.get("tier") or "").strip().lower()
    if t in ratelimit.TIERS:
        return t
    price_map = {}
    for pair in os.getenv("STRIPE_PRICE_TIERS", "").split(","):
        if ":" in pair:
            pid, tier = pair.split(":", 1)
            price_map[pid.strip()] = tier.strip().lower()
    # Line-Items / Subscription-Items nach bekannter Price-ID absuchen.
    for path in (("items", "data"), ("lines", "data")):
        node = obj
        for k in path:
            node = (node or {}).get(k) if isinstance(node, dict) else None
        for it in (node or []):
            pid = (((it.get("price") or {}).get("id")) or it.get("price") or "")
            if pid in price_map:
                return price_map[pid]
    return price_map.get(obj.get("price", ""), "pro")


@app.post("/billing/webhook")
async def billing_webhook(request: Request):
    """Stripe/IAP → Entitlement-Flip. Signatur wird mit STRIPE_WEBHOOK_SECRET geprüft
    (Replay-Schutz). checkout.session.completed / subscription.updated → intel=true + Tier;
    subscription.deleted → zurück auf free/kein Intel.

    Tenant-Zuordnung: client_reference_id bzw. metadata.tenant_id aus dem Checkout —
    beim Upgrade-Link als ?client_reference_id=<tenant> mitgeben."""
    raw = await request.body()
    secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    sig = request.headers.get("stripe-signature", "")
    event: dict
    if secret:
        try:
            import stripe  # optional dependency
            event = stripe.Webhook.construct_event(raw, sig, secret)
        except ImportError:
            # Kein SDK installiert → HMAC-Verifikation von Hand (Stripe-Scheme v1).
            if not _verify_stripe_sig(raw, sig, secret):
                raise HTTPException(status_code=400, detail="bad signature")
            event = json.loads(raw or b"{}")
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"invalid webhook: {exc.__class__.__name__}")
    else:
        # Dev/IAP ohne Secret: unsigniert akzeptieren (nur lokal/Test einsetzen).
        event = json.loads(raw or b"{}")

    etype = event.get("type", "")
    obj = ((event.get("data") or {}).get("object")) or {}
    tenant_id = (obj.get("client_reference_id")
                 or (obj.get("metadata") or {}).get("tenant_id")
                 or DEPLOYMENT_TENANT)
    customer = obj.get("customer") if isinstance(obj.get("customer"), str) else None

    if etype in ("checkout.session.completed", "customer.subscription.updated",
                 "customer.subscription.created", "invoice.paid"):
        status = obj.get("status", "")
        active = status not in ("canceled", "unpaid", "incomplete_expired")
        if etype == "checkout.session.completed":
            active = obj.get("payment_status", "paid") in ("paid", "no_payment_required")
        tier = _tier_from_stripe(obj) if active else "free"
        db.set_entitlement(tenant_id, intel=active, tier=tier, stripe_customer=customer)
    elif etype in ("customer.subscription.deleted",):
        db.set_entitlement(tenant_id, intel=False, tier="free", stripe_customer=customer)

    _ent_cache.pop(tenant_id, None)  # Cache invalidieren → sofort wirksam
    return {"ok": True, "tenant_id": tenant_id, "event": etype}


def _verify_stripe_sig(raw: bytes, header: str, secret: str) -> bool:
    """Stripe-Signatur (t=…,v1=…) ohne SDK prüfen: HMAC-SHA256 über 't.payload'."""
    import hashlib
    import hmac
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    t, v1 = parts.get("t"), parts.get("v1")
    if not t or not v1:
        return False
    signed = f"{t}.".encode() + raw
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, v1)


# --------------------------------------------------------------------------
# Epic O — Teams (Org × Team-Rollen-Gate): org admin/owner ODER Team-Lead
# --------------------------------------------------------------------------
class TeamReq(BaseModel):
    name: str
    description: str = ""


class TeamMemberReq(BaseModel):
    email: str
    role: str = "member"        # lead | member


class TeamRoleReq(BaseModel):
    role: str                   # lead | member


def _is_team_manager(identity: Identity, team_id: str) -> bool:
    """Darf dieses Team verwalten: Org-admin/owner (teams:manage) ODER Lead des Teams."""
    if auth.has_perm(identity.role, "teams:manage"):
        return True
    return db.user_team_role(team_id, identity.user_id, identity.tenant_id,
                             is_super=identity.is_super) == "lead"


@app.get("/tenant/teams")
def list_teams(identity: Identity = Depends(current_identity)):
    """Alle Teams der Org + die eigene Team-Rolle je Team (für die UI)."""
    teams = db.list_teams(identity.tenant_id, is_super=identity.is_super)
    mine = {t["id"]: t["role"] for t in
            db.list_teams_for_user(identity.user_id, identity.tenant_id, is_super=identity.is_super)}
    for t in teams:
        t["my_role"] = mine.get(t["id"])
    return {"tenant_id": identity.tenant_id, "teams": teams}


@app.get("/tenant/my-teams")
def my_teams(identity: Identity = Depends(current_identity)):
    return {"teams": db.list_teams_for_user(identity.user_id, identity.tenant_id,
                                            is_super=identity.is_super)}


@app.post("/tenant/teams")
def create_team(req: TeamReq,
                identity: Identity = Depends(require_permission("teams:manage"))):
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="name required")
    team = db.create_team(identity.tenant_id, req.name.strip(), req.description.strip(),
                          created_by=identity.email, is_super=identity.is_super)
    # Ersteller als Lead — tenant-lokalen User auflösen (users sind pro Tenant-DB; ein
    # Super-Admin/act-as hat evtl. keine user-Zeile in DIESER Org-DB → sonst FK-Fehler).
    u = db.upsert_user(identity.email)
    if not db.get_membership(u["id"], identity.tenant_id):
        db.add_membership(u["id"], identity.tenant_id, "admin" if identity.is_super else "member")
    db.add_team_member(team["id"], u["id"], identity.tenant_id, "lead", is_super=identity.is_super)
    return {"ok": True, "team": team}


@app.delete("/tenant/teams/{team_id}")
def delete_team(team_id: str,
                identity: Identity = Depends(require_permission("teams:manage"))):
    ok = db.delete_team(team_id, identity.tenant_id, is_super=identity.is_super)
    if not ok:
        raise HTTPException(status_code=404, detail="team not found")
    return {"ok": True, "deleted": team_id}


@app.get("/tenant/teams/{team_id}/members")
def team_members(team_id: str, identity: Identity = Depends(current_identity)):
    # Sichtbar für Team-Mitglieder + Org-Manager.
    if not (_is_team_manager(identity, team_id)
            or db.user_team_role(team_id, identity.user_id, identity.tenant_id,
                                 is_super=identity.is_super)):
        raise HTTPException(status_code=403, detail="not a team member")
    return {"team_id": team_id,
            "members": db.list_team_members(team_id, identity.tenant_id, is_super=identity.is_super)}


@app.post("/tenant/teams/{team_id}/members")
def team_add_member(team_id: str, req: TeamMemberReq,
                    identity: Identity = Depends(current_identity)):
    if not _is_team_manager(identity, team_id):
        raise HTTPException(status_code=403, detail="requires org admin/owner or team lead")
    role = req.role if req.role in ("lead", "member") else "member"
    user = db.upsert_user(req.email.strip().lower())
    # Team-Mitglied setzt eine Org-Mitgliedschaft voraus (sonst kein Org-Zugang).
    if not db.get_membership(user["id"], identity.tenant_id):
        db.add_membership(user["id"], identity.tenant_id, "member")
    m = db.add_team_member(team_id, user["id"], identity.tenant_id, role,
                           is_super=identity.is_super)
    return {"ok": True, "member": {**m, "email": user["email"]}}


@app.put("/tenant/teams/{team_id}/members/{user_id}")
def team_set_role(team_id: str, user_id: str, req: TeamRoleReq,
                  identity: Identity = Depends(current_identity)):
    if not _is_team_manager(identity, team_id):
        raise HTTPException(status_code=403, detail="requires org admin/owner or team lead")
    ok = db.set_team_role(team_id, user_id, identity.tenant_id, req.role,
                          is_super=identity.is_super)
    if not ok:
        raise HTTPException(status_code=404, detail="team member not found")
    return {"ok": True}


@app.delete("/tenant/teams/{team_id}/members/{user_id}")
def team_remove_member(team_id: str, user_id: str,
                       identity: Identity = Depends(current_identity)):
    if not _is_team_manager(identity, team_id):
        raise HTTPException(status_code=403, detail="requires org admin/owner or team lead")
    ok = db.remove_team_member(team_id, user_id, identity.tenant_id, is_super=identity.is_super)
    if not ok:
        raise HTTPException(status_code=404, detail="team member not found")
    return {"ok": True}


class InviteReq(BaseModel):
    email: str
    org_role: str = "member"     # owner|admin|member|viewer
    team_id: str | None = None
    team_role: str | None = None  # lead|member (nur mit team_id)


@app.post("/tenant/invites")
def create_invite(req: InviteReq, identity: Identity = Depends(current_identity)):
    """Einladung (Magic-Link) mit Org-Rolle + optional Team + Team-Rolle. Gate: org
    admin/owner für alles; Team-Lead darf in EIGENES Team einladen (Org-Rolle = member)."""
    email = req.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="valid email required")
    is_org_mgr = auth.has_perm(identity.role, "members:manage")
    org_role, team_role = "member", None

    if req.team_id:
        is_lead = db.user_team_role(req.team_id, identity.user_id, identity.tenant_id,
                                    is_super=identity.is_super) == "lead"
        if not (is_org_mgr or is_lead):
            raise HTTPException(status_code=403, detail="requires org admin/owner or team lead")
        team_role = req.team_role if req.team_role in ("lead", "member") else "member"
        org_role = req.org_role if (is_org_mgr and req.org_role in ("admin", "member", "viewer")) else "member"
    else:
        if not is_org_mgr:
            raise HTTPException(status_code=403, detail="requires org admin/owner")
        org_role = req.org_role if req.org_role in ("owner", "admin", "member", "viewer") else "member"

    # Nur owner/super darf owner vergeben.
    if org_role == "owner" and identity.role not in ("owner", "super_admin"):
        org_role = "admin"

    token = secrets.token_urlsafe(32)
    inv = db.create_invite(identity.tenant_id, email, org_role, _token_hash(token),
                           team_id=req.team_id, team_role=team_role,
                           invited_by=identity.email, is_super=identity.is_super)
    link = f"{PUBLIC_BASE_URL}/auth/accept-invite?token={token}"
    tenant = db.get_tenant(identity.tenant_id)
    tname = (tenant or {}).get("label") or identity.tenant_id
    html = (f"<p>Du wurdest zu <b>{tname}</b> eingeladen.</p>"
            f"<p><a href=\"{link}\">Einladung annehmen &amp; anmelden</a></p>"
            f"<p style=\"color:#888;font-size:12px\">Link läuft in 7 Tagen ab.</p>")
    sent = _send_email(email, f"Einladung zu {tname}", html)
    if not sent:
        log.warning("INVITE for %s → %s", email, link)
    return {"ok": True, "invite_id": inv["id"], "email": email, "org_role": org_role,
            "team_id": req.team_id, "team_role": team_role, "sent": sent,
            "dev_link": None if sent else link}


@app.put("/tenant/settings")
def tenant_settings(req: SettingsReq,
                    identity: Identity = Depends(require_permission("settings:manage"))):
    updated = db.update_tenant_settings(identity.tenant_id, req.settings)
    if not updated:
        raise HTTPException(status_code=404, detail="tenant not found")
    return updated


# --------------------------------------------------------------------------
# Promotions (Admin proposes → Super-Admin decides → market ingest)
# --------------------------------------------------------------------------
@app.post("/promotions")
def create_promotion(req: PromotionReq,
                     identity: Identity = Depends(require_permission("promotions:create"))):
    p = db.create_promotion(
        req.source_id, identity.tenant_id, identity.email,
        levels=["client", "market"], note=req.note, is_super=identity.is_super,
    )
    return p


@app.get("/admin/promotions")
def list_promotions(status: str | None = Query(None),
                    identity: Identity = Depends(require_permission("promotions:decide"))):
    return {"promotions": db.list_promotions(status=status, is_super=True)}


@app.post("/admin/promotions/{promotion_id}/approve")
async def approve_promotion(promotion_id: str,
                            identity: Identity = Depends(require_permission("promotions:decide"))):
    p = db.get_promotion(promotion_id, is_super=True)
    if not p:
        raise HTTPException(status_code=404, detail="promotion not found")
    if p["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"already {p['status']}")
    decided = db.decide_promotion(promotion_id, "approved", identity.email, is_super=True)

    # Ingest into the market level (engine group_id="market").
    ingest_result = {"status": "skipped"}
    try:
        async with httpx.AsyncClient(timeout=T_LONG) as c:
            r = await c.post(
                f"{ENGINE_URL}/ingest",
                json={
                    "label": p["source_id"],
                    "type": "Document",
                    "props": {"promoted_from": p["tenant_id"], "promotion_id": promotion_id},
                    "links": [],
                    "client_id": p["tenant_id"],
                    "levels": ["market"],
                },
            )
            ingest_result = r.json()
    except Exception as exc:  # noqa: BLE001
        ingest_result = {"status": "engine_unreachable", "error": exc.__class__.__name__}

    return {"promotion": decided, "ingest": ingest_result}


@app.post("/admin/promotions/{promotion_id}/reject")
def reject_promotion(promotion_id: str,
                     identity: Identity = Depends(require_permission("promotions:decide"))):
    p = db.get_promotion(promotion_id, is_super=True)
    if not p:
        raise HTTPException(status_code=404, detail="promotion not found")
    if p["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"already {p['status']}")
    decided = db.decide_promotion(promotion_id, "rejected", identity.email, is_super=True)
    return {"promotion": decided}


# --------------------------------------------------------------------------
# SCOPE v3 — Folders (tenant-scoped from JWT)
# --------------------------------------------------------------------------
@app.post("/admin/mesh/seed")
async def admin_mesh_seed(identity: Identity = Depends(require_super_admin)):
    """E2.5: Mesh-Ebene mit generischem Makro-Wissen befüllen (nur Super-Admin)."""
    try:
        async with httpx.AsyncClient(timeout=T_LONG) as c:
            r = await c.post(f"{ENGINE_URL}/mesh/seed")
            return r.json()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": "engine_unreachable", "detail": e.__class__.__name__}


@app.post("/admin/market/seed")
async def admin_market_seed(identity: Identity = Depends(require_super_admin)):
    """NENA-Markt-Ebene mit kuratiertem Marktwissen befüllen (nur Super-Admin).
    Das ist die bezahlte Ebene — im Chat erst mit intel=true / SHARED_LAYERS sichtbar."""
    try:
        async with httpx.AsyncClient(timeout=T_LONG) as c:
            r = await c.post(f"{ENGINE_URL}/market/seed")
            return r.json()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": "engine_unreachable", "detail": e.__class__.__name__}


@app.post("/admin/mesh/contribute")
async def admin_mesh_contribute(identity: Identity = Depends(require_super_admin)):
    """E2.4: anonymisierte Typ-Aggregate des Mandanten in den Mesh geben (nur Super-Admin)."""
    try:
        async with httpx.AsyncClient(timeout=T_LONG) as c:
            r = await c.post(f"{ENGINE_URL}/mesh/contribute",
                             json={"client_id": identity.tenant_id})
            return r.json()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": "engine_unreachable", "detail": e.__class__.__name__}


@app.get("/folders")
def get_folders(identity: Identity = Depends(current_identity)):
    return {"folders": db.list_folders(identity.tenant_id, is_super=identity.is_super)}


@app.post("/folders")
def post_folder(req: FolderReq, identity: Identity = Depends(current_identity)):
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    return db.create_folder(identity.tenant_id, name, identity.email,
                            is_super=identity.is_super)


@app.put("/folders/{folder_id}")
def put_folder(folder_id: str, req: FolderReq,
               identity: Identity = Depends(current_identity)):
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    updated = db.rename_folder(folder_id, identity.tenant_id, name,
                               is_super=identity.is_super)
    if not updated:
        raise HTTPException(status_code=404, detail="folder not found")
    return updated


@app.delete("/folders/{folder_id}")
def delete_folder(folder_id: str, identity: Identity = Depends(current_identity)):
    ok = db.delete_folder(folder_id, identity.tenant_id, is_super=identity.is_super)
    if not ok:
        raise HTTPException(status_code=404, detail="folder not found")
    return {"ok": True, "deleted": folder_id}


# --------------------------------------------------------------------------
# SCOPE v3 — Threads: PUT (patch) / DELETE (owner or admin/super)
# --------------------------------------------------------------------------
@app.put("/threads/{thread_id}")
def put_thread(thread_id: str, req: ThreadPatchReq,
               identity: Identity = Depends(current_identity)):
    thread = db.get_thread(thread_id, identity.tenant_id, is_super=identity.is_super)
    if not thread:
        raise HTTPException(status_code=404, detail="thread not found")
    if not _is_thread_owner(thread, identity):
        raise HTTPException(status_code=403, detail="only the owner or an admin may edit")
    if req.visibility is not None and req.visibility not in ("private", "team", "org"):
        raise HTTPException(status_code=400, detail="visibility must be private|team|org")
    updated = db.update_thread(
        thread_id, identity.tenant_id,
        title=req.title,
        folder_id=(... if req.folder_id is None else req.folder_id),
        visibility=req.visibility,
        members=req.members,
        team_id=(req.team_id if req.set_team else ...),
        is_super=identity.is_super,
    )
    return updated


@app.get("/threads/{thread_id}/messages")
def get_thread_messages(thread_id: str, identity: Identity = Depends(current_identity)):
    """Persistierte Nachrichten eines Threads (role+text) für die Wiederherstellung im UI."""
    thread = db.get_thread(thread_id, identity.tenant_id, is_super=identity.is_super)
    if not thread:
        raise HTTPException(status_code=404, detail="thread not found")
    if not _can_access_thread(thread, identity):
        raise HTTPException(status_code=403, detail="no access to this thread")
    messages = db.get_history(thread_id, identity.tenant_id, limit=200,
                              is_super=identity.is_super)
    return {"thread_id": thread_id, "messages": messages}


@app.delete("/threads/{thread_id}")
def delete_thread(thread_id: str, identity: Identity = Depends(current_identity)):
    thread = db.get_thread(thread_id, identity.tenant_id, is_super=identity.is_super)
    if not thread:
        raise HTTPException(status_code=404, detail="thread not found")
    if not _is_thread_owner(thread, identity):
        raise HTTPException(status_code=403, detail="only the owner or an admin may delete")
    db.delete_thread(thread_id, identity.tenant_id, is_super=identity.is_super)
    return {"ok": True, "deleted": thread_id}


# NOTE: PUT of folder_id via ThreadPatchReq — a JSON body that omits folder_id
# leaves it unchanged; sending `"folder_id": null` moves the thread out of any
# folder. (Pydantic can't distinguish the two here, so 'null' == 'move to root'.)


# --------------------------------------------------------------------------
# SCOPE v3 — Notifications (recipient-scoped: a user reads their own)
# --------------------------------------------------------------------------
@app.get("/notifications")
def get_notifications(identity: Identity = Depends(current_identity)):
    items = db.list_notifications(identity.email)
    # normalise field name to the frozen contract ({...,"from":...})
    for it in items:
        it["from"] = it.pop("from_email", None)
    return {"items": items, "unread": db.count_unread(identity.email)}


@app.post("/notifications/{notif_id}/read")
def read_notification(notif_id: str, identity: Identity = Depends(current_identity)):
    ok = db.mark_notification_read(notif_id, identity.email)
    if not ok:
        raise HTTPException(status_code=404, detail="notification not found")
    return {"ok": True, "unread": db.count_unread(identity.email)}


@app.post("/notifications/read-all")
def read_all_notifications(identity: Identity = Depends(current_identity)):
    n = db.mark_all_notifications_read(identity.email)
    return {"ok": True, "marked": n, "unread": 0}


# --------------------------------------------------------------------------
# SCOPE v3 — Data-requests / escalation (Member→Admin→Super-Admin)
# --------------------------------------------------------------------------
@app.post("/data-requests")
def post_data_request(req: DataRequestReq,
                      identity: Identity = Depends(current_identity)):
    scope = (req.scope or "").strip()
    if not scope:
        raise HTTPException(status_code=400, detail="scope required")
    target_role = _ESCALATION.get(identity.role)
    if not target_role:
        raise HTTPException(
            status_code=400,
            detail="super-admin can provision data directly — no escalation needed",
        )
    dr = db.create_data_request(
        identity.tenant_id, scope, req.note, req.connector,
        identity.email, target_role, is_super=identity.is_super,
    )
    # notify everyone able to approve (super_admin resolved globally)
    recipients = db.emails_with_role(
        target_role, None if target_role == "super_admin" else identity.tenant_id
    )
    db.notify_many(
        recipients,
        tenant_id=identity.tenant_id, ntype="data_request",
        title=f"Daten-Anfrage: {scope}",
        body=(req.note or f"{identity.email} bittet um Zugriff/Connector „{scope}“."),
        from_email=identity.email, data={"data_request_id": dr["id"],
                                         "connector": req.connector},
    )
    return {"data_request": dr, "notified": len(recipients)}


@app.get("/data-requests")
def get_data_requests(identity: Identity = Depends(current_identity)):
    return {"data_requests": db.list_data_requests(
        identity.tenant_id, identity.role, identity.email,
        is_super=identity.is_super)}


def _decide_data_request(request_id: str, decision: str, identity: Identity) -> dict:
    dr = db.get_data_request(request_id, is_super=True)
    if not dr:
        raise HTTPException(status_code=404, detail="data-request not found")
    # only the addressed (target) role may decide
    if identity.role != dr["target_role"]:
        raise HTTPException(
            status_code=403,
            detail=f"only '{dr['target_role']}' may {decision} this request",
        )
    # non-super deciders must stay within their tenant
    if not identity.is_super and dr["tenant_id"] != identity.tenant_id:
        raise HTTPException(status_code=403, detail="tenant scope violation")
    if dr["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"already {dr['status']}")
    decided = db.decide_data_request(request_id, decision, identity.email, is_super=True)
    # notify the requester back
    db.create_notification(
        tenant_id=dr["tenant_id"], recipient_email=dr["requested_by"],
        ntype=f"data_request_{decision}",
        title=f"Daten-Anfrage {('genehmigt' if decision == 'approved' else 'abgelehnt')}",
        body=f"„{dr['scope']}“ wurde von {identity.email} {decision}.",
        from_email=identity.email, data={"data_request_id": request_id},
    )
    return {"data_request": decided}


@app.post("/data-requests/{request_id}/approve")
def approve_data_request(request_id: str,
                         identity: Identity = Depends(current_identity)):
    return _decide_data_request(request_id, "approved", identity)


@app.post("/data-requests/{request_id}/reject")
def reject_data_request(request_id: str,
                        identity: Identity = Depends(current_identity)):
    return _decide_data_request(request_id, "rejected", identity)


# --------------------------------------------------------------------------
# SCOPE v3 — Library (proxy → assets) + active connectors from tenant settings
# --------------------------------------------------------------------------
@app.get("/library")
async def library(thread_id: str | None = Query(None),
                  identity: Identity = Depends(current_identity)):
    files: list = []
    assets_status = "ok"
    gclient = _graph_client(identity)   # pro-User-Workspace (Sandbox) — deckt sich mit dem Chat-Graph
    params = {"client_id": gclient}
    if thread_id:
        params["thread_id"] = thread_id
    try:
        async with httpx.AsyncClient(timeout=T_LONG) as c:
            r = await c.get(f"{ASSETS_URL}/library/files", params=params)
            if r.status_code == 200:
                files = r.json().get("files", r.json() if isinstance(r.json(), list) else [])
            else:
                assets_status = "degraded"
    except Exception:
        assets_status = "unreachable"
    tenant = db.get_tenant(identity.tenant_id) or {}
    connectors = (tenant.get("settings") or {}).get("connectors", [])
    return {"files": files, "connectors": connectors,
            "client_id": gclient, "assets": assets_status}


@app.post("/library/upload")
async def library_upload(files: list[UploadFile] = File(...),
                         thread_id: str | None = Form(None),
                         identity: Identity = Depends(require_permission("ingest:client"))):
    """Multi-file upload → jede Datei einzeln an den Assets-Service weiterreichen.

    Das Frontend sendet das Feld ``files`` (auch bei einer Datei) und optional
    ``thread_id`` (Chat-/Thread-Upload → in der rechten Thread-Sidebar sichtbar).
    Tenant wird serverseitig aus dem JWT gesetzt, nie aus dem Request-Body.
    """
    results: list = []
    errors: list = []
    # pro-User-Workspace (Sandbox) → Datei landet im SELBEN Graph, aus dem der Chat liest,
    # und wird so nach dem Upload sofort im Chat/Gedächtnis nutzbar (nicht nur im Tenant-Graph).
    fwd: dict = {"client_id": _graph_client(identity)}
    if thread_id:
        fwd["thread_id"] = thread_id
    try:
        async with httpx.AsyncClient(timeout=T_LONG) as c:
            for f in files:
                data = await f.read()
                try:
                    r = await c.post(
                        f"{ASSETS_URL}/library/upload",
                        files={"file": (f.filename or "upload.bin", data,
                                        f.content_type or "application/octet-stream")},
                        data=fwd,
                    )
                    if r.status_code >= 400:
                        errors.append({"name": f.filename, "status": r.status_code,
                                       "detail": r.text[:300]})
                    else:
                        body = r.json()
                        rec = body.get("file", body) if isinstance(body, dict) else body
                        if isinstance(rec, dict) and isinstance(body, dict):
                            # Auszug + Titel mitgeben, damit der Chat den Inhalt einordnen kann.
                            rec["excerpt"] = body.get("excerpt", "")
                            rec["title"] = body.get("title", rec.get("name", ""))
                        results.append(rec)
                except Exception as e:  # eine Datei scheitert → andere weiterlaufen lassen
                    errors.append({"name": f.filename, "detail": str(e)})
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"assets service unreachable: {e}")
    if not results and errors:
        raise HTTPException(status_code=502, detail={"errors": errors})
    return {"ok": True, "files": results, "ingested": len(results), "errors": errors}


@app.delete("/library/files/{file_id}")
async def library_delete(file_id: str,
                         identity: Identity = Depends(require_permission("ingest:client"))):
    try:
        async with httpx.AsyncClient(timeout=T_LONG) as c:
            r = await c.delete(f"{ASSETS_URL}/library/files/{file_id}",
                               params={"client_id": _graph_client(identity)})
        if r.status_code == 404:
            raise HTTPException(status_code=404, detail="file not found")
        try:
            return r.json()
        except Exception:
            return {"ok": r.status_code < 400, "deleted": file_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"assets service unreachable: {e}")


# --------------------------------------------------------------------------
# SCOPE v3 — Google integration (LIVE Authorization-Code-Flow + Gmail/Drive).
#
# When GOOGLE_OAUTH_CLIENT_ID/SECRET are unset every action-endpoint answers
# ``{ok:false, reason:"not_configured"}`` (HTTP 200, no crash). Once creds are
# wired the connector runs the real OAuth flow and talks to the Gmail/Drive REST
# APIs via httpx.
#
# IMPORTANT — Google Cloud Console setup required for the live path:
#   * GOOGLE_OAUTH_REDIRECT_URI must be registered *verbatim* as an "Authorized
#     redirect URI" on the OAuth 2.0 Client (default:
#     ``{PUBLIC_BASE_URL}/integrations/google/oauth/callback``).
#   * The Drive endpoints need the ``.../auth/drive`` scope (create/list files);
#     Gmail search needs ``.../auth/gmail.readonly``. Both are in
#     GOOGLE_OAUTH_SCOPES by default. Enable the Gmail API + Drive API for the
#     project.
# --------------------------------------------------------------------------
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
# state token lifetime (short-lived — it only bridges install → callback)
_GOOGLE_STATE_TTL = 600


def _google_not_configured() -> dict:
    return {"ok": False, "reason": "not_configured"}


def _frontend_origin() -> str:
    """First configured CORS origin — where the browser is sent post-OAuth."""
    origins = os.getenv("CORS_ORIGINS", "http://localhost:3010").split(",")
    return (origins[0].strip() if origins and origins[0].strip()
            else "http://localhost:3010").rstrip("/")


def _google_state_encode(identity: Identity) -> str:
    """Signed JWT carrying the tenant + user across the OAuth redirect."""
    now = int(time.time())
    payload = {
        "tenant_id": identity.tenant_id,
        "user_email": identity.email,
        "iat": now,
        "exp": now + _GOOGLE_STATE_TTL,
    }
    return jwt.encode(payload, auth.AUTH_SECRET, algorithm=auth.JWT_ALG)


def _google_state_decode(state: str) -> dict:
    return jwt.decode(state, auth.AUTH_SECRET, algorithms=[auth.JWT_ALG])


async def _google_token_request(data: dict) -> dict:
    """POST to Google's token endpoint (auth-code exchange or refresh)."""
    async with httpx.AsyncClient(timeout=T_LONG) as c:
        r = await c.post(_GOOGLE_TOKEN_URL, data=data)
        r.raise_for_status()
        return r.json()


async def _google_access_token(identity: Identity) -> str | None:
    """Return a valid access token for the identity, refreshing if needed.

    Returns None when the tenant/user has never connected Google. On refresh
    failure the (possibly stale) stored token is returned so the caller's API
    call surfaces the real error rather than a silent None.
    """
    row = db.get_google_tokens(identity.tenant_id, identity.email)
    if not row:
        return None
    access = row.get("access_token")
    expiry = row.get("expiry") or 0
    try:
        expiry = float(expiry)
    except (TypeError, ValueError):
        expiry = 0.0
    # still fresh (60s safety margin)?
    if access and time.time() < (expiry - 60):
        return access
    refresh = row.get("refresh_token")
    if not refresh:
        return access  # nothing to refresh with — may 401 downstream
    try:
        tok = await _google_token_request({
            "client_id": GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": GOOGLE_OAUTH_CLIENT_SECRET,
            "refresh_token": refresh,
            "grant_type": "refresh_token",
        })
    except Exception as e:  # noqa: BLE001
        log.warning("google token refresh failed: %s", e)
        return access
    new_access = tok.get("access_token")
    if not new_access:
        return access
    expires_in = int(tok.get("expires_in", 3600))
    try:
        db.save_google_tokens(
            identity.tenant_id, identity.email,
            access_token=new_access,
            refresh_token=tok.get("refresh_token"),  # usually absent on refresh
            token_type=tok.get("token_type"),
            scope=tok.get("scope") or row.get("scope"),
            expiry=int(time.time()) + expires_in,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("google token persist (refresh) failed: %s", e)
    return new_access


@app.get("/integrations/google/status")
def google_status(identity: Identity = Depends(current_identity)):
    row = db.get_google_tokens(identity.tenant_id, identity.email)
    if row and row.get("scope"):
        scopes = row["scope"].split()
    elif _google_configured():
        scopes = GOOGLE_OAUTH_SCOPES.split()
    else:
        scopes = []
    return {
        "configured": _google_configured(),
        "connected": bool(row and row.get("access_token")),
        "email": row.get("user_email") if row else None,
        "scopes": scopes,
    }


@app.post("/integrations/google/disconnect")
def google_disconnect(identity: Identity = Depends(current_identity)):
    """Remove the stored Google tokens for the current (tenant, user)."""
    removed = db.delete_google_tokens(identity.tenant_id, identity.email)
    return {"ok": True, "connected": False, "removed": removed}


@app.get("/integrations/google/oauth/install")
def google_install(identity: Identity = Depends(current_identity)):
    if PUBLIC_DEMO:
        raise HTTPException(status_code=403, detail="integrations_not_in_sandbox")
    if not _google_configured():
        return _google_not_configured()
    # live path: send the user to Google's consent screen. tenant+user carried
    # in a signed ``state`` JWT so the callback can attribute the tokens.
    params = {
        "client_id": GOOGLE_OAUTH_CLIENT_ID,
        "redirect_uri": GOOGLE_OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": GOOGLE_OAUTH_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": _google_state_encode(identity),
    }
    url = _GOOGLE_AUTH_URL + "?" + urlencode(params)
    return RedirectResponse(url, status_code=302)


@app.get("/integrations/google/oauth/callback")
async def google_callback(code: str | None = Query(None),
                          state: str | None = Query(None),
                          error: str | None = Query(None)):
    # No auth dependency: Google redirects the browser here; the signed `state`
    # is the trusted carrier of tenant + user identity.
    if not _google_configured():
        return _google_not_configured()
    origin = _frontend_origin()
    err_redirect = RedirectResponse(f"{origin}/?google=error", status_code=302)
    if error or not code or not state:
        return err_redirect
    try:
        claims = _google_state_decode(state)
    except jwt.PyJWTError as e:
        log.warning("google oauth state invalid: %s", e)
        return err_redirect
    tenant_id = claims.get("tenant_id") or ""
    user_email = claims.get("user_email") or ""
    try:
        tok = await _google_token_request({
            "code": code,
            "client_id": GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": GOOGLE_OAUTH_CLIENT_SECRET,
            "redirect_uri": GOOGLE_OAUTH_REDIRECT_URI,
            "grant_type": "authorization_code",
        })
    except Exception as e:  # noqa: BLE001
        log.warning("google token exchange failed: %s", e)
        return err_redirect
    access = tok.get("access_token")
    if not access:
        return err_redirect
    expires_in = int(tok.get("expires_in", 3600))
    try:
        db.save_google_tokens(
            tenant_id, user_email,
            access_token=access,
            refresh_token=tok.get("refresh_token"),
            token_type=tok.get("token_type"),
            scope=tok.get("scope") or GOOGLE_OAUTH_SCOPES,
            expiry=int(time.time()) + expires_in,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("google token persist failed: %s", e)
        return err_redirect
    return RedirectResponse(f"{origin}/?google=connected", status_code=302)


@app.post("/integrations/google/gmail/search")
async def google_gmail_search(req: GoogleQueryReq,
                              identity: Identity = Depends(current_identity)):
    if not _google_configured():
        return _google_not_configured()
    token = await _google_access_token(identity)
    if not token:
        return {"ok": False, "reason": "not_connected"}
    headers = {"Authorization": f"Bearer {token}"}
    try:
        max_results = max(1, min(int(req.max or 10), 50))
    except (TypeError, ValueError):
        max_results = 10
    try:
        async with httpx.AsyncClient(timeout=T_LONG) as c:
            lr = await c.get(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                params={"q": req.q, "maxResults": max_results},
                headers=headers,
            )
            if lr.status_code != 200:
                return {"ok": False, "reason": "gmail_error",
                        "detail": lr.text[:300]}
            ids = [m["id"] for m in (lr.json().get("messages") or []) if m.get("id")]
            messages = []
            for mid in ids:
                mr = await c.get(
                    f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{mid}",
                    params=[("format", "metadata"),
                            ("metadataHeaders", "Subject"),
                            ("metadataHeaders", "From"),
                            ("metadataHeaders", "Date")],
                    headers=headers,
                )
                if mr.status_code != 200:
                    continue
                mj = mr.json()
                hdrs = {h.get("name", "").lower(): h.get("value", "")
                        for h in (mj.get("payload", {}).get("headers") or [])}
                messages.append({
                    "id": mid,
                    "subject": hdrs.get("subject", ""),
                    "from": hdrs.get("from", ""),
                    "date": hdrs.get("date", ""),
                    "snippet": mj.get("snippet", ""),
                })
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": "gmail_exception", "detail": str(e)[:300]}
    return {"ok": True, "messages": messages}


@app.post("/integrations/google/drive/list")
async def google_drive_list(req: DriveListReq,
                            identity: Identity = Depends(current_identity)):
    if not _google_configured():
        return _google_not_configured()
    token = await _google_access_token(identity)
    if not token:
        return {"ok": False, "reason": "not_connected"}
    headers = {"Authorization": f"Bearer {token}"}
    try:
        page_size = max(1, min(int(req.max or 20), 100))
    except (TypeError, ValueError):
        page_size = 20
    params = {"pageSize": page_size,
              "fields": "files(id,name,mimeType,modifiedTime,webViewLink)"}
    if req.q:
        params["q"] = req.q
    try:
        async with httpx.AsyncClient(timeout=T_LONG) as c:
            r = await c.get("https://www.googleapis.com/drive/v3/files",
                            params=params, headers=headers)
            if r.status_code != 200:
                return {"ok": False, "reason": "drive_error",
                        "detail": r.text[:300]}
            files = r.json().get("files", [])
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": "drive_exception", "detail": str(e)[:300]}
    return {"ok": True, "files": files}


@app.post("/integrations/google/drive/put")
async def google_drive_put(req: DrivePutReq,
                           identity: Identity = Depends(current_identity)):
    if not _google_configured():
        return _google_not_configured()
    token = await _google_access_token(identity)
    if not token:
        return {"ok": False, "reason": "not_connected"}
    mime = req.mime or "text/plain"
    metadata: dict = {"name": req.name}
    if req.mime:
        metadata["mimeType"] = req.mime
    # Build a multipart/related body by hand (stdlib) — metadata part + media
    # part — for Drive's uploadType=multipart endpoint.
    boundary = db.new_id("cnode")
    body = (
        f"--{boundary}\r\n"
        "Content-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{json.dumps(metadata)}\r\n"
        f"--{boundary}\r\n"
        f"Content-Type: {mime}\r\n\r\n"
        f"{req.content}\r\n"
        f"--{boundary}--"
    ).encode("utf-8")
    headers = {"Authorization": f"Bearer {token}",
               "Content-Type": f"multipart/related; boundary={boundary}"}
    try:
        async with httpx.AsyncClient(timeout=T_LONG) as c:
            r = await c.post(
                "https://www.googleapis.com/upload/drive/v3/files",
                params={"uploadType": "multipart",
                        "fields": "id,name,webViewLink"},
                content=body, headers=headers,
            )
            if r.status_code not in (200, 201):
                return {"ok": False, "reason": "drive_error",
                        "detail": r.text[:300]}
            file = r.json()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": "drive_exception", "detail": str(e)[:300]}
    return {"ok": True, "file": file}


# --------------------------------------------------------------------------
# E2.1 Connector-Auto-Ingest — Gmail/Drive → Gedächtnis (mit Provenienz)
# --------------------------------------------------------------------------
@app.post("/integrations/google/sync")
async def google_sync(req: GoogleSyncReq,
                      identity: Identity = Depends(current_identity)):
    """Liest die jüngsten Gmail-Betreffe + Drive-Dateien und schreibt sie als Knoten
    mit Provenienz (Quelle, Autor, Zeit, Mandant) ins Gedächtnis. Nutzer-getriggert."""
    if not _google_configured():
        return _google_not_configured()
    token = await _google_access_token(identity)
    if not token:
        return {"ok": False, "reason": "not_connected",
                "detail": "Google-Konto ist nicht verbunden."}
    tenant_id = identity.tenant_id
    gclient = _graph_client(identity)   # pro-User-Graph in der Sandbox
    headers = {"Authorization": f"Bearer {token}"}
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    nodes: list[dict] = []
    gmail_n = 0
    drive_n = 0
    max_gmail = max(0, min(int(req.max_gmail or 0), 25))
    max_drive = max(0, min(int(req.max_drive or 0), 25))

    async def _ingest(label: str, props: dict) -> None:
        try:
            r = await c.post(f"{ENGINE_URL}/ingest", json={
                "label": label[:180] or "(ohne Titel)", "type": "Document",
                "props": {**props, "erstellt_von": identity.email, "erstellt_am": stamp,
                          "mandant": tenant_id},
                "links": [], "client_id": gclient, "levels": ["client"]})
            nodes.extend(r.json().get("graph_delta", {}).get("nodes", []))
        except Exception:  # noqa: BLE001
            pass

    async with httpx.AsyncClient(timeout=T_LONG) as c:
        # ---- Gmail (Betreff/From/Date als Knoten) ----
        if max_gmail:
            try:
                lr = await c.get(
                    "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                    params={"maxResults": max_gmail}, headers=headers)
                ids = [m["id"] for m in (lr.json().get("messages") or []) if m.get("id")]
                for mid in ids:
                    mr = await c.get(
                        f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{mid}",
                        params=[("format", "metadata"), ("metadataHeaders", "Subject"),
                                ("metadataHeaders", "From"), ("metadataHeaders", "Date")],
                        headers=headers)
                    if mr.status_code != 200:
                        continue
                    mj = mr.json()
                    h = {x.get("name", "").lower(): x.get("value", "")
                         for x in (mj.get("payload", {}).get("headers") or [])}
                    await _ingest(h.get("subject", "(ohne Betreff)"), {
                        "quelle": "gmail", "von": h.get("from", ""), "datum": h.get("date", ""),
                        "snippet": (mj.get("snippet", "") or "")[:220]})
                    gmail_n += 1
            except Exception as e:  # noqa: BLE001
                log.warning("gmail sync failed: %s", e)
        # ---- Drive (Dateinamen als Knoten) ----
        if max_drive:
            try:
                dr = await c.get(
                    "https://www.googleapis.com/drive/v3/files",
                    params={"pageSize": max_drive, "orderBy": "modifiedTime desc",
                            "fields": "files(id,name,mimeType,modifiedTime,webViewLink)"},
                    headers=headers)
                for f in (dr.json().get("files", []) if dr.status_code == 200 else []):
                    await _ingest(f.get("name", "(Datei)"), {
                        "quelle": "drive", "mime": f.get("mimeType", ""),
                        "geaendert": f.get("modifiedTime", ""), "link": f.get("webViewLink", "")})
                    drive_n += 1
            except Exception as e:  # noqa: BLE001
                log.warning("drive sync failed: %s", e)

    return {"ok": True, "gmail": gmail_n, "drive": drive_n, "nodes": len(nodes),
            "graph_delta": {"nodes": nodes, "edges": []}}


# --------------------------------------------------------------------------
# Agentische Aktion ausführen — NUR nach expliziter Bestätigung im Frontend
# --------------------------------------------------------------------------
@app.post("/action/execute")
async def action_execute(req: ActionExecuteReq,
                         identity: Identity = Depends(current_identity)):
    """Führt eine zuvor bestätigte agentische Aktion echt über den Connector aus."""
    if req.type == "gmail_draft":
        return await _exec_gmail_draft(identity, req.params or {})
    if req.type == "gcal_event":
        return await _exec_gcal_event(identity, req.params or {})
    if req.type == "outlook_draft":
        return await _exec_outlook_draft(identity, req.params or {})
    if req.type == "outlook_event":
        return await _exec_outlook_event(identity, req.params or {})
    return {"ok": False, "reason": "unsupported_action",
            "detail": f"Aktion '{req.type}' wird noch nicht unterstützt."}


async def _exec_gmail_draft(identity: Identity, params: dict) -> dict:
    """Legt einen echten Gmail-Entwurf an (users/me/drafts). Braucht gmail.compose."""
    if not _google_configured():
        return {"ok": False, "reason": "not_configured",
                "detail": "Google ist serverseitig nicht konfiguriert."}
    token = await _google_access_token(identity)
    if not token:
        return {"ok": False, "reason": "not_connected",
                "detail": "Google-Konto ist nicht verbunden."}
    subject = str(params.get("subject") or "Nachricht von c:node")
    body = str(params.get("body") or "")
    to = str(params.get("to") or "")
    # RFC-2822 → base64url (ohne Padding), wie von der Gmail-API verlangt.
    mime = (
        (f"To: {to}\r\n" if to else "")
        + f"Subject: {subject}\r\n"
        + "Content-Type: text/plain; charset=UTF-8\r\n\r\n"
        + body
    )
    raw = base64.urlsafe_b64encode(mime.encode("utf-8")).decode("ascii").rstrip("=")
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(timeout=T_LONG) as c:
            r = await c.post(
                "https://gmail.googleapis.com/gmail/v1/users/me/drafts",
                headers=headers, json={"message": {"raw": raw}},
            )
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": "gmail_exception", "detail": str(e)[:300]}
    if r.status_code in (200, 201):
        return {"ok": True, "id": r.json().get("id", ""),
                "message": "Entwurf in Gmail angelegt — du kannst ihn dort prüfen und senden."}
    if r.status_code in (401, 403):
        return {"ok": False, "reason": "scope_missing",
                "detail": "Gmail-Entwurf braucht die Berechtigung 'gmail.compose'. "
                          "Bitte den Scope im Google-Consent ergänzen und Google neu verbinden.",
                "raw": r.text[:200]}
    return {"ok": False, "reason": "gmail_error", "detail": r.text[:300]}


async def _exec_gcal_event(identity: Identity, params: dict) -> dict:
    """Legt einen echten Google-Calendar-Termin an (primary). Braucht calendar.events."""
    if not _google_configured():
        return {"ok": False, "reason": "not_configured",
                "detail": "Google ist serverseitig nicht konfiguriert."}
    token = await _google_access_token(identity)
    if not token:
        return {"ok": False, "reason": "not_connected",
                "detail": "Google-Konto ist nicht verbunden."}
    summary = str(params.get("summary") or "Termin (c:node)")
    desc = str(params.get("description") or "")
    start = str(params.get("start") or "").strip()
    end = str(params.get("end") or "").strip()
    if not start or not end:
        return {"ok": False, "reason": "missing_time",
                "detail": "Start- und Endzeit werden benötigt (ISO, z. B. 2026-09-03T10:00:00)."}
    tz = str(params.get("timezone") or "Europe/Berlin")
    body = {
        "summary": summary, "description": desc,
        "start": {"dateTime": start, "timeZone": tz},
        "end": {"dateTime": end, "timeZone": tz},
    }
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(timeout=T_LONG) as c:
            r = await c.post(
                "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                headers=headers, json=body,
            )
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": "gcal_exception", "detail": str(e)[:300]}
    if r.status_code in (200, 201):
        data = r.json()
        return {"ok": True, "id": data.get("id", ""),
                "message": "Termin im Google Kalender angelegt — du kannst ihn dort prüfen.",
                "link": data.get("htmlLink", "")}
    if r.status_code in (401, 403):
        return {"ok": False, "reason": "scope_missing",
                "detail": "Kalender-Termin braucht die Berechtigung 'calendar.events'. "
                          "Bitte Google neu verbinden, damit der neue Scope erteilt wird.",
                "raw": r.text[:200]}
    return {"ok": False, "reason": "gcal_error", "detail": r.text[:300]}


# --------------------------------------------------------------------------
# Microsoft / Outlook (Graph) — OAuth-Flow + Draft/Event (mirror zu Google)
# --------------------------------------------------------------------------
async def _ms_token_request(data: dict) -> dict:
    async with httpx.AsyncClient(timeout=T_LONG) as c:
        r = await c.post(_MS_TOKEN_URL, data=data)
        r.raise_for_status()
        return r.json()


async def _ms_access_token(identity: Identity) -> str | None:
    row = db.get_microsoft_tokens(identity.tenant_id, identity.email)
    if not row:
        return None
    access = row.get("access_token")
    try:
        expiry = float(row.get("expiry") or 0)
    except (TypeError, ValueError):
        expiry = 0.0
    if access and time.time() < (expiry - 60):
        return access
    refresh = row.get("refresh_token")
    if not refresh:
        return access
    try:
        tok = await _ms_token_request({
            "client_id": MICROSOFT_CLIENT_ID, "client_secret": MICROSOFT_CLIENT_SECRET,
            "refresh_token": refresh, "grant_type": "refresh_token",
            "scope": MICROSOFT_SCOPES,
        })
    except Exception as e:  # noqa: BLE001
        log.warning("ms token refresh failed: %s", e)
        return access
    new_access = tok.get("access_token") or access
    try:
        db.save_microsoft_tokens(
            identity.tenant_id, identity.email, access_token=new_access,
            refresh_token=tok.get("refresh_token"), token_type=tok.get("token_type"),
            scope=tok.get("scope") or MICROSOFT_SCOPES,
            expiry=int(time.time()) + int(tok.get("expires_in", 3600)))
    except Exception as e:  # noqa: BLE001
        log.warning("ms token persist (refresh) failed: %s", e)
    return new_access


@app.get("/integrations/microsoft/status")
def microsoft_status(identity: Identity = Depends(current_identity)):
    row = db.get_microsoft_tokens(identity.tenant_id, identity.email)
    scopes = (row.get("scope") or "").split() if row and row.get("scope") else (
        MICROSOFT_SCOPES.split() if _ms_configured() else [])
    return {"configured": _ms_configured(),
            "connected": bool(row and row.get("access_token")),
            "email": row.get("user_email") if row else None, "scopes": scopes}


@app.post("/integrations/microsoft/disconnect")
def microsoft_disconnect(identity: Identity = Depends(current_identity)):
    return {"ok": True, "connected": False,
            "removed": db.delete_microsoft_tokens(identity.tenant_id, identity.email)}


@app.get("/integrations/microsoft/oauth/install")
def microsoft_install(identity: Identity = Depends(current_identity)):
    if PUBLIC_DEMO:
        raise HTTPException(status_code=403, detail="integrations_not_in_sandbox")
    if not _ms_configured():
        return {"ok": False, "reason": "not_configured"}
    params = {
        "client_id": MICROSOFT_CLIENT_ID, "redirect_uri": MICROSOFT_REDIRECT_URI,
        "response_type": "code", "scope": MICROSOFT_SCOPES,
        "response_mode": "query", "prompt": "consent",
        "state": _google_state_encode(identity),  # generischer tenant+user-State
    }
    return RedirectResponse(_MS_AUTH_URL + "?" + urlencode(params), status_code=302)


@app.get("/integrations/microsoft/oauth/callback")
async def microsoft_callback(code: str | None = Query(None), state: str | None = Query(None),
                             error: str | None = Query(None)):
    if not _ms_configured():
        return {"ok": False, "reason": "not_configured"}
    origin = _frontend_origin()
    err_redirect = RedirectResponse(f"{origin}/?microsoft=error", status_code=302)
    if error or not code or not state:
        return err_redirect
    try:
        claims = _google_state_decode(state)
    except jwt.PyJWTError:
        return err_redirect
    tenant_id = claims.get("tenant_id") or ""
    user_email = claims.get("user_email") or ""
    try:
        tok = await _ms_token_request({
            "client_id": MICROSOFT_CLIENT_ID, "client_secret": MICROSOFT_CLIENT_SECRET,
            "code": code, "redirect_uri": MICROSOFT_REDIRECT_URI,
            "grant_type": "authorization_code", "scope": MICROSOFT_SCOPES,
        })
    except Exception as e:  # noqa: BLE001
        log.warning("ms token exchange failed: %s", e)
        return err_redirect
    access = tok.get("access_token")
    if not access:
        return err_redirect
    try:
        db.save_microsoft_tokens(
            tenant_id, user_email, access_token=access,
            refresh_token=tok.get("refresh_token"), token_type=tok.get("token_type"),
            scope=tok.get("scope") or MICROSOFT_SCOPES,
            expiry=int(time.time()) + int(tok.get("expires_in", 3600)))
    except Exception as e:  # noqa: BLE001
        log.warning("ms token persist failed: %s", e)
        return err_redirect
    return RedirectResponse(f"{origin}/?microsoft=connected", status_code=302)


async def _exec_outlook_draft(identity: Identity, params: dict) -> dict:
    """Legt einen Outlook-Entwurf via Microsoft Graph an (/me/messages, isDraft)."""
    if not _ms_configured():
        return {"ok": False, "reason": "not_configured",
                "detail": "Microsoft ist serverseitig nicht konfiguriert."}
    token = await _ms_access_token(identity)
    if not token:
        return {"ok": False, "reason": "not_connected", "detail": "Outlook nicht verbunden."}
    to = str(params.get("to") or "")
    msg: dict = {"subject": str(params.get("subject") or "Nachricht von c:node"),
                 "body": {"contentType": "Text", "content": str(params.get("body") or "")}}
    if to:
        msg["toRecipients"] = [{"emailAddress": {"address": to}}]
    try:
        async with httpx.AsyncClient(timeout=T_LONG) as c:
            r = await c.post("https://graph.microsoft.com/v1.0/me/messages",
                             headers={"Authorization": f"Bearer {token}"}, json=msg)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": "graph_exception", "detail": str(e)[:300]}
    if r.status_code in (200, 201):
        return {"ok": True, "id": r.json().get("id", ""),
                "message": "Entwurf in Outlook angelegt — du kannst ihn dort prüfen und senden."}
    if r.status_code in (401, 403):
        return {"ok": False, "reason": "scope_missing",
                "detail": "Outlook-Entwurf braucht 'Mail.ReadWrite'. Bitte Outlook neu verbinden.",
                "raw": r.text[:200]}
    return {"ok": False, "reason": "graph_error", "detail": r.text[:300]}


async def _exec_outlook_event(identity: Identity, params: dict) -> dict:
    """Legt einen Outlook-Kalendertermin via Microsoft Graph an (/me/events)."""
    if not _ms_configured():
        return {"ok": False, "reason": "not_configured"}
    token = await _ms_access_token(identity)
    if not token:
        return {"ok": False, "reason": "not_connected", "detail": "Outlook nicht verbunden."}
    start, end = str(params.get("start") or ""), str(params.get("end") or "")
    if not start or not end:
        return {"ok": False, "reason": "missing_time", "detail": "Start/Ende werden benötigt."}
    tz = str(params.get("timezone") or "Europe/Berlin")
    body = {"subject": str(params.get("summary") or "Termin (c:node)"),
            "body": {"contentType": "Text", "content": str(params.get("description") or "")},
            "start": {"dateTime": start, "timeZone": tz},
            "end": {"dateTime": end, "timeZone": tz}}
    try:
        async with httpx.AsyncClient(timeout=T_LONG) as c:
            r = await c.post("https://graph.microsoft.com/v1.0/me/events",
                             headers={"Authorization": f"Bearer {token}"}, json=body)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": "graph_exception", "detail": str(e)[:300]}
    if r.status_code in (200, 201):
        return {"ok": True, "id": r.json().get("id", ""),
                "message": "Termin im Outlook-Kalender angelegt."}
    if r.status_code in (401, 403):
        return {"ok": False, "reason": "scope_missing",
                "detail": "Termin braucht 'Calendars.ReadWrite'. Bitte Outlook neu verbinden."}
    return {"ok": False, "reason": "graph_error", "detail": r.text[:300]}


# --------------------------------------------------------------------------
# SCOPE v3 — Onboarding hint (general vs. scoped) from engine graph stats
# --------------------------------------------------------------------------
@app.get("/threads/{thread_id}/onboarding")
async def thread_onboarding(thread_id: str,
                            identity: Identity = Depends(current_identity)):
    thread = db.get_thread(thread_id, identity.tenant_id, is_super=identity.is_super)
    if not thread:
        raise HTTPException(status_code=404, detail="thread not found")
    if not _can_access_thread(thread, identity):
        raise HTTPException(status_code=403, detail="no access to this thread")

    node_count = 0
    reachable = False
    try:
        async with httpx.AsyncClient(timeout=T_SHORT) as c:
            r = await c.get(f"{ENGINE_URL}/graph",
                            params={"client_id": identity.tenant_id, "limit": 5})
            if r.status_code == 200:
                node_count = len(r.json().get("nodes", []))
                reachable = True
    except Exception:
        reachable = False

    scoped = node_count > 0
    data_gaps: list[str] = []
    if not scoped:
        data_gaps = [
            "Noch keine mandantenspezifischen Daten im Gedächtnis.",
            "Lade Dokumente in die Library oder verbinde einen Connector.",
        ]
    elif node_count < 5:
        data_gaps = ["Wenig Kontext vorhanden — weitere Quellen verbessern Antworten."]
    if not reachable:
        data_gaps = ["Engine-Graph nicht erreichbar — Antworten laufen im General-Modus."]

    return {
        "suggestion": "scoped" if scoped else "general",
        "data_gaps": data_gaps,
        "can_request": identity.role != "super_admin",
        "node_count": node_count,
    }


class ThreadMsgReq(BaseModel):
    role: str = "assistant"
    text: str
    author: str | None = None


@app.post("/threads/{thread_id}/messages")
def append_thread_message(thread_id: str, req: ThreadMsgReq,
                          identity: Identity = Depends(current_identity)):
    """Hängt eine Nachricht an einen Thread — z.B. ein im Chat integriertes Formular-
    Artefakt (Impact Score / Quartalsreport). So wird es Teil der DB-History und der
    Chat kann sich in Folgefragen darauf beziehen."""
    if not req.text.strip():
        return {"ok": False, "reason": "empty"}
    role = req.role if req.role in ("user", "assistant") else "assistant"
    db.ensure_thread(thread_id, identity.tenant_id, title=(req.text[:60] or "Chat"),
                     is_super=identity.is_super, created_by=identity.email)
    msg = db.add_message(thread_id, identity.tenant_id, role, req.text[:8000],
                         is_super=identity.is_super, author=req.author)
    return {"ok": True, "message": msg}


# --------------------------------------------------------------------------
# /ask — unified entry (SCOPE §2.1) — auth-gated + tenant-scoped from JWT
# --------------------------------------------------------------------------
@app.post("/ask")
async def ask(req: AskReq, identity: Identity = Depends(require_permission("ask"))):
    req.provider = _effective_provider(req.provider)  # Sandbox → immer Gemini (engine-bound)
    tenant_id = identity.tenant_id  # from JWT (or super-admin act-as); NEVER from body
    gclient = _graph_client(identity)  # Graph-Namespace (Sandbox: pro-User; sonst == tenant_id)

    # SCOPE v2: only super-admin may push straight to the market level.
    levels = req.levels or ["client"]
    if "market" in levels and not identity.is_super:
        raise HTTPException(
            status_code=403,
            detail="market-level ingest requires super-admin — admins use POST /promotions",
        )

    thread = db.ensure_thread(req.thread_id, tenant_id, title=req.text[:60],
                              is_super=identity.is_super, created_by=identity.email)
    if not _can_access_thread(thread, identity):
        raise HTTPException(status_code=403, detail="no access to this thread")
    thread_id = thread["id"]
    history = db.get_history(thread_id, tenant_id, is_super=identity.is_super)
    db.add_message(thread_id, tenant_id, "user", req.text, is_super=identity.is_super,
                   author=identity.email)

    trace: list[dict] = [
        {"step": "gateway", "method": "POST /ask", "result": "received",
         "service": "bff"}
    ]

    async with httpx.AsyncClient(timeout=T_LONG) as c:
        # 1) Intent klassifizieren via engine
        intent = "knowledge"
        try:
            r = await c.post(
                f"{ENGINE_URL}/classify",
                json={"text": req.text, "client_id": tenant_id},
            )
            intent = r.json().get("intent", "knowledge")
            # URL + Einlese-Wunsch → Website scrapen (nicht als Wissensfrage behandeln).
            if _detect_url_ingest(req.text):
                intent = "ingest"
            trace.append({"step": "classify", "method": "POST /classify",
                          "result": intent, "service": "engine"})
        except Exception as exc:
            trace.append({"step": "classify", "method": "POST /classify",
                          "result": f"unreachable: {exc.__class__.__name__}",
                          "service": "engine"})
            env = envelope(
                "smalltalk", "engine",
                "⚠️ Engine derzeit nicht erreichbar — Intent-Klassifikation "
                "übersprungen. Bitte Stack prüfen (`make health`).",
                trace=trace, provider=req.provider,
            )
            db.add_message(thread_id, tenant_id, "assistant", env["result_text"],
                           is_super=identity.is_super, author="c:node")
            env["thread_id"] = thread_id
            return env

        # 2a0) Agent starten/auflisten? → Envelope mit echten Agent-CTAs (F4/F5/F6).
        a_kind, a_id, a_goal = _detect_agent_request(req.text)
        if PUBLIC_DEMO and a_kind in ("leads", "foerderung"):
            a_kind = None  # Demo: market-IP-Agenten unterdrücken → Wissens-/Chat-Pfad
        if a_kind:
            env = _agent_request_envelope(a_kind, a_id, a_goal, req.provider)
            db.add_message(thread_id, tenant_id, "assistant", env.get("result_text", ""),
                           is_super=identity.is_super, author="c:node")
            env["thread_id"] = thread_id
            return env

        # 2a1) Explizite Schreib-Aktion in Graph/Artefakt? → WIRKLICH ausführen (F8).
        gw = _detect_graph_write(req.text)
        if gw:
            env = await _run_graph_write(c, gw, req, identity, tenant_id, thread_id,
                                         history, trace)
            db.add_message(thread_id, tenant_id, "assistant", env.get("result_text", ""),
                           is_super=identity.is_super, author="c:node")
            env["thread_id"] = thread_id
            return env

        # 2a) Agentische Aktion? → Bestätigungs-Gate (keine Ausführung ohne Confirm)
        action_type = _detect_action(req.text)
        if action_type:
            env = await _propose_action(c, action_type, req, identity, tenant_id,
                                        history, trace)
            db.add_message(thread_id, tenant_id, "assistant", env.get("result_text", ""),
                           is_super=identity.is_super, author="c:node")
            env["thread_id"] = thread_id
            return env

        # 2a2) Web-Recherche gewünscht? → SerpAPI-Recherche + belegte Synthese
        if _detect_research(req.text):
            env = await _run_research(c, req, gclient, trace)
            db.add_message(thread_id, tenant_id, "assistant", env.get("result_text", ""),
                           is_super=identity.is_super, author="c:node")
            env["thread_id"] = thread_id
            return env

        # 2b) Routing (Graph-Namespace = gclient; DB-Persistenz bleibt tenant_id)
        env = await _route(c, intent, req, gclient, levels, trace, history)

    # 3) Artefakt-Anforderung? → zusätzlich engine POST /artifact
    kind = _detect_artifact_kind(req.text)
    if kind:
        await _attach_artifact(kind, req, tenant_id, thread_id, env,
                               is_super=identity.is_super, gclient=gclient)

    db.add_message(thread_id, tenant_id, "assistant", env.get("result_text", ""),
                   is_super=identity.is_super, author="c:node")
    # Graph lernt auch aus dem Chat: substanziellen Turn fire-and-forget ins Gedächtnis.
    asyncio.create_task(_learn_chat_bg(gclient, identity, req.text,
                                       env.get("result_text", ""), thread_id))
    env["thread_id"] = thread_id
    return env


def _sse(obj: dict) -> str:
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


@app.post("/ask/stream")
async def ask_stream(req: AskReq, request: Request, identity: Identity = Depends(current_identity)):
    """Wie /ask, aber Server-Sent-Events: Token-für-Token für die LLM-Text-Pfade,
    Einzel-Event (done) für Daten-Routen (Leads/Förderung/Graph/Ingest/Aktion/Recherche)."""
    req.provider = _effective_provider(req.provider)  # Sandbox → immer Gemini (engine-bound)
    tenant_id = identity.tenant_id
    gclient = _graph_client(identity)  # Graph-Namespace (Sandbox: pro-User; sonst == tenant_id)
    levels = req.levels or ["client"]
    thread = db.ensure_thread(req.thread_id, tenant_id, title=req.text[:60],
                              is_super=identity.is_super, created_by=identity.email)
    if not _can_access_thread(thread, identity):
        raise HTTPException(status_code=403, detail="no access to this thread")
    thread_id = thread["id"]
    history = db.get_history(thread_id, tenant_id, is_super=identity.is_super)
    db.add_message(thread_id, tenant_id, "user", req.text, is_super=identity.is_super,
                   author=identity.email)
    trace: list[dict] = [{"step": "gateway", "method": "POST /ask/stream",
                          "result": "received", "service": "bff"}]

    async def gen():
        yield _sse({"type": "meta", "thread_id": thread_id})
        async with httpx.AsyncClient(timeout=T_LONG) as c:
            # Intent klassifizieren
            intent = "knowledge"
            try:
                r = await c.post(f"{ENGINE_URL}/classify",
                                 json={"text": req.text, "client_id": tenant_id})
                intent = r.json().get("intent", "knowledge")
            except Exception:
                pass
            if _detect_url_ingest(req.text):
                intent = "ingest"
            trace.append({"step": "classify", "method": "POST /classify",
                          "result": intent, "service": "engine"})

            # Nicht-gestreamte Pfade (Agent / Aktion / Recherche / Daten-Routen) → ein done-Event.
            env = None
            a_kind, a_id, a_goal = _detect_agent_request(req.text)
            gw = _detect_graph_write(req.text)
            # Demo: market-IP-Agenten (Förderung/Leads) unterdrücken.
            if PUBLIC_DEMO and a_kind in ("leads", "foerderung"):
                a_kind = None
            route_intents = ({"ingest", "graph"} if PUBLIC_DEMO
                             else {"leads", "foerderung", "ingest", "graph"})
            if a_kind:
                env = _agent_request_envelope(a_kind, a_id, a_goal, req.provider)
            elif gw:
                env = await _run_graph_write(c, gw, req, identity, tenant_id, thread_id,
                                             history, trace)
            elif _detect_action(req.text):
                env = await _propose_action(c, _detect_action(req.text), req, identity,
                                            tenant_id, history, trace)
            elif _detect_research(req.text):
                env = await _run_research(c, req, gclient, trace)
            elif intent in route_intents:
                env = await _route(c, intent, req, gclient, levels, trace, history)

            if env is not None:
                # Kein Doppel-Artefakt: Schreib-/Agent-Pfade liefern ihr Artefakt selbst.
                kind = _detect_artifact_kind(req.text)
                if kind and not env.get("artifact"):
                    await _attach_artifact(kind, req, tenant_id, thread_id, env,
                                           is_super=identity.is_super, gclient=gclient)
                db.add_message(thread_id, tenant_id, "assistant", env.get("result_text", ""),
                               is_super=identity.is_super, author="c:node")
                env["thread_id"] = thread_id
                yield _sse({"type": "done", "envelope": env})
                return

            # LLM-Text-Pfad → engine /answer/stream proxien.
            data_done: dict = {}
            _team_ids = [t["id"] for t in db.list_teams_for_user(
                identity.user_id, tenant_id, is_super=identity.is_super)]
            try:
                async with c.stream("POST", f"{ENGINE_URL}/answer/stream",
                                    json={"text": req.text, "client_id": gclient,
                                          "history": history, "provider": req.provider,
                                          "teams": _team_ids,
                                          "intel": _intel_flag(tenant_id)}) as r:
                    async for line in r.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        try:
                            evt = json.loads(line[5:].strip())
                        except Exception:
                            continue
                        if evt.get("type") == "token":
                            yield _sse({"type": "token", "text": evt.get("text", "")})
                        elif evt.get("type") == "done":
                            data_done = evt
                            # Echte Token-Nutzung in den Sandbox-Cap eintragen (ersetzt Schätzung).
                            ratelimit.add_tokens(
                                ratelimit.client_ip(request.headers,
                                                    request.client.host if request.client else None),
                                int(data_done.get("tokens", 0) or 0))
            except Exception as e:  # noqa: BLE001
                trace.append({"step": "route", "method": "POST /answer/stream",
                              "result": f"unreachable: {e.__class__.__name__}", "service": "engine"})

            sources = _norm_sources(data_done.get("sources", []))
            if sources:
                out_trace = trace + data_done.get("trace", []) + [
                    {"step": "route", "method": "POST /answer/stream",
                     "result": f"{len(sources)} sources", "service": "engine"}]
                out_highlight = [s["id"] for s in sources]
            else:
                out_trace, out_highlight = [], []
            env = envelope(
                intent, "engine", data_done.get("result", ""),
                sources=sources, highlight=out_highlight,
                trace=out_trace, provider=data_done.get("provider", req.provider),
                model=data_done.get("model", DEFAULT_MODEL),
                suggestions=data_done.get("suggestions", []),
                ctas=data_done.get("ctas"),
                grounding=data_done.get("grounding", "chat"),
                grounded=bool(data_done.get("grounded")),
            )
            db.add_message(thread_id, tenant_id, "assistant", env.get("result_text", ""),
                           is_super=identity.is_super, author="c:node")
            asyncio.create_task(_learn_chat_bg(gclient, identity, req.text,
                                               env.get("result_text", ""), thread_id))
            env["thread_id"] = thread_id
            yield _sse({"type": "done", "envelope": env})

    return StreamingResponse(gen(), media_type="text/event-stream")


# --------------------------------------------------------------------------
# E7 — Agenten „losschicken" (Katalog · Läufe · Ausführung mit Live-Fortschritt)
# --------------------------------------------------------------------------
@app.get("/agents")
def list_agents(identity: Identity = Depends(current_identity)):
    """Katalog verfügbarer Agenten (Config über geteilter Engine)."""
    return {"agents": agents.catalog()}


@app.get("/agents/runs")
def get_agent_runs(thread_id: str | None = Query(None),
                   identity: Identity = Depends(current_identity)):
    """Agenten-Läufe (für die rechte Sidebar), optional nach Thread gefiltert."""
    rows = db.list_agent_runs(identity.tenant_id, thread_id, is_super=identity.is_super)
    return {"runs": _demo_owned(rows, identity)}


@app.get("/agents/runs/{run_id}")
def get_agent_run_detail(run_id: str, identity: Identity = Depends(current_identity)):
    run = db.get_agent_run(run_id, identity.tenant_id, is_super=identity.is_super)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    # PUBLIC_DEMO: geteilter Tenant → nur der Ersteller (oder super) darf den Lauf sehen.
    if PUBLIC_DEMO and not identity.is_super \
            and (run.get("created_by") or "").lower() != (identity.email or "").lower():
        raise HTTPException(status_code=403, detail="no access to this run")
    return run


# ── Named Domain Agents (Personas) + A2A ────────────────────────────────────
class AgentConsultReq(BaseModel):
    text: str
    provider: str | None = None


async def _agent_grounded_answer(agent: dict, question: str, gclient: str,
                                 intel: bool | None, tenant: str, provider: str) -> dict:
    """Ein Fach-Agent beantwortet EINE Frage — geerdet auf NENA (tenant/workspace), mit
    Persona-System. READ-only. Rückgabe: {answer, sources, grounding}."""
    body = {"text": question, "client_id": gclient, "provider": provider, "intel": intel,
            "system_override": domain_agents.render_system(agent, tenant)}
    async with httpx.AsyncClient(timeout=T_LONG) as c:
        r = await c.post(f"{ENGINE_URL}/answer", json=body)
        r.raise_for_status()
        d = r.json()
    return {"answer": d.get("result", ""), "sources": d.get("sources", []),
            "grounding": d.get("grounding", "allgemein")}


def _provenance(sources: list[dict], agent_id: str) -> list[dict]:
    """engine-Sources → A2A-provenance[] (claim/source_id/source_type/snippet)."""
    out = []
    for s in sources[:6]:
        props = s.get("props") or {}
        out.append({"claim": s.get("label", ""), "source_id": s.get("id", ""),
                    "source_type": s.get("type", "Fact"),
                    "snippet": (props.get("summary") or props.get("content") or "")[:240],
                    "provenance": s.get("provenance", ""), "by_agent": agent_id})
    return out


async def _consult_chain(agent: dict, question: str, identity: Identity) -> dict:
    """A2A-Orchestrierung (zentral, wie im Spec erlaubt): Primär-Agent liest, zieht per
    Domänen-Discovery bis zu 2 weitere Agenten desselben Mandanten hinzu (max_hops=3),
    Provenienz wandert mit, Synthese durch den Primär-Agenten. WRITE bleibt gesperrt."""
    tenant = _real_tenant(identity.tenant_id)
    gclient = _graph_client(identity)
    intel = _intel_flag(identity.tenant_id)
    provider = _effective_provider(DEFAULT_PROVIDER)  # Sandbox → immer Gemini
    task_id = db.new_id("a2a")
    hops: list[dict] = []
    provenance: list[dict] = []

    primary = await _agent_grounded_answer(agent, question, gclient, intel, tenant, provider)
    provenance += _provenance(primary["sources"], agent["id"])
    hops.append({"a2a_version": "1", "task_id": task_id, "tenant_id": tenant,
                 "from_agent": "orchestrator", "to_agent": agent["id"], "intent": question,
                 "status": "ok", "grounding": primary["grounding"]})

    contributions = [{"agent": agent, "answer": primary["answer"], "grounding": primary["grounding"]}]
    # Discovery aus den belegten Quellen des Primär-Agenten (Domänen der Fakten), sonst
    # Fallback auf Intent-Keywords über Frage + Primärantwort.
    targets = domain_agents.agents_from_domains(primary["sources"], exclude_id=agent["id"], limit=2)
    if not targets:
        targets = domain_agents.discover(
            f"{question} {primary['answer']}", exclude_id=agent["id"], limit=2)
    for other in targets:
        intent = f"{other['trigger_question']} Fall-Kontext: {question}"
        sub = await _agent_grounded_answer(other, intent, gclient, intel, tenant, provider)
        provenance += _provenance(sub["sources"], other["id"])
        contributions.append({"agent": other, "answer": sub["answer"], "grounding": sub["grounding"]})
        hops.append({"a2a_version": "1", "task_id": task_id, "tenant_id": tenant,
                     "from_agent": agent["id"], "to_agent": other["id"], "intent": intent,
                     "status": "ok", "grounding": sub["grounding"],
                     "constraints": {"max_hops": 3, "write_allowed": False}})

    if len(contributions) > 1:
        blocks = "\n\n".join(
            f"### Beitrag von {c['agent']['name']} ({c['agent']['role']}) [{c['grounding']}]\n{c['answer']}"
            for c in contributions)
        synth_prompt = (
            f"Frage des Nutzers: {question}\n\n"
            f"Du hast folgende belegte Teilantworten der hinzugezogenen Fach-Agenten desselben "
            f"Mandanten erhalten:\n\n{blocks}\n\n"
            f"Fasse als {agent['name']} zu EINER beratenden Empfehlung zusammen: (1) klare Antwort "
            f"auf die Frage, (2) die tragenden Belege je Domäne, (3) Next Best Action + Rückfrage "
            f"nach fehlenden Quellen. Erfinde nichts hinzu, was nicht in den Teilantworten steht.")
        try:
            async with httpx.AsyncClient(timeout=T_LONG) as c:
                r = await c.post(f"{ENGINE_URL}/agent/synthesize", json={
                    "system": domain_agents.render_system(agent, tenant),
                    "prompt": synth_prompt, "provider": provider})
                r.raise_for_status()
                final = r.json().get("result", "") or primary["answer"]
        except Exception:  # noqa: BLE001 — Synthese-Ausfall → Primärantwort behalten
            final = primary["answer"]
    else:
        final = primary["answer"]

    return {"task_id": task_id, "agent": domain_agents.card(agent, tenant), "answer": final,
            "provenance": provenance, "consulted": [c["agent"]["id"] for c in contributions[1:]],
            "contributions": [{"agent_id": c["agent"]["id"], "name": c["agent"]["name"],
                               "role": c["agent"]["role"], "answer": c["answer"],
                               "grounding": c["grounding"]} for c in contributions],
            "hops": hops, "write_allowed": False, "status": "ok"}


async def _agent_pending_action(text: str, provider: str, identity: Identity) -> dict | None:
    """P3 Human-in-the-Loop: Verlangt der Turn eine WRITE-Aktion (Außenwirkung), BEREITET der
    Agent sie vor (Entwurf) und gibt sie als pending_action zur menschlichen Freigabe zurück —
    er führt sie NIE selbst aus. Ausführung erst nach Bestätigung über /action/execute.
    write_allowed wird dabei nie vom Agenten auf true gesetzt."""
    at = _detect_action(text or "")
    if not at:
        return None
    try:
        async with httpx.AsyncClient(timeout=T_LONG) as c:
            prop = await _propose_action(
                c, at, AskReq(text=text, provider=provider), identity,
                _real_tenant(identity.tenant_id), [], [])
        return prop.get("action")
    except Exception:  # noqa: BLE001 — Vorbereitung darf die Antwort nie brechen
        return None


def _attach_pending(res: dict, action: dict | None) -> dict:
    """Hängt eine vorbereitete WRITE-Aktion an die Agent-Antwort (Freigabe-Karte)."""
    if not action:
        return res
    res["pending_action"] = action        # UI zeigt Bestätigungs-Karte → /action/execute
    res["status"] = "needs_approval"
    res["write_allowed"] = False          # niemals vom Agenten selbst freigegeben
    res["answer"] = (res.get("answer", "") +
                     f"\n\n---\n**Zur Freigabe vorbereitet — nicht ausgeführt:** "
                     f"{action.get('title', 'Aktion')}. {action.get('summary', '')} "
                     f"Bestätige die Karte, dann führe ich es über den Connector aus.")
    return res


@app.get("/agents/cards")
def agent_cards(identity: Identity = Depends(current_identity)):
    """Registry der benannten Fach-Agenten (Cards) — Quelle für App/Sandbox/Marketing."""
    tenant = _real_tenant(identity.tenant_id)
    return {"agents": [domain_agents.card(a, tenant) for a in domain_agents.DOMAIN_AGENTS]}


@app.post("/agents/domain/{agent_id}/ask")
async def agent_domain_ask(agent_id: str, req: AgentConsultReq,
                           identity: Identity = Depends(require_permission("ask"))):
    """Ein einzelner Fach-Agent (kein A2A) — geerdet, belegt, READ-only."""
    agent = domain_agents.get_agent(agent_id)
    if not agent or agent.get("status") != "live":
        raise HTTPException(status_code=404, detail=f"unknown/inactive agent: {agent_id}")
    tenant = _real_tenant(identity.tenant_id)
    res = await _agent_grounded_answer(
        agent, req.text, _graph_client(identity), _intel_flag(identity.tenant_id),
        tenant, _effective_provider(req.provider))
    out = {"agent": domain_agents.card(agent, tenant), "answer": res["answer"],
           "provenance": _provenance(res["sources"], agent_id),
           "grounding": res["grounding"], "write_allowed": False, "status": "ok"}
    return _attach_pending(out, await _agent_pending_action(
        req.text, _effective_provider(req.provider), identity))


@app.post("/agents/domain/{agent_id}/consult")
async def agent_domain_consult(agent_id: str, req: AgentConsultReq,
                               identity: Identity = Depends(require_permission("ask"))):
    """A2A-Konsultation: Primär-Agent + Domänen-Discovery + Synthese; Provenienz wandert mit."""
    agent = domain_agents.get_agent(agent_id)
    if not agent or agent.get("status") != "live":
        raise HTTPException(status_code=404, detail=f"unknown/inactive agent: {agent_id}")
    res = await _consult_chain(agent, req.text, identity)
    return _attach_pending(res, await _agent_pending_action(
        req.text, _effective_provider(req.provider), identity))


@app.post("/agents/{agent_id}/run/stream")
async def agent_run_stream(agent_id: str, req: AgentRunReq,
                           identity: Identity = Depends(require_permission("ask"))):
    """Startet einen Agenten-Lauf als SSE: plan → step* → done.

    Der Plan wird sofort gezeigt (inszeniert), dann laufen die Schritte mit
    Live-Status. Lauf + Schritte werden in Postgres persistiert (Source of Truth).
    """
    spec = agents.get(agent_id)
    if not spec:
        raise HTTPException(status_code=404, detail=f"unknown agent: {agent_id}")
    tenant_id = identity.tenant_id
    # Outreach/Action (Mail + CRM-Push) ist ein bezahltes Feature: nur mit Entitlement
    # (intel/Pro+) oder in einem dedizierten (nicht-Public) Deployment. Free-Sandbox → Upsell.
    if spec.get("family") == "action" and PUBLIC_DEMO and not _entitlement(tenant_id).get("intel"):
        raise HTTPException(
            status_code=402,
            detail={"error": "upgrade_required", "feature": "outreach",
                    "message": ("Outreach (Mail/CRM) ist ein Pro-Feature — schalte NENA/Pro frei, "
                                "um aus gefundenen Startups direkt Entwürfe zu erzeugen.")})
    thread = db.ensure_thread(req.thread_id, tenant_id, title=req.goal[:60],
                              is_super=identity.is_super, created_by=identity.email)
    if not _can_access_thread(thread, identity):
        raise HTTPException(status_code=403, detail="no access to this thread")
    thread_id = thread["id"]
    history = db.get_history(thread_id, tenant_id, is_super=identity.is_super)

    async def gen():
        yield _sse({"type": "meta", "thread_id": thread_id})
        run_id: str | None = None
        finished = False
        async with httpx.AsyncClient(timeout=T_LONG) as c:
            done_text = ""
            try:
                async for evt in agents.run_stream(
                    c, agent_id=agent_id, goal=req.goal, tenant_id=tenant_id,
                    thread_id=thread_id, provider=_effective_provider(req.provider),
                    created_by=identity.email, is_super=identity.is_super,
                    history=history, graph_client=_graph_client(identity),
                ):
                    if evt.get("type") == "plan":
                        run_id = evt.get("run_id")
                    if evt.get("type") == "done":
                        done_text = evt.get("result_text", "")
                        finished = True
                    yield _sse(evt)
            except Exception as e:  # noqa: BLE001
                yield _sse({"type": "error", "error": e.__class__.__name__})
            finally:
                # Bricht der Client mitten im Lauf ab (Disconnect/Timeout), bleibt der
                # Lauf sonst ewig auf 'running' → als 'failed' markieren (kein Waisen-Lauf).
                if run_id and not finished:
                    try:
                        db.set_agent_run_status(run_id, tenant_id, "failed",
                                                is_super=identity.is_super)
                    except Exception:  # noqa: BLE001
                        pass
            if done_text:
                db.add_message(thread_id, tenant_id, "assistant", done_text,
                               is_super=identity.is_super, author="c:node")

    return StreamingResponse(gen(), media_type="text/event-stream")


# --------------------------------------------------------------------------
# Agentische Aktionen — Bestätigungs-Gate (NIE ohne explizite Confirmation)
# --------------------------------------------------------------------------
_ACT_SEND = re.compile(r"\b(sende|senden|schick|schicke|verschick|versend|versende|abschick|abschicken)\b", re.I)
_ACT_MAIL = re.compile(r"\b(e-?mails?|mails?|nachrichten?|outreach|anschreiben)\b", re.I)
_ACT_DRAFT = re.compile(r"\b(entwurf|entwürfe|entwuerfe|draft|drafts)\b", re.I)


def _detect_action(text: str) -> str | None:
    """Erkennt agentische Aktionen mit Außenwirkung → Bestätigungs-Gate.

    Wichtig: reines VERFASSEN von Text ('entwirf eine Nachricht') ist KEINE Aktion —
    das läuft über den normalen NL-Generier-Pfad. Erst SENDEN oder ein Entwurf IN
    Gmail ist eine Aktion.
    """
    t = text.lower()
    # Gmail-Entwurf explizit: „entwurf in gmail", „gmail-entwurf", „als entwurf anlegen"
    if _ACT_DRAFT.search(t) and ("gmail" in t or _ACT_MAIL.search(t)):
        return "gmail_draft"
    # „E-Mails senden / Nachricht verschicken" → wir legen SICHER einen Entwurf an (kein Auto-Send)
    if _ACT_SEND.search(t) and _ACT_MAIL.search(t):
        return "gmail_draft"
    return None


_URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.IGNORECASE)


def _first_url(text: str) -> str | None:
    m = _URL_RE.search(text or "")
    if not m:
        return None
    return m.group(0).rstrip(".,;:!?)")


_RESEARCH_RE = re.compile(
    r"(recherchier|recherche|web-?recherche|durchsuch|im web such|websuche|web-?such|"
    r"finde quellen|quellen finden|wissenschaftliche quelle|studien? (zu|über|zur|zum))",
    re.IGNORECASE,
)


def _detect_research(text: str) -> bool:
    return bool(_RESEARCH_RE.search(text or ""))


# --- E7 7.2: Agenten aus dem Chat starten/auflisten (echte Tool-Bindung) ----
_AGENT_LIST_RE = re.compile(
    r"(welche|was\s+f[uü]r|welche\s+art\s+von).{0,24}(agent|assistent)"
    r"|agent(en|s)?\s+(kannst|k[oö]nnt|hast|gibt|verf[uü]gbar|starten|losschicken)"
    r"|(liste|zeig).{0,16}agent",
    re.IGNORECASE,
)
_AGENT_START_RE = re.compile(
    r"(starte?|start|schick|los(schick)?|f[uü]hre?\s+aus|run)\b.{0,28}"
    r"(recherche|research|such|agent|scout|lead|memo|entscheid|trend|f[oö]rder|funding|foerder|"
    r"governance|compliance|dsgvo|gdpr|audit|ai.?act|outreach|anschreiben)"
    r"|(recherche|research|lead|memo|trend|f[oö]rder|funding)[-\s]?(agent|scout)(en)?\b.{0,20}"
    r"(starten|losschick|ausf[uü]hr|start)",
    re.IGNORECASE,
)
# Ziel aus dem Satz herauslösen: alles nach dem Agenten-Wort, sonst nach zu/über/…/:.
_GOAL_TAIL_RE = re.compile(r"\b(?:zu|über|ueber|zum|für|fuer|zur|about|on)\s+(.{4,})$", re.IGNORECASE)
_TRIGGER_PREFIX_RE = re.compile(r"^.*?\b(?:agent|scout)\b[:\-\s]*", re.IGNORECASE)
_LEAD_PREP_RE = re.compile(r"^(?:zu|über|ueber|zum|zur|für|fuer|an|about|on)\s+", re.IGNORECASE)


def _extract_agent_goal(text: str) -> str:
    t = (text or "").strip()
    m = _TRIGGER_PREFIX_RE.match(t)
    if m and t[m.end():].strip():
        g = t[m.end():].strip()
    else:
        mm = _GOAL_TAIL_RE.search(t)
        if mm:
            g = mm.group(1).strip()
        elif ":" in t:
            g = t.split(":", 1)[1].strip()
        else:
            g = ""
    g = _LEAD_PREP_RE.sub("", g).strip(" .?!:")
    return g if len(g) >= 3 else ""


def _detect_agent_request(text: str) -> tuple[str | None, str | None, str]:
    """→ ('start', agent_id, goal) | ('list', None, '') | (None, None, '')."""
    t = text or ""
    if _AGENT_START_RE.search(t):
        # Agent per Name/Alias auflösen — NUR aus dem Trigger-Kopf (vor dem Ziel),
        # damit Ziel-Keywords (z.B. „zu Förder …") die Agenten-Wahl nicht kapern.
        pm = _TRIGGER_PREFIX_RE.match(t)
        if pm:
            head = t[: pm.end()]
        else:
            sep = re.search(r"\b(?:zu|über|ueber|zum|zur|für|fuer|an|about|on)\b|:", t, re.IGNORECASE)
            head = t[: sep.start()] if sep else t
        low = head.lower()
        # Reihenfolge wichtig: funding/trend VOR generischem scout/lead.
        if any(k in low for k in ("governance", "compliance", "dsgvo", "gdpr",
                                  "ai act", "ai-act", "ki-verordnung", "audit")):
            agent_id = "governance"
        elif any(k in low for k in ("funding", "förder", "foerder", "foerder")):
            agent_id = "funding"
        elif "trend" in low:
            agent_id = "trend"
        elif any(k in low for k in ("outreach", "anschreiben", "mail-agent", "e-mail-agent")):
            agent_id = "outreach"
        elif "startup" in low or "start-up" in low or "ausgründ" in low or "ausgruend" in low:
            agent_id = "startup"
        elif "scout" in low or "lead" in low:
            agent_id = "leadscout"
        elif "memo" in low or "entscheid" in low:
            agent_id = "memo"
        else:
            agent_id = "recherche"
        return "start", agent_id, _extract_agent_goal(t)
    if _AGENT_LIST_RE.search(t):
        return "list", None, ""
    return None, None, ""


def _agent_request_envelope(kind: str, agent_id: str | None, goal: str,
                            provider: str) -> dict:
    """Envelope mit echten Agent-CTAs (type='agent'+agent[+goal]) — kein Prompt-Text."""
    if kind == "list":
        cat = agents.catalog()
        lines = "\n".join(f"- **{a['name']}** — {a['description']}" for a in cat)
        text = (
            "Ich kann diese Agenten für dich losschicken — sie zeigen ihren Plan und laufen "
            "Schritt für Schritt mit belegtem Ergebnis:\n\n" + lines +
            "\n\nWähle einen — dann öffne ich rechts den Starter, du gibst das Ziel ein."
        )
        ctas = [{"type": "agent", "agent": a["id"], "label": f"▶ {a['name']} starten"}
                for a in cat]
        return envelope("agent", "bff", text, ctas=ctas, provider=provider)

    spec = agents.get(agent_id or "")
    name = spec["name"] if spec else "Agent"
    if goal:
        text = (f"Bereit: **{name}** für dein Ziel „{goal}“. Ein Klick startet den Lauf — "
                "ich zeige den Plan und lasse ihn Schritt für Schritt laufen (rechte Sidebar).")
        cta = {"type": "agent", "agent": agent_id, "goal": goal,
               "label": f"▶ {name} starten"}
    else:
        text = (f"Klar — **{name}** kann ich losschicken. Ein Klick öffnet rechts den Starter; "
                "gib dort das Ziel ein, dann läuft er mit sichtbaren Schritten.")
        cta = {"type": "agent", "agent": agent_id, "label": f"▶ {name} starten"}
    return envelope("agent", "bff", text, ctas=[cta], provider=provider)


async def _run_research(c: httpx.AsyncClient, req: AskReq, tenant_id: str,
                        trace: list[dict]) -> dict:
    """Web-Recherche: assets /research (SerpAPI + Scrape) → engine /synthesize → belegte Antwort."""
    try:
        r = await c.post(f"{ASSETS_URL}/research",
                         json={"query": req.text, "client_id": tenant_id,
                               "max_results": 5, "ingest": False})
        data = r.json()
    except Exception as e:  # noqa: BLE001
        return envelope("knowledge", "assets",
                        f"Web-Recherche nicht erreichbar ({e.__class__.__name__}).",
                        trace=trace, provider=req.provider)
    if not data.get("ok"):
        reason = data.get("reason", "no_results")
        _msgs = {
            "no_provider": ("Die Web-Recherche ist serverseitig noch nicht konfiguriert "
                            "(SERPAPI_KEY fehlt). Sobald der Schlüssel gesetzt ist, recherchiere ich "
                            "live mit wissenschaftlichen/offiziellen Quellen."),
            "serpapi_auth": ("Die Web-Recherche ist derzeit nicht nutzbar: Der SerpAPI-Schlüssel ist "
                             "ungültig oder das Kontingent ist erschöpft. Bitte den Schlüssel prüfen."),
            "serpapi_rate_limit": ("Die Web-Recherche ist kurzzeitig ausgelastet (SerpAPI-Ratenlimit). "
                                   "Bitte in einem Moment erneut versuchen."),
            "serpapi_unavailable": ("Der Recherche-Dienst ist vorübergehend nicht erreichbar. Ich habe es "
                                    "mehrfach versucht — bitte gleich noch einmal probieren."),
            "no_results": "Die Web-Recherche lieferte keine verwertbaren Treffer.",
        }
        msg = _msgs.get(reason) or f"Die Web-Recherche lieferte keine verwertbaren Treffer (`{reason}`)."
        trace.append({"step": "route", "method": "POST /research",
                      "result": f"failed: {reason}", "service": "assets"})
        return envelope("knowledge", "assets", msg, trace=trace, provider=req.provider)

    results = data.get("results", [])
    refs = data.get("references", [])
    facts = "\n\n".join(
        f"[{i + 1}] {r.get('title', '')} ({r.get('domain', '')}):\n{r.get('extract', '')}"
        for i, r in enumerate(results)
    )
    answer, sugs = "", []
    try:
        sy = await c.post(f"{ENGINE_URL}/synthesize",
                          json={"query": req.text, "facts": facts, "provider": req.provider})
        sd = sy.json()
        answer = sd.get("result", "")
        sugs = sd.get("suggestions", [])
    except Exception:
        answer = ""
    ref_block = "\n".join(
        f"[{ref['n']}] {ref['title']} — {ref['url']}"
        + ("  ·  wissenschaftlich/offiziell" if ref.get("scientific") else "")
        for ref in refs
    )
    text = (answer or "Zusammenfassung nicht verfügbar.") + \
        (f"\n\n**Quellen (Web-Recherche):**\n{ref_block}" if ref_block else "")
    sources = _norm_sources([
        {"id": ref["url"], "label": ref["title"], "type": "WebQuelle",
         "provenance": ref["url"], "props": {"domain": ref.get("domain"),
                                             "scientific": ref.get("scientific")}}
        for ref in refs
    ])
    trace.append({"step": "route", "method": "POST /research",
                  "result": f"{len(results)} Quellen", "service": "assets"})
    trace.append({"step": "synthesize", "method": "POST /synthesize", "service": "engine"})
    return envelope("knowledge", "assets", text, sources=sources,
                    highlight=[s["id"] for s in sources], trace=trace,
                    provider=req.provider, suggestions=sugs,
                    grounding="web", grounded=bool(sources))


# --- E7 7.3: echte Schreib-Aktionen in Graph/Artefakt (behebt F8) -----------
_GRAPH_WRITE_RE = re.compile(
    r"(erstell\w*|erzeug\w*|leg\w*\s+ab|ableg\w*|aufnehm\w*|schreib\w*|speicher\w*|"
    r"ergänz\w*|erganz\w*|erweiter\w*|befüll\w*|befull\w*|hinzuf\w*|anleg\w*|nimm)\b",
    re.IGNORECASE,
)
# Substring (kein \b): deutsche Komposita wie „Gedächtnis" enthalten keine Wortgrenze bei „graph".
_GRAPH_TARGET_RE = re.compile(r"(wissensgraph|graph|knoten|node)", re.IGNORECASE)
_ARTIFACT_NOUN_RE = re.compile(
    r"\b(artefakt|artifact|memo|spezifikation|spezi|proposal|one.?pager|briefing|"
    r"dokument|zusammenfassung|protokoll|steckbrief)\b",
    re.IGNORECASE,
)


_URL_INGEST_RE = re.compile(
    r"(lies|einles|aufnehm|scrape|scrapen|importier|einpfleg|hol[e]?\s|von der (seite|url)|in den (wissens)?graph)",
    re.IGNORECASE,
)


def _detect_url_ingest(text: str) -> bool:
    """URL einlesen? Zwei saubere Fälle → immer die Aktion INGEST (nicht Chat/Wissen):
      • URL + expliziter Einlese-/Aufnahme-Wunsch ("… aufnehmen/einlesen"), oder
      • eine NACKTE URL (die Nachricht ist im Wesentlichen nur der Link).
    So löst das Einfügen eines Links konsistent den Ingest aus statt einer wirren Mischung."""
    if not _first_url(text):
        return False
    if _URL_INGEST_RE.search(text or ""):
        return True
    # Nackte URL: nach Entfernen aller Links bleibt praktisch nichts übrig.
    rest = _URL_RE.sub("", text or "").strip(" \t\n\r-–—·:.,;!?()[]\"'")
    return len(rest) <= 3


def _detect_graph_write(text: str) -> str | None:
    """→ 'artifact' (Artefakt erstellen + in Graph ablegen) | 'nodes' | None.

    Liegt eine URL vor, gewinnt der Scrape/Ingest-Pfad — Graph-Write kapert das NICHT.
    """
    t = text or ""
    if _first_url(t):
        return None
    if not (_GRAPH_WRITE_RE.search(t) and _GRAPH_TARGET_RE.search(t)):
        return None
    return "artifact" if _ARTIFACT_NOUN_RE.search(t) else "nodes"


async def _graph_ingest_artifact(c: httpx.AsyncClient, saved: dict, identity: Identity) -> int:
    """Persistiertes Artefakt als Knoten in den Graphen schreiben (DB→Graph-Projektion)."""
    try:
        r = await c.post(f"{ENGINE_URL}/ingest", json={
            "label": saved.get("title") or "Artefakt", "type": "Document",
            "props": {
                "kind": saved.get("kind", "memo"),
                "quelle": f"artefakt:{saved.get('id', '')}",
                "erstellt_von": identity.email,
                "erstellt_am": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "mandant": identity.tenant_id,
                "inhalt": (saved.get("markdown") or "")[:1800],
            },
            "links": [], "client_id": _graph_client(identity), "levels": ["client"],
        })
        return r.json().get("graph_delta", {}).get("nodes", [])
    except Exception as e:  # noqa: BLE001
        log.warning("graph_ingest_artifact failed: %s", e)
        return []


async def _run_graph_write(c: httpx.AsyncClient, mode: str, req: AskReq, identity: Identity,
                           tenant_id: str, thread_id: str, history: list[dict],
                           trace: list[dict]) -> dict:
    """Führt die Schreib-Aktion WIRKLICH aus (F8): Artefakt→Graph oder geerdete Knoten."""
    gclient = _graph_client(identity)   # Graph-Namespace (Sandbox: pro-User); DB bleibt tenant_id
    if mode == "artifact":
        kind = _detect_artifact_kind(req.text) or "memo"
        # 1) Artefakt erzeugen (belegt, engine /artifact)
        try:
            r = await c.post(f"{ENGINE_URL}/artifact", json={
                "kind": kind, "thread_id": thread_id, "client_id": gclient,
                "context": f"{req.text}\n\n{_last_assistant_text(history)}".strip()})
            art = r.json()
        except Exception as e:  # noqa: BLE001
            trace.append({"step": "artifact", "method": "POST /artifact",
                          "result": f"unreachable: {e.__class__.__name__}", "service": "engine"})
            return envelope("graph", "engine",
                            "Das Artefakt konnte nicht erzeugt werden (engine nicht erreichbar).",
                            trace=trace, provider=req.provider)
        art.setdefault("kind", kind)
        art["thread_id"] = thread_id
        art.setdefault("id", db.new_id("a"))
        # 2) DB (Source of Truth) — der Nutzer hat das Ablegen explizit verlangt
        saved = db.save_artifact(art, tenant_id, is_super=identity.is_super,
                                 created_by=identity.email)
        # 3) Graph-Projektion (Knoten mit Provenienz)
        nodes = await _graph_ingest_artifact(c, saved, identity)
        saved["saved"] = True
        graph_delta = {"nodes": nodes, "edges": []}
        title = saved.get("title") or "Artefakt"
        txt = (f"**{title}** erstellt und als Knoten im Gedächtnis abgelegt "
               f"({len(nodes)} Knoten, Provenienz: Autor + Zeit + Mandant). Es liegt in der "
               f"Bibliothek und rechts im Panel.")
        trace.append({"step": "artifact", "method": "POST /artifact", "result": saved.get("id"),
                      "service": "engine"})
        trace.append({"step": "ingest", "method": "POST /ingest",
                      "result": f"{len(nodes)} nodes", "service": "engine"})
        return envelope("graph", "engine", txt, artifact=saved, graph_delta=graph_delta,
                        highlight=[n.get("id") for n in nodes if n.get("id")],
                        trace=trace, provider=req.provider)

    # mode == "nodes": geerdete Extraktion aus dem Chat-Kontext → schreiben
    context = "\n".join(
        (h.get("content") or h.get("text") or "") for h in (history or [])[-6:]
    ).strip()
    context = f"{context}\n{req.text}".strip()
    try:
        r = await c.post(f"{ENGINE_URL}/extract",
                         json={"text": context, "client_id": gclient,
                               "max_nodes": 6, "provider": req.provider})
        ex = r.json()
    except Exception as e:  # noqa: BLE001
        trace.append({"step": "extract", "method": "POST /extract",
                      "result": f"unreachable: {e.__class__.__name__}", "service": "engine"})
        return envelope("graph", "engine",
                        "Die Knoten-Extraktion ist nicht erreichbar.", trace=trace,
                        provider=req.provider)
    ext_nodes = ex.get("nodes", [])
    ext_edges = ex.get("edges", [])
    if not ext_nodes:
        # Keine belegbaren Entitäten → NICHT erfinden, sondern nach Quelle fragen.
        return envelope("graph", "engine",
                        "Ich lege nichts Erfundenes im Gedächtnis ab. Aus dem bisherigen Verlauf "
                        "lässt sich kein belegbarer Knoten ableiten — nenne mir die konkreten "
                        "Entitäten oder stelle eine Quelle (Datei/URL) bereit, dann schreibe ich "
                        "sie mit Provenienz ins Gedächtnis.",
                        ctas=[{"type": "ingest", "label": "📎 Quelle bereitstellen"}],
                        trace=trace, provider=req.provider)
    # Knoten sequenziell schreiben; Kanten zu bereits erzeugten Zielen mitnehmen.
    label_to_id: dict[str, str] = {}
    all_nodes: list[dict] = []
    all_edges: list[dict] = []
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for n in ext_nodes:
        links = [{"target": label_to_id[e["target"].lower()], "rel": e.get("rel", "RELATED_TO")}
                 for e in ext_edges
                 if e.get("source", "").lower() == n["label"].lower()
                 and e.get("target", "").lower() in label_to_id]
        try:
            ir = await c.post(f"{ENGINE_URL}/ingest", json={
                "label": n["label"], "type": n.get("type", "Konzept"),
                "props": {"extracted": True, "quelle": f"chat:{thread_id}",
                          "erstellt_von": identity.email, "erstellt_am": stamp,
                          "mandant": tenant_id},
                "links": links, "client_id": gclient, "levels": ["client"]})
            delta = ir.json().get("graph_delta", {"nodes": [], "edges": []})
        except Exception:  # noqa: BLE001
            continue
        for nd in delta.get("nodes", []):
            all_nodes.append(nd)
            label_to_id[n["label"].lower()] = nd.get("id", "")
        all_edges += delta.get("edges", [])
    txt = (f"{len(all_nodes)} Knoten aus dem Verlauf extrahiert und ins Gedächtnis "
           f"geschrieben (mit Provenienz: Autor + Zeit + Chat-Bezug)"
           + (f", {len(all_edges)} Kanten." if all_edges else ".")
           + " Nur belegbare Entitäten — nichts erfunden.")
    trace.append({"step": "extract", "method": "POST /extract",
                  "result": f"{len(ext_nodes)} entities", "service": "engine"})
    trace.append({"step": "ingest", "method": "POST /ingest",
                  "result": f"{len(all_nodes)} nodes", "service": "engine"})
    return envelope("graph", "engine", txt,
                    graph_delta={"nodes": all_nodes, "edges": all_edges},
                    highlight=[n.get("id") for n in all_nodes if n.get("id")],
                    trace=trace, provider=req.provider)


def _last_assistant_text(history: list[dict]) -> str:
    for h in reversed(history or []):
        if isinstance(h, dict) and h.get("role") == "assistant":
            c = (h.get("content") or h.get("text") or "").strip()
            if len(c) >= 20:
                return c
    return ""


def _derive_subject(body: str) -> str:
    first = (body or "").strip().splitlines()[0] if body.strip() else ""
    first = re.sub(r'^[\s>*\-•"]+', "", first).strip().strip('"')
    if 3 <= len(first) <= 72:
        return first
    return "Nachricht von c:node"


async def _grounded_mail_draft(c: httpx.AsyncClient, goal: str, tenant_id: str,
                               history: list[dict], provider: str) -> str:
    """Belegter, strukturierter Mail-Entwurf — gleiche Logik wie der Outreach-Agent:
    zuerst Tenant-Fakten aus dem Graphen ziehen, dann klar strukturierten deutschen
    Text verfassen (Anrede, knappe Absätze, Grußformel; nur Belegtes, nichts erfinden).
    So liefert auch die Ad-hoc-Anfrage „sende Mail an X" einen starken Entwurf.
    """
    ofacts = ""
    try:
        r = await c.post(f"{ENGINE_URL}/retrieve",
                         json={"text": goal, "client_id": tenant_id, "limit": 6})
        ofacts = (r.json().get("facts") or "").strip()
    except Exception:  # noqa: BLE001
        ofacts = ""
    turns = [h for h in (history or []) if (h.get("content") or h.get("text"))]
    hist_txt = "\n".join(
        f"{'Nutzer' if h.get('role') == 'user' else 'Assistent'}: "
        f"{(h.get('content') or h.get('text') or '').strip()}" for h in turns[-6:])
    draft_prompt = (
        f"Entwirf eine kurze, professionelle deutsche E-Mail. Anliegen: {goal}.\n"
        + (f"\nKontext/Fakten (nur Belegtes nutzen, nichts erfinden):\n{ofacts}\n" if ofacts else "")
        + (f"\nGesprächsverlauf:\n{hist_txt}\n" if hist_txt else "")
        + "\nGib NUR den E-Mail-Text (Anrede, 2–4 knappe Absätze, Grußformel) — keine "
          "Betreffzeile, keine Erklärungen."
    )
    try:
        ar = await c.post(f"{ENGINE_URL}/answer",
                          json={"text": draft_prompt, "client_id": tenant_id,
                                "history": [], "provider": provider})
        return (ar.json().get("result") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


async def _propose_action(c: httpx.AsyncClient, action_type: str, req: AskReq,
                          identity: Identity, tenant_id: str, history: list[dict],
                          trace: list[dict]) -> dict:
    """Baut eine Aktions-Vorschlag-Envelope (KEINE Ausführung) für die Bestätigungs-Karte."""
    if action_type == "gmail_draft":
        connected = bool(db.get_google_tokens(tenant_id, identity.email))  # Tokens: echter Tenant
        body = _last_assistant_text(history)
        if len(body) < 20:  # noch kein Entwurfstext im Verlauf → belegt & strukturiert generieren
            body = await _grounded_mail_draft(c, req.text, _graph_client(identity), history, req.provider)
        subject = _derive_subject(body)
        action = {
            "id": db.new_id("act"),
            "type": "gmail_draft",
            "connector": "gmail",
            "connected": connected,
            "title": "Gmail-Entwurf anlegen",
            "summary": "Wird als Entwurf in deinem Gmail gespeichert — nichts wird automatisch gesendet.",
            "params": {"subject": subject, "body": body, "to": ""},
            "status": "pending",
        }
        intro = (
            "Ich habe einen **Gmail-Entwurf** vorbereitet — ich sende nichts automatisch. "
            "Prüfe Betreff und Text und bestätige, dann lege ich den Entwurf in deinem Gmail an."
            if connected else
            "Ich kann den Text als **Gmail-Entwurf** anlegen — dafür muss zuerst dein Google-Konto "
            "verbunden sein. Verbinde Google, dann lege ich den Entwurf nach deiner Bestätigung an."
        )
        trace.append({"step": "action", "method": "propose", "result": "gmail_draft",
                      "service": "bff"})
        return envelope("action", "action", intro, action=action, trace=trace,
                        provider=req.provider)
    return envelope("smalltalk", "engine", "Diese Aktion ist noch nicht verfügbar.",
                    trace=trace, provider=req.provider)


async def _route(c: httpx.AsyncClient, intent: str, req: AskReq, tenant_id: str,
                 levels: list[str], trace: list[dict], history: list[dict]) -> dict:
    """Intent → Downstream-Service. client_id kommt SERVERSEITIG aus dem JWT."""
    # Öffentliche Demo: Förderung/Leads (market-Ebenen-IP via assets) nie bedienen →
    # auf den abgeriegelten Wissens-Pfad (engine /answer, nur eigene Ebene) umleiten.
    if PUBLIC_DEMO and intent in _PUBLIC_BLOCKED_INTENTS:
        intent = "knowledge"
    try:
        if intent == "leads":
            r = await c.post(
                f"{ASSETS_URL}/leadscout/find",
                json={"icp": req.text, "client_id": tenant_id},
            )
            leads = r.json().get("leads", [])
            txt = "**Gefundene Leads (LeadScout):**\n" + "\n".join(
                f"- **{l.get('name','?')}** · {l.get('segment','')} · "
                f"Score {l.get('score','')} — {l.get('reason','')}"
                for l in leads
            ) if leads else "Keine passenden Leads gefunden."
            sources = _norm_sources(
                [{"id": l.get("name", f"lead_{i}"), "label": l.get("name", ""),
                  "type": "Lead", "props": l, "provenance": "LeadScout"}
                 for i, l in enumerate(leads)]
            )
            trace.append({"step": "route", "method": "POST /leadscout/find",
                          "result": f"{len(leads)} leads", "service": "assets"})
            return envelope(intent, "assets", txt, sources=sources,
                            highlight=[s["id"] for s in sources],
                            trace=trace, provider=req.provider)

        if intent == "foerderung":
            r = await c.post(
                f"{ASSETS_URL}/foerder/match",
                json={"query": req.text,
                      "client_profile": {"client_id": tenant_id},
                      "client_id": tenant_id},
            )
            progs = r.json().get("programs", [])
            txt = "**Passende Förderprogramme (Förder):**\n" + "\n".join(
                f"- **{p.get('name','?')}** · Fit {p.get('fit','')} · "
                f"{p.get('max_foerderung','')} · Frist {p.get('frist','')} — {p.get('reason','')}"
                for p in progs
            ) if progs else "Keine passenden Förderprogramme gefunden."
            sources = _norm_sources(
                [{"id": p.get("name", f"prog_{i}"), "label": p.get("name", ""),
                  "type": "FundingProgram", "props": p, "provenance": "Förder"}
                 for i, p in enumerate(progs)]
            )
            trace.append({"step": "route", "method": "POST /foerder/match",
                          "result": f"{len(progs)} programs", "service": "assets"})
            return envelope(intent, "assets", txt, sources=sources,
                            highlight=[s["id"] for s in sources],
                            trace=trace, provider=req.provider)

        if intent == "ingest":
            lvl = "+".join(levels)
            url = _first_url(req.text)
            # URL genannt → Website WIRKLICH holen, Haupttext extrahieren und als
            # Info-Basis in den Graphen einlesen (statt nur den Nachrichtentext).
            if url:
                sr = await c.post(
                    f"{ASSETS_URL}/scrape",
                    json={"url": url, "client_id": tenant_id, "levels": levels},
                )
                data = sr.json()
                if not data.get("ok"):
                    reason = data.get("reason", "fetch_failed")
                    txt = (f"Die Seite **{url}** konnte nicht eingelesen werden "
                           f"(`{reason}`). Prüfe die URL bzw. Erreichbarkeit.")
                    trace.append({"step": "route", "method": "POST /scrape",
                                  "result": f"failed: {reason}", "service": "assets"})
                    return envelope(intent, "assets", txt, trace=trace, provider=req.provider)
                delta = data.get("graph_delta", {"nodes": [], "edges": []})
                nodes = delta.get("nodes", [])
                chars = data.get("chars", 0)
                title = data.get("title") or url
                txt = (f"Website eingelesen (Ebene: {lvl}): **{title}** — "
                       f"{chars} Zeichen Haupttext extrahiert, {len(nodes)} Knoten in den "
                       f"Gedächtnis geschrieben. Quelle: {url}")
                if chars < 400:
                    txt += ("\n\n_Hinweis: nur wenig Text extrahiert — die Seite lädt Inhalte "
                            "vermutlich per JavaScript nach. Für mehr Tiefe eine konkrete "
                            "Unterseite oder ein Dokument (PDF) einlesen._")
                trace.append({"step": "route", "method": "POST /scrape",
                              "result": f"{chars} chars, {len(nodes)} nodes ({lvl})",
                              "service": "assets"})
                return envelope(intent, "assets", txt, graph_delta=delta,
                                highlight=[n.get("id") for n in nodes if n.get("id")],
                                trace=trace, provider=req.provider)
            # Kein URL → Freitext-Notiz als Knoten einlesen (bisheriges Verhalten).
            r = await c.post(
                f"{ENGINE_URL}/ingest",
                json={"label": req.text, "type": "Document",
                      "props": {"ingested": True}, "links": [],
                      "client_id": tenant_id, "levels": levels},
            )
            delta = r.json().get("graph_delta", {"nodes": [], "edges": []})
            nodes = delta.get("nodes", [])
            txt = (f"Notiz eingelesen (Ebene: {lvl}): **{req.text}** → {len(nodes)} "
                   "Knoten ins Gedächtnis geschrieben. Der Graph ist live gewachsen.")
            trace.append({"step": "route", "method": "POST /ingest",
                          "result": f"{len(nodes)} nodes ({lvl})", "service": "engine"})
            return envelope(intent, "engine", txt, graph_delta=delta,
                            highlight=[n.get("id") for n in nodes if n.get("id")],
                            trace=trace, provider=req.provider)

        if intent == "graph":
            r = await c.get(f"{ENGINE_URL}/graph", params={"client_id": tenant_id})
            g = r.json()
            txt = (f"Gedächtnis: **{len(g.get('nodes', []))} Knoten**, "
                   f"**{len(g.get('edges', []))} Kanten**. Klicke einen Knoten "
                   "für Details + Provenienz.")
            trace.append({"step": "route", "method": "GET /graph",
                          "result": f"{len(g.get('nodes', []))} nodes",
                          "service": "engine"})
            return envelope(intent, "graph", txt, graph_delta=g,
                            trace=trace, provider=req.provider)

        # knowledge | decision | smalltalk → engine /answer
        r = await c.post(
            f"{ENGINE_URL}/answer",
            json={"text": req.text, "client_id": tenant_id,
                  "history": history, "provider": req.provider,
                  "intel": _intel_flag(tenant_id)},
        )
        data = r.json()
        sources = _norm_sources(data.get("sources", []))
        # Quellen UND Rechenweg nur zeigen, wenn wirklich Fakten genutzt wurden.
        # Reiner Berater-Chat (keine Quellen) → sauberer Bubble ohne Rechenweg/Highlight.
        if sources:
            trace += data.get("trace", [])
            trace.append({"step": "route", "method": "POST /answer",
                          "result": f"{len(sources)} sources", "service": "engine"})
            out_trace, out_highlight = trace, [s["id"] for s in sources]
        else:
            out_trace, out_highlight = [], []
        return envelope(
            data.get("intent", intent), "engine", data.get("result", ""),
            sources=sources, highlight=out_highlight,
            graph_delta=data.get("graph_delta", {"nodes": [], "edges": []}),
            trace=out_trace, provider=data.get("provider", req.provider),
            model=data.get("model", DEFAULT_MODEL),
            suggestions=data.get("suggestions", []),
            ctas=data.get("ctas"),
            grounding=data.get("grounding", "chat"),
            grounded=bool(data.get("grounded")),
        )

    except Exception as exc:
        service = "assets" if intent in ("leads", "foerderung") else "engine"
        route = service if intent != "graph" else "graph"
        trace.append({"step": "route", "method": "downstream",
                      "result": f"unreachable: {exc.__class__.__name__}",
                      "service": service})
        return envelope(
            intent, route,
            f"⚠️ Downstream-Service `{service}` nicht erreichbar — degraded. "
            "Antwort konnte nicht erzeugt werden.",
            trace=trace, provider=req.provider,
        )


async def _attach_artifact(kind: str, req: AskReq, tenant_id: str, thread_id: str,
                           env: dict, is_super: bool = False, gclient: str | None = None) -> None:
    """Ruft engine POST /artifact, persistiert und hängt es ins Envelope.
    gclient = Graph-Namespace (Sandbox pro-User); Default tenant_id (dediziert/lokal inert)."""
    try:
        async with httpx.AsyncClient(timeout=T_LONG) as c:
            r = await c.post(
                f"{ENGINE_URL}/artifact",
                json={"kind": kind, "thread_id": thread_id,
                      "client_id": gclient or tenant_id,
                      "context": f"{req.text}\n\n{env.get('result_text', '')}".strip()},
            )
            art = r.json()
        art.setdefault("kind", kind)
        art["thread_id"] = thread_id
        # NICHT automatisch persistieren: Artefakt bleibt zunächst nur für die Session
        # (Download/Export). Der Nutzer entscheidet im Panel, ob es in die Bibliothek
        # (+ Gedächtnis) gespeichert wird → POST /artifacts/save.
        art.setdefault("id", db.new_id("a"))
        art["saved"] = False
        env["artifact"] = art
        env["trace"].append({"step": "artifact", "method": "POST /artifact",
                             "result": f"{art.get('id', kind)} (session)", "service": "engine"})
    except Exception as exc:
        env["trace"].append({"step": "artifact", "method": "POST /artifact",
                             "result": f"unreachable: {exc.__class__.__name__}",
                             "service": "engine"})
