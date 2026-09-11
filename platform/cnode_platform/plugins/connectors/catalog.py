"""Generischer Katalog-Connector — ein config-getriebenes Plugin je Stack-Tool.

Liest die recherchierten API-Metadaten aus `connectors_catalog.CATALOG` und stellt
für jedes Tool eine `Connector`-Instanz bereit. Die Registry entdeckt sie über die
Modul-Variable `PLUGINS` (Liste). So sind alle Connectoren tenant-aktivierbar
(tenant.yaml `connectors.<id>.enabled`), ohne pro Tool eine eigene Datei.

`fetch_sources`:
  • löst das Credential über `auth.secret_ref` (env:/ssm:/vault:) bzw. den vom BFF
    injizierten Per-Tenant-Token auf (`ctx.connector_token(id)`),
  • ruft — sobald ein Token vorliegt und ein `SearchSpec` existiert — die API real ab
    (httpx) und mappt Treffer nach {title, text, url, meta},
  • liefert vertragskonform eine leere Liste, wenn nichts konfiguriert/erreichbar ist.

`push_output` läuft NIE direkt hinaus — Ausgabe erfolgt ausschließlich über das
Core-Bestätigungs-Gate (action.execute), exakt wie bei Gmail/Webhook.
"""
from __future__ import annotations

import os
from typing import Any

from cnode_platform.connectors_catalog import CATALOG, AuthSpec, ConnectorSpec, SearchSpec
from cnode_platform.contracts import Connector, PluginKind, PluginManifest

try:  # httpx ist im Service-Image vorhanden; Registry-Discovery darf ohne es nicht kippen
    import httpx
except Exception:  # pragma: no cover
    httpx = None  # type: ignore


def _resolve_secret(ref: str, ctx: Any, plugin_id: str) -> str | None:
    """Credential auflösen — Refs bleiben Refs, Werte kommen aus der Umgebung/BFF.

    Reihenfolge: per-Tenant-Token vom BFF (ctx) → env:-Ref. `ssm:`/`vault:` werden im
    Betrieb vom Deployment aufgelöst; hier nur env: (Dev/Container)."""
    if ctx is not None:
        getter = getattr(ctx, "connector_token", None)
        if callable(getter):
            try:
                tok = getter(plugin_id)
                if tok:
                    return str(tok)
            except Exception:
                pass
    if not ref:
        return None
    scheme, _, rest = ref.partition(":")
    if scheme == "env":
        return os.getenv(rest)
    # ssm:/vault: → Deployment-Resolver (nicht im Prozess); Dev-Fallback: gleichnamige Env
    return os.getenv(rest) if rest else None


def _dig(obj: Any, path: str) -> Any:
    """Dotted-Path mit optionalem Listen-Index ('a.b.0.c'). Leerer Path → obj."""
    if not path:
        return obj
    cur = obj
    for part in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
                continue
            except (ValueError, IndexError):
                return None
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


class CatalogConnector:
    """Ein Connector, parametrisiert durch einen ConnectorSpec."""

    def __init__(self, spec: ConnectorSpec) -> None:
        self.spec = spec
        cfg: dict = {"api_base": spec.api_base, "docs": spec.docs_url,
                     "auth": spec.auth.kind, "secret_ref": spec.auth.secret_ref}
        if spec.auth.scopes:
            cfg["scopes"] = spec.auth.scopes
        if spec.region_aware:
            cfg["region_aware"] = True
        self.manifest = PluginManifest(
            id=spec.id, kind=PluginKind.connector, name=spec.name,
            description=spec.description or spec.note,
            capabilities=list(spec.capabilities),
            config_schema=cfg, provenance_label=spec.provenance_label or spec.id,
        )

    # --- Auth-Header aufbauen -------------------------------------------------
    def _auth_headers(self, token: str) -> tuple[dict, dict]:
        """→ (headers, query_params). Basic/Bearer/api_key/OAuth teilen sich den Bearer-Pfad;
        Query-Param-Keys (z.B. Pipedrive) gehen in params."""
        a: AuthSpec = self.spec.auth
        headers = dict(a.extra_headers)
        params: dict = {}
        if a.query_param:
            params[a.query_param] = token
        elif a.header:
            headers[a.header] = f"{a.header_prefix}{token}"
        return headers, params

    # --- Input ----------------------------------------------------------------
    def fetch_sources(self, query: str, ctx) -> list[dict]:
        s: SearchSpec | None = self.spec.search
        if s is None or httpx is None or self.spec.auth.kind == "signed" or not self.spec.api_base:
            return []  # kein Read-Endpoint / Signer nötig → vertragskonform leer
        token = _resolve_secret(self.spec.auth.secret_ref, ctx, self.spec.id)
        if not token:
            return []  # nicht konfiguriert (OAuth-Token liegt sonst im BFF)
        base = self.spec.api_base
        if "{" in base:  # host/instance-Platzhalter unaufgelöst → nicht aufrufbar
            return []
        url = base + s.path
        if "{" in s.path:
            return []
        headers, params = self._auth_headers(token)
        try:
            with httpx.Client(timeout=15.0) as client:
                if s.method.upper() == "POST":
                    body = self._render_body(s.body_template, query)
                    r = client.post(url, headers=headers, params=params, json=body)
                else:
                    if s.query_param:
                        params[s.query_param] = query
                    r = client.get(url, headers=headers, params=params)
                r.raise_for_status()
                data = r.json()
        except Exception:
            return []
        items = _dig(data, s.result_path)
        if not isinstance(items, list):
            return []
        out: list[dict] = []
        for it in items[:20]:
            title = _dig(it, s.map_title) or ""
            text = _dig(it, s.map_text) if s.map_text else it
            url_v = _dig(it, s.map_url) if s.map_url else ""
            out.append({
                "title": str(title)[:200] or self.spec.name,
                "text": text if isinstance(text, str) else str(text)[:2000],
                "url": str(url_v or ""),
                "meta": {"connector": self.spec.id, "provenance": self.manifest.provenance_label},
            })
        return out

    @staticmethod
    def _render_body(tmpl: dict, q: str) -> dict:
        import json
        return json.loads(json.dumps(tmpl).replace("{q}", q.replace('"', '\\"')))

    # --- Output (nur über das Gate) ------------------------------------------
    def push_output(self, payload: dict, ctx) -> dict:
        return {"ok": False, "detail": "über Bestätigungs-Gate ausführen (action.execute)"}


# Registry entdeckt diese Liste (siehe registry._discover_first_party).
PLUGINS: list[Connector] = [CatalogConnector(spec) for spec in CATALOG]
