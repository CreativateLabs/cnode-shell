"""client_id → NEN-AI group_id Auflösung (TenantContext-aware).

Drei-Ebenen-Wissensgraph:
  • client — der TENANT-eigene, ontologie-basierte Graph. Primär durch die tenant.yaml
    (`graph.group_id`) bestimmt; fehlt sie, greift die bekannte Alias-Tabelle.
  • market — geteilte, kuratierte Market-Intelligence. Für ALLE Tenants identisch.
  • mesh   — tenant-unabhängiger, globaler Mesh (general/market intel), self-learning.

Market + Mesh sind die GLOBALEN Ebenen (read für alle Tenants); der client-Graph ist
je Tenant isoliert.
"""
from __future__ import annotations

# --- Globale, geteilte Ebenen (für alle Tenants gleich) ---------------------
MARKET_GROUP = "market"
MESH_GROUP = "mesh"

# Basis-Aliase/Groups (verifizierte NEN-AI-Groups). Der eigene Tenant-Group wird
# unten aus dem TenantContext ergänzt.
_BASE_KNOWN = {"cnode", "creativate"}
ALIASES = {}


def _tenant_ctx() -> tuple[str | None, str | None]:
    """(tenant_id, group_id) dieses Deployments aus tenant.yaml. Offline-sicher → (None,None)."""
    try:
        from tenant_core import load_default  # via PYTHONPATH (compose-Overlay)

        ctx = load_default()
        return ctx.id or None, (ctx.spec.graph.group_id or ctx.id) or None
    except Exception:
        return None, None


TENANT_ID, TENANT_GROUP = _tenant_ctx()


def _tenant_domains() -> list[dict]:
    """Aktive Domänen-Services dieses Tenants (funding/sales/legal …) aus tenant.yaml.
    Jede: {id, base_url, layer}. Offline-sicher → []."""
    try:
        from tenant_core import load_default

        ctx = load_default()
        return [
            {"id": d.id, "base_url": d.base_url.rstrip("/"), "layer": d.layer}
            for d in (ctx.spec.domains or [])
            if getattr(d, "enabled", True)
        ]
    except Exception:
        return []


TENANT_DOMAINS = _tenant_domains()

KNOWN_GROUPS = set(_BASE_KNOWN)
if TENANT_GROUP:
    KNOWN_GROUPS.add(TENANT_GROUP)
# Tenant-eigene id (Client) → ihr group_id (z.B. tenant → group), damit der
# Shell-Client_id korrekt in den Tenant-Graph auflöst.
if TENANT_ID and TENANT_GROUP:
    ALIASES[TENANT_ID] = TENANT_GROUP

# Default-Group = der Graph DIESES Tenant-Deployments (Fallback: creativate).
# So landet ein leerer/unbekannter client_id im eigenen Tenant-Graph, nicht in einem fremden.
DEFAULT_GROUP = TENANT_GROUP or "creativate"


import re as _re


def map_client_to_group(client_id: str | None) -> str:
    """client_id → gültige NEN-AI group_id (offline-sicher, tenant-aware).

    `ws:<name>` ist ein EXPLIZIT isolierter Workspace-Namespace (Sandbox: pro-User-
    Gedächtnis). Der Rest von `<name>` wird zu einem eigenen, stabilen group_id sanitisiert
    — so bekommt jeder Sandbox-User seinen eigenen Graph (RLS-/group-isoliert), statt in den
    DEFAULT_GROUP zu fallen. Unbekannte Nicht-`ws:`-client_ids bleiben wie gehabt DEFAULT_GROUP."""
    if not client_id:
        return DEFAULT_GROUP
    cid = client_id.strip().lower()
    if cid.startswith("ws:"):
        g = _re.sub(r"[^a-z0-9_-]+", "-", cid[3:]).strip("-")[:64]
        return g or DEFAULT_GROUP
    if cid in ALIASES:
        return ALIASES[cid]
    if cid in KNOWN_GROUPS:
        return cid
    return DEFAULT_GROUP
