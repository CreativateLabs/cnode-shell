"""LLM-Adapter: lokales Ollama (default, EU-souverän) + optional Claude.

Enthält die Intent-Klassifikation (LLM-first + offline-sicherer Keyword-Fallback,
Aktions-Keywords gewinnen) und Freitext-Generierung für Artefakte.
"""
from __future__ import annotations

import json
import os
import re
from typing import AsyncIterator

import httpx

OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
# Google Gemini — Cloud-Provider für die öffentliche Demo (frictionless, kein lokales Ollama).
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
# Deployment-Default-Provider: LLM_PROVIDER setzt den Standard (z.B. 'gemini' als Cloud-
# Sandbox-LLM über alle Tenants). Eine EXPLIZITE Wahl aus der Shell (ollama/gemini/claude)
# gewinnt jedoch immer → so lässt sich pro Anfrage zwischen On-Prem (Ollama) und Cloud
# (Gemini) umschalten. Ohne beides: Ollama.
DEFAULT_PROVIDER = os.getenv("LLM_PROVIDER", "").strip().lower()
_KNOWN_PROVIDERS = ("ollama", "gemini", "claude")


def resolve_provider(requested: str) -> str:
    req = (requested or "").strip().lower()
    if req in _KNOWN_PROVIDERS:
        return req              # explizite Shell-Wahl schlägt den Default
    return DEFAULT_PROVIDER or "ollama"


def provider_status() -> dict:
    """Welche Provider real nutzbar sind + der Default — für die Shell-Umschaltung."""
    return {
        "default": resolve_provider(""),
        "ollama": True,                       # lokal immer als Fallback vorgesehen
        "gemini": bool(GOOGLE_API_KEY),
        "claude": bool(ANTHROPIC_API_KEY),
    }

# Echte Token-Nutzung des letzten LLM-Calls (per async-Task via ContextVar → concurrency-safe).
# Die Generatoren setzen es aus der Provider-Usage; Handler lesen es via last_tokens().
import contextvars
_LAST_TOKENS: "contextvars.ContextVar[int]" = contextvars.ContextVar("last_tokens", default=0)


def last_tokens() -> int:
    """Gesamte Tokens (Prompt+Antwort) des letzten generate()-Aufrufs in dieser Task; 0 wenn unbekannt."""
    try:
        return int(_LAST_TOKENS.get())
    except Exception:
        return 0

# Stop-Sequenzen: verhindern, dass das Modell den Dialog fortsetzt und eigene
# „Nutzer:"-Turns erfindet (Ursache des Fake-Dialog-Leaks im Test).
_STOP = ["\nNutzer:", "\nNutzer :", "\nUser:", "\nUser :", "\nAssistent:", "\nHuman:"]

INTENTS = ["decision", "knowledge", "leads", "foerderung", "ingest", "graph", "smalltalk"]

# Aktions-/Entscheidungs-Keywords sind zuverlässig + offline-sicher und gewinnen sofort.
KEYWORDS = {
    "leads": ["lead", "kunde", "kunden", "vertrieb", "outreach", "akquise", "prospect", "neukund"],
    "foerderung": ["förder", "foerder", "zuschuss", "zuschüss", "antrag", "grant",
                   "subvention", "foerder", "fördermittel", "beihilfe"],
    "ingest": ["ingest", "lade quelle", "importier", "dokument hinzu", "quelle hinzu", "einlesen",
               "hochladen", "upload", "einpflegen"],
    "decision": ["entscheid", "grundlage", "begründ", "begruend", "empfehl", "sollen wir", "warum",
                 "risiko", "abwäg", "abwaeg", "pro und contra"],
}

# Graph-ANZEIGE nur bei echten Anzeige-Verben. „graph/wissensgraph" als bloße Ortsangabe
# („was wissen wir über X im Wissensgraphen", „erkläre, wie ein Wissensgraph …") darf NICHT
# die Graph-Ansicht triggern — das sind Wissensfragen (Retrieval) bzw. Erklärungen.
_GRAPH_DISPLAY_RE = re.compile(
    r"(zeig|zeige|öffne|oeffne|visualisier|darstell|render|anzeig)\w*\b.{0,30}graph"
    r"|graph\w*\b.{0,20}(öffn|zeig|anzeig|visualisier|darstell|render)"
    r"|^\s*(wissens)?graph\w*\s*$",
    re.IGNORECASE,
)


def is_graph_display(text: str) -> bool:
    return bool(_GRAPH_DISPLAY_RE.search(text or ""))

GREETINGS = {"hi", "hallo", "hey", "moin", "servus", "guten tag", "guten morgen",
             "danke", "ok", "okay", "test", "hello"}


