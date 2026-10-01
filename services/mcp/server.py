"""c:node Agents — MCP Server.

Macht die benannten Fach-Agenten (Mara/Jonas/Lena/Viktor/Nora/Ben) als MCP-Skills verfügbar,
mit IDENTISCHEM Verhalten wie die In-App-Fläche: geerdet auf dem c:node Graph, belegt (Provenienz),
mandanten-isoliert, READ-only (WRITE bleibt hinter menschlicher Freigabe).

Dünner, authentifizierter Proxy auf das c:node-BFF — die gesamte Fach-/Beleg-/Isolations-
Logik lebt serverseitig, nicht hier. Auth via langlebigem Service-Key (Bearer → apikey:<label>,
Tenant = Deployment-Org).

Config (env):
  CNODE_BFF_URL   Basis-URL des BFF (Default: http://localhost:8080 = eure eigene Installation;
                  c:node Cloud: https://api.app.c-node.ai)
  CNODE_API_KEY   Service-Key (muss serverseitig in CNODE_API_KEYS registriert sein)
  MCP_TRANSPORT   "stdio" (Default, lokale Clients) | "streamable-http" (Hosting)
  MCP_HOST/MCP_PORT  nur für streamable-http (Default 0.0.0.0:8090)
"""
from __future__ import annotations

import hmac
import os
import re
import sys
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

BFF_URL = os.getenv("CNODE_BFF_URL", "http://localhost:8080").rstrip("/")
API_KEY = os.getenv("CNODE_API_KEY", "").strip()
TIMEOUT = float(os.getenv("CNODE_MCP_TIMEOUT", "150"))

# DNS-Rebinding-Schutz bleibt AN, erlaubt aber den öffentlichen Host/Origin (hinter Caddy).
_hosts = [h.strip() for h in os.getenv(
    "MCP_ALLOWED_HOSTS", "localhost:*,127.0.0.1:*,localhost,127.0.0.1").split(",") if h.strip()]
_origins = [o.strip() for o in os.getenv(
    "MCP_ALLOWED_ORIGINS", "http://localhost:*,http://127.0.0.1:*").split(",") if o.strip()]
# Agent-IDs landen im URL-Pfad des BFF → nur einfache IDs zulassen (kein "../", "?", "%2F" …).
_AGENT_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
mcp = FastMCP("cnode-agents", transport_security=TransportSecuritySettings(
    allowed_hosts=_hosts, allowed_origins=_origins))


def _headers() -> dict[str, str]:
    if not API_KEY:
        raise ConfigError(
            "CNODE_API_KEY ist nicht gesetzt. Lege serverseitig einen Service-Key in "
            "CNODE_API_KEYS an und exportiere ihn hier als CNODE_API_KEY.")
    return {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}


async def _get(path: str) -> Any:
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.get(f"{BFF_URL}{path}", headers=_headers())
        r.raise_for_status()
        return r.json()


async def _post(path: str, body: dict) -> Any:
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.post(f"{BFF_URL}{path}", headers=_headers(), json=body)
        r.raise_for_status()
        return r.json()


class ConfigError(RuntimeError):
    """Lokale Fehlkonfiguration (z. B. fehlender Schlüssel) — kein Verbindungsfehler."""


def _check_agent_id(agent_id: str) -> str | None:
    if not _AGENT_ID.match(agent_id or ""):
        return "Ungültige agent_id — nutze eine ID aus cnode_list_agents (z. B. 'agent-einkauf')."
    return None


def _friendly(exc: Exception) -> str:
    if isinstance(exc, ConfigError):
        return str(exc)
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in (401, 403):
            return ("Auth fehlgeschlagen: CNODE_API_KEY ist ungültig oder nicht in "
                    "CNODE_API_KEYS registriert (Rolle mind. 'member').")
        if code == 404:
            return "Unbekannter/inaktiver Agent — nutze cnode_list_agents für gültige IDs."
        if code == 402:
            return "Feature erfordert ein Upgrade (c:node Graph/Pro) für diesen Mandanten."
        if code == 429:
            return "Sandbox-Limit erreicht — kurz warten und erneut versuchen."
        return f"BFF-Fehler {code}: {exc.response.text[:180]}"
    return f"Verbindungsfehler zum BFF ({BFF_URL}): {exc}"


@mcp.tool(
    annotations={"readOnlyHint": True, "destructiveHint": False,
                 "idempotentHint": True, "openWorldHint": True})
