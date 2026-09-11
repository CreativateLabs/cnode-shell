"""Postgres persistence for the BFF (psycopg 3).

Multi-tenant governance store for the c:node Assistant Shell.

Tables
------
tenants        Mandanten (formerly v1 "clients")
users          global identities (email is the key)
memberships    user↔tenant with role in (super_admin|admin|member|viewer)
threads        chat threads, tenant-scoped
messages       chat messages, tenant-scoped
artifacts      persisted artifacts (SCOPE §2.3), tenant-scoped
shares         share-tokens for threads, tenant-scoped
promotions     Admin→Super-Admin market-ingest requests
magic_tokens   one-shot magic-link login tokens

Isolation
---------
The **application layer** is the primary enforcer: every tenant-scoped query is
filtered by the tenant derived from the verified JWT. Postgres **RLS** is added
as defense-in-depth: tenant-scoped tables have `FORCE ROW LEVEL SECURITY` and a
policy keyed on the per-transaction GUC `app.current_tenant` (super-admin bypass
via `app.is_superadmin`). Tenant-scoped access goes through `tenant_tx()`, which
sets those GUCs with `set_config(..., is_local => true)` inside the transaction.

A tiny home-grown connection pool keeps the dependency surface to psycopg only.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import queue
import threading
import time
import uuid
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://cnode:cnode@postgres:5432/cnode"
)


def _ensure_database() -> None:
    """Legt die Ziel-DB an, falls sie fehlt (Auto-Provisioning je Tenant).
    Verbindet dazu mit der Wartungs-DB 'postgres' und CREATE DATABASE bei Bedarf.
    Idempotent, offline-sicher (schluckt Fehler → normaler Connect-Retry greift)."""
    from urllib.parse import urlsplit
    try:
        u = urlsplit(DATABASE_URL)
        dbname = (u.path or "/").lstrip("/") or "postgres"
        if dbname == "postgres":
            return
        admin_url = DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
        for _ in range(30):
            try:
                with psycopg.connect(admin_url, autocommit=True) as adm:
                    exists = adm.execute(
                        "SELECT 1 FROM pg_database WHERE datname=%s", (dbname,)).fetchone()
                    if not exists:
                        adm.execute(f'CREATE DATABASE "{dbname}"')
                return
            except Exception:
                time.sleep(1.0)
    except Exception:
        pass
POOL_SIZE = int(os.getenv("BFF_DB_POOL", "8"))
MAGIC_TTL_SECONDS = int(os.getenv("MAGIC_TTL_SECONDS", "900"))  # 15 min
# Non-superuser role used ONLY for tenant-scoped queries so Postgres RLS actually
# applies (the connection role is often a superuser, which bypasses RLS entirely).
APP_DB_ROLE = os.getenv("APP_DB_ROLE", "cnode_app")

_SEED_TENANTS = []

# Demo accounts (dev): one per role, all sharing the same password. Seeded
# idempotently at startup; the cleartext password is exposed ONLY via the
# dev-gated GET /auth/demo-accounts endpoint.
DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "demo1234")
DEMO_TENANT = ("demo", "Demo GmbH")
# (email, role, tenant_id) — super_admin lives on the shared 'platform' tenant.
DEMO_ACCOUNTS: list[tuple[str, str, str]] = [
    ("super@demo.cnode", "super_admin", "platform"),
    ("admin@demo.cnode", "admin", "demo"),
    ("member@demo.cnode", "member", "demo"),
    ("viewer@demo.cnode", "viewer", "demo"),
]

_pool: "queue.Queue[psycopg.Connection]" = queue.Queue()
_init_lock = threading.Lock()
_ready = False
_app_role_ready = False  # True once the non-superuser RLS role exists + is granted

VALID_ROLES = ("super_admin", "owner", "admin", "member", "viewer")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _connect() -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=False)


@contextmanager
def _conn():
    """Check a connection out of the pool (plain, no tenant GUCs)."""
    c = _pool.get()
    try:
        yield c
        c.commit()
    except Exception:
        try:
            c.rollback()
        except Exception:
            pass
        raise
    finally:
        _pool.put(c)


@contextmanager
def tenant_tx(tenant_id: str | None, is_superadmin: bool = False):
    """Yield a cursor whose transaction carries the RLS tenant context.

    ``SET LOCAL ROLE`` drops to a non-superuser role for the duration of the
    transaction so the RLS policies are actually enforced (superusers and the
    table owner under FORCE-RLS are still bound, but a plain superuser
    connection would otherwise bypass RLS). GUCs + role reset on COMMIT.
    """
    with _conn() as c:
        with c.cursor() as cur:
            if _app_role_ready:
                cur.execute(f'SET LOCAL ROLE "{APP_DB_ROLE}"')
            cur.execute(
                "SELECT set_config('app.current_tenant', %s, true)",
                (tenant_id or "",),
            )
            cur.execute(
                "SELECT set_config('app.is_superadmin', %s, true)",
                ("on" if is_superadmin else "off",),
            )
            yield cur


# --------------------------------------------------------------------------
# Migrations (idempotent) — run at startup
# --------------------------------------------------------------------------
_SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
    id         TEXT PRIMARY KEY,
    label      TEXT NOT NULL,
    settings   JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS memberships (
    id         TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tenant_id  TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    role       TEXT NOT NULL CHECK (role IN ('super_admin','admin','member','viewer')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, tenant_id)
);

CREATE TABLE IF NOT EXISTS threads (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT NOT NULL,
    title      TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS messages (
    id         TEXT PRIMARY KEY,
    thread_id  TEXT NOT NULL,
    tenant_id  TEXT NOT NULL,
    role       TEXT NOT NULL,
    text       TEXT NOT NULL,
    author     TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS artifacts (
    id         TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,
    title      TEXT,
    markdown   TEXT,
    tenant_id  TEXT NOT NULL,
    thread_id  TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS shares (
    token      TEXT PRIMARY KEY,
    thread_id  TEXT NOT NULL,
    tenant_id  TEXT NOT NULL,
    role       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS promotions (
    id           TEXT PRIMARY KEY,
    source_id    TEXT NOT NULL,
    tenant_id    TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending','approved','rejected')),
    requested_by TEXT,
    decided_by   TEXT,
    levels       JSONB NOT NULL DEFAULT '["client","market"]'::jsonb,
    note         TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_at   TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS magic_tokens (
    token      TEXT PRIMARY KEY,
    email      TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    used       BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- OTP-Codes (E-Mail-Login, primär). Nur der Hash liegt; Brute-Force via attempts.
CREATE TABLE IF NOT EXISTS auth_codes (
    email      TEXT PRIMARY KEY,
    code_hash  TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    attempts   INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- SCOPE v3 --------------------------------------------------------------
CREATE TABLE IF NOT EXISTS folders (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT NOT NULL,
    name       TEXT NOT NULL,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS notifications (
    id              TEXT PRIMARY KEY,
    tenant_id       TEXT NOT NULL,
    recipient_email TEXT NOT NULL,
    type            TEXT NOT NULL,
    title           TEXT,
    body            TEXT,
    from_email      TEXT,
    thread_id       TEXT,
    data            JSONB NOT NULL DEFAULT '{}'::jsonb,
    read            BOOLEAN NOT NULL DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS data_requests (
    id           TEXT PRIMARY KEY,
    tenant_id    TEXT NOT NULL,
    scope        TEXT NOT NULL,
    note         TEXT,
    connector    TEXT,
    requested_by TEXT,
    target_role  TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending','approved','rejected')),
    decided_by   TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_at   TIMESTAMPTZ
);

-- SCOPE v3: Google connector tokens (per tenant + user). Tokens are stored
-- lightly encrypted at rest when ENCRYPTION_SECRET/AUTH_SECRET is set (see
-- _enc_token/_dec_token below); otherwise cleartext with a 'plain:' marker.
CREATE TABLE IF NOT EXISTS google_tokens (
    tenant_id     TEXT NOT NULL,
    user_email    TEXT NOT NULL,
    access_token  TEXT,
    refresh_token TEXT,
    token_type    TEXT,
    scope         TEXT,
    expiry        BIGINT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, user_email)
);

CREATE TABLE IF NOT EXISTS microsoft_tokens (
    tenant_id     TEXT NOT NULL,
    user_email    TEXT NOT NULL,
    access_token  TEXT,
    refresh_token TEXT,
    token_type    TEXT,
    scope         TEXT,
    expiry        BIGINT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, user_email)
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id          TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    thread_id   TEXT,
    agent       TEXT NOT NULL,
    goal        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'planned'
                CHECK (status IN ('planned','running','done','failed')),
    provider    TEXT NOT NULL DEFAULT 'ollama',
    plan        JSONB NOT NULL DEFAULT '[]'::jsonb,
    result      TEXT,
    artifact_id TEXT,
    created_by  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agent_steps (
    id          TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL,
    tenant_id   TEXT NOT NULL,
    idx         INTEGER NOT NULL,
    title       TEXT NOT NULL,
    tool        TEXT,
    status      TEXT NOT NULL DEFAULT 'planned'
                CHECK (status IN ('planned','running','done','failed','skipped')),
    summary     TEXT,
    provenance  JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Epic O — Teams innerhalb einer Org (=tenant): Team-Lead + Members.
CREATE TABLE IF NOT EXISTS teams (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT NOT NULL,
    name       TEXT NOT NULL,
    slug       TEXT NOT NULL,
    description TEXT,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, slug)
);

CREATE TABLE IF NOT EXISTS team_members (
    id         TEXT PRIMARY KEY,
    team_id    TEXT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tenant_id  TEXT NOT NULL,
    role       TEXT NOT NULL CHECK (role IN ('lead','member')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (team_id, user_id)
);

-- Org-Einladungen (magic-link): Ziel-Org-Rolle + optional Team + Team-Rolle.
CREATE TABLE IF NOT EXISTS invites (
    id         TEXT PRIMARY KEY,
    tenant_id  TEXT NOT NULL,
    email      TEXT NOT NULL,
    org_role   TEXT NOT NULL CHECK (org_role IN ('owner','admin','member','viewer')),
    team_id    TEXT,
    team_role  TEXT CHECK (team_role IN ('lead','member')),
    token_hash TEXT NOT NULL,
    invited_by TEXT,
    expires_at TIMESTAMPTZ,
    accepted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Owner-Org-Setup (Launch-Wizard): vordefinierte Quellen + Org-Profil + Fortschritt.
-- Eine Zeile je Tenant. Wissensbasis-Initialisierung ("pre-training") + Kuratier-State.
-- Owner-Setup: je Tenant UND Workspace (Sandbox: pro-User-Workspace = ws:<tenant>~<user>).
-- workspace = tenant_id im dedizierten Betrieb (ein Setup je Tenant).
CREATE TABLE IF NOT EXISTS tenant_setup (
    tenant_id   TEXT NOT NULL,
    workspace   TEXT NOT NULL DEFAULT '',
    data        JSONB NOT NULL DEFAULT '{}'::jsonb,
    completed   BOOLEAN NOT NULL DEFAULT false,
    updated_by  TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace)
);

-- Entitlements (Monetarisierung): je Tenant, ob NENA-Intel frei + welcher Tier + Token-Budget.
-- Wird vom Stripe/IAP-Webhook gesetzt; steuert SHARED_LAYERS + die Caps.
CREATE TABLE IF NOT EXISTS tenant_entitlements (
    tenant_id     TEXT PRIMARY KEY,
    intel         BOOLEAN NOT NULL DEFAULT false,   -- NENA (market/mesh) frei?
    tier          TEXT NOT NULL DEFAULT 'free',      -- free | pro | team | enterprise
    stripe_customer TEXT,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_teams_tenant       ON teams(tenant_id);
CREATE INDEX IF NOT EXISTS idx_team_members_team  ON team_members(team_id);
CREATE INDEX IF NOT EXISTS idx_team_members_user  ON team_members(user_id);
CREATE INDEX IF NOT EXISTS idx_team_members_tenant ON team_members(tenant_id);
CREATE INDEX IF NOT EXISTS idx_invites_tenant     ON invites(tenant_id);
CREATE INDEX IF NOT EXISTS idx_invites_email      ON invites(email);
CREATE INDEX IF NOT EXISTS idx_agent_runs_thread ON agent_runs(thread_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_tenant ON agent_runs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_agent_steps_run   ON agent_steps(run_id);
CREATE INDEX IF NOT EXISTS idx_threads_tenant   ON threads(tenant_id);
CREATE INDEX IF NOT EXISTS idx_messages_thread  ON messages(thread_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_tenant ON artifacts(tenant_id);
CREATE INDEX IF NOT EXISTS idx_memberships_user ON memberships(user_id);
CREATE INDEX IF NOT EXISTS idx_promotions_tenant ON promotions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_folders_tenant   ON folders(tenant_id);
CREATE INDEX IF NOT EXISTS idx_notif_recipient  ON notifications(recipient_email);
CREATE INDEX IF NOT EXISTS idx_datareq_tenant   ON data_requests(tenant_id);
"""

