# c:node Agents — MCP Server

Macht die benannten Fach-Agenten (Mara/Jonas/Lena/Viktor/Nora/Ben) als **MCP-Skills**
verfügbar — gleiches Verhalten wie in-App: geerdet auf dem Wissensgraph-Gedächtnis, belegt (Provenienz),
mandanten-isoliert, **READ-only** (WRITE bleibt hinter menschlicher Freigabe).

Dünner, authentifizierter Proxy auf das c:node-BFF. Die Fach-/Beleg-/Isolations-Logik
lebt serverseitig.

## Tools
| Tool | Zweck |
|---|---|
| `cnode_list_agents` | Verfügbare Personas (Domäne, Leitfrage, Fähigkeiten) — Discovery |
| `cnode_ask_agent(agent_id, question)` | EIN Fach-Agent, geerdet + belegt |
| `cnode_consult_agent(agent_id, question)` | A2A-Kette: Primär-Agent zieht Geschwister hinzu, Provenienz wandert mit, Synthese |

## Auth
Bearer-Service-Key. Serverseitig in `CNODE_API_KEYS` registrieren
(`"label:secret[:role]"`, Rolle ≥ `member`), clientseitig als `CNODE_API_KEY` setzen.
Der Tenant ist immer die Deployment-Org (cnode) — ein Key greift nie darüber hinaus.

## Welche URL?
`CNODE_BFF_URL` zeigt auf den Gateway (BFF), mit dem der MCP-Server spricht:

| Setup | `CNODE_BFF_URL` |
|---|---|
| Eigene Installation (Default, `make sandbox` / `docker compose up`) | `http://localhost:8080` |
| MCP-Server im selben Compose-Netz wie der BFF | `http://bff:8080` |
| c:node Cloud (gehostet, mit c:node Graph) | `https://api.app.c-node.ai` |

## Lokal einbinden (stdio) — Claude Desktop
`claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "cnode-agents": {
      "command": "/ABS/PFAD/venv/bin/python",
      "args": ["/ABS/PFAD/cnode-shell/services/mcp/server.py"],
      "env": {
        "MCP_TRANSPORT": "stdio",
        "CNODE_BFF_URL": "http://localhost:8080",
        "CNODE_API_KEY": "<dein-service-key>"
      }
    }
  }
}
```
Setup einmalig: `python -m venv venv && ./venv/bin/pip install -r requirements.txt`.

## Lokal einbinden — Claude Code (CLI)
```bash
claude mcp add cnode-agents \
  -e MCP_TRANSPORT=stdio \
  -e CNODE_BFF_URL=http://localhost:8080 \
  -e CNODE_API_KEY=<dein-service-key> \
  -- /ABS/PFAD/venv/bin/python /ABS/PFAD/cnode-shell/services/mcp/server.py
```

## Hosten (streamable-http)
Das Dockerfile startet den Server als `streamable-http` auf `:8090`. **Wichtig:** Im HTTP-Modus
nutzt der Server *seinen* `CNODE_API_KEY` für jeden Aufrufer. Damit er kein offener Proxy auf euren
BFF wird, gilt:

- Außerhalb von localhost startet er nur mit **`MCP_HTTP_TOKEN`**. Clients senden dann
  `Authorization: Bearer <MCP_HTTP_TOKEN>`; ohne/mit falschem Token antwortet er mit `401`.
- Ohne Token läuft der HTTP-Modus nur auf `MCP_HOST=127.0.0.1`.
- Schutz gegen DNS-Rebinding ist an: Erlaubte Hosts/Origins per `MCP_ALLOWED_HOSTS` /
  `MCP_ALLOWED_ORIGINS` setzen (Default: localhost), z. B. `mcp.example.com` hinter Caddy
  (`mcp.example.com → 127.0.0.1:8090`).
- `agent_id` wird geprüft (nur `a-z`, `0-9`, `-`, `_`), damit Aufrufe nicht auf andere
  BFF-Endpunkte umgelenkt werden können.
