# cnode-client — Python-Client für die cNode Cloud-API

Schlanker, typisierter Client gegen den cNode-BFF — dieselbe API, die auch die Shell nutzt.
Auth per **API-Key** (Service-Token), der serverseitig auf die Instanz-Org (Tenant) aufgelöst wird.

## Installation

```bash
pip install -e packages/cnode-client        # lokal aus dem Monorepo
# oder später: pip install cnode-client
```

Nur eine Laufzeit-Abhängigkeit: `httpx`.

## Schnellstart

```python
from cnode_client import CNodeClient

# api_key aus Argument oder Umgebung CNODE_API_KEY (nie im Code hartkodieren)
cn = CNodeClient("https://api.cnode.example", api_key="…")

print(cn.health())                       # {"status": "ok", ...}
print(cn.tenant_context()["name"])       # "cNode"

ans = cn.ask("Worauf achten Investoren bei der Bewertung?")
print(ans.text)
for s in ans.sources:                    # belegte Quellen (Provenienz)
    print("·", s.get("title"))

# Orchestrator: Pfad einer Nachricht bestimmen
print(cn.route("Quartals-Report ausfüllen"))     # {"route": "form", "form_id": "...", ...}

# Freitext → geerdete Knoten in den Tenant-Graph (Provenienz erzwungen)
print(cn.capture("Partner ACME GmbH, Ansprechpartnerin Jane Doe (CTO)"))

# Wissensgraph lesen
g = cn.graph(); print(len(g["nodes"]), "Knoten")

# Connector-Bibliothek (29 recherchierte Integrationen)
for c in cn.connectors_catalog():
    print(c["id"], c["auth"], c["enabled"])
```

Async identisch über `AsyncCNodeClient` (alle Methoden awaitable).

## Auth / API-Keys

Der Server (Cloud-Profil) liest API-Keys aus der Umgebung — **nie inline**:

```bash
# label:secret[:role]   — role default "member" (ask + graph:read + artifacts:*)
export CNODE_API_KEYS="sdk:$(openssl rand -hex 24):member"
```

Der Client sendet den Key als `Authorization: Bearer <secret>`. Bei dediziertem Deployment
ist der Tenant immer die Instanz-Org — ein Key kann nie über seinen Tenant hinausgreifen.

## Methoden

| Methode | Endpoint | Zweck |
|---|---|---|
| `health()` | GET `/health` | Erreichbarkeit |
| `tenant_context()` | GET `/tenant/context` | Identität + Branding + Module |
| `ask(text, …)` | POST `/ask` | Belegte, beratende Antwort (3-Ebenen-Graph) → `Answer` |
| `route(text)` | POST `/route` | Orchestrator-Route: form / graph_ingest / graph_display / knowledge / chat |
| `graph()` | GET `/graph` | Subgraph `{nodes, edges}` |
| `capture(text)` | POST `/graph/capture` | Freitext → geerdete Knoten in den Graph |
| `forms()` / `form(id)` | GET `/forms[/id]` | Interaktive Formulare (FraBö) |
| `submit_form(id, …)` | POST `/forms/{id}/submit` | Formular scoren/persistieren |
| `connectors_catalog()` | GET `/connectors/catalog` | Connector-Bibliothek + je Tenant aktiv |
| `plugins()` | GET `/plugins` | Aktive Plugins der Instanz |

Fehler (nicht-2xx) werfen `CNodeError(status, detail)`.