# tenant-scoped tables get RLS (defense-in-depth). notifications are
# recipient-scoped (a user reads their own across tenants) and therefore stay
# out of the tenant-keyed RLS set — they are always filtered by recipient_email.
_RLS_TABLES = ("threads", "messages", "artifacts", "shares", "promotions",
               "folders", "data_requests", "agent_runs", "agent_steps",
               "teams", "team_members", "invites", "tenant_setup")


def _apply_rls(cur) -> None:
    for t in _RLS_TABLES:
        cur.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        # FORCE so even the table owner (our app role) is subject to the policy
        cur.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        cur.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {t}")
        cur.execute(
            f"""
            CREATE POLICY tenant_isolation ON {t}
            USING (
                tenant_id = current_setting('app.current_tenant', true)
                OR coalesce(current_setting('app.is_superadmin', true), 'off') = 'on'
            )
            WITH CHECK (
                tenant_id = current_setting('app.current_tenant', true)
                OR coalesce(current_setting('app.is_superadmin', true), 'off') = 'on'
            )
            """
        )


def _ensure_app_role(cur) -> bool:
    """Create the non-superuser RLS role + grants (idempotent).

    Returns True if the role is usable. If role creation is not permitted
    (e.g. managed Postgres without CREATEROLE), returns False and tenant_tx
    falls back to the connection role — the app-layer tenant filter still
    protects every query; only the RLS safety-net is then inert.
    """
    try:
        cur.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{APP_DB_ROLE}') THEN
                    CREATE ROLE "{APP_DB_ROLE}" NOLOGIN NOSUPERUSER NOBYPASSRLS;
                END IF;
            END $$;
            """
        )
        cur.execute(
            f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public '
            f'TO "{APP_DB_ROLE}"'
        )
        cur.execute(f'GRANT USAGE ON SCHEMA public TO "{APP_DB_ROLE}"')
        # the connection role must be a member of the app role to SET ROLE to it
        cur.execute(f'GRANT "{APP_DB_ROLE}" TO CURRENT_USER')
        return True
    except Exception:  # noqa: BLE001
        return False


def init() -> None:
    """Create the pool, run idempotent migrations, seed baseline rows."""
    global _ready
    with _init_lock:
        if _ready:
            return
        _ensure_database()  # Ziel-DB je Tenant selbst anlegen, falls fehlend
        # wait for Postgres (compose ordering / cold start)
        last_err: Exception | None = None
        admin: psycopg.Connection | None = None
        for _ in range(30):
            try:
                admin = psycopg.connect(DATABASE_URL, autocommit=True)
                break
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                time.sleep(1.0)
        if admin is None:
            raise RuntimeError(f"Postgres not reachable: {last_err}")

        global _app_role_ready
        with admin.cursor() as cur:
            cur.execute(_SCHEMA)
            # additive migration for pre-existing DBs where users was created
            # before the password_hash column existed (idempotent).
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT")
            # Signup-Profil (für spätere Onboarding-Ansprache): Name + Firma.
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS name TEXT")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS company TEXT")
            # Eigentümer für per-User-Isolation im geteilten Sandbox-Tenant (PUBLIC_DEMO).
            cur.execute("ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS created_by TEXT")
            cur.execute("ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS created_by TEXT")
            # Owner-Setup pro Workspace (Sandbox pro-User): workspace-Spalte + composite PK.
            cur.execute("ALTER TABLE tenant_setup ADD COLUMN IF NOT EXISTS workspace TEXT")
            cur.execute("UPDATE tenant_setup SET workspace=tenant_id WHERE workspace IS NULL OR workspace=''")
            cur.execute("ALTER TABLE tenant_setup ALTER COLUMN workspace SET DEFAULT ''")
            cur.execute("ALTER TABLE tenant_setup ALTER COLUMN workspace SET NOT NULL")
            cur.execute("ALTER TABLE tenant_setup DROP CONSTRAINT IF EXISTS tenant_setup_pkey")
            cur.execute("ALTER TABLE tenant_setup ADD PRIMARY KEY (tenant_id, workspace)")
            # SCOPE v3: threads gain folder/visibility/members/owner (idempotent).
            cur.execute("ALTER TABLE threads ADD COLUMN IF NOT EXISTS folder_id TEXT")
            cur.execute(
                "ALTER TABLE threads ADD COLUMN IF NOT EXISTS "
                "visibility TEXT NOT NULL DEFAULT 'private'"
            )
            cur.execute(
                "ALTER TABLE threads ADD COLUMN IF NOT EXISTS "
                "members JSONB NOT NULL DEFAULT '[]'::jsonb"
            )
            cur.execute("ALTER TABLE threads ADD COLUMN IF NOT EXISTS created_by TEXT")
            # Sender pro Nachricht (für Avatare / Multi-User-Team-Chat).
            cur.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS author TEXT")
            # Epic O — Ressourcen-Scoping je Team (additiv, backward-compatible).
            cur.execute("ALTER TABLE threads ADD COLUMN IF NOT EXISTS team_id TEXT")
            cur.execute("ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS team_id TEXT")
            cur.execute(
                "ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS "
                "visibility TEXT NOT NULL DEFAULT 'private'"
            )
            # Org-Rolle 'owner' zulassen (getrennt von admin) — CHECK neu setzen.
            cur.execute("ALTER TABLE memberships DROP CONSTRAINT IF EXISTS memberships_role_check")
            cur.execute(
                "ALTER TABLE memberships ADD CONSTRAINT memberships_role_check "
                "CHECK (role IN ('super_admin','owner','admin','member','viewer'))"
            )
            _apply_rls(cur)
            _app_role_ready = _ensure_app_role(cur)
        admin.close()

        # fill the pool
        for _ in range(POOL_SIZE):
            _pool.put(_connect())

        _seed_baseline()
        _ready = True


def _seed_baseline() -> None:
    """Ensure demo tenants + the configured super-admin exist."""
    for tid, label in _SEED_TENANTS:
        upsert_tenant(tid, label)

    super_email = os.getenv("SUPERADMIN_EMAIL", "").strip().lower()
    if super_email:
        # super-admin's home tenant: dedicated 'platform' tenant
        upsert_tenant("platform", "Platform")
        u = upsert_user(super_email)
        add_membership(u["id"], "platform", "super_admin")

    _seed_demo_accounts()

    # O7 — Bootstrap: Default-Team („General") NUR für die eigene Org dieser DB
    # (TENANT_ID). Kein Cross-Tenant (users/teams sind pro Tenant-DB).
    ensure_default_team(os.getenv("TENANT_ID", "").strip())


def _seed_demo_accounts() -> None:
    """Idempotently seed the per-role demo accounts (all password DEMO_PASSWORD).

    The real super-admin (SUPERADMIN_EMAIL, magic-link bootstrap) is untouched.

    PUBLIC_DEMO: the shared password would be a public admin backdoor — so on the public
    sandbox we do NOT seed these accounts and actively REMOVE any that already exist.
    """
    import auth  # local import avoids a circular import at module load

    if os.getenv("PUBLIC_DEMO", "").strip().lower() in ("1", "true", "yes", "on"):
        emails = [e for e, _r, _t in DEMO_ACCOUNTS]
        with _conn() as c, c.cursor() as cur:
            cur.execute("DELETE FROM users WHERE email = ANY(%s)", (emails,))  # memberships cascade
        return

    upsert_tenant("platform", "Platform")
    upsert_tenant(*DEMO_TENANT)
    pw_hash = auth.hash_password(DEMO_PASSWORD)
    for email, role, tenant in DEMO_ACCOUNTS:
        u = upsert_user(email, password_hash=pw_hash)
        add_membership(u["id"], tenant, role)


# --------------------------------------------------------------------------
# Tenants
# --------------------------------------------------------------------------
def list_tenants() -> list[dict]:
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            "SELECT id, label, settings, created_at::text FROM tenants ORDER BY created_at"
        )
        return cur.fetchall()


def get_tenant(tenant_id: str) -> dict | None:
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            "SELECT id, label, settings, created_at::text FROM tenants WHERE id=%s",
            (tenant_id,),
        )
        return cur.fetchone()


def upsert_tenant(tenant_id: str, label: str | None = None) -> dict:
    tenant_id = (tenant_id or new_id("tn")).strip()
    label = label or tenant_id
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            "INSERT INTO tenants (id, label) VALUES (%s,%s) "
            "ON CONFLICT (id) DO UPDATE SET label=EXCLUDED.label "
            "RETURNING id, label, settings, created_at::text",
            (tenant_id, label),
        )
        return cur.fetchone()


def update_tenant_settings(tenant_id: str, settings: dict) -> dict | None:
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            "UPDATE tenants SET settings=%s WHERE id=%s "
            "RETURNING id, label, settings, created_at::text",
            (json.dumps(settings), tenant_id),
        )
        return cur.fetchone()


def delete_tenant(tenant_id: str) -> bool:
    with _conn() as c, c.cursor() as cur:
        cur.execute("DELETE FROM tenants WHERE id=%s", (tenant_id,))
        return cur.rowcount > 0


# --------------------------------------------------------------------------
# Users & memberships
# --------------------------------------------------------------------------
def get_user_by_email(email: str) -> dict | None:
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            "SELECT id, email, password_hash, name, company, created_at::text "
            "FROM users WHERE email=%s",
            (email.lower(),),
        )
        return cur.fetchone()


def upsert_user(email: str, password_hash: str | None = None,
                name: str | None = None, company: str | None = None) -> dict:
    """Create or fetch a user by email. Given fields are written; omitted ones keep
    their existing value (COALESCE), so the magic-link/OTP path never clears a
    password and a later signup can enrich name/company. Backward-compatible."""
    email = email.lower().strip()
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            "INSERT INTO users (id, email, password_hash, name, company) VALUES (%s,%s,%s,%s,%s) "
            "ON CONFLICT (email) DO UPDATE SET "
            "password_hash = COALESCE(EXCLUDED.password_hash, users.password_hash), "
            "name = COALESCE(EXCLUDED.name, users.name), "
            "company = COALESCE(EXCLUDED.company, users.company) "
            "RETURNING id, email, password_hash, name, company, created_at::text",
            (new_id("u"), email, password_hash, (name or None), (company or None)),
        )
        return cur.fetchone()


def set_user_password(user_id: str, password_hash: str) -> dict | None:
    """Set/replace a user's password hash (used by signup)."""
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            "UPDATE users SET password_hash=%s WHERE id=%s "
            "RETURNING id, email, password_hash, created_at::text",
            (password_hash, user_id),
        )
        return cur.fetchone()


