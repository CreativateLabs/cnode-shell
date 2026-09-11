"""cnode-core — Intent-Router + Orchestrator für die Creativate Dev-Shell.

Der kontrollierende Kern des agentischen Regelkreises (schlanke Demo-Variante):
  NL-Text  →  classify (LLM-first, Keyword-Fallback)  →  route/orchestrate
           →  Wissen aus graph-core  →  Generierung via model-router
           →  {result, sources[], trace[], intent}

Human-in-the-loop, Quelle je Aussage, offener Rechenweg (trace) — die
"Vertrauens-Architektur" als Code, nicht als Behauptung.
"""
from __future__ import annotations

import os
import re

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

GRAPH_CORE_URL = os.getenv("GRAPH_CORE_URL", "http://graph-core:8010")
MODEL_ROUTER_URL = os.getenv("MODEL_ROUTER_URL", "http://model-router:8050")

app = FastAPI(title="cnode-core", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

INTENTS = ["decision", "knowledge", "leads", "foerderung", "ingest", "graph", "smalltalk"]

KEYWORDS = {
    "leads": ["lead", "kunde", "kunden", "vertrieb", "outreach", "akquise", "prospect"],
    "foerderung": ["förder", "foerder", "zuschuss", "antrag", "grant", "subvention"],
    "ingest": ["ingest", "lade quelle", "importier", "dokument hinzu", "quelle hinzu", "einlesen"],
    "graph": ["graph", "zusammenhang", "wie hängt", "wie haengt", "verbindung", "verbunden", "netzwerk"],
    "decision": ["entscheid", "grundlage", "begründ", "begruend", "empfehl", "sollen wir", "warum", "risiko"],
}

STOPWORDS = set("der die das ein eine und oder mit für fuer von zu im in den dem des auf ist sind was wie wer "
                "welche welcher zeig mir zeige uns über ueber the a an of to for is are show me".split())


class ClassifyReq(BaseModel):
    text: str


class AnswerReq(BaseModel):
    text: str
    provider: str = "ollama"
    model: str | None = None


def keyword_intent(text: str) -> str:
    t = text.lower()
    for intent, kws in KEYWORDS.items():
        if any(k in t for k in kws):
            return intent
    return "knowledge"


GREETINGS = {"hi", "hallo", "hey", "moin", "servus", "guten tag", "guten morgen", "danke", "ok", "test"}


def _is_greeting(text: str) -> bool:
    t = text.strip().lower().rstrip("!.")
    return t in GREETINGS or (len(t.split()) <= 2 and "?" not in text and t not in ("graph",))


async def llm_classify(text: str, trace: list) -> tuple[str, str]:
    # Hybrid: Aktions-/Entscheidungs-Keywords sind zuverlässig + offline-sicher und
    # gewinnen sofort. Nur bei generischem Wissen verfeinert das LLM (knowledge/decision).
    kw = keyword_intent(text)
    if kw in ("leads", "foerderung", "ingest", "graph", "decision"):
        trace.append({"step": "classify", "method": "keyword", "result": kw})
        return kw, "keyword"
    if _is_greeting(text):
        trace.append({"step": "classify", "method": "rule", "result": "smalltalk"})
        return "smalltalk", "rule"

    prompt = (
        "Klassifiziere die Nutzereingabe in GENAU eine Kategorie: decision, knowledge.\n"
        "'decision' = fragt nach Entscheidung/Empfehlung/Begründung/Risiko. "
        "'knowledge' = fragt nach Fakten/Wissen.\n"
        "Antworte NUR mit dem Kategorie-Wort.\n\n"
        f"Eingabe: {text}\nKategorie:"
    )
    try:
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post(f"{MODEL_ROUTER_URL}/complete", json={"prompt": prompt, "max_tokens": 6})
            data = r.json()
        if data.get("ok"):
            raw = (data.get("text") or "").strip().lower()
            for it in ("decision", "knowledge"):
                if it in raw:
                    trace.append({"step": "classify", "method": "llm", "result": it})
                    return it, "llm"
    except Exception as e:
        trace.append({"step": "classify", "method": "llm", "error": str(e)})
    # Fallback: echte Frage → knowledge, nie smalltalk
    trace.append({"step": "classify", "method": "keyword-fallback", "result": "knowledge"})
    return "knowledge", "keyword-fallback"


def keywords(text: str) -> list[str]:
    words = re.findall(r"[\wäöüßÄÖÜ]{3,}", text.lower())
    return [w for w in words if w not in STOPWORDS][:6]


@app.get("/health")
async def health():
    deps = {}
    for name, url in (("graph-core", GRAPH_CORE_URL), ("model-router", MODEL_ROUTER_URL)):
        try:
            async with httpx.AsyncClient(timeout=3.0) as c:
                deps[name] = (await c.get(f"{url}/health")).json().get("status", "?")
        except Exception:
            deps[name] = "unreachable"
    return {"status": "ok", "service": "cnode-core", "deps": deps}


@app.post("/classify")
async def classify(req: ClassifyReq):
    trace: list = []
    intent, method = await llm_classify(req.text, trace)
    return {"intent": intent, "method": method, "trace": trace}


async def gather_sources(text: str, trace: list) -> list[dict]:
    found: dict[str, dict] = {}
    for kw in keywords(text) or [text]:
        try:
            async with httpx.AsyncClient(timeout=8.0) as c:
                r = await c.get(f"{GRAPH_CORE_URL}/search", params={"q": kw, "limit": 4})
            for hit in r.json().get("results", []):
                found[hit["id"]] = hit
        except Exception as e:
            trace.append({"step": "retrieve", "keyword": kw, "error": str(e)})
    src = list(found.values())[:8]
    trace.append({"step": "retrieve", "source": "graph-core", "hits": len(src),
                  "ids": [s["id"] for s in src]})
    return src


@app.post("/answer")
async def answer(req: AnswerReq):
    trace: list = []
    intent, _ = await llm_classify(req.text, trace)
    sources = await gather_sources(req.text, trace)

    facts = "\n".join(
        f"- {s['label']} ({s['type']}): "
        + ", ".join(f"{k}={v}" for k, v in (s.get('props') or {}).items())
        for s in sources
    ) or "(keine passenden Fakten im Gedächtnis gefunden)"

    system = (
        "Du bist cNode, ein belegbarer Decision-Intelligence-Assistent. Antworte NUR auf Basis "
        "der gelieferten Fakten aus dem Gedächtnis. Erfinde nichts. Wenn die Fakten nicht "
        "reichen, sage das offen. Antworte auf Deutsch, sachlich, kompakt (max. 6 Sätze). "
        "Nenne am Ende die genutzten Quellen als Liste ihrer Labels."
    )
    prompt = f"Fakten aus dem Gedächtnis:\n{facts}\n\nFrage: {req.text}\n\nBelegte Antwort:"

    result_text, model_used, provider_used = "", req.model or "", req.provider
    try:
        async with httpx.AsyncClient(timeout=120.0) as c:
            r = await c.post(f"{MODEL_ROUTER_URL}/complete",
                             json={"prompt": prompt, "system": system,
                                   "provider": req.provider, "model": req.model, "max_tokens": 600})
            data = r.json()
        result_text = data.get("text", "")
        model_used, provider_used = data.get("model", ""), data.get("provider", req.provider)
        trace.append({"step": "generate", "provider": provider_used, "model": model_used,
                      "ok": data.get("ok", False)})
    except Exception as e:
        trace.append({"step": "generate", "error": str(e)})

    if not result_text:
        # Deterministischer Fallback ohne LLM — Demo bleibt stabil.
        result_text = ("Belegte Kurzantwort (LLM offline, deterministisch aus dem Graphen):\n" + facts)
        trace.append({"step": "generate", "method": "deterministic-fallback"})

    return {
        "intent": intent,
        "result": result_text,
        "sources": sources,
        "trace": trace,
        "provider": provider_used,
        "model": model_used,
    }
