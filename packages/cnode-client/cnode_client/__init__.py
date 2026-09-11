"""cnode-client — offizieller Python-Client für die cNode Cloud-API.

Schlanker, typisierter Client gegen den cNode-BFF (dieselbe API, die auch die Shell nutzt).
Authentifizierung per **API-Key** (Service-Token) — der Key wird als `Authorization: Bearer`
gesendet und serverseitig auf die Instanz-Org (Tenant) aufgelöst.

    from cnode_client import CNodeClient

    cn = CNodeClient("https://api.cnode.example", api_key="…")   # oder env CNODE_API_KEY
    print(cn.health())
    ans = cn.ask("Worauf achten Investoren bei der Bewertung?")
    print(ans.text)
    for src in ans.sources:
        print("·", src.get("title"), src.get("provenance"))

    # Orchestrator-Route einer Nachricht (form|graph_ingest|knowledge|chat)
    print(cn.route("Quartals-Report ausfüllen"))
    # Freitext → geerdete Knoten in den Tenant-Graph (Provenienz erzwungen)
    print(cn.capture("Partner ACME GmbH, Ansprechpartnerin Jane Doe (CTO)"))

Nur eine Laufzeit-Abhängigkeit: httpx. Secrets kommen als Argument oder aus der Umgebung
(`CNODE_API_KEY`) — nie im Code hartkodiert.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

import httpx

__version__ = "0.1.0"

DEFAULT_TIMEOUT = 120.0


class CNodeError(RuntimeError):
    """API-Fehler (nicht-2xx) inkl. Statuscode + Server-Detail."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"cNode API {status}: {detail}")
        self.status = status
        self.detail = detail


@dataclass
class Answer:
    """Antwort-Envelope von /ask (belegte, beratende Antwort)."""
    text: str = ""
    sources: list[dict] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    layers: dict = field(default_factory=dict)
    provider: str = ""
    model: str = ""
    thread_id: str | None = None
    raw: dict = field(default_factory=dict)

    @classmethod
    def _from(cls, d: dict) -> "Answer":
        return cls(
            text=d.get("result") or d.get("text") or "",
            sources=d.get("sources") or [], trace=d.get("trace") or [],
            suggestions=d.get("suggestions") or [], layers=d.get("layers") or {},
            provider=d.get("provider") or "", model=d.get("model") or "",
            thread_id=d.get("thread_id"), raw=d,
        )