def add_membership(user_id: str, tenant_id: str, role: str) -> dict:
    role = role if role in VALID_ROLES else "member"
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            "INSERT INTO memberships (id, user_id, tenant_id, role) VALUES (%s,%s,%s,%s) "
            "ON CONFLICT (user_id, tenant_id) DO UPDATE SET role=EXCLUDED.role "
            "RETURNING id, user_id, tenant_id, role, created_at::text",
            (new_id("mb"), user_id, tenant_id, role),
        )
        return cur.fetchone()


def list_memberships_for_user(user_id: str) -> list[dict]:
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            "SELECT id, user_id, tenant_id, role, created_at::text "
            "FROM memberships WHERE user_id=%s ORDER BY created_at",
            (user_id,),
        )
        return cur.fetchall()


def list_members_for_tenant(tenant_id: str) -> list[dict]:
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            "SELECT m.id, m.user_id, u.email, m.tenant_id, m.role, m.created_at::text "
            "FROM memberships m JOIN users u ON u.id=m.user_id "
            "WHERE m.tenant_id=%s ORDER BY m.created_at",
            (tenant_id,),
        )
        return cur.fetchall()


def get_membership(user_id: str, tenant_id: str) -> dict | None:
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            "SELECT id, user_id, tenant_id, role, created_at::text "
            "FROM memberships WHERE user_id=%s AND tenant_id=%s",
            (user_id, tenant_id),
        )
        return cur.fetchone()


def delete_membership(membership_id: str, tenant_id: str) -> bool:
    """Delete a membership, scoped to the tenant (admin cannot touch others)."""
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            "DELETE FROM memberships WHERE id=%s AND tenant_id=%s",
            (membership_id, tenant_id),
        )
        return cur.rowcount > 0


# --------------------------------------------------------------------------
# Epic O — Teams & Invites (RLS-Tabellen → tenant_tx mit gesetztem Kontext)
# --------------------------------------------------------------------------
def _slugify(s: str) -> str:
    out = "".join(ch if ch.isalnum() else "-" for ch in (s or "").lower()).strip("-")
    while "--" in out:
        out = out.replace("--", "-")
    return out[:40] or "team"


