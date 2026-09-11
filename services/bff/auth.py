"""Auth & tenancy for the BFF — Magic-Link login + JWT session (SCOPE v2).

The verified JWT is the *only* source of tenant + role. Downstream services
(engine/assets) never see a client_id/role from the request body; the BFF sets
client_id server-side from this context.

Roles: super_admin > admin > member > viewer.
Super-admin may switch the acting tenant via header ``X-Act-As-Tenant`` (or the
``act_as`` query param); all other roles are pinned to their JWT tenant.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import time
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request, Response

import api_keys
import db

AUTH_SECRET = os.getenv("AUTH_SECRET", "dev-insecure-change-me")
JWT_ALG = "HS256"
COOKIE_NAME = os.getenv("SESSION_COOKIE", "cnode_session")
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", str(7 * 24 * 3600)))
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"

# Password hashing — Python stdlib only (no new dependencies).
# Stored format: ``pbkdf2$<iterations>$<salt_hex>$<hash_hex>`` (PBKDF2-HMAC-SHA256).
PBKDF2_ITERATIONS = int(os.getenv("PBKDF2_ITERATIONS", "200000"))


def hash_password(password: str, *, iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2${iterations}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        scheme, iter_s, salt_hex, hash_hex = stored.split("$")
        if scheme != "pbkdf2":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"),
            bytes.fromhex(salt_hex), int(iter_s),
        )
    except (ValueError, TypeError):
        return False
    return secrets.compare_digest(dk.hex(), hash_hex)

# --------------------------------------------------------------------------
# Permission matrix (governance)
# --------------------------------------------------------------------------
PERMISSIONS: dict[str, set[str]] = {
    "super_admin": {
        "ask", "graph:read", "artifacts:read", "artifacts:write",
        "ingest:client", "ingest:market", "promotions:create",
        "promotions:decide", "tenants:manage", "tenant:admins:manage",
        "members:manage", "settings:manage", "tenant:switch", "teams:manage",
    },
    # Org-Eigentümer: wie admin + org-weite Hoheit (Teams verwalten, Org-Settings/Owner-Rechte).
    # (Epic O — feinere Team-Rechte kommen in O3.)
    "owner": {
        "ask", "graph:read", "artifacts:read", "artifacts:write",
        "ingest:client", "promotions:create",
        "members:manage", "settings:manage", "teams:manage",
    },
    "admin": {
        "ask", "graph:read", "artifacts:read", "artifacts:write",
        "ingest:client", "promotions:create",
        "members:manage", "settings:manage", "teams:manage",
    },
    "member": {
        "ask", "graph:read", "artifacts:read", "artifacts:write",
        "ingest:client",
    },
    "viewer": {
        "graph:read", "artifacts:read",
    },
}


def permissions_for(role: str) -> list[str]:
    return sorted(PERMISSIONS.get(role, set()))


def has_perm(role: str, perm: str) -> bool:
    return perm in PERMISSIONS.get(role, set())


# --------------------------------------------------------------------------
# JWT
# --------------------------------------------------------------------------
def issue_jwt(user_id: str, email: str, tenant_id: str, role: str) -> str:
    payload = {
        "user_id": user_id,
        "email": email,
        "tenant_id": tenant_id,
        "role": role,
        "iat": int(time.time()),
        "exp": int(time.time()) + SESSION_TTL_SECONDS,
    }
    return jwt.encode(payload, AUTH_SECRET, algorithm=JWT_ALG)


def decode_jwt(token: str) -> dict:
    return jwt.decode(token, AUTH_SECRET, algorithms=[JWT_ALG])


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        max_age=SESSION_TTL_SECONDS,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    # Löschung MUSS die Set-Attribute spiegeln (secure/samesite/path), sonst lassen
    # moderne Browser das Cookie stehen → „ausgeloggt, aber noch eingeloggt".
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        secure=COOKIE_SECURE,
        samesite="lax",
        httponly=True,
    )


# --------------------------------------------------------------------------
# Identity (resolved per-request from the verified JWT)
# --------------------------------------------------------------------------
@dataclass
class Identity:
    user_id: str
    email: str
    role: str
    tenant_id: str          # effective tenant (may be an act-as override)
    home_tenant_id: str     # tenant from the JWT
    acting_as: bool = False

    @property
    def is_super(self) -> bool:
        return self.role == "super_admin"


def _extract_token(request: Request) -> str | None:
    tok = request.cookies.get(COOKIE_NAME)
    if tok:
        return tok
    # allow Bearer for API clients / tests
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def current_identity(request: Request) -> Identity:
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="not authenticated")
    try:
        claims = decode_jwt(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="session expired")
    except jwt.PyJWTError:
        # Cloud-API: langlebiger Service-Key statt JWT? Auf die Instanz-Org gebunden.
        meta = api_keys.resolve_api_key(token)
        if not meta:
            raise HTTPException(status_code=401, detail="invalid session")
        deployment = os.getenv("TENANT_ID", "").strip() or "cnode"
        label = meta["label"]
        return Identity(
            user_id=f"apikey:{label}", email=f"apikey:{label}",
            role=meta["role"], tenant_id=deployment, home_tenant_id=deployment,
            acting_as=False,
        )

    role = claims.get("role", "viewer")
    home_tenant = claims.get("tenant_id", "")
    tenant_id = home_tenant
    acting = False

    # Dediziertes Deployment: diese Instanz bedient GENAU eine Org (TENANT_ID). Der
    # effektive Tenant ist immer diese Org — unabhängig vom Home-Tenant des Users (z.B.
    # ein Super-Admin mit Home 'platform'). Sonst landeten Chats/Teams/Graph unter dem
    # falschen Tenant und wären nach Reload „weg" (tenant-scoped Lookup schlägt fehl).
    deployment = os.getenv("TENANT_ID", "").strip()
    if deployment:
        tenant_id = deployment
        acting = deployment != home_tenant
    else:
        # Shared/Multi-Tenant: Super-Admin darf per Header/Query den Tenant wechseln.
        act_as = request.headers.get("x-act-as-tenant") or request.query_params.get("act_as")
        if act_as and role == "super_admin" and act_as != home_tenant:
            if not db.get_tenant(act_as):
                raise HTTPException(status_code=404, detail=f"tenant '{act_as}' not found")
            tenant_id = act_as
            acting = True

    return Identity(
        user_id=claims.get("user_id", ""),
        email=claims.get("email", ""),
        role=role,
        tenant_id=tenant_id,
        home_tenant_id=home_tenant,
        acting_as=acting,
    )


def require_permission(perm: str):
    """Dependency factory enforcing a single permission from the JWT role."""
    def _dep(identity: Identity = Depends(current_identity)) -> Identity:
        if not has_perm(identity.role, perm):
            raise HTTPException(
                status_code=403,
                detail=f"role '{identity.role}' lacks permission '{perm}'",
            )
        return identity
    return _dep


def require_super_admin(identity: Identity = Depends(current_identity)) -> Identity:
    if not identity.is_super:
        raise HTTPException(status_code=403, detail="super-admin only")
    return identity