# Schreib-/Generier-Absichten: Text VERFASSEN (Nachricht, E-Mail, Memo, Zusammenfassung …).
# Diese gewinnen VOR den Discovery-Keywords (leads/foerderung) — sonst re-runnt z.B.
# „Entwirf eine Outreach-Nachricht für diese Leads" fälschlich die Lead-Suche.
GENERATE_HINTS = (
    "entwirf", "entwurf", "formulier", "verfass", "outreach", "anschreiben",
    "betreff", "elevator pitch", "antwortmail", "antwort-mail",
    "schreibe eine", "schreib eine", "schreibe mir", "schreib mir",
    "erstelle eine nachricht", "erstelle eine mail", "erstelle eine e-mail",
    "erstelle eine email", "erstelle ein anschreiben", "erstelle einen entwurf",
    "fasse zusammen", "zusammenfass", "übersetze", "übersetz mir", "formuliere um",
)


def is_generation(text: str) -> bool:
    """True, wenn der Nutzer Text VERFASST haben will (schreiben/formulieren/zusammenfassen)."""
    t = text.lower()
    return any(h in t for h in GENERATE_HINTS)


def keyword_intent(text: str) -> str | None:
    t = text.lower()
    for intent, kws in KEYWORDS.items():
        if any(k in t for k in kws):
            return intent
    return None


def is_greeting(text: str) -> bool:
    """Echte Begrüßung/Floskel — NICHT jeder kurze Input. Ein 1–2-Wort-Input gilt nur
    dann als Small-Talk, wenn KEIN inhaltlicher Begriff dabei ist (sonst würden kurze
    Fachbegriffe wie „Forschungszulage BSFZ" oder „DSGVO Pflichten" fälschlich als Gruß
    behandelt und übersprängen das Retrieval)."""
    t = text.strip().lower().rstrip("!.?")
    if t in GREETINGS:
        return True
    words = t.split()
    if "?" in text or len(words) > 2 or not words:
        return False
    return all(w in GREETINGS or len(w) <= 2 for w in words)


async def ollama_generate(prompt: str, system: str | None = None,
                          max_tokens: int = 600, model: str | None = None,
                          timeout: float = 120.0) -> tuple[str, str]:
    """Ruft Ollama /api/generate. Gibt (text, model) zurück; leere Antwort bei Fehler."""
    mdl = model or OLLAMA_MODEL
    payload: dict = {
        "model": mdl,
        "prompt": prompt,
        "stream": False,
        # Modell 30 min warm halten → keine Reload-Latenz zwischen Anfragen.
        "keep_alive": "30m",
        "options": {"num_predict": max_tokens, "stop": _STOP},
    }
    if system:
        payload["system"] = system
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.post(f"{OLLAMA_URL}/api/generate", json=payload)
        r.raise_for_status()
        data = r.json()
    _LAST_TOKENS.set(int(data.get("prompt_eval_count", 0) or 0) + int(data.get("eval_count", 0) or 0))
    return (data.get("response") or "").strip(), mdl


async def ollama_stream(prompt: str, system: str | None = None, max_tokens: int = 600,
                        model: str | None = None, timeout: float = 180.0) -> AsyncIterator[str]:
    """Streamt Ollama-Tokens (stream=true, NDJSON). Yieldet Text-Chunks."""
    mdl = model or OLLAMA_MODEL
    payload: dict = {
        "model": mdl, "prompt": prompt, "stream": True, "keep_alive": "30m",
        "options": {"num_predict": max_tokens, "stop": _STOP},
    }
    if system:
        payload["system"] = system
    async with httpx.AsyncClient(timeout=timeout) as c:
        async with c.stream("POST", f"{OLLAMA_URL}/api/generate", json=payload) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                tok = obj.get("response", "")
                if tok:
                    yield tok
                if obj.get("done"):
                    break


async def generate_stream(prompt: str, system: str | None = None, max_tokens: int = 600,
                          provider: str = "ollama") -> AsyncIterator[str]:
    """Provider-agnostischer Token-Stream. Ollama streamt echt; Claude (falls Key) wird
    als ein Chunk geliefert (kein Token-Stream implementiert). Fällt auf Ollama zurück."""
    provider = resolve_provider(provider)
    if provider == "claude" and ANTHROPIC_API_KEY:
        try:
            text, _model = await claude_generate(prompt, system, max_tokens)
            if text:
                yield text
                return
        except Exception:
            pass  # → Fallback unten
    if provider == "gemini" and GOOGLE_API_KEY:
        try:
            text, _model = await gemini_generate(prompt, system, max_tokens)
            if text:
                yield text
                return
        except Exception:
            pass  # → Ollama-Stream
    # Ausnahmen NICHT verschlucken: Ein Abbruch mitten im Stream (Timeout,
    # Verbindungsblip) muss den Aufrufer erreichen, damit er robust nachgeneriert
    # statt eine abgeschnittene Teilantwort als Endergebnis zu finalisieren.
    async for tok in ollama_stream(prompt, system, max_tokens):
        yield tok


