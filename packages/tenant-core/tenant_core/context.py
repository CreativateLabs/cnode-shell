"""TenantContext-Loader — die eine Stelle, die einen Tenant auflöst.

Zwei Quellen, ein Ergebnis (config-driven):
  • Dedicated / On-Prem  → load_from_file("tenant.yaml")
  • Shared / SaaS        → load_from_row(db_row_dict)

Danach lesen alle Services nur noch den validierten `TenantContext`. Secret-Refs
(`env:` / `ssm:` / `vault:`) werden hier zu echten Werten aufgelöst — echte Secrets
stehen NIE in der Config, nur Referenzen.
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

from .schema import TenantSpec


class SecretResolutionError(RuntimeError):
    pass


def _resolve_secret(ref: str) -> str:
    """`env:NAME` | `ssm:/path` | `vault:/path` | `file:/run/secrets/x` → Wert.

    Leerer Ref → "". SSM/Vault sind Platzhalter-Hooks (Deploy-Umgebung liefert sie
    üblicherweise als env), damit derselbe Code lokal und in AWS läuft.
    """
    if not ref:
        return ""
    scheme, _, rest = ref.partition(":")
    if scheme == "env":
        val = os.getenv(rest, "")
    elif scheme == "file":
        p = Path(rest)
        val = p.read_text().strip() if p.exists() else ""
    elif scheme in ("ssm", "vault"):
        # In AWS injiziert die Deploy-Schicht diese als env — hier nur Fallback.
        val = os.getenv(rest.strip("/").replace("/", "_").upper(), "")
    else:
        raise SecretResolutionError(f"unbekanntes Secret-Schema: {scheme}")
    return val


class TenantContext:
    """Read-only Sicht auf einen validierten Tenant + aufgelöste Secrets."""

    def __init__(self, spec: TenantSpec):
        self.spec = spec
        # group_id default = tenant.id, wenn nicht explizit gesetzt.
        if not spec.graph.group_id:
            spec.graph.group_id = spec.tenant.id

    # bequeme Shortcuts
    @property
    def id(self) -> str: return self.spec.tenant.id
    @property
    def name(self) -> str: return self.spec.tenant.name
    @property
    def mode(self) -> str: return self.spec.tenant.mode
    @property
    def group_id(self) -> str: return self.spec.graph.group_id

    def module_enabled(self, kind: str, name: str) -> bool:
        m = self.spec.modules
        pool = getattr(m, kind, None)
        return bool(pool) and name in pool

    def connector_secret(self, provider: str) -> str:
        c = self.spec.connectors.get(provider)
        if not c or not c.enabled:
            return ""
        return _resolve_secret(c.secret_ref)


def load_from_file(path: str | Path) -> TenantContext:
    """Dedicated / On-Prem: die tenant.yaml ist die Wahrheit."""
    data = yaml.safe_load(Path(path).read_text()) or {}
    return TenantContext(TenantSpec.model_validate(data))


def load_from_row(row: dict) -> TenantContext:
    """Shared / SaaS: eine Zeile aus der tenants-Tabelle (gleiches Schema)."""
    return TenantContext(TenantSpec.model_validate(row))


def load_default() -> TenantContext:
    """Bootstrap-Helfer: TENANT_CONFIG (Datei) → sonst Minimal-Default 'cnode'."""
    cfg = os.getenv("TENANT_CONFIG", "")
    if cfg and Path(cfg).exists():
        return load_from_file(cfg)
    return TenantContext(TenantSpec.model_validate({"tenant": {"id": "cnode", "name": "cNode"}}))