def create_team(tenant_id: str, name: str, description: str = "",
                created_by: str | None = None, is_super: bool = False) -> dict:
    slug = _slugify(name)
    with tenant_tx(tenant_id, is_super) as cur:
        # slug je Org eindeutig machen (Kollision → Suffix).
        cur.execute("SELECT slug FROM teams WHERE tenant_id=%s", (tenant_id,))
        existing = {r["slug"] for r in cur.fetchall()}
        base, n = slug, 2
        while slug in existing:
            slug = f"{base}-{n}"; n += 1
        tid = new_id("tm")
        cur.execute(
            "INSERT INTO teams (id, tenant_id, name, slug, description, created_by) "
            "VALUES (%s,%s,%s,%s,%s,%s) "
            "RETURNING id, tenant_id, name, slug, description, created_by, created_at::text",
            (tid, tenant_id, name, slug, description, created_by),
        )
        return cur.fetchone()


def list_teams(tenant_id: str, is_super: bool = False) -> list[dict]:
    with tenant_tx(tenant_id, is_super) as cur:
        cur.execute(
            "SELECT t.id, t.tenant_id, t.name, t.slug, t.description, t.created_at::text, "
            "  (SELECT count(*) FROM team_members tmb WHERE tmb.team_id=t.id) AS member_count "
            "FROM teams t WHERE t.tenant_id=%s ORDER BY t.created_at",
            (tenant_id,),
        )
        return cur.fetchall()


def get_team(team_id: str, tenant_id: str, is_super: bool = False) -> dict | None:
    with tenant_tx(tenant_id, is_super) as cur:
        cur.execute(
            "SELECT id, tenant_id, name, slug, description, created_at::text "
            "FROM teams WHERE id=%s AND tenant_id=%s",
            (team_id, tenant_id),
        )
        return cur.fetchone()


def delete_team(team_id: str, tenant_id: str, is_super: bool = False) -> bool:
    with tenant_tx(tenant_id, is_super) as cur:
        cur.execute("DELETE FROM teams WHERE id=%s AND tenant_id=%s", (team_id, tenant_id))
        return cur.rowcount > 0


def add_team_member(team_id: str, user_id: str, tenant_id: str, role: str = "member",
                    is_super: bool = False) -> dict:
    role = role if role in ("lead", "member") else "member"
    with tenant_tx(tenant_id, is_super) as cur:
        cur.execute(
            "INSERT INTO team_members (id, team_id, user_id, tenant_id, role) "
            "VALUES (%s,%s,%s,%s,%s) "
            "ON CONFLICT (team_id, user_id) DO UPDATE SET role=EXCLUDED.role "
            "RETURNING id, team_id, user_id, tenant_id, role, created_at::text",
            (new_id("tmb"), team_id, user_id, tenant_id, role),
        )
        return cur.fetchone()


def set_team_role(team_id: str, user_id: str, tenant_id: str, role: str,
                  is_super: bool = False) -> bool:
    role = role if role in ("lead", "member") else "member"
    with tenant_tx(tenant_id, is_super) as cur:
        cur.execute(
            "UPDATE team_members SET role=%s WHERE team_id=%s AND user_id=%s AND tenant_id=%s",
            (role, team_id, user_id, tenant_id),
        )
        return cur.rowcount > 0


def remove_team_member(team_id: str, user_id: str, tenant_id: str,
                       is_super: bool = False) -> bool:
    with tenant_tx(tenant_id, is_super) as cur:
        cur.execute(
            "DELETE FROM team_members WHERE team_id=%s AND user_id=%s AND tenant_id=%s",
            (team_id, user_id, tenant_id),
        )
        return cur.rowcount > 0


def list_team_members(team_id: str, tenant_id: str, is_super: bool = False) -> list[dict]:
    with tenant_tx(tenant_id, is_super) as cur:
        cur.execute(
            "SELECT tmb.id, tmb.team_id, tmb.user_id, u.email, tmb.role, tmb.created_at::text "
            "FROM team_members tmb JOIN users u ON u.id=tmb.user_id "
            "WHERE tmb.team_id=%s AND tmb.tenant_id=%s ORDER BY tmb.role DESC, tmb.created_at",
            (team_id, tenant_id),
        )
        return cur.fetchall()


def list_teams_for_user(user_id: str, tenant_id: str, is_super: bool = False) -> list[dict]:
    """Teams (in dieser Org), in denen der User ist — inkl. seiner Team-Rolle."""
    with tenant_tx(tenant_id, is_super) as cur:
        cur.execute(
            "SELECT t.id, t.name, t.slug, tmb.role "
            "FROM team_members tmb JOIN teams t ON t.id=tmb.team_id "
            "WHERE tmb.user_id=%s AND tmb.tenant_id=%s ORDER BY t.name",
            (user_id, tenant_id),
        )
        return cur.fetchall()


def user_team_role(team_id: str, user_id: str, tenant_id: str, is_super: bool = False) -> str | None:
    with tenant_tx(tenant_id, is_super) as cur:
        cur.execute(
            "SELECT role FROM team_members WHERE team_id=%s AND user_id=%s AND tenant_id=%s",
            (team_id, user_id, tenant_id),
        )
        row = cur.fetchone()
        return row["role"] if row else None


def ensure_default_team(tenant_id: str, name: str = "General") -> dict | None:
    """O7-Bootstrap: genau EIN Default-Team (slug 'general') je Org, idempotent per slug
    (kein Suffix), + ordnet bestehende Org-Mitglieder zu (owner/admin/super → lead)."""
    if not tenant_id:
        return None
    try:
        with tenant_tx(tenant_id, is_superadmin=True) as cur:
            cur.execute(
                "INSERT INTO teams (id, tenant_id, name, slug, description) "
                "VALUES (%s,%s,%s,'general',%s) "
                "ON CONFLICT (tenant_id, slug) DO NOTHING",
                (new_id("tm"), tenant_id, name, "Standard-Team der Organisation"),
            )
            cur.execute("SELECT id FROM teams WHERE tenant_id=%s AND slug='general'", (tenant_id,))
            row = cur.fetchone()
        if not row:
            return None
        team_id = row["id"]
        for m in list_members_for_tenant(tenant_id):
            role = "lead" if m["role"] in ("owner", "admin", "super_admin") else "member"
            try:
                add_team_member(team_id, m["user_id"], tenant_id, role, is_super=True)
            except Exception:  # noqa: BLE001
                pass
        return {"id": team_id}
    except Exception:  # noqa: BLE001
        return None


def create_invite(tenant_id: str, email: str, org_role: str, token_hash: str,
                  team_id: str | None = None, team_role: str | None = None,
                  invited_by: str | None = None, ttl_seconds: int = 604800,
                  is_super: bool = False) -> dict:
    with tenant_tx(tenant_id, is_super) as cur:
        cur.execute(
            "INSERT INTO invites (id, tenant_id, email, org_role, team_id, team_role, "
            "  token_hash, invited_by, expires_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s, now() + (%s || ' seconds')::interval) "
            "RETURNING id, tenant_id, email, org_role, team_id, team_role, expires_at::text",
            (new_id("inv"), tenant_id, email.strip().lower(), org_role, team_id, team_role,
             token_hash, invited_by, str(ttl_seconds)),
        )
        return cur.fetchone()


def get_invite_by_token(token_hash: str) -> dict | None:
    """Invite über den (gehashten) Token finden — Accept-Flow ohne Tenant-Kontext, daher
    Super-Bypass (systemseitig, Token ist das Geheimnis)."""
    with tenant_tx(None, is_superadmin=True) as cur:
        cur.execute(
            "SELECT id, tenant_id, email, org_role, team_id, team_role, "
            "  expires_at::text, accepted_at::text FROM invites "
            "WHERE token_hash=%s AND accepted_at IS NULL AND expires_at > now()",
            (token_hash,),
        )
        return cur.fetchone()


def accept_invite(invite_id: str, tenant_id: str) -> bool:
    with tenant_tx(tenant_id, is_superadmin=True) as cur:
        cur.execute(
            "UPDATE invites SET accepted_at=now() WHERE id=%s AND accepted_at IS NULL",
            (invite_id,),
        )
        return cur.rowcount > 0


def is_superadmin_email(email: str) -> bool:
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM memberships m JOIN users u ON u.id=m.user_id "
            "WHERE u.email=%s AND m.role='super_admin' LIMIT 1",
            (email.lower(),),
        )
        return cur.fetchone() is not None


# --------------------------------------------------------------------------
# Magic tokens
# --------------------------------------------------------------------------
def create_magic_token(email: str) -> dict:
    token = new_id("mgc")
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            "INSERT INTO magic_tokens (token, email, expires_at) "
            "VALUES (%s,%s, now() + make_interval(secs => %s)) "
            "RETURNING token, email, expires_at::text",
            (token, email.lower().strip(), MAGIC_TTL_SECONDS),
        )
        return cur.fetchone()


