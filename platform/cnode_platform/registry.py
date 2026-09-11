"""Plugin-Registry — Discovery, Tenant-Filter, Katalog.

Findet First-Party-Plugins (cnode_platform.plugins.*) und Tenant-/Extension-Plugins
(Python entry-points der Gruppen `cnode.connectors|formats|agents|systems`). Jedes
Plugin-Modul stellt eine Instanz unter `PLUGIN` bereit oder registriert per
entry-point. `for_tenant(ctx)` filtert auf das, was tenant.yaml aktiviert.
"""
from __future__ import annotations

import importlib
import pkgutil
from importlib import metadata
from typing import Any, Iterable

from .contracts import Plugin, PluginKind

_FIRST_PARTY = (
    "cnode_platform.plugins.connectors",
    "cnode_platform.plugins.formats",
    "cnode_platform.plugins.agents",
    "cnode_platform.plugins.systems",
)
_ENTRYPOINT_GROUPS = (
    "cnode.connectors",
    "cnode.formats",
    "cnode.agents",
    "cnode.systems",
)


class PluginRegistry:
    def __init__(self) -> None:
        self._by_id: dict[str, Plugin] = {}

    # --- Registrierung -------------------------------------------------------
    def register(self, plugin: Plugin) -> None:
        mid = plugin.manifest.id
        if mid in self._by_id:
            raise ValueError(f"Plugin-ID doppelt: {mid}")
        self._by_id[mid] = plugin

    def _register_safe(self, plugin: Plugin) -> None:
        try:
            self.register(plugin)
        except Exception:  # defektes Plugin darf den Start nicht kippen
            pass

    # --- Discovery -----------------------------------------------------------
    def discover(self) -> "PluginRegistry":
        self._discover_first_party()
        self._discover_entrypoints()
        return self

    def _discover_first_party(self) -> None:
        for pkg_name in _FIRST_PARTY:
            try:
                pkg = importlib.import_module(pkg_name)
            except Exception:
                continue
            for _f, modname, _p in pkgutil.iter_modules(pkg.__path__):
                try:
                    mod = importlib.import_module(f"{pkg_name}.{modname}")
                except Exception:
                    continue
                plugin = getattr(mod, "PLUGIN", None)
                if plugin is not None and hasattr(plugin, "manifest"):
                    self._register_safe(plugin)
                # Ein Modul darf auch mehrere Plugins liefern (z.B. Katalog-Connectoren)
                for plg in getattr(mod, "PLUGINS", []) or []:
                    if hasattr(plg, "manifest"):
                        self._register_safe(plg)

    def _discover_entrypoints(self) -> None:
        for group in _ENTRYPOINT_GROUPS:
            try:
                eps = metadata.entry_points(group=group)
            except Exception:
                eps = []
            for ep in eps:
                try:
                    obj = ep.load()
                    plugin = obj() if isinstance(obj, type) else obj
                    if hasattr(plugin, "manifest"):
                        self._register_safe(plugin)
                except Exception:
                    continue

    # --- Zugriff -------------------------------------------------------------
    def all(self) -> list[Plugin]:
        return list(self._by_id.values())

    def get(self, plugin_id: str) -> Plugin | None:
        return self._by_id.get(plugin_id)

    def by_kind(self, kind: PluginKind | str) -> list[Plugin]:
        k = kind.value if isinstance(kind, PluginKind) else kind
        return [p for p in self._by_id.values() if p.manifest.kind.value == k]

    def for_tenant(self, ctx: Any) -> list[Plugin]:
        """Nur Plugins, die dieser Tenant aktiviert hat.

        Regeln:
          • connector: aktiv, wenn tenant.connectors[<id>].enabled
          • agent:     aktiv, wenn id in tenant.modules.agents
          • format:    immer aktiv (Ingest-Basis), außer tenant schaltet ab
          • system:    aktiv, wenn als Extension deklariert
        Fällt ctx weg (kein Tenant), gilt alles als aktiv (Dev).
        """
        if ctx is None:
            return self.all()
        spec = getattr(ctx, "spec", None)
        out: list[Plugin] = []
        for p in self._by_id.values():
            m = p.manifest
            if not m.tenant_scoped:
                out.append(p); continue
            if m.kind == PluginKind.connector:
                c = (spec.connectors or {}).get(m.id) if spec else None
                if c and getattr(c, "enabled", False):
                    out.append(p)
            elif m.kind == PluginKind.agent:
                if spec and m.id in (spec.modules.agents or []):
                    out.append(p)
            elif m.kind == PluginKind.format:
                out.append(p)  # Formate sind Ingest-Basis
            elif m.kind == PluginKind.system:
                ext = [e.name for e in (spec.extensions or [])] if spec else []
                if m.id in ext:
                    out.append(p)
        return out

    def catalog(self, ctx: Any = None) -> list[dict]:
        """Für die Shell-Bibliothek: serialisierbarer Überblick der (Tenant-)Plugins."""
        src: Iterable[Plugin] = self.for_tenant(ctx) if ctx is not None else self.all()
        return [
            {"id": p.manifest.id, "kind": p.manifest.kind.value, "name": p.manifest.name,
             "version": p.manifest.version, "description": p.manifest.description,
             "capabilities": p.manifest.capabilities}
            for p in src
        ]


# Prozessweite Standard-Registry (lazy discovered).
_REGISTRY: PluginRegistry | None = None


def registry() -> PluginRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = PluginRegistry().discover()
    return _REGISTRY