class CNodeClient:
    """Synchroner cNode-Client. Für Async siehe `AsyncCNodeClient` (gleiche Methoden, awaitable)."""

    def __init__(self, base_url: str, api_key: str | None = None,
                 timeout: float = DEFAULT_TIMEOUT, verify: bool = True) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.getenv("CNODE_API_KEY", "")
        headers = {"User-Agent": f"cnode-client/{__version__}"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        self._c = httpx.Client(base_url=self.base_url, headers=headers,
                               timeout=timeout, verify=verify)

    # --- intern ---------------------------------------------------------------
    def _req(self, method: str, path: str, **kw) -> Any:
        r = self._c.request(method, path, **kw)
        if r.status_code >= 400:
            detail = ""
            try:
                detail = r.json().get("detail", r.text)
            except Exception:
                detail = r.text
            raise CNodeError(r.status_code, str(detail)[:500])
        return r.json() if r.content else None

    # --- Meta / Identität ------------------------------------------------------
    def health(self) -> dict:
        return self._req("GET", "/health")

    def tenant_context(self) -> dict:
        """Identität + Branding + aktive Module der Instanz."""
        return self._req("GET", "/tenant/context")

    # --- Chat / Orchestrator ---------------------------------------------------
    def ask(self, text: str, thread_id: str | None = None,
            provider: str | None = None, levels: list[str] | None = None) -> Answer:
        """Belegte, beratende Antwort über den Tenant-Wissensgraphen (drei Ebenen)."""
        body: dict = {"text": text}
        if thread_id:
            body["thread_id"] = thread_id
        if provider:
            body["provider"] = provider
        if levels:
            body["levels"] = levels
        return Answer._from(self._req("POST", "/ask", json=body))

    def route(self, text: str, history: list | None = None) -> dict:
        """Tenant-Orchestrator: Pfad EINER Nachricht → {route, form_id?, method, confidence?}.
        route ∈ {form, graph_ingest, graph_display, knowledge, chat}."""
        return self._req("POST", "/route", json={"text": text, "history": history or []})

    # --- Wissensgraph ----------------------------------------------------------
    def graph(self, client_id: str | None = None) -> dict:
        """Subgraph {nodes, edges} der Instanz für Visualisierung/Analyse."""
        params = {"client_id": client_id} if client_id else None
        return self._req("GET", "/graph", params=params)

    def capture(self, text: str) -> dict:
        """Freitext → geerdete Entitäts-/Relationsextraktion → in den Tenant-Graph.
        Keine Erfindung, Provenienz erzwungen. → {ok, added:[{label,type}], edges, provenance}."""
        return self._req("POST", "/graph/capture", json={"text": text})

    # --- Formulare (FraBö) -----------------------------------------------------
    def forms(self) -> list[dict]:
        return (self._req("GET", "/forms") or {}).get("forms", [])

    def form(self, form_id: str) -> dict:
        return self._req("GET", f"/forms/{form_id}")

    def submit_form(self, form_id: str, *, answers: dict | None = None,
                    values: dict | None = None, subject: str = "",
                    period: str = "", narrative: bool = False) -> dict:
        body: dict = {"narrative": narrative}
        if answers is not None:
            body["answers"] = answers
        if values is not None:
            body["values"] = values
        if subject:
            body["subject"] = subject
        if period:
            body["period"] = period
        return self._req("POST", f"/forms/{form_id}/submit", json=body)

    # --- Connectoren / Plugins -------------------------------------------------
    def connectors_catalog(self) -> list[dict]:
        return (self._req("GET", "/connectors/catalog") or {}).get("connectors", [])

    def plugins(self) -> list[dict]:
        return (self._req("GET", "/plugins") or {}).get("plugins", [])

    # --- Lifecycle -------------------------------------------------------------
    def close(self) -> None:
        self._c.close()

    def __enter__(self) -> "CNodeClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class AsyncCNodeClient:
    """Async-Variante (httpx.AsyncClient). Gleiche Methoden, alle awaitable."""

    def __init__(self, base_url: str, api_key: str | None = None,
                 timeout: float = DEFAULT_TIMEOUT, verify: bool = True) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.getenv("CNODE_API_KEY", "")
        headers = {"User-Agent": f"cnode-client/{__version__}"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        self._c = httpx.AsyncClient(base_url=self.base_url, headers=headers,
                                    timeout=timeout, verify=verify)

    async def _req(self, method: str, path: str, **kw) -> Any:
        r = await self._c.request(method, path, **kw)
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except Exception:
                detail = r.text
            raise CNodeError(r.status_code, str(detail)[:500])
        return r.json() if r.content else None

    async def health(self) -> dict:
        return await self._req("GET", "/health")

    async def tenant_context(self) -> dict:
        return await self._req("GET", "/tenant/context")

    async def ask(self, text: str, thread_id: str | None = None,
                  provider: str | None = None, levels: list[str] | None = None) -> Answer:
        body: dict = {"text": text}
        if thread_id:
            body["thread_id"] = thread_id
        if provider:
            body["provider"] = provider
        if levels:
            body["levels"] = levels
        return Answer._from(await self._req("POST", "/ask", json=body))

    async def route(self, text: str, history: list | None = None) -> dict:
        return await self._req("POST", "/route", json={"text": text, "history": history or []})

    async def graph(self, client_id: str | None = None) -> dict:
        params = {"client_id": client_id} if client_id else None
        return await self._req("GET", "/graph", params=params)

    async def capture(self, text: str) -> dict:
        return await self._req("POST", "/graph/capture", json={"text": text})

    async def forms(self) -> list[dict]:
        return (await self._req("GET", "/forms") or {}).get("forms", [])

    async def submit_form(self, form_id: str, **kw) -> dict:
        return await self._req("POST", f"/forms/{form_id}/submit", json=kw)

    async def connectors_catalog(self) -> list[dict]:
        return (await self._req("GET", "/connectors/catalog") or {}).get("connectors", [])

    async def close(self) -> None:
        await self._c.aclose()

    async def __aenter__(self) -> "AsyncCNodeClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()


__all__ = ["CNodeClient", "AsyncCNodeClient", "Answer", "CNodeError", "__version__"]