def consume_magic_token(token: str) -> dict | None:
    """Validate + burn a magic token; returns row (with email) or None."""
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            "UPDATE magic_tokens SET used=true "
            "WHERE token=%s AND used=false AND expires_at > now() "
            "RETURNING token, email",
            (token,),
        )
        return cur.fetchone()


# --------------------------------------------------------------------------
# OTP-Codes (E-Mail-Login) — nur Hash gespeichert, Brute-Force-Limit
# --------------------------------------------------------------------------
import hashlib as _hashlib  # noqa: E402

OTP_TTL_SECONDS = int(os.getenv("OTP_TTL_SECONDS", "600"))   # 10 min
OTP_MAX_ATTEMPTS = int(os.getenv("OTP_MAX_ATTEMPTS", "5"))


def _otp_hash(email: str, code: str) -> str:
    return _hashlib.sha256(f"{email.lower().strip()}:{code}".encode()).hexdigest()


def set_auth_code(email: str, code: str) -> None:
    """Speichert (überschreibt) den OTP-Hash für die E-Mail, TTL + attempts=0."""
    email = email.lower().strip()
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            "INSERT INTO auth_codes (email, code_hash, expires_at, attempts) "
            "VALUES (%s,%s, now() + make_interval(secs => %s), 0) "
            "ON CONFLICT (email) DO UPDATE SET code_hash=EXCLUDED.code_hash, "
            "expires_at=EXCLUDED.expires_at, attempts=0, created_at=now()",
            (email, _otp_hash(email, code), OTP_TTL_SECONDS),
        )


def verify_auth_code(email: str, code: str) -> bool:
    """Prüft den OTP-Code: gültig + nicht abgelaufen + unter Attempt-Limit.
    Bei Erfolg wird der Code verbraucht (gelöscht); sonst attempts++ (und ggf. gesperrt)."""
    email = email.lower().strip()
    want = _otp_hash(email, (code or "").strip())
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            "SELECT code_hash, attempts, (expires_at > now()) AS live "
            "FROM auth_codes WHERE email=%s", (email,))
        row = cur.fetchone()
        if not row or not row["live"] or row["attempts"] >= OTP_MAX_ATTEMPTS:
            return False
        if row["code_hash"] == want:
            cur.execute("DELETE FROM auth_codes WHERE email=%s", (email,))  # burn
            return True
        cur.execute("UPDATE auth_codes SET attempts=attempts+1 WHERE email=%s", (email,))
        return False


# --------------------------------------------------------------------------
# Threads / messages (tenant-scoped)
# --------------------------------------------------------------------------
# column list shared by the thread selects (incl. SCOPE v3 fields)
_THREAD_COLS = ("id, tenant_id, title, folder_id, visibility, members, "
                "team_id, created_by, created_at::text")


def list_threads(tenant_id: str, is_super: bool = False) -> list[dict]:
    with tenant_tx(tenant_id, is_super) as cur:
        cur.execute(
            f"SELECT {_THREAD_COLS} FROM threads "
            "WHERE tenant_id=%s ORDER BY created_at DESC",
            (tenant_id,),
        )
        return cur.fetchall()


def get_thread(thread_id: str, tenant_id: str, is_super: bool = False) -> dict | None:
    with tenant_tx(tenant_id, is_super) as cur:
        cur.execute(
            f"SELECT {_THREAD_COLS} FROM threads WHERE id=%s",
            (thread_id,),
        )
        return cur.fetchone()


def ensure_thread(
    thread_id: str | None, tenant_id: str, title: str | None = None,
    is_super: bool = False, created_by: str | None = None,
) -> dict:
    if thread_id:
        existing = get_thread(thread_id, tenant_id, is_super)
        if existing:
            return existing
    tid = thread_id or new_id("t")
    with tenant_tx(tenant_id, is_super) as cur:
        cur.execute(
            "INSERT INTO threads (id, tenant_id, title, created_by) VALUES (%s,%s,%s,%s) "
            "ON CONFLICT (id) DO NOTHING",
            (tid, tenant_id, title, created_by),
        )
        cur.execute(
            f"SELECT {_THREAD_COLS} FROM threads WHERE id=%s",
            (tid,),
        )
        return cur.fetchone()


def update_thread(thread_id: str, tenant_id: str, *, title=None, folder_id=...,
                  visibility=None, members=None, team_id=..., is_super: bool = False) -> dict | None:
    """Patch a thread. Sentinel ``...`` on folder_id/team_id means 'leave unchanged'
    (None is a valid value meaning 'clear it')."""
    sets, args = [], []
    if title is not None:
        sets.append("title=%s"); args.append(title)
    if folder_id is not ...:
        sets.append("folder_id=%s"); args.append(folder_id)
    if team_id is not ...:
        sets.append("team_id=%s"); args.append(team_id)
    if visibility is not None:
        vis = visibility if visibility in ("private", "team", "org") else "private"
        sets.append("visibility=%s"); args.append(vis)
    if members is not None:
        norm = sorted({str(e).lower().strip() for e in members if str(e).strip()})
        sets.append("members=%s"); args.append(json.dumps(norm))
    if not sets:
        return get_thread(thread_id, tenant_id, is_super)
    args += [thread_id, tenant_id]
    with tenant_tx(tenant_id, is_super) as cur:
        cur.execute(
            f"UPDATE threads SET {', '.join(sets)} WHERE id=%s AND tenant_id=%s "
            f"RETURNING {_THREAD_COLS}",
            args,
        )
        return cur.fetchone()


def delete_thread(thread_id: str, tenant_id: str, is_super: bool = False) -> bool:
    with tenant_tx(tenant_id, is_super) as cur:
        cur.execute("DELETE FROM messages WHERE thread_id=%s AND tenant_id=%s",
                    (thread_id, tenant_id))
        cur.execute("DELETE FROM threads WHERE id=%s AND tenant_id=%s",
                    (thread_id, tenant_id))
        return cur.rowcount > 0


def add_message(thread_id: str, tenant_id: str, role: str, text: str,
                is_super: bool = False, author: str | None = None) -> dict:
    mid = new_id("m")
    with tenant_tx(tenant_id, is_super) as cur:
        cur.execute(
            "INSERT INTO messages (id, thread_id, tenant_id, role, text, author) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (mid, thread_id, tenant_id, role, text, author),
        )
    return {"id": mid, "thread_id": thread_id, "role": role, "text": text, "author": author}


def get_history(thread_id: str, tenant_id: str, limit: int = 20,
                is_super: bool = False) -> list[dict]:
    with tenant_tx(tenant_id, is_super) as cur:
        cur.execute(
            "SELECT role, text, author FROM messages WHERE thread_id=%s "
            "ORDER BY created_at DESC, id DESC LIMIT %s",
            (thread_id, limit),
        )
        rows = cur.fetchall()
    return [{"role": r["role"], "text": r["text"], "author": r.get("author")}
            for r in reversed(rows)]


# --------------------------------------------------------------------------
# Artifacts (tenant-scoped)
# --------------------------------------------------------------------------
def save_artifact(artifact: dict, tenant_id: str, is_super: bool = False,
                  created_by: str | None = None) -> dict:
    aid = artifact.get("id") or new_id("a")
    rec = {
        "id": aid,
        "kind": artifact.get("kind", "memo"),
        "title": artifact.get("title", ""),
        "markdown": artifact.get("markdown", ""),
        "tenant_id": tenant_id,
        "thread_id": artifact.get("thread_id", ""),
        "created_by": created_by or artifact.get("created_by"),
    }
    with tenant_tx(tenant_id, is_super) as cur:
        cur.execute(
            "INSERT INTO artifacts (id, kind, title, markdown, tenant_id, thread_id, created_by) "
            "VALUES (%(id)s,%(kind)s,%(title)s,%(markdown)s,%(tenant_id)s,%(thread_id)s,%(created_by)s) "
            "ON CONFLICT (id) DO UPDATE SET kind=EXCLUDED.kind, title=EXCLUDED.title, "
            "markdown=EXCLUDED.markdown, thread_id=EXCLUDED.thread_id, "
            # Eigentümer NIE überschreiben (Owner bleibt der Ersteller).
            "created_by=COALESCE(artifacts.created_by, EXCLUDED.created_by) "
            "RETURNING id, kind, title, markdown, tenant_id AS client_id, thread_id, "
            "created_by, created_at::text",
            rec,
        )
        return cur.fetchone()


def list_artifacts(tenant_id: str, thread_id: str | None = None,
                   is_super: bool = False) -> list[dict]:
    q = ("SELECT id, kind, title, markdown, tenant_id AS client_id, thread_id, "
         "created_by, created_at::text FROM artifacts WHERE tenant_id=%s")
    args: list = [tenant_id]
    if thread_id:
        q += " AND thread_id=%s"
        args.append(thread_id)
    q += " ORDER BY created_at DESC"
    with tenant_tx(tenant_id, is_super) as cur:
        cur.execute(q, args)
        return cur.fetchall()


