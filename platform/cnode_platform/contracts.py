"""Plugin-Contracts der cNode-Plattform.

Die erweiterbare „Bibliothek": neue Fähigkeiten werden als Plugins ergänzt, ohne
Kernservices anzufassen. Vier Arten:

  • connector — Integrationen: Quellen herein (Upload/Fetch) und/oder Ergebnisse hinaus
  • format    — Datenformat-Handler für Ingest (PDF, CSV, DOCX, HTML, …)
  • agent     — Agenten-Plan über dem Werkzeug-Bus (graph/web/llm/action)
  • system    — externes System (REST-API, DB), das angebunden wird

Jedes Plugin trägt ein `PluginManifest` und implementiert das zu seiner Art
gehörige Protocol. Aktivierung erfolgt pro Tenant (tenant.yaml). Der Kern erzwingt
weiterhin Provenienz, Auth und das Bestätigungs-Gate — Plugins umgehen das nie.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class PluginKind(str, Enum):
    connector = "connector"
    format = "format"
    agent = "agent"
    system = "system"


@dataclass
class PluginManifest:
    id: str                              # eindeutig, kebab-case (z.B. "gmail")
    kind: PluginKind
    name: str
    version: str = "0.1.0"
    description: str = ""
    capabilities: list[str] = field(default_factory=list)   # z.B. ["input","output","oauth"]
    tenant_scoped: bool = True           # per Tenant aktivierbar (Default)
    config_schema: dict = field(default_factory=dict)        # optionale JSON-Schema-Hints
    provenance_label: str = ""           # Quelle-Label für belegte Antworten


@runtime_checkable
class Plugin(Protocol):
    manifest: PluginManifest


@runtime_checkable
class Connector(Protocol):
    """Integration. `input`-Connectoren liefern Quellen, `output` senden Ergebnisse.
    Welche Richtung gilt, steht in manifest.capabilities."""
    manifest: PluginManifest

    def fetch_sources(self, query: str, ctx: Any) -> list[dict]:
        """Input: Quellen/Dokumente holen → [{title, text, url, meta}]. Leere Liste, wenn n/a."""
        ...

    def push_output(self, payload: dict, ctx: Any) -> dict:
        """Output: Ergebnis senden (nur hinter Bestätigungs-Gate) → {ok, detail}."""
        ...


@runtime_checkable
class FormatHandler(Protocol):
    """Wandelt ein hochgeladenes Datenformat in Text + Metadaten für den Ingest."""
    manifest: PluginManifest

    def can_handle(self, filename: str, mime: str) -> bool: ...

    def extract(self, data: bytes, filename: str) -> dict:
        """→ {text, meta}. Fehler werfen statt still leer zurückgeben."""
        ...


@runtime_checkable
class AgentPlugin(Protocol):
    """Neuer Agent als Plan über dem Werkzeug-Bus (nutzt cnode_sdk.step/tools)."""
    manifest: PluginManifest

    def plan(self) -> list: ...


@runtime_checkable
class SystemConnector(Protocol):
    """Anbindung eines externen Systems (REST/DB) als abfragbare Quelle."""
    manifest: PluginManifest

    def connect(self, config: dict, ctx: Any) -> None: ...

    def query(self, q: str, ctx: Any) -> list[dict]: ...
