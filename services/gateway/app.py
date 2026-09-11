"""gateway — BFF / API-Gateway für die Creativate Dev-Shell.

Ein Eingang für die Shell: POST /ask {text}. Der Gateway klassifiziert die
Absicht (via cnode-core) und routet an den passenden Service — cNode (Wissen/
Entscheidung), Scout (Leads), Förder (Förderung) oder graph-core (Ingest/Graph).
Antwortet immer im selben Envelope, damit die UI eine Form kennt.

Demo-Leitsatz: ein NL-Befehl → Intent-Router → passender Service → belegte Antwort.
"""
from __future__ import annotations

import os

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

GRAPH_CORE_URL = os.getenv("GRAPH_CORE_URL", "http://graph-core:8010")
CNODE_CORE_URL = os.getenv("CNODE_CORE_URL", "http://cnode-core:8020")
SCOUT_URL = os.getenv("SCOUT_URL", "http://asset-scout:8030")
FOERDER_URL = os.getenv("FOERDER_URL", "http://asset-foerder:8040")
MODEL_ROUTER_URL = os.getenv("MODEL_ROUTER_URL", "http://model-router:8050")

SERVICES = {
    "graph-core": GRAPH_CORE_URL, "cnode-core": CNODE_CORE_URL,
    "asset-scout": SCOUT_URL, "asset-foerder": FOERDER_URL, "model-router": MODEL_ROUTER_URL,
}

app = FastAPI(title="gateway", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class AskReq(BaseModel):
    text: str
    provider: str = "ollama"
    model: str | None = None


def envelope(intent, route, result_text, **extra):
    base = {"intent": intent, "route": route, "result_text": result_text,
            "sources": [], "graph_delta": {"nodes": [], "edges": []},
            "highlight": [], "trace": [], "provider": "", "model": ""}
    base.update(extra)
    return base


@app.get("/health")
async def health():
    deps = {}
    async with httpx.AsyncClient(timeout=3.0) as c:
        for name, url in SERVICES.items():
            try:
                deps[name] = (await c.get(f"{url}/health")).json().get("status", "?")
            except Exception:
                deps[name] = "unreachable"
    ok = all(v not in ("unreachable",) for v in deps.values())
    return {"status": "ok" if ok else "degraded", "service": "gateway", "deps": deps}


@app.get("/graph")
async def graph():
    async with httpx.AsyncClient(timeout=10.0) as c:
        return (await c.get(f"{GRAPH_CORE_URL}/graph")).json()


@app.get("/models")
async def models():
    async with httpx.AsyncClient(timeout=6.0) as c:
        return (await c.get(f"{MODEL_ROUTER_URL}/models")).json()


@app.post("/ask")
async def ask(req: AskReq):
    trace = [{"step": "gateway", "text": req.text}]
    async with httpx.AsyncClient(timeout=140.0) as c:
        cls = (await c.post(f"{CNODE_CORE_URL}/classify", json={"text": req.text})).json()
        intent = cls.get("intent", "knowledge")
        trace += cls.get("trace", [])

        if intent == "leads":
            data = (await c.post(f"{SCOUT_URL}/find", json={"text": req.text})).json()
            leads = data.get("leads", [])
            txt = "**Gefundene Leads (Scout):**\n" + "\n".join(
                f"- {l['name']} · {l.get('segment','')} · Score {l.get('score','')} — {l.get('reason','')}"
                for l in leads)
            trace.append({"step": "route", "service": "asset-scout", "hits": len(leads)})
            return envelope(intent, "asset-scout", txt, sources=leads, trace=trace)

        if intent == "foerderung":
            data = (await c.post(f"{FOERDER_URL}/match", json={"text": req.text})).json()
            progs = data.get("programs", [])
            txt = "**Passende Förderprogramme (Förder):**\n" + "\n".join(
                f"- {p['name']} · Fit {p.get('fit','')} · {p.get('max_foerderung','')} — {p.get('reason','')}"
                for p in progs)
            trace.append({"step": "route", "service": "asset-foerder", "hits": len(progs)})
            return envelope(intent, "asset-foerder", txt, sources=progs, trace=trace)

        if intent == "ingest":
            data = (await c.post(f"{GRAPH_CORE_URL}/ingest",
                                 json={"label": req.text, "type": "Document",
                                       "props": {"ingested": True}})).json()
            delta = data.get("graph_delta", {"nodes": [], "edges": []})
            txt = (f"Quelle ingested: **{req.text}** → {len(delta.get('nodes',[]))} Knoten in den "
                   "Gedächtnis geschrieben. Der Graph ist live gewachsen.")
            trace.append({"step": "route", "service": "graph-core", "action": "ingest"})
            return envelope(intent, "graph-core", txt, graph_delta=delta,
                            highlight=[n["id"] for n in delta.get("nodes", [])], trace=trace)

        if intent == "graph":
            g = (await c.get(f"{GRAPH_CORE_URL}/graph")).json()
            txt = (f"Gedächtnis: **{len(g.get('nodes',[]))} Knoten**, "
                   f"**{len(g.get('edges',[]))} Kanten**. Klicke einen Knoten für Details + Provenienz.")
            trace.append({"step": "route", "service": "graph-core", "action": "graph"})
            return envelope(intent, "graph-core", txt, graph_delta=g, trace=trace)

        # decision / knowledge / smalltalk → cNode orchestriert eine belegte Antwort
        data = (await c.post(f"{CNODE_CORE_URL}/answer",
                             json={"text": req.text, "provider": req.provider, "model": req.model})).json()
        trace += data.get("trace", [])
        return envelope(data.get("intent", intent), "cnode-core", data.get("result", ""),
                        sources=data.get("sources", []),
                        highlight=[s["id"] for s in data.get("sources", []) if "id" in s],
                        trace=trace, provider=data.get("provider", ""), model=data.get("model", ""))