async def claude_generate(prompt: str, system: str | None = None,
                          max_tokens: int = 600) -> tuple[str, str]:
    """Ruft die Anthropic-API (nur wenn ANTHROPIC_API_KEY gesetzt)."""
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body: dict = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        body["system"] = system
    async with httpx.AsyncClient(timeout=120.0) as c:
        r = await c.post("https://api.anthropic.com/v1/messages", headers=headers, json=body)
        r.raise_for_status()
        data = r.json()
    parts = data.get("content") or []
    text = "".join(p.get("text", "") for p in parts if p.get("type") == "text").strip()
    u = data.get("usage") or {}
    _LAST_TOKENS.set(int(u.get("input_tokens", 0) or 0) + int(u.get("output_tokens", 0) or 0))
    return text, data.get("model", ANTHROPIC_MODEL)


async def gemini_generate(prompt: str, system: str | None = None,
                          max_tokens: int = 600) -> tuple[str, str]:
    """Ruft die Google-Gemini-API (nur wenn GOOGLE_API_KEY gesetzt). Cloud-Provider für
    die öffentliche Demo — kein lokales Ollama nötig."""
    if not GOOGLE_API_KEY:
        raise RuntimeError("GOOGLE_API_KEY not set")
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent")
    body: dict = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        # Niedrige Temperatur → weniger Zufalls-Drift (u.a. Sprach-/Skript-Wechsel bei flash).
        # thinkingBudget=0: gemini-flash-latest ist ein Thinking-Modell — ohne dies fressen die
        # "thoughts" das maxOutputTokens-Budget (bei großem System-Prompt komplett) → leere
        # Antwort + hohe Latenz. Für den Chat-Assistenten brauchen wir kein Extended-Reasoning.
        "generationConfig": {
            "maxOutputTokens": max_tokens, "temperature": 0.3, "topP": 0.9,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    async with httpx.AsyncClient(timeout=120.0) as c:
        r = await c.post(url, params={"key": GOOGLE_API_KEY}, json=body)
        r.raise_for_status()
        data = r.json()
    cands = data.get("candidates") or []
    parts = (cands[0].get("content", {}).get("parts") if cands else []) or []
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
    um = data.get("usageMetadata") or {}
    _LAST_TOKENS.set(int(um.get("totalTokenCount", 0) or 0)
                     or (int(um.get("promptTokenCount", 0) or 0) + int(um.get("candidatesTokenCount", 0) or 0)))
    return text, GEMINI_MODEL


async def generate(prompt: str, system: str | None = None, max_tokens: int = 600,
                   provider: str = "ollama", timeout: float = 120.0) -> tuple[str, str, str]:
    """Generiert Text über den gewünschten Provider mit Fallback auf Ollama.

    Returns (text, provider_used, model_used). Text kann leer sein, wenn alles scheitert
    (Caller liefert dann deterministischen Fallback).
    """
    provider = resolve_provider(provider)
    if provider == "claude" and ANTHROPIC_API_KEY:
        try:
            text, model = await claude_generate(prompt, system, max_tokens)
            if text:
                return text, "claude", model
        except Exception:
            pass  # → Fallback unten
    if provider == "gemini" and GOOGLE_API_KEY:
        try:
            text, model = await gemini_generate(prompt, system, max_tokens)
            if text:
                return text, "gemini", model
        except Exception:
            pass  # → Ollama-Fallback (falls lokal verfügbar)
    try:
        text, model = await ollama_generate(prompt, system, max_tokens, timeout=timeout)
        return text, "ollama", model
    except Exception:
        return "", "none", ""


async def classify(text: str) -> tuple[str, str, list[dict]]:
    """Intent-Klassifikation. Returns (intent, method, trace)."""
    trace: list[dict] = []

    # Schreib-/Generier-Absicht gewinnt vor Discovery-Keywords → beratende Generierung
    # (engine /answer nutzt die History), statt Leads/Förderung neu zu suchen.
    if is_generation(text):
        trace.append({"step": "classify", "method": "rule", "result": "knowledge",
                      "service": "engine", "note": "generation"})
        return "knowledge", "rule", trace

    # Graph-ANZEIGE (nur bei Anzeige-Verben) gewinnt vor generischer Wissensfrage.
    if is_graph_display(text):
        trace.append({"step": "classify", "method": "rule", "result": "graph", "service": "engine"})
        return "graph", "rule", trace

    kw = keyword_intent(text)
    if kw in ("leads", "foerderung", "ingest", "decision"):
        trace.append({"step": "classify", "method": "keyword", "result": kw, "service": "engine"})
        return kw, "keyword", trace

    if is_greeting(text):
        trace.append({"step": "classify", "method": "rule", "result": "smalltalk", "service": "engine"})
        return "smalltalk", "rule", trace

    if is_conversational(text):
        trace.append({"step": "classify", "method": "rule", "result": "smalltalk", "service": "engine"})
        return "smalltalk", "rule", trace

    # KEIN LLM-Call fürs Routing (Tempo). Default = knowledge; 'decision' kommt via Keywords.
    trace.append({"step": "classify", "method": "rule", "result": "knowledge", "service": "engine"})
    return "knowledge", "rule", trace


# Chit-chat / beratendes Gespräch ohne Fakten-Bedarf → kein Graph, keine Quellen/Rechenweg.
CHITCHAT_HINTS = (
    "wer bist du", "was kannst du", "was kann dieses", "wie funktionier", "hilfe",
    "wie kannst du", "wie kann ich", "was geht", "wie gehts", "wie geht's",
    "danke", "alles klar", "verstanden", "guten morgen", "guten tag", "guten abend",
    "hallo", "servus", "moin",
    # Beratende/meta Opener (allgemeines Gespräch, Selbstvorstellung, Fähigkeiten) —
    # gezielt phrasiert, damit echte Fach-/Wissensfragen NICHT fälschlich als Chat gelten.
    "lass uns allgemein", "allgemein sprechen", "lass uns reden", "lass uns sprechen",
    "womit kannst du", "wobei kannst du", "worin kannst du", "wobei unterstützt du",
    "kannst du mich unterstützen", "wie kannst du mir helfen", "was du alles kannst",
    "was kannst du alles", "stell dich vor", "stell dich kurz vor", "was bist du",
)


# Signale, dass eine Frage Tenant-/Graph-Grounding braucht → Retrieval sinnvoll.
_TENANT_SIGNALS = (
    "unser", "unsere", "unserem", "mein", "meine", "bei uns", "im graph", "wissensgraph",
    "graph", "welche daten", "welche quellen", "zeig", "liste", "auflist", "mandant",
    "kunde", "kunden", "archiv", "beleg", "quelle", "dokument", "vertrag", "hochgeladen",
    "datei", "projekt", "cnode", "c:node", ":node", "nen", "nena", "foerder",
    "leadscout", "creativate", "kpi",
    "zahlen", "umsatz", "report", "strategie", "wettbewerb",
)
# Klar generische Erklär-/Definitionsfragen ohne Tenant-Bezug → kein Graph nötig.
_GENERIC_STARTERS = (
    "was ist", "was sind", "erkläre", "erklär", "definier", "wie funktioniert",
    "was bedeutet", "unterschied zwischen", "vor- und nachteile", "vor und nachteile",
    "beispiele für", "wie kann man", "warum ist", "was macht", "gib mir tipps",
)


def needs_retrieval(text: str) -> bool:
    """Heuristik: braucht die Frage Tenant-/Graph-Grounding? Default True (sicher);
    nur klar generische Erklär-/Definitionsfragen ohne Tenant-Signal überspringen es."""
    t = text.lower()
    if any(s in t for s in _TENANT_SIGNALS):
        return True
    if any(g in t[:48] for g in _GENERIC_STARTERS):
        return False
    return True


def is_conversational(text: str) -> bool:
    """True für Begrüßungen/Meta/Small-Talk → direkter Berater-Chat statt Graph-Suche."""
    t = text.strip().lower().rstrip("!.?")
    if is_greeting(text):
        return True
    if keyword_intent(text):  # klare Fach-/Aktions-Absicht → kein Small-Talk
        return False
    if any(h in t for h in CHITCHAT_HINTS):
        return True
    # sehr kurze, nicht-fragende Eingaben — aber NUR, wenn kein inhaltlicher Begriff
    # dabei ist (kurze Fachfragen wie „cNode Roadmap" sollen ins Retrieval, nicht in Chat).
    words = t.split()
    if len(words) <= 3 and "?" not in text and all(w in GREETINGS or len(w) <= 2 for w in words):
        return True
    return False


async def list_ollama_models() -> list[str]:
    async with httpx.AsyncClient(timeout=5.0) as c:
        r = await c.get(f"{OLLAMA_URL}/api/tags")
        r.raise_for_status()
        data = r.json()
    return [m.get("name", "") for m in data.get("models", []) if m.get("name")]


async def loaded_models() -> list[dict]:
    """Aktuell in den RAM/VRAM geladene (warme) Modelle via Ollama /api/ps.
    Kennzahl fürs /health: zeigt, ob das Default-Modell warm ist (keine Reload-Latenz)."""
    try:
        async with httpx.AsyncClient(timeout=4.0) as c:
            r = await c.get(f"{OLLAMA_URL}/api/ps")
            r.raise_for_status()
            data = r.json()
        return [{"name": m.get("name", ""),
                 "vram_mb": round((m.get("size_vram") or 0) / 1048576)}
                for m in data.get("models", []) if m.get("name")]
    except Exception:
        return []