# --------------------------------------------------------------------------
# Agent runs + steps (tenant-scoped, source of truth for E7 agents)
# --------------------------------------------------------------------------
def create_agent_run(tenant_id: str, agent: str, goal: str, plan_steps: list[dict],
                     thread_id: str | None = None, provider: str = "ollama",
                     created_by: str | None = None, is_super: bool = False) -> dict:
    """Legt einen Agenten-Lauf + seine geplanten Schritte an (status=planned)."""
    rid = new_id("run")
    with tenant_tx(tenant_id, is_super) as cur:
        cur.execute(
            "INSERT INTO agent_runs (id, tenant_id, thread_id, agent, goal, status, "
            "provider, plan, created_by) VALUES (%s,%s,%s,%s,%s,'planned',%s,%s,%s)",
            (rid, tenant_id, thread_id, agent, goal, provider,
             json.dumps(plan_steps), created_by),
        )
        steps: list[dict] = []
        for i, st in enumerate(plan_steps):
            sid = new_id("step")
            cur.execute(
                "INSERT INTO agent_steps (id, run_id, tenant_id, idx, title, tool, status) "
                "VALUES (%s,%s,%s,%s,%s,%s,'planned')",
                (sid, rid, tenant_id, i, st.get("title", f"Schritt {i + 1}"), st.get("tool")),
            )
            steps.append({"id": sid, "idx": i, "title": st.get("title", ""),
                          "tool": st.get("tool"), "status": "planned",
                          "summary": None, "provenance": []})
    return {"id": rid, "agent": agent, "goal": goal, "status": "planned",
            "provider": provider, "thread_id": thread_id, "steps": steps}


def update_agent_step(step_id: str, tenant_id: str, status: str,
                      summary: str | None = None, provenance: list | None = None,
                      is_super: bool = False) -> None:
    with tenant_tx(tenant_id, is_super) as cur:
        cur.execute(
            "UPDATE agent_steps SET status=%s, summary=COALESCE(%s, summary), "
            "provenance=COALESCE(%s, provenance), updated_at=now() WHERE id=%s",
            (status, summary,
             json.dumps(provenance) if provenance is not None else None, step_id),
        )


def finish_agent_run(run_id: str, tenant_id: str, status: str,
                     result: str | None = None, artifact_id: str | None = None,
                     is_super: bool = False) -> None:
    with tenant_tx(tenant_id, is_super) as cur:
        cur.execute(
            "UPDATE agent_runs SET status=%s, result=COALESCE(%s, result), "
            "artifact_id=COALESCE(%s, artifact_id), updated_at=now() WHERE id=%s",
            (status, result, artifact_id, run_id),
        )


def set_agent_run_status(run_id: str, tenant_id: str, status: str,
                         is_super: bool = False) -> None:
    with tenant_tx(tenant_id, is_super) as cur:
        cur.execute("UPDATE agent_runs SET status=%s, updated_at=now() WHERE id=%s",
                    (status, run_id))


def _run_steps(cur, run_id: str) -> list[dict]:
    cur.execute(
        "SELECT id, idx, title, tool, status, summary, provenance FROM agent_steps "
        "WHERE run_id=%s ORDER BY idx", (run_id,))
    return [dict(r) for r in cur.fetchall()]


def get_agent_run(run_id: str, tenant_id: str, is_super: bool = False) -> dict | None:
    with tenant_tx(tenant_id, is_super) as cur:
        cur.execute(
            "SELECT id, thread_id, agent, goal, status, provider, result, artifact_id, "
            "created_by, created_at::text FROM agent_runs WHERE id=%s", (run_id,))
        run = cur.fetchone()
        if not run:
            return None
        run = dict(run)
        run["steps"] = _run_steps(cur, run_id)
    return run


def list_agent_runs(tenant_id: str, thread_id: str | None = None,
                    is_super: bool = False) -> list[dict]:
    q = ("SELECT id, thread_id, agent, goal, status, provider, artifact_id, "
         "created_by, created_at::text FROM agent_runs WHERE tenant_id=%s")
    args: list = [tenant_id]
    if thread_id:
        q += " AND thread_id=%s"
        args.append(thread_id)
    q += " ORDER BY created_at DESC LIMIT 50"
    with tenant_tx(tenant_id, is_super) as cur:
        cur.execute(q, args)
        runs = [dict(r) for r in cur.fetchall()]
        for r in runs:
            r["steps"] = _run_steps(cur, r["id"])
    return runs


# --------------------------------------------------------------------------
# Shares (tenant-scoped)
# --------------------------------------------------------------------------
def create_share(thread_id: str, tenant_id: str, role: str = "viewer",
                 is_super: bool = False) -> dict:
    role = role if role in ("viewer", "editor") else "viewer"
    token = new_id("shr")
    with tenant_tx(tenant_id, is_super) as cur:
        cur.execute(
            "INSERT INTO shares (token, thread_id, tenant_id, role) VALUES (%s,%s,%s,%s)",
            (token, thread_id, tenant_id, role),
        )
    return {"token": token, "thread_id": thread_id, "role": role}


def resolve_share(token: str) -> dict | None:
    """Resolve a share token (public-ish; carries its own tenant for scoping)."""
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            "SELECT token, thread_id, tenant_id, role, created_at::text "
            "FROM shares WHERE token=%s",
            (token,),
        )
        return cur.fetchone()


# --------------------------------------------------------------------------
# Promotions (Admin proposes market-ingest → Super-Admin decides)
# --------------------------------------------------------------------------
def create_promotion(source_id: str, tenant_id: str, requested_by: str,
                     levels: list[str], note: str | None = None,
                     is_super: bool = False) -> dict:
    pid = new_id("pr")
    with tenant_tx(tenant_id, is_super) as cur:
        cur.execute(
            "INSERT INTO promotions (id, source_id, tenant_id, requested_by, levels, note) "
            "VALUES (%s,%s,%s,%s,%s,%s) "
            "RETURNING id, source_id, tenant_id, status, requested_by, decided_by, "
            "levels, note, created_at::text, decided_at::text",
            (pid, source_id, tenant_id, requested_by, json.dumps(levels), note),
        )
        return cur.fetchone()


def list_promotions(tenant_id: str | None = None, status: str | None = None,
                    is_super: bool = False) -> list[dict]:
    """Super-admin lists all (is_super=True, tenant_id ignored); admin lists own."""
    q = ("SELECT id, source_id, tenant_id, status, requested_by, decided_by, "
         "levels, note, created_at::text, decided_at::text FROM promotions")
    conds, args = [], []
    if not is_super and tenant_id:
        conds.append("tenant_id=%s")
        args.append(tenant_id)
    if status:
        conds.append("status=%s")
        args.append(status)
    if conds:
        q += " WHERE " + " AND ".join(conds)
    q += " ORDER BY created_at DESC"
    with tenant_tx(tenant_id, is_super) as cur:
        cur.execute(q, args)
        return cur.fetchall()


def get_promotion(promotion_id: str, is_super: bool = True) -> dict | None:
    with tenant_tx(None, is_super) as cur:
        cur.execute(
            "SELECT id, source_id, tenant_id, status, requested_by, decided_by, "
            "levels, note, created_at::text, decided_at::text "
            "FROM promotions WHERE id=%s",
            (promotion_id,),
        )
        return cur.fetchone()


def decide_promotion(promotion_id: str, status: str, decided_by: str,
                     is_super: bool = True) -> dict | None:
    with tenant_tx(None, is_super) as cur:
        cur.execute(
            "UPDATE promotions SET status=%s, decided_by=%s, decided_at=now() "
            "WHERE id=%s AND status='pending' "
            "RETURNING id, source_id, tenant_id, status, requested_by, decided_by, "
            "levels, note, created_at::text, decided_at::text",
            (status, decided_by, promotion_id),
        )
        return cur.fetchone()


# --------------------------------------------------------------------------
# Role helpers (recipient resolution for notifications)
# --------------------------------------------------------------------------
def emails_with_role(role: str, tenant_id: str | None = None) -> list[str]:
    """Emails of users holding ``role``. super_admin is resolved globally
    (platform-wide); every other role is scoped to ``tenant_id``."""
    with _conn() as c, c.cursor() as cur:
        if role == "super_admin":
            cur.execute(
                "SELECT DISTINCT u.email FROM memberships m "
                "JOIN users u ON u.id=m.user_id WHERE m.role='super_admin'"
            )
        else:
            cur.execute(
                "SELECT DISTINCT u.email FROM memberships m "
                "JOIN users u ON u.id=m.user_id WHERE m.role=%s AND m.tenant_id=%s",
                (role, tenant_id),
            )
        return [r["email"] for r in cur.fetchall()]