async def cnode_list_agents() -> dict:
    """Listet die verfügbaren c:node-Fach-Agenten (Personas) mit Domäne, Leitfrage und
    Fähigkeiten. Nutze dies, um die richtige agent_id für cnode_ask_agent /
    cnode_consult_agent zu wählen (Auswahl über Domäne, nicht über den Namen)."""
    try:
        data = await _get("/agents/cards")
    except Exception as exc:  # noqa: BLE001
        return {"error": _friendly(exc)}
    agents = [{"agent_id": a["id"], "name": a["name"], "role": a["role"], "domain": a["domain"],
               "trigger_question": a["trigger_question"], "can_do": a["can_do"],
               "status": a["status"]} for a in data.get("agents", [])]
    return {"agents": agents,
            "hint": "status=live ist aufrufbar; roadmap nur informativ. WRITE ist immer gesperrt."}


@mcp.tool(
    annotations={"readOnlyHint": True, "destructiveHint": False,
                 "idempotentHint": True, "openWorldHint": True})
async def cnode_ask_agent(agent_id: str, question: str) -> dict:
    """Fragt EINEN c:node-Fach-Agenten (z. B. 'agent-finanzen'). Der Agent antwortet geerdet
    auf das Mandanten-Gedächtnis (c:node Graph) und liefert Belege (provenance). READ-only.

    agent_id: Agenten-ID aus cnode_list_agents (z. B. 'agent-einkauf').
    question: die fachliche Frage in natürlicher Sprache.
    """
    if bad := _check_agent_id(agent_id):
        return {"error": bad}
    try:
        d = await _post(f"/agents/domain/{agent_id}/ask", {"text": question})
    except Exception as exc:  # noqa: BLE001
        return {"error": _friendly(exc)}
    return {"agent": d["agent"]["name"], "answer": d.get("answer", ""),
            "grounding": d.get("grounding"), "provenance": d.get("provenance", []),
            "write_allowed": d.get("write_allowed", False)}


@mcp.tool(
    annotations={"readOnlyHint": True, "destructiveHint": False,
                 "idempotentHint": True, "openWorldHint": True})
async def cnode_consult_agent(agent_id: str, question: str) -> dict:
    """Startet eine A2A-Konsultation ab einem Primär-Agenten: er zieht bei Bedarf weitere
    Fach-Agenten desselben Mandanten hinzu (Domänen-Discovery aus den belegten Quellen),
    die Provenienz wandert mit, und der Primär-Agent synthetisiert eine Empfehlung. READ-only.

    agent_id: Primär-Agent (z. B. 'agent-einkauf').
    question: die (Leit-)Frage; die Delegation richtet sich nach den gefundenen Fakten.
    """
    if bad := _check_agent_id(agent_id):
        return {"error": bad}
    try:
        d = await _post(f"/agents/domain/{agent_id}/consult", {"text": question})
    except Exception as exc:  # noqa: BLE001
        return {"error": _friendly(exc)}
    return {"agent": d["agent"]["name"], "answer": d.get("answer", ""),
            "consulted": d.get("consulted", []),
            "contributions": d.get("contributions", []),
            "provenance": d.get("provenance", []), "hops": d.get("hops", []),
            "write_allowed": d.get("write_allowed", False), "status": d.get("status")}


def _run_http() -> None:
    """HTTP-Modus: der Server nutzt SEINEN CNODE_API_KEY für jeden Aufrufer. Ohne eigene
    Zugangsprüfung wäre er ein offener Proxy auf euren BFF. Darum: außerhalb von localhost
    nur mit MCP_HTTP_TOKEN (Clients senden `Authorization: Bearer <token>`)."""
    import uvicorn

    host = os.getenv("MCP_HOST", "127.0.0.1")
    port = int(os.getenv("MCP_PORT", "8090"))
    token = os.getenv("MCP_HTTP_TOKEN", "").strip()
    if not token and host not in ("127.0.0.1", "localhost", "::1"):
        sys.exit("MCP_HTTP_TOKEN fehlt: Ohne Token läuft der HTTP-Modus nur auf localhost "
                 "(MCP_HOST=127.0.0.1). Setze MCP_HTTP_TOKEN, um ihn im Netz anzubieten.")
    app = mcp.streamable_http_app()

    async def guarded(scope, receive, send):
        if token and scope["type"] == "http":
            auth = dict(scope.get("headers") or []).get(b"authorization", b"").decode()
            given = auth[7:].strip() if auth[:7].lower() == "bearer " else ""
            if not hmac.compare_digest(given, token):
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json"),
                                        (b"www-authenticate", b"Bearer")]})
                await send({"type": "http.response.body",
                            "body": b'{"error":"unauthorized"}'})
                return
        await app(scope, receive, send)

    uvicorn.run(guarded, host=host, port=port)


def main() -> None:
    transport = os.getenv("MCP_TRANSPORT", "stdio").strip()
    if transport == "streamable-http":
        _run_http()
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
