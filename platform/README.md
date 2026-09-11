# cNode Plugin-Framework (`cnode_platform`)

Die erweiterbare **Bibliothek** der Plattform: neue Fähigkeiten kommen als **Plugins**
hinzu, ohne die Kernservices anzufassen. Vier Arten:

| Art | Wofür | Contract |
|---|---|---|
| **connector** | Integrationen — Quellen herein (Upload/Fetch), Ergebnisse hinaus | `Connector` |
| **format** | Datenformat-Handler für Ingest (PDF, CSV, DOCX, HTML …) | `FormatHandler` |
| **agent** | neuer Agent als Plan über dem Werkzeug-Bus | `AgentPlugin` |
| **system** | externes System (REST/DB) anbinden | `SystemConnector` |

## Ein Plugin hinzufügen (First-Party)
1. Modul unter `cnode_platform/plugins/<art>/<name>.py` anlegen.
2. Klasse implementieren, `manifest = PluginManifest(...)` setzen.
3. Instanz als Modul-Attribut `PLUGIN = <Instanz>` exportieren.
4. Fertig — die Registry entdeckt es beim Start.

```python
from cnode_platform.contracts import Connector, PluginKind, PluginManifest

class MyConnector:
    manifest = PluginManifest(id="my", kind=PluginKind.connector,
                              name="Mein Connector", capabilities=["input"])
    def fetch_sources(self, query, ctx): return [...]
    def push_output(self, payload, ctx): return {"ok": True}

PLUGIN = MyConnector()
```

## Ein Plugin als Tenant-Extension (ohne Core-Fork)
Im Tenant-Repo ein Paket mit entry-point registrieren:
```toml
[project.entry-points."cnode.connectors"]
my = "my_pkg.connector:MyConnector"
```
`tenant.yaml` aktiviert es (unter `connectors`/`extensions`) — die Registry lädt nur,
was der Tenant aktiviert hat.

## Nutzung im Service
```python
from cnode_platform import registry
cat = registry().catalog(tenant_ctx)      # für die Shell-Bibliothek
formats = registry().by_kind("format")     # z.B. beim Upload passenden Handler wählen
```

## Regeln
- Plugins umgehen **nie** Provenienz, Auth oder das Bestätigungs-Gate — `action.execute`
  und Output-Connectoren laufen immer durch den Core.
- Aktivierung ist **pro Tenant** (`tenant_scoped=True`), außer echte Ingest-Basis (Formate).