# --------------------------------------------------------------------------
# Folders (tenant-scoped)
# --------------------------------------------------------------------------
_FOLDER_COLS = "id, tenant_id, name, created_by, created_at::text"


def list_folders(tenant_id: str, is_super: bool = False) -> list[dict]:
    with tenant_tx(tenant_id, is_super) as cur:
        cur.execute(
            f"SELECT {_FOLDER_COLS} FROM folders WHERE tenant_id=%s ORDER BY created_at",
            (tenant_id,),
        )
        return cur.fetchall()


def create_folder(tenant_id: str, name: str, created_by: str,
                  is_super: bool = False) -> dict:
    fid = new_id("fld")
    with tenant_tx(tenant_id, is_super) as cur:
        cur.execute(
            "INSERT INTO folders (id, tenant_id, name, created_by) VALUES (%s,%s,%s,%s) "
            f"RETURNING {_FOLDER_COLS}",
            (fid, tenant_id, name, created_by),
        )
        return cur.fetchone()


def rename_folder(folder_id: str, tenant_id: str, name: str,
                  is_super: bool = False) -> dict | None:
    with tenant_tx(tenant_id, is_super) as cur:
        cur.execute(
            "UPDATE folders SET name=%s WHERE id=%s AND tenant_id=%s "
            f"RETURNING {_FOLDER_COLS}",
            (name, folder_id, tenant_id),
        )
        return cur.fetchone()


def delete_folder(folder_id: str, tenant_id: str, is_super: bool = False) -> bool:
    """Delete a folder; contained threads fall back to folder_id=NULL."""
    with tenant_tx(tenant_id, is_super) as cur:
        cur.execute(
            "UPDATE threads SET folder_id=NULL WHERE folder_id=%s AND tenant_id=%s",
            (folder_id, tenant_id),
        )
        cur.execute("DELETE FROM folders WHERE id=%s AND tenant_id=%s",
                    (folder_id, tenant_id))
        return cur.rowcount > 0


# --------------------------------------------------------------------------
# Notifications (recipient-scoped — a user reads their own, across tenants)
# --------------------------------------------------------------------------
_NOTIF_COLS = ("id, tenant_id, recipient_email, type, title, body, from_email, "
               "thread_id, data, read, created_at::text")


def create_notification(tenant_id: str, recipient_email: str, ntype: str,
                        title: str = "", body: str = "", from_email: str | None = None,
                        thread_id: str | None = None, data: dict | None = None) -> dict:
    nid = new_id("ntf")
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            "INSERT INTO notifications (id, tenant_id, recipient_email, type, title, "
            "body, from_email, thread_id, data) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            f"RETURNING {_NOTIF_COLS}",
            (nid, tenant_id, recipient_email.lower().strip(), ntype, title, body,
             from_email, thread_id, json.dumps(data or {})),
        )
        return cur.fetchone()


def notify_many(recipients: list[str], **kwargs) -> int:
    n = 0
    for email in {e.lower().strip() for e in recipients if e}:
        create_notification(recipient_email=email, **kwargs)
        n += 1
    return n


def list_notifications(recipient_email: str, limit: int = 100) -> list[dict]:
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            f"SELECT {_NOTIF_COLS} FROM notifications WHERE recipient_email=%s "
            "ORDER BY created_at DESC LIMIT %s",
            (recipient_email.lower().strip(), limit),
        )
        return cur.fetchall()


def count_unread(recipient_email: str) -> int:
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM notifications "
            "WHERE recipient_email=%s AND read=false",
            (recipient_email.lower().strip(),),
        )
        return int(cur.fetchone()["n"])


def mark_notification_read(notif_id: str, recipient_email: str) -> bool:
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            "UPDATE notifications SET read=true WHERE id=%s AND recipient_email=%s",
            (notif_id, recipient_email.lower().strip()),
        )
        return cur.rowcount > 0


def mark_all_notifications_read(recipient_email: str) -> int:
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            "UPDATE notifications SET read=true "
            "WHERE recipient_email=%s AND read=false",
            (recipient_email.lower().strip(),),
        )
        return cur.rowcount


# --------------------------------------------------------------------------
# Data-requests / escalation (tenant-scoped)
# --------------------------------------------------------------------------
_DR_COLS = ("id, tenant_id, scope, note, connector, requested_by, target_role, "
            "status, decided_by, created_at::text, decided_at::text")


def create_data_request(tenant_id: str, scope: str, note: str | None,
                        connector: str | None, requested_by: str, target_role: str,
                        is_super: bool = False) -> dict:
    did = new_id("dr")
    with tenant_tx(tenant_id, is_super) as cur:
        cur.execute(
            "INSERT INTO data_requests (id, tenant_id, scope, note, connector, "
            "requested_by, target_role) VALUES (%s,%s,%s,%s,%s,%s,%s) "
            f"RETURNING {_DR_COLS}",
            (did, tenant_id, scope, note, connector, requested_by, target_role),
        )
        return cur.fetchone()


def list_data_requests(tenant_id: str, role: str, email: str,
                       is_super: bool = False) -> list[dict]:
    """Role-filtered: a user sees requests addressed to their role (super_admin
    globally, others in their tenant) plus their own requests."""
    with tenant_tx(None if is_super else tenant_id, is_super) as cur:
        cur.execute(
            f"SELECT {_DR_COLS} FROM data_requests "
            "WHERE target_role=%s OR requested_by=%s "
            "ORDER BY created_at DESC",
            (role, email.lower().strip()),
        )
        return cur.fetchall()


def get_data_request(request_id: str, is_super: bool = True) -> dict | None:
    with tenant_tx(None, is_super) as cur:
        cur.execute(f"SELECT {_DR_COLS} FROM data_requests WHERE id=%s", (request_id,))
        return cur.fetchone()


def decide_data_request(request_id: str, status: str, decided_by: str,
                        is_super: bool = True) -> dict | None:
    with tenant_tx(None, is_super) as cur:
        cur.execute(
            "UPDATE data_requests SET status=%s, decided_by=%s, decided_at=now() "
            "WHERE id=%s AND status='pending' "
            f"RETURNING {_DR_COLS}",
            (status, decided_by, request_id),
        )
        return cur.fetchone()


# --------------------------------------------------------------------------
# Google connector tokens (SCOPE v3)
# --------------------------------------------------------------------------
# Lightweight symmetric obfuscation using only the stdlib (hashlib+hmac+base64
# keystream XOR). This is NOT a substitute for a KMS-backed secret box, but it
# keeps OAuth tokens from sitting in the DB in cleartext once a secret exists,
# without adding a crypto dependency. Format: ``enc1:<nonce_b64>:<ct_b64>``.
# When no secret is configured tokens are stored as ``plain:<value>``.
_TOKEN_SECRET = (
    os.getenv("ENCRYPTION_SECRET") or os.getenv("AUTH_SECRET") or ""
).encode("utf-8")


