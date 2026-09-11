"""cnode-sdk — Erweiterungs-Contract für Tenant-Extensions.

Ein Tenant ergänzt custom Agents/Connectoren OHNE den Core zu forken: er definiert
Plan-Definitionen über dem bestehenden Werkzeug-Bus und registriert sie per
Entry-Point (Gruppe `cnode.agents` / `cnode.connectors`). Der Core lädt genau die
Extensions, die `tenant.yaml` deklariert.

Wichtig: Extensions dürfen NICHT das Bestätigungs-Gate, Auth oder Kernrouten
umgehen — `action.execute` läuft immer durch den Core.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


# --- Werkzeug-Bus (die vier erlaubten Werkzeuge; vom Core injiziert) ----------
class tools:
    graph_query = "graph.query"       # belegtes Wissen aus dem Graphen
    web_research = "web.research"      # Quellen mit Beleg
    llm_generate = "llm.generate"      # Adapter: API ↔ Ollama
    action_execute = "action.execute"  # NUR mit Bestätigungs-Gate (Core-enforced)


@dataclass
class Step:
    title: str
    tool: str
    prompt: str = ""


def step(title: str, tool: str, prompt: str = "") -> Step:
    return Step(title=title, tool=tool, prompt=prompt)


@dataclass
class Agent:
    """Basisklasse für einen Extension-Agenten. Unterklasse setzt id/name/family/plan."""
    id: str = ""
    name: str = ""
    family: str = "growth"           # growth | funding | comms | assurance | wissen
    description: str = ""
    plan: list[Step] = field(default_factory=list)


@dataclass
class Connector:
    """Basisklasse für einen Extension-Connector (Output-Ziel, z.B. Kunden-CRM)."""
    id: str = ""
    name: str = ""
    kind: str = "webhook"            # webhook | oauth
    execute: Callable | None = None  # wird vom Core hinter dem Gate aufgerufen


__all__ = ["Agent", "Connector", "Step", "step", "tools"]