def _keystream(nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        out.extend(
            hmac.new(_TOKEN_SECRET, nonce + counter.to_bytes(4, "big"),
                     hashlib.sha256).digest()
        )
        counter += 1
    return bytes(out[:length])


def _enc_token(value: str | None) -> str | None:
    if value is None:
        return None
    if not _TOKEN_SECRET:
        # TODO: no ENCRYPTION_SECRET/AUTH_SECRET set — token stored in cleartext.
        return "plain:" + value
    raw = value.encode("utf-8")
    nonce = os.urandom(16)
    ct = bytes(a ^ b for a, b in zip(raw, _keystream(nonce, len(raw))))
    return "enc1:" + base64.urlsafe_b64encode(nonce).decode() + ":" \
        + base64.urlsafe_b64encode(ct).decode()


def _dec_token(stored: str | None) -> str | None:
    if stored is None:
        return None
    if stored.startswith("plain:"):
        return stored[len("plain:"):]
    if stored.startswith("enc1:"):
        if not _TOKEN_SECRET:
            return None
        try:
            _, nb, cb = stored.split(":", 2)
            nonce = base64.urlsafe_b64decode(nb)
            ct = base64.urlsafe_b64decode(cb)
            return bytes(a ^ b for a, b in zip(ct, _keystream(nonce, len(ct)))).decode("utf-8")
        except Exception:  # noqa: BLE001
            return None
    return stored  # legacy/unmarked cleartext


def save_google_tokens(tenant_id: str, user_email: str, *,
                       access_token: str | None,
                       refresh_token: str | None = None,
                       token_type: str | None = None,
                       scope: str | None = None,
                       expiry: int | None = None) -> None:
    """Upsert Google OAuth tokens for (tenant, user). A missing refresh_token
    (as on a refresh-grant response) preserves the previously stored one."""
    user_email = (user_email or "").lower().strip()
    with _conn() as c, c.cursor() as cur:
        if refresh_token:
            enc_refresh = _enc_token(refresh_token)
        else:
            cur.execute(
                "SELECT refresh_token FROM google_tokens "
                "WHERE tenant_id=%s AND user_email=%s",
                (tenant_id, user_email),
            )
            prev = cur.fetchone()
            enc_refresh = prev["refresh_token"] if prev else None
        cur.execute(
            """
            INSERT INTO google_tokens
                (tenant_id, user_email, access_token, refresh_token,
                 token_type, scope, expiry, created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s, now(), now())
            ON CONFLICT (tenant_id, user_email) DO UPDATE SET
                access_token  = EXCLUDED.access_token,
                refresh_token = EXCLUDED.refresh_token,
                token_type    = EXCLUDED.token_type,
                scope         = EXCLUDED.scope,
                expiry        = EXCLUDED.expiry,
                updated_at    = now()
            """,
            (tenant_id, user_email, _enc_token(access_token), enc_refresh,
             token_type, scope, expiry),
        )


def get_google_tokens(tenant_id: str, user_email: str) -> dict | None:
    """Return the decrypted token row for (tenant, user), or None."""
    user_email = (user_email or "").lower().strip()
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            "SELECT tenant_id, user_email, access_token, refresh_token, "
            "token_type, scope, expiry, created_at::text, updated_at::text "
            "FROM google_tokens WHERE tenant_id=%s AND user_email=%s",
            (tenant_id, user_email),
        )
        row = cur.fetchone()
    if not row:
        return None
    row["access_token"] = _dec_token(row.get("access_token"))
    row["refresh_token"] = _dec_token(row.get("refresh_token"))
    return row


def delete_google_tokens(tenant_id: str, user_email: str) -> bool:
    """Remove the stored Google tokens for (tenant, user). Returns True if a row was deleted."""
    user_email = (user_email or "").lower().strip()
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            "DELETE FROM google_tokens WHERE tenant_id=%s AND user_email=%s",
            (tenant_id, user_email),
        )
        return cur.rowcount > 0


# ---- Microsoft (Outlook/Graph) OAuth-Tokens — parallel zu google_tokens ----
def save_microsoft_tokens(tenant_id: str, user_email: str, *,
                          access_token: str | None,
                          refresh_token: str | None = None,
                          token_type: str | None = None,
                          scope: str | None = None,
                          expiry: int | None = None) -> None:
    user_email = (user_email or "").lower().strip()
    with _conn() as c, c.cursor() as cur:
        if refresh_token:
            enc_refresh = _enc_token(refresh_token)
        else:
            cur.execute("SELECT refresh_token FROM microsoft_tokens "
                        "WHERE tenant_id=%s AND user_email=%s", (tenant_id, user_email))
            prev = cur.fetchone()
            enc_refresh = prev["refresh_token"] if prev else None
        cur.execute(
            """
            INSERT INTO microsoft_tokens
                (tenant_id, user_email, access_token, refresh_token,
                 token_type, scope, expiry, created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s, now(), now())
            ON CONFLICT (tenant_id, user_email) DO UPDATE SET
                access_token  = EXCLUDED.access_token,
                refresh_token = EXCLUDED.refresh_token,
                token_type    = EXCLUDED.token_type,
                scope         = EXCLUDED.scope,
                expiry        = EXCLUDED.expiry,
                updated_at    = now()
            """,
            (tenant_id, user_email, _enc_token(access_token), enc_refresh,
             token_type, scope, expiry),
        )


def get_microsoft_tokens(tenant_id: str, user_email: str) -> dict | None:
    user_email = (user_email or "").lower().strip()
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            "SELECT tenant_id, user_email, access_token, refresh_token, "
            "token_type, scope, expiry, created_at::text, updated_at::text "
            "FROM microsoft_tokens WHERE tenant_id=%s AND user_email=%s",
            (tenant_id, user_email),
        )
        row = cur.fetchone()
    if not row:
        return None
    row["access_token"] = _dec_token(row.get("access_token"))
    row["refresh_token"] = _dec_token(row.get("refresh_token"))
    return row


def delete_microsoft_tokens(tenant_id: str, user_email: str) -> bool:
    user_email = (user_email or "").lower().strip()
    with _conn() as c, c.cursor() as cur:
        cur.execute("DELETE FROM microsoft_tokens WHERE tenant_id=%s AND user_email=%s",
                    (tenant_id, user_email))
        return cur.rowcount > 0


# --- Owner-Org-Setup (Launch-Wizard) -----------------------------------------
def get_tenant_setup(tenant_id: str, is_super: bool = False, workspace: str | None = None) -> dict:
    """Setup-Record je (Tenant, Workspace). workspace=None → tenant-weit (dediziert).
    RLS bleibt tenant_id-scoped; die Zeile wird zusätzlich nach workspace gefiltert."""
    ws = workspace or tenant_id
    with tenant_tx(tenant_id, is_super) as cur:
        cur.execute("SELECT data, completed, updated_at FROM tenant_setup "
                    "WHERE tenant_id=%s AND workspace=%s", (tenant_id, ws))
        row = cur.fetchone()
    if not row:
        return {"completed": False, "org_profile": "", "sources": [], "updated_at": None}
    data = row.get("data") or {}
    return {"completed": bool(row.get("completed")),
            "org_name": data.get("org_name", ""),
            "org_profile": data.get("org_profile", ""),
            "sources": data.get("sources", []),
            "updated_at": row.get("updated_at").isoformat() if row.get("updated_at") else None}


def save_tenant_setup(tenant_id: str, *, org_name: str, org_profile: str, sources: list,
                      completed: bool, updated_by: str, is_super: bool = False,
                      workspace: str | None = None) -> dict:
    """Upsert des Setup-Records je (Tenant, Workspace). workspace=None → tenant-weit."""
    import json as _json
    ws = workspace or tenant_id
    payload = _json.dumps({"org_name": org_name or "", "org_profile": org_profile or "",
                           "sources": sources or []})
    with tenant_tx(tenant_id, is_super) as cur:
        cur.execute(
            """INSERT INTO tenant_setup (tenant_id, workspace, data, completed, updated_by, updated_at)
               VALUES (%s, %s, %s::jsonb, %s, %s, now())
               ON CONFLICT (tenant_id, workspace) DO UPDATE
                 SET data=EXCLUDED.data, completed=EXCLUDED.completed,
                     updated_by=EXCLUDED.updated_by, updated_at=now()
               RETURNING data, completed, updated_at""",
            (tenant_id, ws, payload, completed, updated_by),
        )
        row = cur.fetchone()
    data = row.get("data") or {}
    return {"completed": bool(row.get("completed")),
            "org_name": data.get("org_name", ""),
            "org_profile": data.get("org_profile", ""),
            "sources": data.get("sources", []),
            "updated_at": row.get("updated_at").isoformat() if row.get("updated_at") else None}


# --- Entitlements (Monetarisierung: NENA-Intel + Tier) -----------------------
def get_entitlement(tenant_id: str) -> dict:
    """→ {intel, tier, stripe_customer}. Default: free / kein Intel."""
    with _conn() as c, c.cursor() as cur:
        cur.execute("SELECT intel, tier, stripe_customer FROM tenant_entitlements WHERE tenant_id=%s",
                    (tenant_id,))
        row = cur.fetchone()
    if not row:
        return {"intel": False, "tier": "free", "stripe_customer": None}
    return {"intel": bool(row.get("intel")), "tier": row.get("tier") or "free",
            "stripe_customer": row.get("stripe_customer")}


def set_entitlement(tenant_id: str, *, intel: bool, tier: str,
                    stripe_customer: str | None = None) -> dict:
    """Upsert (vom Billing-Webhook). Schaltet NENA + Tier je Tenant."""
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            """INSERT INTO tenant_entitlements (tenant_id, intel, tier, stripe_customer, updated_at)
               VALUES (%s,%s,%s,%s, now())
               ON CONFLICT (tenant_id) DO UPDATE
                 SET intel=EXCLUDED.intel, tier=EXCLUDED.tier,
                     stripe_customer=COALESCE(EXCLUDED.stripe_customer, tenant_entitlements.stripe_customer),
                     updated_at=now()
               RETURNING intel, tier, stripe_customer""",
            (tenant_id, intel, tier, stripe_customer),
        )
        row = cur.fetchone()
    return {"intel": bool(row.get("intel")), "tier": row.get("tier"),
            "stripe_customer": row.get("stripe_customer")}
