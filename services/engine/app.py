"""engine — Engine-Adapter (§2.4) für die c:node / Creativate Dev-Shell.

Frontet die echte NEN AI (CIG, :8001) und das lokale Ollama (:11434). Liefert das in
SCOPE.md §2.4 eingefrorene interne API, das die BFF konsumiert:

  GET  /health                          → eigener Status + NEN-AI-Erreichbarkeit + LLM/Modell
  POST /classify {text}                 → {intent}  (LLM-first + Keyword-Fallback)
  POST /answer   {text, client_id, …}   → {result, sources, trace, provider, model}
  GET  /graph?client_id=                → {nodes, edges}  (§2.2 normalisiert)
  POST /ingest   {label,type,props,…}   → {graph_delta}
  POST /artifact {kind, thread_id, …}   → Artifact (§2.3)
  GET  /models                          → verfügbare Ollama-Modelle + Claude-Status

De-Risking: ist die NEN AI nicht erreichbar, liefert jeder Endpunkt plausible
deterministische Antworten in derselben Contract-Form — kein Crash, kein 500.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import unicodedata
import uuid

import httpx
from collections import Counter
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

import artifacts
import llm
import nen
from tenants import MARKET_GROUP, MESH_GROUP, TENANT_DOMAINS, map_client_to_group

# Das LLM hängt kontextuelle Folge-Vorschläge an eine eigene letzte Zeile an; die
# Engine trennt sie heraus (dynamische, gesprächsbezogene Chips — kein Extra-Call).
_SUGGEST_INSTRUCTION = (
    "\n\nBeende deine Antwort mit einer EIGENEN letzten Zeile im Format "
    "'VORSCHLÄGE: <a> | <b> | <c>' — 2–3 sehr kurze, konkret zum bisherigen Gespräch "
    "passende nächste Schritte (je max. 4 Wörter), mit ' | ' getrennt. Keine Sternchen."
)

# No-Action-Guardrail: das LLM darf niemals behaupten, Aktionen mit Außenwirkung
# ausgeführt zu haben. Solche Aktionen laufen ausschließlich über den Bestätigungs-Flow.
_NO_ACTION_GUARD = (
    "\n\nWICHTIG: Du führst selbst KEINE Aktionen mit Außenwirkung aus — du sendest keine "
    "E-Mails/Nachrichten, legst keine Entwürfe oder Termine an und schreibst nichts in ein "
    "CRM. Behaupte NIEMALS, du hättest etwas gesendet, angelegt oder übertragen. Wenn der "
    "Nutzer so etwas möchte, formuliere höchstens den Inhalt (z. B. den Nachrichtentext) und "
    "weise kurz darauf hin, dass die Ausführung separat nach ausdrücklicher Bestätigung über "
    "den passenden Connector erfolgt."
)


# Grounding-Pflicht: das Modell darf keine Fakten/Quellen erfinden. Kernregel gegen
# Halluzination (z.B. erfundene Förderprogramm-Details oder Links).
_GROUNDING_GUARD = (
    "\n\nGROUNDING-PFLICHT: Erfinde NIEMALS Fakten, Zahlen, Fristen, Programm-/Eigennamen, "
    "Zitate oder Links. Stütze konkrete Aussagen ausschließlich auf die dir gelieferten "
    "Fakten/Quellen. Liegt zu einem konkreten Begriff, Programm oder einer Zahl KEINE "
    "belegte Quelle vor, sag das offen (etwa: dazu liegt mir keine belegte Quelle vor) und "
    "rate NICHT. Biete dann an: (a) eine passende Quelle bereitzustellen/einzulesen oder (b) "
    "eine Web-Recherche mit Quellenangabe zu starten (bevorzugt wissenschaftliche/offizielle "
    "Quellen). Wirst du nach der Herkunft gefragt, nenne die tatsächlichen Belege — hast du "
    "keine, sage das klar, statt zu behaupten, du habest die Information nur strukturiert. "
    "Bittet der Nutzer, etwas zu recherchieren oder zu durchsuchen, entwirf KEINE E-Mail und "
    "erfinde keine Treffer — biete an, eine Web-Recherche mit Quellen zu starten oder eine "
    "konkrete Quelle (URL/Datei) einzulesen. "
    "Expandiere zudem KEINE Abkürzungen und ergänze KEINE Definitionen, die nicht wörtlich in "
    "den Fakten stehen — kennst du die Auflösung nicht belegt, lass sie weg. "
    "Interpretiere Eigennamen NICHT über die Fakten hinaus: leite aus einem Namensbestandteil "
    "(z.B. 'Lab', 'AI', 'Group') KEINE Tätigkeit oder Bedeutung ab. Beschreibe ausschließlich, "
    "was die gelieferten Fakten konkret sagen; wo die Fakten schweigen, schweige auch."
)

# Leichter Grounding-Guard für den REINEN CHAT-Pfad (keine Fakten nötig): keine erfundenen
# Mandanten-Fakten, aber IMMER hilfreich antworten — nie stumm bleiben. (Der strikte
# _GROUNDING_GUARD mit „wo die Fakten schweigen, schweige auch" gilt nur für die belegte
# CONSULT-Synthese; im Chat führte er dazu, dass das Modell leer/„Wie kann ich dir helfen?" lieferte.)
_CHAT_GUARD = (
    "\n\nGROUNDING (Chat): Erfinde KEINE konkreten Mandanten-Fakten, Zahlen, Fristen, Eigennamen "
    "oder Links — die stammen nur aus belegten Quellen. Allgemeines Fach-/Methodenwissen darfst "
    "du frei erklären. Gib IMMER eine konkrete, hilfreiche Antwort und bleib NIEMALS stumm "
    "(niemals eine leere Nachricht). Fehlen belegte Mandanten-Daten, sag das in einem kurzen "
    "Satz UND liefere trotzdem eine brauchbare allgemeine Einordnung — plus das Angebot, eine "
    "Quelle einzulesen oder im Web zu recherchieren."
)

# Single-Turn/Sprach-Guard: das Modell darf NUR die eine Assistenten-Antwort liefern —
# keinen Dialog fortsetzen, keine erfundenen „Nutzer:"-Turns, konsequent Deutsch.
_SINGLE_TURN_GUARD = (
    "\n\nWICHTIG: Antworte NUR mit deiner einen Assistenten-Antwort. Setze das Gespräch NICHT "
    "fort, schreibe KEINE weiteren 'Nutzer:'- oder 'Assistent:'-Zeilen und simuliere keinen "
    "Dialog."
    "\n\nSPRACHE (ABSOLUT): Antworte in GENAU EINER Sprache — derselben, in der die Frage des "
    "Nutzers gestellt ist (Standard: Deutsch). Wechsle NIEMALS mitten in der Antwort die Sprache. "
    "Verwende AUSSCHLIESSLICH lateinische Schrift; benutze KEINE chinesischen, japanischen, "
    "koreanischen, kyrillischen, arabischen oder sonstigen nicht-lateinischen Zeichen, es sei "
    "denn, der Nutzer hat sie selbst verwendet. Jeder Satz muss in der Zielsprache stehen."
)

_SUGGEST_MARKER = re.compile(r"(?:[*_>#\s-]*)vorschl(?:ä|ae|a)ge\s*:?\s*\*{0,2}", re.IGNORECASE)


def _split_suggestions(text: str) -> tuple[str, list[str]]:
    """Trennt die 'VORSCHLÄGE:'-Marke ab → (bereinigter Text, [vorschläge]).

    Robust gegen Varianten: eigene Zeile ODER inline im Satz, mit/ohne Umlaut
    ('VORSCHLÄGE'/'VORSCHLAGE'), Groß/Klein, mit/ohne Doppelpunkt. Es zählt die
    LETZTE Fundstelle (die Instruktion verlangt die Vorschläge am Ende) und nur,
    wenn sie im Schlussteil steht — sonst wird nichts abgeschnitten.
    """
    if not text:
        return text, []
    last = None
    for m in _SUGGEST_MARKER.finditer(text):
        last = m
    if not last:
        return text, []
    # Nur akzeptieren, wenn die Marke wirklich am Ende steht (kein Treffer mitten im Fließtext).
    if last.start() < len(text) - 220:
        return text, []
    tail = text[last.end():].split("\n", 1)[0]  # nur bis zum Zeilenende
    parts = re.split(r"\s*[|;]\s*|\s+·\s+", tail)
    sugs = [re.sub(r"^[\s*\-•·]+|[\s*]+$", "", p) for p in parts]
    sugs = [s for s in sugs if 1 < len(s) <= 48][:4]
    if not sugs:
        return text, []
    clean = text[: last.start()].rstrip(" \t\n\r-*_>#·|")
    return (clean or text), sugs


# Beratende, begleitende Persona für /answer — natürlich, zielführend, proaktiv.
CONSULT_SYSTEM = (
    "Du bist der c:node-Assistent, geerdet auf NENA — der mitdenkenden Intelligenz "
    "(Wissensgraph + Gedächtnis). Grundsatz: c:node steuert, NENA denkt, die Agenten machen. "
    "Du bist ein beratender, begleitender Decision-Intelligence-Partner "
    "für Unternehmen. Sprich natürlich und direkt auf Deutsch, in einem klaren beratenden Ton — "
    "keine Floskeln, keine Roboter-Sprache. Gehe unmittelbar auf die Frage des Gegenübers ein.\n"
    "Nutze AUSSCHLIESSLICH die gelieferten Fakten (Mandanten-Ebene + geteilte Market-Ebene) als "
    "Beleg — erfinde nichts dazu. Arbeite effektiv und effizient auf das Ziel des Nutzers hin:\n"
    "1) Beantworte die Frage konkret und verständlich.\n"
    "2) Gib eine kurze, umsetzbare Empfehlung oder den sinnvollen nächsten Schritt (Next Best Action).\n"
    "3) Wenn die Faktenlage dünn ist, sag das offen und frage gezielt nach der konkret fehlenden "
    "Quelle oder Information — oder biete an, sie zu recherchieren/einzulesen.\n"
    "Antworte AUSFÜHRLICH und mit echtem Mehrwert: konkrete Analyse, klare Empfehlung(en) "
    "und die sinnvollen nächsten Schritte. Strukturiere längere Antworten gut lesbar "
    "(kurze Absätze, bei Bedarf Aufzählungen mit '- ' oder nummerierten Schritten). Vermeide "
    "Floskeln und leere Sätze — jeder Satz soll dem Nutzer weiterhelfen. Bleib dabei präzise "
    "und immer belegt; nutze den verfügbaren Platz, wenn das Thema es rechtfertigt (gern "
    "mehrere Absätze), fasse dich bei einfachen Fragen aber angemessen."
    + _GROUNDING_GUARD
    + _NO_ACTION_GUARD
    + _SUGGEST_INSTRUCTION
    + _SINGLE_TURN_GUARD
)

# Reiner Gesprächs-Modus (kein Graph, keine Fakten nötig) — wie ein Berater reden.
CHAT_SYSTEM = (
    "Du bist der c:node-Assistent, geerdet auf NENA (die mitdenkende Intelligenz) — ein "
    "freundlicher, kompetenter Berater. Antworte natürlich "
    "und direkt auf Deutsch, wie im Gespräch mit einem Kollegen: knapp, hilfreich, zugewandt. "
    "Erfinde KEINE konkreten Fakten/Zahlen; wenn es um belegbares Wissen geht, biete an, im "
    "Gedächtnis nachzusehen oder eine Quelle einzulesen. Frag bei Bedarf kurz nach, um "
    "das Ziel des Nutzers effizient zu erreichen. Antworte AUSFÜHRLICH und hilfreich statt "
    "knapp: gib konkrete, umsetzbare Substanz und strukturiere längere Antworten gut lesbar "
    "(kurze Absätze, bei Bedarf Aufzählungen oder nummerierte Schritte). Wenn der Nutzer einen "
    "Text will (z. B. eine Nachricht), liefere einen vollständigen, sofort verwendbaren Entwurf "
    "— nicht nur einen Platzhalter oder einen einzelnen Satz. Keine Floskeln; jeder Satz soll "
    "Mehrwert bringen. Bei einfachen Fragen fasse dich angemessen."
    + _CHAT_GUARD
    + _NO_ACTION_GUARD
    + _SUGGEST_INSTRUCTION
    + _SINGLE_TURN_GUARD
)

# Web-Recherche-Synthese: Antwort NUR aus den gelieferten Web-Quellen, mit [n]-Verweisen.
RESEARCH_SYSTEM = (
    "Du bist der c:node-Assistent. Beantworte die Frage AUSSCHLIESSLICH auf Basis der "
    "gelieferten Web-Rechercheergebnisse (nummerierte Quellen). Erfinde nichts dazu und "
    "füge keine weiteren Links hinzu. Verweise auf die genutzten Quellen im Text mit [n]. "
    "Priorisiere wissenschaftliche/offizielle Aussagen; bei Widersprüchen benenne sie. Wenn "
    "die Quellen die Frage nicht beantworten, sag das offen. Antworte klar und strukturiert."
    + _SUGGEST_INSTRUCTION
    + _SINGLE_TURN_GUARD
)

app = FastAPI(title="engine", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# G7 — Observability: /metrics (Prometheus, zero-dep) + HTTP-Zähler.
_REQS: dict[tuple, int] = {}


@app.middleware("http")
async def _count_requests(request, call_next):
    resp = await call_next(request)
    try:
        _REQS[(request.method, resp.status_code)] = _REQS.get((request.method, resp.status_code), 0) + 1
    except Exception:  # noqa: BLE001
        pass
    return resp


@app.get("/metrics")
def metrics():
    lines = ["# TYPE cnode_up gauge", 'cnode_up{service="engine"} 1',
             "# HELP cnode_http_requests_total HTTP-Requests nach Methode/Status.",
             "# TYPE cnode_http_requests_total counter"]
    for (method, status), n in _REQS.items():
        m = str(method).replace('"', '')
        lines.append(f'cnode_http_requests_total{{service="engine",method="{m}",status="{status}"}} {n}')
    return Response("\n".join(lines) + "\n", media_type="text/plain")

# E2.3 — „lernende" Retrieval-Gewichtung je Group. Terme belegter Quellen, die in
# geerdeten Antworten genutzt wurden, gewinnen an Gewicht → ranken künftig höher.
# Persistiert auf ein Volume (überlebt Neustarts); fällt sauber auf Session-scope zurück.
import os as _os

_LEARN_PATH = _os.getenv("LEARN_STORE_PATH", "/data/learned_weights.json")
LEARNED_WEIGHTS: dict[str, dict[str, float]] = {}

# Self-learning Mesh (Loop 2): belegte Antworten je Group zählen; alle _MESH_EVERY
# fließen governance-sichere Typ-Aggregate automatisch in den globalen Mesh.
_GROUNDED_COUNT: dict[str, int] = {}
_MESH_EVERY = 5

# Öffentliche Demo (c:node): IP-Abriegelung — NUR die eigene Client-Ebene. Kein Market/Mesh
# (kuratiertes/gelerntes Cross-Tenant-Wissen bleibt privat), keine Mesh-Contribution, keine
# Ontologie-Exposition. Aktiv per Env im Public-Overlay.
PUBLIC_DEMO = os.getenv("PUBLIC_DEMO", "").strip().lower() in ("1", "true", "yes", "on")
# Geteilte Ebenen (market/mesh) NUR für Tenants, die eine Fach-Domäne deklariert haben
# (tenant.yaml `domains:`). Ohne Domäne — z.B. c:node/Creativate — bleibt es beim eigenen
# Graphen; so zieht kein themenfremdes LeiKa/Mesh-Rauschen in den Chat. In der Demo ohnehin aus.
SHARED_LAYERS = (not PUBLIC_DEMO) and any(
    (d.get("layer") in ("market", "mesh")) for d in TENANT_DOMAINS
)


def _use_shared(intel: bool | None) -> bool:
    """Ob geteilte NENA-Ebenen (market/mesh) für DIESE Anfrage aktiv sind.

    Der bff löst das Entitlement je Tenant auf und reicht `intel` durch: bezahlt → True
    schaltet NENA auch in der Public-Sandbox frei; None → strukturelle Default-Regel
    (SHARED_LAYERS: eigene Fach-Domäne vorhanden und nicht Public-Demo).
    """
    return bool(intel) if intel is not None else SHARED_LAYERS


def _load_learned() -> None:
    try:
        with open(_LEARN_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            LEARNED_WEIGHTS.clear()
            LEARNED_WEIGHTS.update({g: dict(w) for g, w in data.items() if isinstance(w, dict)})
    except FileNotFoundError:
        pass
    except Exception:
        pass


def _save_learned() -> None:
    try:
        _os.makedirs(_os.path.dirname(_LEARN_PATH), exist_ok=True)
        tmp = _LEARN_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(LEARNED_WEIGHTS, f)
        _os.replace(tmp, _LEARN_PATH)
    except Exception:
        pass  # Volume evtl. nicht vorhanden → Session-scope-Fallback


_load_learned()


def _learn_from_sources(group: str, sources: list[dict], cap: float = 12.0) -> None:
    """Bumpt die Term-Gewichte der genutzten (relevanten) Quellen-Labels + persistiert."""
    bag = LEARNED_WEIGHTS.setdefault(group, {})
    changed = False
    for s in sources[:6]:
        for term in nen._content_terms(str(s.get("label") or "")):
            new = min(bag.get(term, 0.0) + 0.5, cap)
            if new != bag.get(term):
                bag[term] = new
                changed = True
    if changed:
        _save_learned()


# Produkt-Identitäts-Ebene: kuratierte, quellenbelegte Fakten über c:node & NENA selbst.
# IMMER mitgeliefert (auch in PUBLIC_DEMO und über alle per-User-Workspaces hinweg), damit
# „Was ist c:node?" belegt (grounding: gedaechtnis) statt generisch (allgemein) beantwortet
# wird. Read-only Produktwissen — KEINE Nutzerdaten → kein Cross-Tenant-Leak.
BASE_GROUP = os.getenv("BASE_GROUP", "cnode-base")
BASE_SEED: list[dict] = [
    {"label": "c:node", "type": "Produkt", "props": {"summary": "c:node ist die souveräne, EU-first KI-Plattform von Creativate Labs für Decision Intelligence: eine nicht-halluzinierende, Knowledge-Graph-gestützte KI, die jede Aussage mit Herkunft belegt (Provenienz, Audit-Trail für den EU AI Act). Architektur: Shell (Chat-UI) + Microservices + Plugin-Framework + Mandanten-Layer. Läuft lokal (Ollama) oder in der EU-Cloud.", "quelle": "c-node.ai", "region": "EU"}},
    {"label": "NENA", "type": "Produkt", "props": {"summary": "NENA ist die mitdenkende Intelligenz-Ebene von c:node: sie verbindet Gesprächskontext, ein wachsendes Gedächtnis (pgvector-Graph-Runtime, pro Nutzer isoliert) und Web-Retrieval zu einer belegten Antwort und zeigt pro Antwort ein Grounding-Badge (chat/allgemein/gedächtnis/web) — statt zu halluzinieren.", "quelle": "c-node.ai", "region": "EU"}},
    {"label": "c:node Grounding-Badge", "type": "Feature", "props": {"summary": "Jede c:node-Antwort deklariert offen ihre Beleg-Basis: chat (Gesprächs-Turn), allgemein (allgemeine Einschätzung, nicht belegt), gedächtnis (aus belegten Knoten synthetisiert), web (frische Quellen). Ehrlichkeits-Signal statt Blackbox.", "quelle": "c-node.ai"}},
    {"label": "c:node Souveränität", "type": "Prinzip", "props": {"summary": "Daten bleiben in der EU (eu-central-1), kein Training auf Kundendaten, Provenienz je Datenpunkt, on-prem/air-gapped via Ollama möglich. Ausgelegt auf EU-AI-Act-Konformität.", "quelle": "c-node.ai", "region": "EU"}},
    {"label": "try.c-node.ai", "type": "Angebot", "props": {"summary": "Die öffentliche c:node-Sandbox zum Ausprobieren — frictionless Login per E-Mail-Code, Cloud-LLM, keine lokale Installation nötig.", "quelle": "try.c-node.ai"}},
    {"label": "Creativate Labs", "type": "Organisation", "props": {"summary": "Hersteller von c:node und NENA; EU-Tech-Studio mit Fokus auf souveräne, belegbare KI für den Mittelstand.", "quelle": "creativate.tech"}},
]
_BASE_LINKS: list[tuple[str, str, str]] = [
    ("NENA", "c:node", "ist Teil von"),
    ("c:node Grounding-Badge", "NENA", "gehört zu"),
    ("c:node Souveränität", "c:node", "beschreibt"),
    ("try.c-node.ai", "c:node", "ist Sandbox von"),
    ("c:node", "Creativate Labs", "entwickelt von"),
]


# Demo-Fakten für die Fach-Agenten (Sandbox): ein kohärentes „Lieferant Mustermann"-Szenario
# über Einkauf/Verträge/Finanzen + HR/Verwaltung/Ops, damit die A2A-Kette im Demo etwas zu
# BELEGEN hat. Bewusst als Demo gekennzeichnet (label „Demo:", quelle „demo-beispiel") — kein
# Fake als echt. Wird in BASE_GROUP geseedet (immer abrufbar, keine echten Mandantendaten).
DEMO_DOMAIN_SEED: list[dict] = [
    {"label": "Demo: Rahmenvertrag Lieferant Mustermann GmbH", "type": "Vertrag", "props": {
        "summary": "Rahmenvertrag mit der Mustermann GmbH (Lieferant). Laufzeit 24 Monate, "
        "Kündigungsfrist 3 Monate zum Quartalsende (§8). Haftung auf den Auftragswert begrenzt "
        "(§11). Preisanpassungsklausel jährlich (§5).", "quelle": "demo-beispiel", "domain": "vertraege"}},
    {"label": "Demo: Bestellung BE-2026-042 (Mustermann GmbH)", "type": "Bestellung", "props": {
        "summary": "Offene Bestellung BE-2026-042 bei Mustermann GmbH über 12.000 €. Liefertermin "
        "seit 2 Wochen überfällig; kein Ersatztermin bestätigt.", "quelle": "demo-beispiel", "domain": "einkauf"}},
    {"label": "Demo: Zahlungsrückstand Mustermann GmbH", "type": "Buchung", "props": {
        "summary": "Zwei offene Eingangsrechnungen der Mustermann GmbH, zusammen 14.500 €, "
        "45 Tage überfällig. Liquiditätswirkung: mittel.", "quelle": "demo-beispiel", "domain": "finanzen"}},
    {"label": "Demo: Arbeitsvertrag Muster-Mitarbeiter", "type": "Arbeitsvertrag", "props": {
        "summary": "Arbeitsvertrag (Demo) mit Probezeit, die in 10 Tagen endet. Kündigungsfrist in "
        "der Probezeit: 2 Wochen. Danach 4 Wochen zum Monatsende.", "quelle": "demo-beispiel", "domain": "hr"}},
    {"label": "Demo: Antrag Gewerbeummeldung", "type": "Antrag", "props": {
        "summary": "Gewerbeummeldung (Demo) beim Gewerbeamt. Frist: binnen 4 Wochen nach der "
        "Änderung; erforderlich sind Formular GewA1 + Handelsregisterauszug.", "quelle": "demo-beispiel", "domain": "verwaltung"}},
    {"label": "Demo: Prozess Wareneingang", "type": "Prozess", "props": {
        "summary": "Wareneingangsprozess (Demo): Engpass an der Prüfstation, Durchlaufzeit aktuell "
        "+3 Tage. Betrifft u.a. Lieferungen der Mustermann GmbH.", "quelle": "demo-beispiel", "domain": "ops"}},
]
_DEMO_LINKS: list[tuple[str, str, str]] = [
    ("Demo: Bestellung BE-2026-042 (Mustermann GmbH)", "Demo: Rahmenvertrag Lieferant Mustermann GmbH", "läuft unter"),
    ("Demo: Zahlungsrückstand Mustermann GmbH", "Demo: Rahmenvertrag Lieferant Mustermann GmbH", "betrifft"),
    ("Demo: Prozess Wareneingang", "Demo: Bestellung BE-2026-042 (Mustermann GmbH)", "verzögert"),
]


# E2.5 — Seed-Wissen für die tenant-unabhängige Mesh-Ebene (generische Makro-Fakten,
# KEINE Mandantendaten/PII). Grundlage, damit neue Tenants ab Tag 1 Kontext haben.
MESH_SEED: list[dict] = [
    {"label": "EU AI Act", "type": "Konzept", "props": {"summary": "EU-KI-Verordnung: risikobasierte Klassen (verboten/hoch/begrenzt/minimal), Transparenz- und Governance-Pflichten für Hochrisiko-Systeme."}},
    {"label": "DSGVO", "type": "Konzept", "props": {"summary": "EU-Datenschutz-Grundverordnung: Rechtsgrundlagen, Betroffenenrechte, Zweckbindung, Datenminimierung, Auftragsverarbeitung."}},
    {"label": "Forschungszulage (BSFZ)", "type": "FundingProgram", "props": {"summary": "Steuerliche FuE-Förderung nach dem Forschungszulagengesetz; technologieoffen; über die Steuererklärung, bescheinigt durch die Bescheinigungsstelle Forschungszulage."}},
    {"label": "ZIM – Zentrales Innovationsprogramm Mittelstand", "type": "FundingProgram", "props": {"summary": "Zuschuss für marktnahe FuE-Projekte im Mittelstand, auch in Kooperation."}},
    {"label": "go-digital (BMWK)", "type": "FundingProgram", "props": {"summary": "Geförderte Beratung + Umsetzung zu Digitalisierung/IT-Sicherheit für kleine Unternehmen."}},
    {"label": "Mittelstand-Digitalisierung", "type": "Thema", "props": {"summary": "KMU-Digitalisierung: Prozessautomatisierung, Datenplattformen, KI-Assistenz; hoher Förder- und Beratungsbedarf."}},
    {"label": "Kommunale Stadtwerke", "type": "Thema", "props": {"summary": "Kommunale Versorger: Energie-/Beteiligungscontrolling, PPA-Pooling, Digitalisierung, öffentliche Beschaffung."}},
    {"label": "Agentic AI", "type": "Konzept", "props": {"summary": "KI-Agenten, die mehrstufige Aufgaben planen und über Tools ausführen; Nutzen v.a. bei wiederkehrenden, strukturierten Routineaufgaben."}},
    {"label": "Decision Intelligence", "type": "Konzept", "props": {"summary": "Entscheidungsunterstützung mit belegbarer, auditierbarer Gedächtnis statt Blackbox-Prognose."}},
    {"label": "Gedächtnis", "type": "Konzept", "props": {"summary": "Graph aus Entitäten + Beziehungen mit Provenienz; macht Antworten belegbar und auditierbar."}},
    {"label": "Reverse-Charge (EU-B2B)", "type": "Konzept", "props": {"summary": "Innergemeinschaftliche B2B-Leistungen: Steuerschuld wechselt auf den Empfänger bei gültiger USt-IdNr."}},
    {"label": "Lead-Scoring", "type": "Konzept", "props": {"summary": "Bewertung von Vertriebskontakten nach ICP-Fit; priorisiert Outreach; DSGVO-relevant bei Profiling."}},
]


# NENA-Markt-Ebene (bezahlt): kuratiertes, quellenbelegtes Cross-Tenant-Marktwissen.
# Free-Sandbox (nur Client-Ebene) sieht das NIE; erst `intel=true` schaltet market/mesh frei.
# Bewusst gepflegt (Provenienz je Knoten), nicht auto-generiert — das ist der Kaufwert.
MARKET_SEED: list[dict] = [
    {"label": "EXIST-Gründerstipendium", "type": "FundingProgram", "props": {"summary": "BMWK-Stipendium für Hochschul-Ausgründungen: Lebensunterhalt + Sachmittel + Coaching in der Frühphase.", "region": "DE", "stage": "pre-seed", "quelle": "exist.de"}},
    {"label": "High-Tech Gründerfonds (HTGF)", "type": "Investor", "props": {"summary": "Aktivster deutscher Seed-Investor; Tickets typ. 0,5–1 Mio € in Tech/Life-Science-Frühphase.", "region": "DE", "stage": "seed", "quelle": "htgf.de"}},
    {"label": "EIC Accelerator", "type": "FundingProgram", "props": {"summary": "EU-Förderung für Deep-Tech-Scaleups: Zuschuss bis 2,5 Mio € + optionale Eigenkapital-Komponente.", "region": "EU", "stage": "growth", "quelle": "eic.ec.europa.eu"}},
    {"label": "INVEST – Zuschuss für Wagniskapital", "type": "FundingProgram", "props": {"summary": "20 % Erwerbszuschuss für Business Angels auf Anteile an jungen innovativen Unternehmen.", "region": "DE", "stage": "seed", "quelle": "bafa.de"}},
    {"label": "DACH HealthTech-Cluster", "type": "Thema", "props": {"summary": "Dichte an Digital-Health/MedTech-Gründungen in Berlin, München, Zürich; getrieben von Uni-Kliniken + regulatorischer Expertise (MDR).", "region": "DACH", "quelle": "nena-market"}},
    {"label": "Climate-Tech Finanzierungswelle", "type": "TrendSignal", "props": {"summary": "Überdurchschnittlicher Kapitalzufluss in europäische Climate/Energy-Startups trotz allgemeiner VC-Zurückhaltung.", "region": "EU", "quelle": "nena-market"}},
    {"label": "Accelerator: UnternehmerTUM / XPRENEURS", "type": "Accelerator", "props": {"summary": "Führender Münchner Inkubator/Accelerator; batch-basiert, starkes Deep-Tech- und Industrienetzwerk.", "region": "DE", "quelle": "unternehmertum.de"}},
    {"label": "Accelerator: Station F (Paris)", "type": "Accelerator", "props": {"summary": "Größter Startup-Campus Europas; relevanter Signal-Pool für früh-Phase EU-Gründungen.", "region": "EU", "quelle": "stationf.co"}},
    {"label": "GmbH-Gründung (Standard-Rechtsform)", "type": "Konzept", "props": {"summary": "Häufigste deutsche Kapitalgesellschaft für Startups; 25.000 € Stammkapital, Haftungsbeschränkung, notarielle Gründung.", "region": "DE", "quelle": "nena-market"}},
    {"label": "SAFE / Wandeldarlehen", "type": "Konzept", "props": {"summary": "Frühphasen-Finanzierungsinstrumente: Wandeldarlehen (DE-üblich) bzw. SAFE (US) verschieben die Bewertung in die nächste Runde.", "quelle": "nena-market"}},
    {"label": "Marktsignal: KI-Ausgründungen aus Forschung", "type": "TrendSignal", "props": {"summary": "Steigende Zahl an KI-Spinoffs aus Fraunhofer/Max-Planck/Unis; oft technisch stark, GTM-schwach — Beratungsbedarf hoch.", "region": "DE", "quelle": "nena-market"}},
    {"label": "MDR – Medical Device Regulation", "type": "Konzept", "props": {"summary": "EU-Verordnung für Medizinprodukte; hohe Konformitäts-/Zertifizierungshürde, prägt Zeit-/Kapitalbedarf von HealthTech-Startups.", "region": "EU", "quelle": "nena-market"}},
]


# ── NENA-Vorschau-Scheibe (PUBLIC_DEMO) ────────────────────────────────────────
# Ziel: der Free-Sandbox *etwas* NENA-Markttiefe geben, ohne die bezahlte Ebene zu
# verschenken. Eine bewusst KURATIERTE, breite-aber-flache Scheibe aus rein
# öffentlichem, lizenzsauberem Wissen (Förderung/Regulierung/Ökosystem/Markt) — je
# Knoten mit Quelle belegt und als `preview` markiert. KEINE Nutzer-/Mandantendaten,
# KEIN Korpus/keine Gewichte. Wird als eigener Layer "NENA-Marktwissen · Vorschau"
# eingeblendet und immer von einem Upgrade-CTA begleitet. Die volle Tiefe (market/mesh,
# cross-tenant gelernt, deutlich mehr Knoten + 1-Hop-Expansion) bleibt `intel=true`.
PREVIEW_GROUP = os.getenv("PREVIEW_GROUP", "cnode-nena-preview")

PREVIEW_SEED: list[dict] = [
    # — Förderung (DE/EU) —
    {"label": "Forschungszulage (BSFZ)", "type": "FundingProgram", "props": {"summary": "Steuerliche FuE-Förderung nach dem Forschungszulagengesetz — technologieoffen, rückwirkend beantragbar, bescheinigt durch die BSFZ.", "region": "DE", "domain": "foerderung", "quelle": "bsfz.de"}},
    {"label": "ZIM – Zentrales Innovationsprogramm Mittelstand", "type": "FundingProgram", "props": {"summary": "Zuschuss für marktnahe FuE im Mittelstand, auch in Kooperation mit Forschung.", "region": "DE", "domain": "foerderung", "quelle": "zim.de"}},
    {"label": "go-digital (BMWK)", "type": "FundingProgram", "props": {"summary": "Geförderte Beratung + Umsetzung zu Digitalisierung/IT-Sicherheit für kleine Unternehmen.", "region": "DE", "domain": "foerderung", "quelle": "bmwk.de"}},
    {"label": "Digital Jetzt (BMWK)", "type": "FundingProgram", "props": {"summary": "Investitionszuschuss für Digitalisierung + Qualifizierung in KMU.", "region": "DE", "domain": "foerderung", "quelle": "bmwk.de"}},
    {"label": "EXIST-Gründerstipendium", "type": "FundingProgram", "props": {"summary": "BMWK-Stipendium für Hochschul-Ausgründungen: Lebensunterhalt + Sachmittel + Coaching in der Frühphase.", "region": "DE", "domain": "foerderung", "quelle": "exist.de"}},
    {"label": "INVEST – Zuschuss für Wagniskapital", "type": "FundingProgram", "props": {"summary": "20 % Erwerbszuschuss für Business Angels auf Anteile an jungen innovativen Unternehmen.", "region": "DE", "domain": "foerderung", "quelle": "bafa.de"}},
    {"label": "KfW-Gründerkredit", "type": "FundingProgram", "props": {"summary": "Zinsgünstige Förderkredite der KfW für Gründung + Wachstum (u.a. ERP-Gründerkredit).", "region": "DE", "domain": "foerderung", "quelle": "kfw.de"}},
    {"label": "EIC Accelerator", "type": "FundingProgram", "props": {"summary": "EU-Förderung für Deep-Tech-Scaleups: Zuschuss bis 2,5 Mio € + optionale Eigenkapital-Komponente.", "region": "EU", "domain": "foerderung", "quelle": "eic.ec.europa.eu"}},
    {"label": "Horizon Europe", "type": "FundingProgram", "props": {"summary": "EU-Rahmenprogramm für Forschung + Innovation; Verbundprojekte, hohe Fördersätze, kompetitiv.", "region": "EU", "domain": "foerderung", "quelle": "ec.europa.eu"}},
    # — Regulierung / Compliance —
    {"label": "EU AI Act", "type": "Konzept", "props": {"summary": "EU-KI-Verordnung: risikobasierte Klassen (verboten/hoch/begrenzt/minimal), Transparenz- + Governance-Pflichten für Hochrisiko-Systeme.", "region": "EU", "domain": "regulierung", "quelle": "artificialintelligenceact.eu"}},
    {"label": "DSGVO", "type": "Konzept", "props": {"summary": "EU-Datenschutz-Grundverordnung: Rechtsgrundlagen, Betroffenenrechte, Zweckbindung, Datenminimierung, Auftragsverarbeitung.", "region": "EU", "domain": "regulierung", "quelle": "eur-lex.europa.eu"}},
    {"label": "NIS2-Richtlinie", "type": "Konzept", "props": {"summary": "EU-Cybersicherheitsrichtlinie: erweiterte Melde- + Sicherheitspflichten für viele Mittelständler in kritischen Sektoren.", "region": "EU", "domain": "regulierung", "quelle": "eur-lex.europa.eu"}},
    {"label": "EU Data Act", "type": "Konzept", "props": {"summary": "EU-Datengesetz: Zugangs- + Portabilitätsrechte für IoT-/Nutzungsdaten, Cloud-Wechsel, faire Vertragsklauseln.", "region": "EU", "domain": "regulierung", "quelle": "eur-lex.europa.eu"}},
    {"label": "Lieferkettensorgfaltspflichtengesetz (LkSG)", "type": "Konzept", "props": {"summary": "Deutsche Sorgfaltspflichten in Lieferketten (Menschenrechte/Umwelt); Risikoanalyse + Berichtspflicht, gestaffelt nach Größe.", "region": "DE", "domain": "regulierung", "quelle": "bafa.de"}},
    {"label": "E-Rechnungspflicht (B2B)", "type": "Konzept", "props": {"summary": "Verpflichtende strukturierte E-Rechnung im inländischen B2B ab 2025 (Empfang), gestaffelte Ausstellungspflichten — treibt Prozess-Digitalisierung.", "region": "DE", "domain": "regulierung", "quelle": "bmf.de"}},
    {"label": "GoBD", "type": "Konzept", "props": {"summary": "Grundsätze ordnungsmäßiger Buchführung + Datenzugriff: Unveränderbarkeit, Nachvollziehbarkeit, Verfahrensdokumentation.", "region": "DE", "domain": "regulierung", "quelle": "bmf.de"}},
    {"label": "MDR – Medical Device Regulation", "type": "Konzept", "props": {"summary": "EU-Verordnung für Medizinprodukte; hohe Konformitäts-/Zertifizierungshürde, prägt Zeit-/Kapitalbedarf von HealthTech.", "region": "EU", "domain": "regulierung", "quelle": "eur-lex.europa.eu"}},
    # — Ökosystem / Markt (DACH) —
    {"label": "Mittelstand-Digitalisierung", "type": "Thema", "props": {"summary": "KMU-Digitalisierung: Prozessautomatisierung, Datenplattformen, KI-Assistenz — hoher Förder- + Beratungsbedarf.", "region": "DE", "domain": "markt", "quelle": "nena-vorschau"}},
    {"label": "Souveräne KI – Nachfrage Mittelstand", "type": "TrendSignal", "props": {"summary": "Wachsende Nachfrage nach EU-gehosteter, belegbarer KI (Datenhoheit, EU-AI-Act-Konformität) statt US-Blackbox-Modellen.", "region": "DACH", "domain": "markt", "quelle": "nena-vorschau"}},
    {"label": "GenAI-Adoption im Mittelstand", "type": "TrendSignal", "props": {"summary": "Von Pilot zu Produktion: Fokus verschiebt sich auf belegbare, integrierte Use-Cases (Wissen, Vertrieb, Verwaltung) mit ROI-Nachweis.", "region": "DACH", "domain": "markt", "quelle": "nena-vorschau"}},
    {"label": "Fachkräftemangel", "type": "Thema", "props": {"summary": "Struktureller Personalengpass in DACH; Treiber für Automatisierung, Assistenzsysteme + Prozessverschlankung.", "region": "DACH", "domain": "markt", "quelle": "nena-vorschau"}},
    {"label": "Kommunale Stadtwerke", "type": "Thema", "props": {"summary": "Kommunale Versorger: Energie-/Beteiligungscontrolling, PPA-Pooling, Digitalisierung, öffentliche Beschaffung.", "region": "DE", "domain": "markt", "quelle": "nena-vorschau"}},
    {"label": "GovTech / öffentliche Verwaltung", "type": "Thema", "props": {"summary": "Digitalisierung der Verwaltung (OZG): Antragsstrecken, Fachverfahren, KI-gestützte Sachbearbeitung mit Nachweispflicht.", "region": "DE", "domain": "markt", "quelle": "nena-vorschau"}},
    {"label": "Climate-Tech Finanzierungswelle", "type": "TrendSignal", "props": {"summary": "Überdurchschnittlicher Kapitalzufluss in europäische Climate/Energy-Startups trotz allgemeiner VC-Zurückhaltung.", "region": "EU", "domain": "markt", "quelle": "nena-vorschau"}},
    {"label": "DACH HealthTech-Cluster", "type": "Thema", "props": {"summary": "Dichte an Digital-Health/MedTech-Gründungen in Berlin, München, Zürich; getrieben von Uni-Kliniken + MDR-Expertise.", "region": "DACH", "domain": "markt", "quelle": "nena-vorschau"}},
    {"label": "KI-Ausgründungen aus Forschung", "type": "TrendSignal", "props": {"summary": "Steigende Zahl an KI-Spinoffs aus Fraunhofer/Max-Planck/Unis — technisch stark, GTM-schwach; hoher Beratungsbedarf.", "region": "DE", "domain": "markt", "quelle": "nena-vorschau"}},
    # — Recht / Kapital / Struktur —
    {"label": "GmbH (Standard-Rechtsform)", "type": "Konzept", "props": {"summary": "Häufigste deutsche Kapitalgesellschaft; 25.000 € Stammkapital, Haftungsbeschränkung, notarielle Gründung.", "region": "DE", "domain": "recht", "quelle": "nena-vorschau"}},
    {"label": "UG (haftungsbeschränkt)", "type": "Konzept", "props": {"summary": "Mini-GmbH ab 1 € Stammkapital mit Thesaurierungspflicht; niedrigschwelliger Einstieg in die Haftungsbeschränkung.", "region": "DE", "domain": "recht", "quelle": "nena-vorschau"}},
    {"label": "SAFE / Wandeldarlehen", "type": "Konzept", "props": {"summary": "Frühphasen-Instrumente: Wandeldarlehen (DE-üblich) bzw. SAFE (US) verschieben die Bewertung in die nächste Runde.", "domain": "recht", "quelle": "nena-vorschau"}},
    {"label": "ESOP / VSOP (Mitarbeiterbeteiligung)", "type": "Konzept", "props": {"summary": "Anteils- bzw. virtuelle Beteiligungsprogramme zur Mitarbeiterbindung; in DE steuerlich zunehmend erleichtert.", "region": "DE", "domain": "recht", "quelle": "nena-vorschau"}},
    {"label": "Reverse-Charge (EU-B2B)", "type": "Konzept", "props": {"summary": "Innergemeinschaftliche B2B-Leistungen: Steuerschuld wechselt auf den Empfänger bei gültiger USt-IdNr.", "region": "EU", "domain": "recht", "quelle": "nena-vorschau"}},
    # — GTM / Vertrieb / Methodik —
    {"label": "Ideal Customer Profile (ICP)", "type": "Konzept", "props": {"summary": "Präzises Zielkundenprofil als Grundlage für fokussierten Vertrieb + Lead-Priorisierung.", "domain": "vertrieb", "quelle": "nena-vorschau"}},
    {"label": "Lead-Scoring", "type": "Konzept", "props": {"summary": "Bewertung von Vertriebskontakten nach ICP-Fit; priorisiert Outreach; DSGVO-relevant bei Profiling.", "domain": "vertrieb", "quelle": "nena-vorschau"}},
    {"label": "PPA-Pooling (KMU)", "type": "Konzept", "props": {"summary": "Bündelung kleiner Abnehmer zu verhandlungsfähigen Power-Purchase-Agreements — Marktzugang für erneuerbare Erzeuger.", "region": "DACH", "domain": "energie", "quelle": "nena-vorschau"}},
    {"label": "Decision Intelligence", "type": "Konzept", "props": {"summary": "Entscheidungsunterstützung mit belegbarem, auditierbarem Gedächtnis statt Blackbox-Prognose.", "domain": "methodik", "quelle": "nena-vorschau"}},
    {"label": "Agentic AI", "type": "Konzept", "props": {"summary": "KI-Agenten, die mehrstufige Aufgaben planen + über Tools ausführen; Nutzen v.a. bei wiederkehrenden, strukturierten Routinen.", "domain": "methodik", "quelle": "nena-vorschau"}},
    {"label": "Provenienz / Audit-Trail", "type": "Konzept", "props": {"summary": "Quelle je Aussage + nachvollziehbarer Rechenweg — Grundlage für EU-AI-Act-Konformität + Vertrauen in KI-Antworten.", "domain": "methodik", "quelle": "nena-vorschau"}},
]

# Ein paar Kanten, damit die Vorschau im Graph als kohärentes Feld statt loser Punkte erscheint.
_PREVIEW_LINKS: list[tuple[str, str, str]] = [
    ("Forschungszulage (BSFZ)", "Mittelstand-Digitalisierung", "fördert"),
    ("ZIM – Zentrales Innovationsprogramm Mittelstand", "KI-Ausgründungen aus Forschung", "fördert"),
    ("go-digital (BMWK)", "Mittelstand-Digitalisierung", "fördert"),
    ("EU AI Act", "Souveräne KI – Nachfrage Mittelstand", "treibt"),
    ("DSGVO", "Provenienz / Audit-Trail", "verlangt"),
    ("E-Rechnungspflicht (B2B)", "Mittelstand-Digitalisierung", "treibt"),
    ("MDR – Medical Device Regulation", "DACH HealthTech-Cluster", "prägt"),
    ("EXIST-Gründerstipendium", "KI-Ausgründungen aus Forschung", "unterstützt"),
    ("PPA-Pooling (KMU)", "Kommunale Stadtwerke", "betrifft"),
    ("Lead-Scoring", "Ideal Customer Profile (ICP)", "basiert auf"),
    ("Decision Intelligence", "Provenienz / Audit-Trail", "beruht auf"),
]


def _include_preview(intel: bool | None) -> bool:
    """Ob die kuratierte NENA-Vorschau-Scheibe für DIESE Anfrage eingeblendet wird.

    Nur in der öffentlichen Free-Sandbox (PUBLIC_DEMO) UND wenn die volle geteilte Ebene
    NICHT freigeschaltet ist. Bezahlte Tenants (intel=true) bekommen market/mesh direkt —
    dann ist die Vorschau überflüssig.
    """
    return PUBLIC_DEMO and not _use_shared(intel)


class ContributeReq(BaseModel):
    client_id: str = "creativate"


# ---------------------------------------------------------------- request models

class ClassifyReq(BaseModel):
    text: str


class RouteFormSpec(BaseModel):
    id: str
    title: str = ""
    kind: str = "assessment"
    triggers: list[str] = Field(default_factory=list)


class RouteReq(BaseModel):
    """Orchestrator-Eingabe: Nachricht + die für diesen Tenant verfügbaren Formulare (FraBö)."""
    text: str
    client_id: str = "creativate"
    forms: list[RouteFormSpec] = Field(default_factory=list)
    history: list = Field(default_factory=list)


class AnswerReq(BaseModel):
    text: str
    client_id: str = "creativate"
    history: list = Field(default_factory=list)
    provider: str = "ollama"
    teams: list[str] = Field(default_factory=list)  # O2b — Team-IDs des Users (team-private Ebene)
    intel: bool | None = None  # Entitlement (NENA): überschreibt SHARED_LAYERS; bff setzt es je Tenant
    system_override: str | None = None  # Persona-System (Fach-Agent) statt CHAT/CONSULT_SYSTEM


class SynthesizeReq(BaseModel):
    query: str
    facts: str = ""
    provider: str = "ollama"


class RetrieveReq(BaseModel):
    text: str
    client_id: str = "creativate"
    limit: int = 8
    teams: list[str] = Field(default_factory=list)  # O2b — Team-IDs des Users
    intel: bool | None = None  # Entitlement (NENA): überschreibt SHARED_LAYERS


class ExtractReq(BaseModel):
    text: str
    client_id: str = "creativate"
    max_nodes: int = 6
    provider: str = "ollama"


class EnrichUrlReq(BaseModel):
    url: str
    client_id: str = "creativate"
    max_nodes: int = 15
    provider: str = "ollama"


ASSETS_URL = os.getenv("ASSETS_URL", "http://assets:8030").rstrip("/")

# LLM-Extract-Typen (DE) → Graph-/Viz-Typen.
_ONTO_TYPE_MAP = {
    "organisation": "Company", "person": "Person", "konzept": "Thought",
    "dokument": "Document", "entscheidung": "Decision", "produkt": "Product",
    "thema": "Thought", "compliance": "Compliance", "fundingprogram": "FundingProgram",
}


def _graph_slug(s: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in (s or "")).strip("_")[:60] or "node"


class GovernReq(BaseModel):
    query: str
    facts: str = ""
    context: str = ""
    provider: str = "ollama"


class IngestReq(BaseModel):
    label: str
    type: str = "Document"
    props: dict = Field(default_factory=dict)
    links: list = Field(default_factory=list)
    # Echter Dokument-/Quelltext. Wird an NEN als primärer `content` durchgereicht,
    # damit dessen Extraktor einen VERBUNDENEN Subgraphen (Quelle + Entitäten + Kanten)
    # ableitet — statt eines isolierten, textlosen Stub-Knotens.
    content: str = ""
    client_id: str = "creativate"
    # SCOPE v2/v3 Ingest-Ebene: in welche group_ids geschrieben wird.
    # ["client"] (default) → nur Mandanten-Graph; ["client","market"] → zusätzlich
    # die geteilte Market-Intelligence; "mesh" → tenant-unabhängige Data-Mesh-Ebene.
    # Market/Mesh direkt schreiben darf laut Governance nur Super-Admin (in der BFF
    # durchgesetzt); die Engine schreibt, was ankommt.
    levels: list[str] = Field(default_factory=lambda: ["client"])


class ArtifactReq(BaseModel):
    kind: str = "memo"
    thread_id: str = ""
    client_id: str = "creativate"
    context: str = ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _chat_prompt(req: "AnswerReq") -> str:
    """Gesprächs-Prompt inkl. kurzer History (für flüssige Berater-Konversation)."""
    convo = ""
    for h in (req.history or [])[-4:]:
        if isinstance(h, dict):
            role = h.get("role", "user")
            content = h.get("content") or h.get("text") or ""
            if content:
                convo += f"{'Nutzer' if role == 'user' else 'Assistent'}: {content}\n"
    return f"{convo}Nutzer: {req.text}\nAssistent:"


# ---------------------------------------------------------------- endpoints

@app.get("/health")
async def health():
    nen_health = await nen.health()
    try:
        models = await llm.list_ollama_models()
        llm_reachable = True
    except Exception:
        models, llm_reachable = [], False
    warm = await llm.loaded_models()

    return {
        "status": "ok",
        "service": "engine",
        "nen_ai": {
            "url": nen.NEN_AI_URL,
            "reachable": nen_health.get("reachable", False),
            "neo4j": nen_health.get("neo4j"),
            "model": nen_health.get("ollama"),
        },
        "llm": {
            "provider": llm.resolve_provider(""),   # Default-Provider (LLM_PROVIDER, sonst ollama)
            "default_provider": llm.DEFAULT_PROVIDER or "ollama",
            "providers": llm.provider_status(),      # was die Shell zum Umschalten anbieten darf
            "url": llm.OLLAMA_URL,
            "reachable": llm_reachable,
            "model": llm.OLLAMA_MODEL,
            "available_models": models,
            "keep_alive": "30m",
            "warm_models": warm,
            "warm": any(m.get("name") == llm.OLLAMA_MODEL for m in warm),
            "claude_configured": bool(llm.ANTHROPIC_API_KEY),
            "gemini_configured": bool(llm.GOOGLE_API_KEY),
        },
    }


@app.post("/classify")
async def classify(req: ClassifyReq):
    intent, method, trace = await llm.classify(req.text)
    return {"intent": intent, "method": method, "trace": trace}


# ---------------------------------------------------------------- Orchestrator / Intent-Routing

def _norm(s: object) -> str:
    """Normalisieren für robusten Match: kleingeschrieben, Diakritika + Sonderzeichen entfernt.
    „Quartals-Report" → „quartalsreport", „quarterly report" → „quarterlyreport"."""
    t = unicodedata.normalize("NFKD", str(s or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", t.lower())


def _norm_tokens(s: object) -> list[str]:
    """Wie _norm, aber tokenweise (Wortgrenzen bleiben) — für Token-Überlappung."""
    t = unicodedata.normalize("NFKD", str(s or ""))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return re.findall(r"[a-z0-9]+", t)


# „Knoten ins Netzwerk aufnehmen" (Graph-Ingest) — NICHT Dokument-Upload.
_INGEST_NODES_RE = re.compile(
    r"(knoten|entit\w+|node[ns]?)\s+.{0,30}?(aufnehm|aufzunehm|hinzu|anleg|erfass|ergänz|ergaenz|einpfleg)"
    r"|(ins?\s+(das\s+)?(netzwerk|graph|wissensgraph)).{0,25}?(aufnehm|aufzunehm|hinzu|ergänz|ergaenz|einpfleg|erweiter|ausbau)"
    r"|(netzwerk|wissensgraph)\s+.{0,20}?(erweiter|ausbau|aufbau|wachs)"
    r"|add\s+(a\s+)?node",
    re.IGNORECASE,
)

# Aktionsverben, die ein Formular-/Assistenten-Start plausibel machen.
_FORM_ACTION_HINTS = (
    "ausfüll", "ausfuell", "füll", "fuell", "starten", "start ", "erstell", "durchführ",
    "durchfuehr", "beginn", "loslegen", "aufnehmen", "aufnahme", "report", "bewert", "assessment",
    "prompt starten", "assistent",
)


def _match_form(text: str, forms: list[RouteFormSpec]) -> tuple[str | None, str, int]:
    """Deterministischer, robuster Form-Match. Längster normalisierter Treffer gewinnt
    (disambiguiert z.B. Impact-Score vs. Quartalsreport). → (form_id, matched_key, score)."""
    nt = _norm(text)
    if not nt:
        return None, "", 0
    best_id, best_key, best_len = None, "", 0
    for f in forms:
        for k in [f.id, f.id.replace("-", " "), f.title, *(f.triggers or [])]:
            nk = _norm(k)
            if len(nk) >= 4 and nk in nt and len(nk) > best_len:
                best_id, best_key, best_len = f.id, k, len(nk)
    return best_id, best_key, best_len


def _form_plausible(text: str, forms: list[RouteFormSpec]) -> bool:
    """Lohnt sich der LLM-Router? Nur wenn Aktionsverb ODER Token-Überlappung mit einem Formular."""
    low = text.lower()
    if any(h in low for h in _FORM_ACTION_HINTS):
        return True
    toks = set(_norm_tokens(text))
    fw: set[str] = set()
    for f in forms:
        for k in [f.title, *(f.triggers or [])]:
            fw |= {w for w in _norm_tokens(k) if len(w) >= 4}
    return bool(toks & fw)


async def _llm_route_form(text: str, forms: list[RouteFormSpec]) -> tuple[str | None, list[dict]]:
    """LLM-Fallback: Will der Nutzer eines der Formulare starten? → form_id | None."""
    listing = "\n".join(f"- {f.id}: {f.title}" for f in forms)
    prompt = (
        f"Verfügbare Formulare/Assistenten dieses Mandanten:\n{listing}\n\n"
        f"Nachricht des Nutzers: \"{text}\"\n\n"
        f"Will der Nutzer eines dieser Formulare ausfüllen oder starten? "
        f"Antworte NUR mit der passenden id aus der Liste — oder 'none', wenn keins gemeint ist."
    )
    try:
        out, _mdl = await llm.ollama_generate(
            prompt, system="Du bist ein Intent-Router. Antworte mit genau einem Wort (einer id oder 'none').",
            max_tokens=12)
    except Exception:  # noqa: BLE001
        return None, [{"step": "route", "method": "llm", "result": "error"}]
    ans = _norm(out)
    for f in forms:
        nid = _norm(f.id)
        if nid and (nid in ans or ans in nid):
            return f.id, [{"step": "route", "method": "llm", "result": out.strip()}]
    return None, [{"step": "route", "method": "llm", "result": (out.strip() or "none")}]


@app.post("/route")
async def route(req: RouteReq):
    """Tenant-Orchestrator: entscheidet den Pfad EINER Nachricht deterministisch (keyword-first)
    und fällt nur bei Formular-Plausibilität auf den LLM zurück.

    → {route: form|graph_display|graph_ingest|knowledge|chat, form_id?, method, confidence?, trace}.
    """
    text = req.text or ""
    t = text.strip().lower()
    trace: list[dict] = []

    # 0) Expliziter Befehl (/id oder exakte id) → Formular sofort.
    for f in req.forms:
        if t == f"/{f.id}" or t == f.id.lower():
            return {"route": "form", "form_id": f.id, "method": "command", "trace": trace}

    # 1) Robuster, normalisierter Form-Match (Bindestrich/Akzente/Groß-klein egal).
    fid, key, score = _match_form(text, req.forms)
    if fid:
        trace.append({"step": "route", "method": "keyword", "match": key})
        return {"route": "form", "form_id": fid, "method": "keyword",
                "confidence": round(min(1.0, score / 12), 2), "trace": trace}

    # 2) Graph-Anzeige („zeig den Graphen").
    if llm.is_graph_display(text):
        return {"route": "graph_display", "method": "keyword", "trace": trace}

    # 3) Knoten ins Netzwerk aufnehmen (Graph-Ingest, kein Formular getroffen).
    if _INGEST_NODES_RE.search(text):
        trace.append({"step": "route", "method": "keyword", "match": "graph-ingest"})
        return {"route": "graph_ingest", "method": "keyword", "trace": trace}

    # 4) LLM-Fallback für Paraphrasen — nur wenn form-plausibel (spart Latenz im Normal-Chat).
    if req.forms and _form_plausible(text, req.forms):
        fid2, tr = await _llm_route_form(text, req.forms)
        trace += tr
        if fid2:
            return {"route": "form", "form_id": fid2, "method": "llm", "trace": trace}

    # 5) Sonst Wissens-/Chat-Pfad (gleiche Heuristik wie _plan_answer).
    if llm.is_conversational(text) or llm.is_generation(text) or not llm.needs_retrieval(text):
        return {"route": "chat", "method": "heuristic", "trace": trace}
    return {"route": "knowledge", "method": "heuristic", "trace": trace}


def _team_group(client_group: str, team_id: str) -> str:
    """Group-id der team-privaten Ebene (O2b). Nur Team-Mitglieder erhalten diese id."""
    return f"{client_group}__team__{team_id}"


async def _retrieve_teams(text: str, client_group: str, teams: list[str], limit: int = 6) -> list[dict]:
    """Team-private Treffer über alle Teams des Users (Layer 'team')."""
    groups = [_team_group(client_group, t) for t in (teams or []) if t]
    if not groups:
        return []
    results = await asyncio.gather(*[nen.retrieve(text, g, limit=limit) for g in groups])
    out: list[dict] = []
    for srcs, _ok in results:
        for s in srcs:
            s["layer"] = "team"
            out.append(s)
    return out


async def _expand_neighbors(groups: list[str], relevant: list[dict],
                            max_per_node: int = 6, cap: int = 14) -> list[str]:
    """1-Hop-Nachbarn der relevanten Knoten als zusätzliche belegte Fakten.

    Holt die Gruppen-Graphen einmal, baut Adjazenz (per Knoten-ID) + Label→ID-Brücke und
    formt je Treffer die verbundenen Knoten als „A —REL→ B: <summary>". So beantwortet der
    Chat auch Fragen, deren Antwort in den Nachbarknoten steht (z.B. was ein Hub „anbietet")."""
    id2node: dict[str, dict] = {}
    label2id: dict[str, str] = {}
    adj: dict[str, list[tuple[str, str]]] = {}
    for g in groups:
        try:
            graph, ok = await nen.graph(g, limit=150)
        except Exception:  # noqa: BLE001
            ok = False
        if not ok:
            continue
        for n in graph.get("nodes", []):
            nid = n.get("id") or ""
            lbl = (n.get("label") or "").strip()
            if nid:
                id2node[nid] = n
            if lbl:
                label2id[lbl.lower()] = nid or lbl
        for e in graph.get("edges", []):
            s, t, rel = e.get("source"), e.get("target"), e.get("rel", "RELATED_TO")
            if s and t:
                adj.setdefault(s, []).append((rel, t))
                adj.setdefault(t, []).append((rel, s))

    lines: list[str] = []
    seen: set[tuple] = set()
    for src in relevant:
        sid = src.get("id") or label2id.get((src.get("label") or "").strip().lower())
        if not sid or sid not in adj:
            continue
        for rel, other in adj[sid][:max_per_node]:
            on = id2node.get(other)
            if not on:
                continue
            key = (sid, rel, other)
            if key in seen:
                continue
            seen.add(key)
            olbl = (on.get("label") or "").strip()
            osum = ((on.get("props") or {}).get("summary")
                    or (on.get("props") or {}).get("content") or "")
            lines.append(f"- {src.get('label')} —{rel}→ {olbl}"
                         + (f": {osum}" if osum else ""))
            if len(lines) >= cap:
                return lines
    return lines


async def _plan_answer(req: AnswerReq) -> dict:
    """Entscheidet Pfad + Prompt/Quellen VOR der Generierung (geteilt von /answer & /answer/stream).

    Rückgabe: system, prompt, max_tokens, sources, trace (pre-gen), ctas, layers, grounded, facts.
    """
    zero = {"team_hits": 0, "client_hits": 0, "market_hits": 0, "mesh_hits": 0, "preview_hits": 0}
    # `grounding` deklariert offen die Beleg-Basis der Antwort (Ehrlichkeits-Signal fürs UI):
    #   chat       = Gesprächs-/Schreib-Turn, keine Faktenbehauptung
    #   allgemein  = allgemeine Einschätzung (NICHT aus dem Gedächtnis belegt)
    #   gedaechtnis= aus belegten Knoten (Mandant/Market/Mesh) synthetisiert
    base = {"sources": [], "trace": [], "ctas": None, "layers": zero,
            "grounded": False, "facts": "", "grounding": "chat"}

    # 1) Konversationell (Begrüßung/Meta/Small-Talk) → direkter Chat, kein Graph.
    if llm.is_conversational(req.text):
        return {**base, "system": CHAT_SYSTEM, "prompt": _chat_prompt(req), "max_tokens": 1100}
    # 1b) Reine Schreib-/Generier-Aufgabe → mit History verfassen, kein Retrieval.
    if llm.is_generation(req.text):
        return {**base, "system": CHAT_SYSTEM, "prompt": _chat_prompt(req), "max_tokens": 1600}
    # 1c) Klar generische Erklär-/Wissensfrage ohne Tenant-Bezug → kein Retrieval, kein CTA.
    if not llm.needs_retrieval(req.text):
        return {**base, "system": CHAT_SYSTEM, "prompt": _chat_prompt(req), "max_tokens": 1100,
                "grounding": "allgemein"}

    # 2) Ebenen-Retrieval (kein LLM) + Relevanz-Filter. Reihenfolge/Priorität:
    #    team-private → client (org) → market → mesh.
    client_group = map_client_to_group(req.client_id)
    use_shared = _use_shared(req.intel)
    # Produkt-Identitäts-Ebene (c:node/NENA) IMMER mitziehen — auch in PUBLIC_DEMO und über
    # alle per-User-Workspaces hinweg. Read-only Produktwissen, keine Nutzerdaten → belegt
    # („Was ist c:node?" → grounding: gedaechtnis statt allgemein).
    base_task = nen.retrieve(req.text, BASE_GROUP, limit=4)
    show_preview = _include_preview(req.intel)
    src_p: list[dict] = []
    if not use_shared:
        # Ohne Fach-Domäne/Entitlement (oder Public-Demo): eigene Client-Ebene + Basis-Wissen.
        # In der Free-Sandbox zusätzlich die kuratierte NENA-Vorschau-Scheibe (Teaser-Tiefe).
        if show_preview:
            (src_c, _rc), (src_b, _rb), (src_p, _rp) = await asyncio.gather(
                nen.retrieve(req.text, client_group, limit=8), base_task,
                nen.retrieve(req.text, PREVIEW_GROUP, limit=4))
        else:
            (src_c, _rc), (src_b, _rb) = await asyncio.gather(
                nen.retrieve(req.text, client_group, limit=8), base_task)
        src_m, src_x, src_t = [], [], []
    else:
        (src_c, _rc), (src_m, _rm), (src_x, _rx), (src_b, _rb) = await asyncio.gather(
            nen.retrieve(req.text, client_group, limit=8),
            nen.retrieve(req.text, MARKET_GROUP, limit=6),
            nen.retrieve(req.text, MESH_GROUP, limit=6),
            base_task,
        )
        src_t = await _retrieve_teams(req.text, client_group, req.teams, limit=6)
    src_c = src_b + src_c            # Produktwissen zählt als belegte Client-Ebene
    for s in src_c:
        s["layer"] = "client"
    for s in src_m:
        s["layer"] = "market"
    for s in src_x:
        s["layer"] = "mesh"
    for s in src_p:
        s["layer"] = "preview"
    layers = {"team_hits": len(src_t), "client_hits": len(src_c),
              "market_hits": len(src_m), "mesh_hits": len(src_x), "preview_hits": len(src_p)}
    merged = nen.rank_sources(req.text, src_t + src_c + src_m + src_x + src_p,
                              weights=LEARNED_WEIGHTS.get(client_group))
    relevant = nen.relevant_sources(req.text, merged)
    retrieve_step = {"step": "retrieve", "method": "nen.query",
                     "result": f"{len(relevant)} relevant / {len(merged)} gesamt",
                     "service": "nen-ai"}

    # E2.3: Aus einer belegten Antwort lernen — genutzte Quellen-Terme gewinnen Gewicht.
    if relevant:
        _learn_from_sources(client_group, relevant)
        # Loop 2: gedrosselte, governance-sichere Auto-Contribution in den globalen Mesh.
        # Nur wenn geteilte Ebenen aktiv sind (Demo/ohne-Domäne tragen nie zum Mesh bei).
        if use_shared:
            _GROUNDED_COUNT[client_group] = _GROUNDED_COUNT.get(client_group, 0) + 1
            if _GROUNDED_COUNT[client_group] % _MESH_EVERY == 0:
                try:
                    await _mesh_contribute_group(client_group)
                except Exception:  # noqa: BLE001
                    pass  # Mesh-Anreicherung darf die Antwort nie blockieren

    # 3) Keine relevanten Fakten → Chat ohne Quellen, aber mit CTAs (Web-Recherche / Quelle).
    if not relevant:
        return {**base, "system": CHAT_SYSTEM, "prompt": _chat_prompt(req), "max_tokens": 1100,
                "layers": layers, "grounding": "allgemein",
                "ctas": [{"type": "research", "label": "🔎 Web-Recherche mit Quellen"},
                         {"type": "ingest", "label": "📎 Eigene Quelle einlesen"}]}

    # 4) Belegte, beratende Synthese über relevante Fakten → MIT Quellen + Rechenweg.
    facts = artifacts.facts_from_sources(relevant)
    # Wurde die kuratierte Vorschau-Scheibe tatsächlich für die Antwort genutzt? Dann rahmen wir
    # sie offen als Teaser und laden zum Upgrade auf die volle NENA-Tiefe ein.
    preview_used = any(s.get("layer") == "preview" for s in relevant)
    # 1-Hop-Nachbarn mitliefern → belegte Antworten, deren Kern in verbundenen Knoten steht
    # (z.B. Angebote/Programme eines Hubs). Kommt aus DEMSELBEN Graphen, bleibt also belegt.
    groups = [client_group] + ([MARKET_GROUP, MESH_GROUP] if use_shared else [])
    if show_preview:
        groups = groups + [PREVIEW_GROUP]
    try:
        neigh = await _expand_neighbors(groups, relevant)
    except Exception:  # noqa: BLE001
        neigh = []
    if neigh:
        facts += "\n\nVerbundene Fakten (1-Hop-Nachbarn aus dem Gedächtnis):\n" + "\n".join(neigh)
    # Bisheriges Gespräch als Kontext einbeziehen — so kann sich der Nutzer auf integrierte
    # Artefakte (Impact Score / Quartalsreport) beziehen („das", „mein Score" …).
    convo = ""
    for h in (req.history or [])[-4:]:
        if isinstance(h, dict):
            c = h.get("content") or h.get("text") or ""
            if c:
                convo += f"{'Nutzer' if h.get('role') == 'user' else 'Assistent'}: {c}\n"
    prompt = (
        (f"Bisheriges Gespräch (Kontext, u.a. integrierte Artefakte wie Scores/Reports):\n"
         f"{convo}\n" if convo else "")
        + f"Fakten aus dem Gedächtnis (Mandant + geteilte Market- + Mesh-Ebene):\n{facts}\n\n"
        + f"Frage des Nutzers: {req.text}\n\nBeratende, belegte Antwort:"
    )
    # Vorschau-Treffer → offener Upgrade-CTA (die volle NENA-Tiefe ist bezahlt).
    ctas = ([{"type": "upgrade", "label": "🔓 Volle NENA-Tiefe freischalten",
              "note": "Diese Antwort nutzt eine kuratierte Vorschau des NENA-Marktwissens."}]
            if preview_used else None)
    return {"system": CONSULT_SYSTEM, "prompt": prompt, "max_tokens": 1600,
            "sources": relevant, "trace": [retrieve_step], "ctas": ctas, "layers": layers,
            "grounded": True, "facts": facts, "grounding": "gedaechtnis",
            "preview_used": preview_used}


def _finalize_answer(plan: dict, full: str, prov: str, mdl: str) -> dict:
    """Nachbereitung nach der Generierung: Trace, deterministischer Fallback, Suggestions."""
    trace = list(plan["trace"])
    if plan["grounded"]:
        if full and full.strip():
            trace.append({"step": "generate", "method": "consultative-synth",
                          "provider": prov, "result": mdl, "service": "engine"})
        else:
            full = "**Belegte Kurzfassung:**\n" + plan["facts"]
            prov, mdl = "none", ""
            trace.append({"step": "generate", "method": "deterministic-facts", "service": "engine"})
    text, sugs = _split_suggestions(full or "Wie kann ich dir helfen?")
    # Deterministischer Fallback (LLM leer) ist zwar belegt, aber keine Synthese → als
    # solche kennzeichnen; sonst die geplante Beleg-Basis übernehmen.
    grounding = plan.get("grounding", "chat")
    if plan["grounded"] and (prov == "none"):
        grounding = "gedaechtnis"  # Kurzfassung direkt aus Fakten — weiterhin belegt
    out = {"result": text, "sources": plan["sources"], "trace": trace, "suggestions": sugs,
           "provider": prov or "ollama", "model": mdl or "", "layers": plan["layers"],
           "grounded": plan["grounded"], "grounding": grounding,
           "tokens": llm.last_tokens()}  # echte Provider-Token-Nutzung (usageMetadata/usage)
    if plan["ctas"]:
        out["ctas"] = plan["ctas"]
    return out


class AgentSynthReq(BaseModel):
    system: str
    prompt: str
    provider: str = "ollama"
    max_tokens: int = 1200


@app.post("/agent/synthesize")
async def agent_synthesize(req: AgentSynthReq):
    """Reine LLM-Synthese (KEIN Retrieval) — für den A2A-Orchestrator: kombiniert die bereits
    belegten Teilantworten der hinzugezogenen Agenten zur Empfehlung des Primär-Agenten."""
    text, prov, mdl = await llm.generate(req.prompt, req.system,
                                         max_tokens=req.max_tokens, provider=req.provider)
    return {"result": text, "provider": prov, "model": mdl, "tokens": llm.last_tokens()}


@app.post("/answer")
async def answer(req: AnswerReq):
    """Drei-Ebenen-Retrieval + adaptive Pfad-Wahl; nicht-gestreamte Vollantwort."""
    plan = await _plan_answer(req)
    if req.system_override:            # Fach-Agent-Persona statt Standard-System
        plan["system"] = req.system_override
    gen, prov, mdl = await llm.generate(plan["prompt"], plan["system"],
                                        max_tokens=plan["max_tokens"], provider=req.provider)
    return _finalize_answer(plan, gen, prov, mdl)


@app.post("/answer/stream")
async def answer_stream(req: AnswerReq):
    """Wie /answer, aber Token-für-Token als SSE: {type:token} … dann {type:done, ...Envelope}."""
    plan = await _plan_answer(req)
    if req.system_override:            # Fach-Agent-Persona statt Standard-System
        plan["system"] = req.system_override

    async def gen():
        acc: list[str] = []
        stream_ok = False
        try:
            async for tok in llm.generate_stream(plan["prompt"], plan["system"],
                                                 max_tokens=plan["max_tokens"],
                                                 provider=req.provider):
                acc.append(tok)
                yield "data: " + json.dumps({"type": "token", "text": tok}) + "\n\n"
            stream_ok = True
        except Exception:
            stream_ok = False  # Stream mittendrin abgebrochen → unten robust nachholen.

        partial = "".join(acc)
        prov, mdl = req.provider, llm.OLLAMA_MODEL
        # E8.4 Anti-Truncation: Bricht der Stream ab (oder liefert verdächtig wenig
        # bei einer belegten Antwort), einmal nicht-gestreamt komplett nachgenerieren.
        # Der Client bevorzugt `result_text` aus dem done-Envelope → Vollantwort gewinnt.
        incomplete = (not stream_ok) or (plan["grounded"] and len(partial.strip()) < 40)
        if incomplete:
            try:
                full, prov, mdl = await llm.generate(
                    plan["prompt"], plan["system"],
                    max_tokens=plan["max_tokens"], provider=req.provider)
                if full and len(full.strip()) > len(partial.strip()):
                    # Fehlenden Rest nachliefern, damit auch der Live-Text vollständig wird.
                    remainder = full[len(partial):] if full.startswith(partial) else "\n" + full
                    if remainder:
                        yield "data: " + json.dumps({"type": "token", "text": remainder}) + "\n\n"
                    partial = full
            except Exception:
                pass

        final = _finalize_answer(plan, partial, prov, mdl)
        final["type"] = "done"
        yield "data: " + json.dumps(final) + "\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/retrieve")
async def retrieve(req: RetrieveReq):
    """Reines Drei-Ebenen-Retrieval (kein LLM) — als Tool für Agenten (graph.query).

    Liefert die relevanten Fakten aus Mandant + Market + Mesh, gerankt und
    relevanz-gefiltert, plus die `facts`-Aufbereitung (wie im /answer-Pfad).
    """
    client_group = map_client_to_group(req.client_id)
    src_p: list[dict] = []
    if not _use_shared(req.intel):
        if _include_preview(req.intel):
            (src_c, _rc), (src_p, _rp) = await asyncio.gather(
                nen.retrieve(req.text, client_group, limit=req.limit),
                nen.retrieve(req.text, PREVIEW_GROUP, limit=max(3, req.limit - 3)))
        else:
            (src_c, _rc) = await nen.retrieve(req.text, client_group, limit=req.limit)
        src_m, src_x, src_t = [], [], []
    else:
        (src_c, _rc), (src_m, _rm), (src_x, _rx) = await asyncio.gather(
            nen.retrieve(req.text, client_group, limit=req.limit),
            nen.retrieve(req.text, MARKET_GROUP, limit=max(4, req.limit - 2)),
            nen.retrieve(req.text, MESH_GROUP, limit=max(4, req.limit - 2)),
        )
        src_t = await _retrieve_teams(req.text, client_group, req.teams, limit=max(4, req.limit - 2))
    for s in src_c:
        s["layer"] = "client"
    for s in src_m:
        s["layer"] = "market"
    for s in src_x:
        s["layer"] = "mesh"
    for s in src_p:
        s["layer"] = "preview"
    layers = {"team_hits": len(src_t), "client_hits": len(src_c),
              "market_hits": len(src_m), "mesh_hits": len(src_x), "preview_hits": len(src_p)}
    merged = nen.rank_sources(req.text, src_t + src_c + src_m + src_x + src_p)
    relevant = nen.relevant_sources(req.text, merged)
    return {"sources": relevant, "facts": artifacts.facts_from_sources(relevant),
            "layers": layers, "count": len(relevant)}


EXTRACT_SYSTEM = (
    "Du extrahierst einen kleinen Gedächtnis aus einem Text. Gib AUSSCHLIESSLICH die "
    "Entitäten und Beziehungen zurück, die im Text WÖRTLICH oder eindeutig vorkommen — "
    "erfinde nichts, ergänze kein Weltwissen. Antworte NUR mit JSON in exakt dieser Form: "
    '{"nodes":[{"label":"...","type":"..."}],"edges":[{"source":"...","target":"...","rel":"..."}]}. '
    "type ist eines von: Organisation, Person, Konzept, Dokument, Entscheidung, Produkt, Thema. "
    "source/target müssen exakt einem node-label entsprechen. Findest du nichts Belegbares, gib "
    '{"nodes":[],"edges":[]} zurück. Kein Fließtext, keine Erklärung, nur das JSON.'
)


def _parse_json_object(raw: str) -> dict:
    """Erste {...}-JSON-Struktur aus einer LLM-Antwort robust herauslösen."""
    if not raw:
        return {}
    start = raw.find("{")
    if start < 0:
        return {}
    depth = 0
    for i in range(start, len(raw)):
        if raw[i] == "{":
            depth += 1
        elif raw[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(raw[start:i + 1])
                except Exception:
                    return {}
    return {}


@app.post("/extract")
async def extract(req: ExtractReq):
    """Geerdete Entitäts-/Relationen-Extraktion aus Text → {nodes, edges} (keine Erfindung)."""
    prompt = (f"Text:\n{req.text.strip()[:4000]}\n\n"
              f"Extrahiere höchstens {req.max_nodes} zentrale Entitäten + ihre Beziehungen als JSON.")
    raw, prov, mdl = await llm.generate(prompt, EXTRACT_SYSTEM, max_tokens=500,
                                        provider=req.provider)
    data = _parse_json_object(raw)
    nodes_raw = data.get("nodes") if isinstance(data, dict) else None
    edges_raw = data.get("edges") if isinstance(data, dict) else None
    nodes: list[dict] = []
    seen: set[str] = set()
    for n in (nodes_raw or [])[: req.max_nodes]:
        if not isinstance(n, dict):
            continue
        label = str(n.get("label", "")).strip()
        if not label or label.lower() in seen:
            continue
        seen.add(label.lower())
        nodes.append({"label": label, "type": str(n.get("type", "Konzept")).strip() or "Konzept"})
    labels = {n["label"].lower() for n in nodes}
    edges: list[dict] = []
    for e in (edges_raw or []):
        if not isinstance(e, dict):
            continue
        s = str(e.get("source", "")).strip()
        t = str(e.get("target", "")).strip()
        if s.lower() in labels and t.lower() in labels and s.lower() != t.lower():
            edges.append({"source": s, "target": t, "rel": str(e.get("rel", "RELATED_TO")).strip() or "RELATED_TO"})
    return {"nodes": nodes, "edges": edges, "provider": prov, "model": mdl}


@app.post("/enrich/url")
async def enrich_url(req: EnrichUrlReq):
    """URL-Import: Scrape → LLM-Entitäts-/Relationsextraktion → synchron in den Tenant-Graph.
    Ersetzt manuelles seed.json. Legt einen Quell-Dokumentknoten an + getypte Entitäten +
    MENTIONS-Kanten + extrahierte Relationen; alles mit Provenienz = Quell-URL."""
    group = map_client_to_group(req.client_id)
    # 1) Scrape (SSRF-geschützt im Assets-Service)
    try:
        async with httpx.AsyncClient(timeout=30.0) as c:
            sd = (await c.post(f"{ASSETS_URL}/scrape",
                  json={"url": req.url, "client_id": req.client_id, "levels": ["client"]})).json()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": "scrape_unreachable", "detail": str(e)[:200]}
    if not sd.get("ok"):
        return {"ok": False, "reason": sd.get("reason", "scrape_failed"), "url": req.url}
    text = sd.get("text") or ""
    title = (sd.get("title") or req.url)[:160]
    final_url = sd.get("url") or req.url
    if not text.strip():
        return {"ok": False, "reason": "no_text", "url": final_url}
    # 2) LLM-Extraktion (geerdet, keine Erfindung)
    prompt = (f"Text:\n{text[:6000]}\n\nExtrahiere höchstens {req.max_nodes} zentrale "
              f"Entitäten + ihre Beziehungen als JSON.")
    raw, prov, _mdl = await llm.generate(prompt, EXTRACT_SYSTEM, max_tokens=900, provider=req.provider)
    data = _parse_json_object(raw)
    enodes = [n for n in (data.get("nodes") or [])
              if isinstance(n, dict) and str(n.get("label", "")).strip()][: req.max_nodes]
    eedges = [e for e in (data.get("edges") or []) if isinstance(e, dict)]
    # 3) Graph-Payload: Quellknoten + getypte Entitäten + Kanten
    src_id = _graph_slug(title)
    nodes = [{"id": src_id, "label": title, "type": "Document",
              "props": {"url": final_url, "provenance": final_url}}]
    label2id: dict[str, str] = {}
    for n in enodes:
        lbl = str(n["label"]).strip()
        lid = _graph_slug(lbl)
        typ = _ONTO_TYPE_MAP.get(str(n.get("type", "")).strip().lower(), "Thought")
        nodes.append({"id": lid, "label": lbl[:160], "type": typ, "props": {"provenance": final_url}})
        label2id[lbl.lower()] = lid
    edges = [{"source": src_id, "target": lid, "rel": "MENTIONS", "provenance": final_url}
             for lid in dict.fromkeys(label2id.values())]
    for e in eedges:
        s = str(e.get("source", "")).strip().lower()
        t = str(e.get("target", "")).strip().lower()
        if s in label2id and t in label2id and s != t:
            edges.append({"source": label2id[s], "target": label2id[t],
                          "rel": str(e.get("rel", "RELATED_TO")).strip() or "RELATED_TO",
                          "provenance": final_url})
    # 4) synchron in die Runtime schreiben
    res, ok = await nen.seed(group, nodes, edges, replace=False)
    return {"ok": ok, "url": final_url, "title": title, "group": group,
            "entities": len(enodes), "nodes_written": len(nodes), "edges_written": len(edges),
            "provider": prov, "backend": res}


class GraphCaptureReq(BaseModel):
    """Chat-basierte manuelle Knoten-Aufnahme (Orchestrator-Route graph_ingest)."""
    text: str
    client_id: str = "creativate"
    contributed_by: str = ""      # O2 — Provenienz je Beitrag
    team: str = ""                # gesetzt → team-private Ebene statt Mandanten-Graph
    max_nodes: int = 8
    provider: str = "ollama"


@app.post("/graph/capture")
async def graph_capture(req: GraphCaptureReq):
    """Freitext → geerdete Entitäts-/Relationsextraktion → synchron in den Tenant-Graph.
    Keine Erfindung (EXTRACT_SYSTEM), Provenienz erzwungen. Gibt die aufgenommenen Knoten
    zurück, damit der Chat sie bestätigen kann. 0 Entitäten → ok=True, added=[] (Nutzer
    wird dann im Frontend nach Details gefragt)."""
    text = (req.text or "").strip()
    if len(text) < 3:
        return {"ok": False, "reason": "no_text", "added": [], "edges": 0}
    prompt = (f"Text:\n{text[:4000]}\n\nExtrahiere höchstens {req.max_nodes} zentrale "
              f"Entitäten + ihre Beziehungen als JSON.")
    raw, prov, _mdl = await llm.generate(prompt, EXTRACT_SYSTEM, max_tokens=600,
                                         provider=req.provider)
    data = _parse_json_object(raw)
    enodes = [n for n in (data.get("nodes") or [])
              if isinstance(n, dict) and str(n.get("label", "")).strip()][: req.max_nodes]
    eedges = [e for e in (data.get("edges") or []) if isinstance(e, dict)]
    if not enodes:
        return {"ok": True, "added": [], "edges": 0, "note": "keine Entitäten erkannt"}

    client_group = map_client_to_group(req.client_id)
    group = _team_group(client_group, req.team) if req.team else client_group
    provenance = "chat:erfassung" + (f" · {req.contributed_by}" if req.contributed_by else "")
    label2id: dict[str, str] = {}
    nodes: list[dict] = []
    for n in enodes:
        lbl = str(n["label"]).strip()
        lid = _graph_slug(lbl)
        typ = _ONTO_TYPE_MAP.get(str(n.get("type", "")).strip().lower(), "Thought")
        props = {"provenance": provenance}
        if req.contributed_by:
            props["contributed_by"] = req.contributed_by
        nodes.append({"id": lid, "label": lbl[:160], "type": typ, "props": props})
        label2id[lbl.lower()] = lid
    edges: list[dict] = []
    for e in eedges:
        s = str(e.get("source", "")).strip().lower()
        t = str(e.get("target", "")).strip().lower()
        if s in label2id and t in label2id and s != t:
            edges.append({"source": label2id[s], "target": label2id[t],
                          "rel": str(e.get("rel", "RELATED_TO")).strip() or "RELATED_TO",
                          "provenance": provenance})
    res, ok = await nen.seed(group, nodes, edges, replace=False)
    return {"ok": ok, "group": group, "provenance": provenance,
            "added": [{"label": n["label"], "type": n["type"]} for n in nodes],
            "edges": len(edges), "backend": res, "tokens": llm.last_tokens()}


# --------------------------------------------------------------------------
# Domänen-Services (G5): Contract GET /ontology · POST /enrich · GET /health.
# Domänen sind zustandslose Producer — NUR die Engine persistiert (Provenienz + Layer
# erzwungen). Aktive Domänen kommen aus tenant.yaml (TENANT_DOMAINS).
# --------------------------------------------------------------------------
def _domain_by_id(domain_id: str) -> dict | None:
    return next((d for d in TENANT_DOMAINS if d["id"] == domain_id), None)


def _layer_group(layer: str, client_id: str | None) -> str:
    """Ziel-Group je Ebene: client → Tenant-Group, market/mesh → globale Ebene."""
    if layer == "market":
        return MARKET_GROUP
    if layer == "mesh":
        return MESH_GROUP
    return map_client_to_group(client_id)


class DomainEnrichReq(BaseModel):
    text: str = ""
    url: str = ""
    record: dict = Field(default_factory=dict)
    hint: str = ""
    client_id: str = "default"


@app.get("/domains")
async def domains_list():
    """Aktive Domänen dieses Tenants inkl. Health + Ontologie-Pack (best-effort)."""
    out = []
    async with httpx.AsyncClient(timeout=8.0) as c:
        for d in TENANT_DOMAINS:
            entry = {"id": d["id"], "base_url": d["base_url"], "layer": d["layer"],
                     "healthy": False, "ontology": None}
            try:
                h = await c.get(f"{d['base_url']}/health")
                entry["healthy"] = h.status_code < 300
                o = await c.get(f"{d['base_url']}/ontology")
                if o.status_code < 300:
                    entry["ontology"] = o.json()
            except Exception:  # noqa: BLE001
                pass
            out.append(entry)
    return {"domains": out, "count": len(out)}


@app.post("/domains/{domain_id}/enrich")
async def domain_enrich(domain_id: str, req: DomainEnrichReq):
    """Ruft die Domäne (POST /enrich) und persistiert das Fragment über den Graph-Adapter.
    Provenienz je Aussage bleibt erhalten; die Ziel-Ebene (Layer) wird hier erzwungen."""
    d = _domain_by_id(domain_id)
    if not d:
        return {"ok": False, "reason": "domain_not_active", "domain": domain_id}
    layer = d["layer"]
    group = _layer_group(layer, req.client_id)
    prov_default = f"domain:{domain_id}"
    # 1) Domäne aufrufen
    try:
        async with httpx.AsyncClient(timeout=60.0) as c:
            r = await c.post(f"{d['base_url']}/enrich", json={
                "text": req.text, "url": req.url, "record": req.record, "hint": req.hint})
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": "domain_unreachable", "detail": str(e)[:200]}
    if r.status_code >= 300:
        return {"ok": False, "reason": "domain_error", "status": r.status_code}
    frag = r.json()
    # 2) Fragment → Graph-Payload (id aus label ableiten, Kanten auf ids remappen)
    label2id: dict[str, str] = {}
    nodes = []
    for n in (frag.get("nodes") or []):
        lbl = str(n.get("label", "")).strip()
        if not lbl:
            continue
        nid = str(n.get("id") or "").strip() or _graph_slug(lbl)
        props = dict(n.get("props") or {})
        props.setdefault("provenance", prov_default)
        props["layer"] = layer            # Layer erzwungen
        props["domain"] = domain_id
        nodes.append({"id": nid, "label": lbl[:160], "type": str(n.get("type") or "Thing"),
                      "props": props})
        label2id[lbl.lower()] = nid
        label2id[nid.lower()] = nid
    edges = []
    for e in (frag.get("edges") or []):
        s_raw = str(e.get("source", "")).strip()
        t_raw = str(e.get("target", "")).strip()
        s = label2id.get(s_raw.lower()) or _graph_slug(s_raw)
        t = label2id.get(t_raw.lower()) or _graph_slug(t_raw)
        if not s or not t or s == t:
            continue
        edges.append({"source": s, "target": t,
                      "rel": str(e.get("rel") or "RELATED_TO").strip() or "RELATED_TO",
                      "provenance": str(e.get("provenance") or prov_default)})
    if not nodes:
        return {"ok": False, "reason": "empty_fragment", "domain": domain_id,
                "note": frag.get("note", "")}
    # 3) über den Adapter persistieren (einzige Schreibstelle)
    res, ok = await nen.seed(group, nodes, edges, replace=False)
    return {"ok": ok, "domain": domain_id, "layer": layer, "group": group,
            "nodes_written": len(nodes), "edges_written": len(edges),
            "note": frag.get("note", ""), "backend": res}


# --------------------------------------------------------------------------
# Tenant Interactive Forms (FraBö): deterministisches Scoring + Persistenz +
# optionale LLM-Interpretation. Specs kommen aus <config>/forms (tenant-scoped).
# --------------------------------------------------------------------------
_ENGINE_CONFIG_DIR = os.path.dirname(os.getenv("TENANT_CONFIG", "/config/tenant.yaml")) or "/config"


def _load_form(form_id: str):
    try:
        from tenant_core.forms import load_forms
        for s in load_forms(_ENGINE_CONFIG_DIR):
            if s.id == form_id:
                return s
    except Exception:  # noqa: BLE001
        pass
    return None


class FormSubmitReq(BaseModel):
    answers: dict[str, list[int]] = Field(default_factory=dict)  # Score-Modus: {section_key: [werte]}
    values: dict = Field(default_factory=dict)                   # Erfassungs-Modus: {field_key: value}
    subject: str = ""            # z.B. Start-up-Name
    period: str = ""             # z.B. „2026-Q2"
    client_id: str = "default"
    persist: bool = True
    narrative: bool = True
    provider: str = ""
    contributed_by: str = ""     # O2 — Provenienz: wer hat beigetragen (User-E-Mail)
    team: str = ""               # O2 — optionales Team


async def _narrate(sys: str, prompt: str, provider: str) -> str:
    try:
        kwargs = {"max_tokens": 380}
        if provider:
            kwargs["provider"] = provider
        out, _prov, _mdl = await llm.generate(prompt, sys, **kwargs)
        return out
    except Exception:  # noqa: BLE001
        return ""


@app.post("/forms/{form_id}/submit")
async def form_submit(form_id: str, req: FormSubmitReq):
    """Wertet ein Formular aus und persistiert es im Tenant-Graph (Provenienz form:<id>).
    Zwei Modi: assessment → deterministischer Score + Handlungsfelder (Assessment-Knoten);
    reporting/intake → erfasste Felder als Report-Knoten (+ optionale LLM-Zusammenfassung)."""
    from tenant_core.forms import collect_values, is_scored, score_submission
    spec = _load_form(form_id)
    if spec is None:
        return {"ok": False, "reason": "form_not_found", "form_id": form_id}

    # O2b — bei gesetztem Team team-privat persistieren (nur Team-Mitglieder sehen es),
    # sonst in den org-globalen Tenant-Graph.
    client_group = map_client_to_group(req.client_id)
    group = _team_group(client_group, req.team) if req.team else client_group
    prov = f"form:{form_id}"
    subj = req.subject or "Start-up"

    # ---- Score-Modus (assessment) --------------------------------------------
    if is_scored(spec):
        result = score_submission(spec, req.answers)
        narrative = ""
        if req.narrative and spec.report.llm_narrative:
            ranked = sorted(result["sections"], key=lambda s: s["score"])
            weak = ", ".join(f"{s['title']} ({s['score']}/{s['max']})" for s in ranked[:3])
            strong = ", ".join(f"{s['title']} ({s['score']}/{s['max']})" for s in ranked[-2:])
            narrative = await _narrate(
                "Du bist Startup-Mentor im Startup-Accelerator. Formuliere knapp, konkret, "
                "auf Deutsch. Keine Erfindungen — nur auf Basis der genannten Scores.",
                f"Impact Score für {subj} ({req.period or 'aktuell'}): "
                f"Gesamt {result['total']}/{result['total_max']} ({result['percent']}%). "
                f"Stärkste Felder: {strong}. Schwächste Felder: {weak}. "
                f"Nenne 3 priorisierte Handlungsfelder fürs Acceleratoren-Programm (je 1 Satz) "
                f"und 1 Satz Gesamteinordnung.", req.provider)
        persisted = False
        if req.persist:
            aid = _graph_slug(f"{form_id}-{subj}-{req.period or 'na'}")
            props = {"provenance": prov, "form_id": form_id, "kind": spec.kind,
                     "subject": req.subject, "period": req.period,
                     "total": result["total"], "total_max": result["total_max"],
                     "percent": result["percent"]}
            if req.contributed_by:
                props["contributed_by"] = req.contributed_by
            if req.team:
                props["team"] = req.team
            for s in result["sections"]:
                props[f"score_{s['key']}"] = s["score"]
            label = f"{spec.title}: {req.subject or 'Start-up'}" + (f" · {req.period}" if req.period else "")
            nodes = [{"id": aid, "label": label[:160], "type": "Assessment", "props": props}]
            edges = []
            if req.subject:
                oid = _graph_slug(req.subject)
                nodes.append({"id": oid, "label": req.subject[:160], "type": "Organization",
                              "props": {"provenance": prov}})
                edges.append({"source": aid, "target": oid, "rel": "ASSESSES", "provenance": prov})
            _res, persisted = await nen.seed(group, nodes, edges, replace=False)
        return {"ok": True, "form_id": form_id, "kind": spec.kind, "score": result,
                "narrative": narrative, "persisted": persisted}

    # ---- Erfassungs-Modus (reporting/intake) ---------------------------------
    fields = collect_values(spec, req.values)
    filled = [f for f in fields if str(f["value"]).strip() != ""]
    narrative = ""
    if req.narrative and spec.report.llm_narrative and filled:
        lines = "; ".join(
            f"{f['label']}: {f['value']}{(' ' + f['unit']) if f['unit'] else ''}"
            + (f" (Vorq. {f['prev']})" if f['prev'] else "")
            for f in filled if f["type"] != "textarea"
        )
        free = " | ".join(f"{f['label']}: {f['value']}" for f in filled if f["type"] == "textarea")
        narrative = await _narrate(
            "Du bist Startup-Mentor im Startup-Accelerator. Fasse den Quartalsreport knapp "
            "(3–4 Sätze), sachlich, auf Deutsch zusammen; hebe Veränderungen ggü. Vorquartal und "
            "Risiken (z.B. Runway/Burn) hervor. Keine Erfindungen — nur genannte Zahlen/Texte.",
            f"Quartalsreport {subj} ({req.period or 'aktuell'}). KPIs: {lines}. "
            f"Ziele/Freitext: {free or '—'}.", req.provider)
    persisted = False
    if req.persist:
        rid = _graph_slug(f"{form_id}-{subj}-{req.period or 'na'}")
        props = {"provenance": prov, "form_id": form_id, "kind": spec.kind,
                 "subject": req.subject, "period": req.period}
        if req.contributed_by:
            props["contributed_by"] = req.contributed_by
        if req.team:
            props["team"] = req.team
        for f in fields:
            props[f["key"]] = f["value"]
        label = f"{spec.title}: {req.subject or 'Start-up'}" + (f" · {req.period}" if req.period else "")
        nodes = [{"id": rid, "label": label[:160], "type": "Report", "props": props}]
        edges = []
        if req.subject:
            oid = _graph_slug(req.subject)
            nodes.append({"id": oid, "label": req.subject[:160], "type": "Organization",
                          "props": {"provenance": prov}})
            edges.append({"source": rid, "target": oid, "rel": "REPORTS_ON", "provenance": prov})
        _res, persisted = await nen.seed(group, nodes, edges, replace=False)
    return {"ok": True, "form_id": form_id, "kind": spec.kind,
            "report": {"subject": req.subject, "period": req.period, "fields": fields},
            "narrative": narrative, "persisted": persisted}


# --------------------------------------------------------------------------
# PDF-Export eines Formular-Ergebnisses (Score oder Report). Zero-dep-nah via fpdf2.
# --------------------------------------------------------------------------
class FormPdfReq(BaseModel):
    subject: str = ""
    period: str = ""
    answers: dict = Field(default_factory=dict)   # Score-Modus: {section_key: [werte|null]}
    values: dict = Field(default_factory=dict)     # Erfassungs-Modus: {field_key: value}
    narrative: str = ""


def _tenant_brand() -> tuple[str, tuple[int, int, int]]:
    """(wordmark, primary_rgb) für den PDF-Kopf. Offline-sicher → Defaults."""
    wm, hexv = "cNode", "#4B6EF5"
    try:
        from tenant_core import load_default
        b = load_default().spec.brand
        wm = b.wordmark or wm
        hexv = b.primary or hexv
    except Exception:  # noqa: BLE001
        pass
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", (hexv or "").strip())
    n = int(m.group(1), 16) if m else 0x4B6EF5
    return wm, ((n >> 16) & 255, (n >> 8) & 255, n & 255)


def _lat1(s: object) -> str:
    """fpdf2-Kernschriften sind latin-1: € → EUR, Rest verlustarm kodieren."""
    t = str(s if s is not None else "").replace("€", "EUR").replace("–", "-").replace("’", "'")
    return t.encode("latin-1", "replace").decode("latin-1")


def _render_form_pdf(spec, req: "FormPdfReq", score: dict | None) -> bytes:
    """Vollständiger PDF-Export: ALLE Daten des Formulars.
    Score → Übersicht + jede Aussage mit gewähltem Wert je Kategorie + Total.
    Report → alle Abschnitte mit allen Feldern (inkl. leerer), Vorquartals-Referenz."""
    from fpdf import FPDF

    wm, prim = _tenant_brand()
    scale = spec.scale
    pdf = FPDF(format="A4", unit="mm")
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.add_page()
    W = pdf.w - pdf.l_margin - pdf.r_margin

    def rule():
        pdf.set_draw_color(*prim); pdf.set_line_width(0.5)
        yy = pdf.get_y(); pdf.line(pdf.l_margin, yy, pdf.l_margin + W, yy); pdf.ln(2)

    # Kopf
    pdf.set_text_color(*prim); pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 9, _lat1(wm), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(30, 30, 30); pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, _lat1(spec.title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10); pdf.set_text_color(110, 110, 110)
    meta = req.subject or "Start-up"
    if req.period:
        meta += f"  -  {req.period}"
    pdf.cell(0, 6, _lat1(meta), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1); rule(); pdf.ln(2)

    def label_for(v) -> str:
        if v is None:
            return "nicht beantwortet"
        try:
            iv = int(v)
        except Exception:
            return str(v)
        if iv == scale.na_value:
            return scale.na_label
        if scale.min <= iv <= scale.max and (iv - scale.min) < len(scale.labels):
            return f"{iv} - {scale.labels[iv - scale.min]}"
        return str(iv)

    # ---- Score-Modus: Übersicht + volle Aussagen-Liste ----
    if score is not None:
        smap = {x["key"]: x for x in score.get("sections", [])}
        pdf.set_text_color(*prim); pdf.set_font("Helvetica", "B", 24)
        pdf.cell(0, 11, _lat1(f"{score.get('total', 0)} / {score.get('total_max', 0)}"),
                 new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10); pdf.set_text_color(110, 110, 110)
        pdf.cell(0, 5.5, _lat1(f"{score.get('percent', 0)} %  Gesamt-Score"),
                 new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        # Übersichtsbalken je Kategorie
        for x in score.get("sections", []):
            sc, mx = float(x.get("score", 0)), float(x.get("max", 1)) or 1
            pdf.set_text_color(40, 40, 40); pdf.set_font("Helvetica", "B", 9)
            pdf.cell(7, 5.5, _lat1(x.get("key", "")))
            pdf.set_font("Helvetica", "", 9)
            pdf.cell(74, 5.5, _lat1(x.get("title", ""))[:44])
            bx, bw = pdf.get_x(), W - 7 - 74 - 22
            by = pdf.get_y() + 1.2
            pdf.set_fill_color(232, 234, 240); pdf.rect(bx, by, bw, 3.0, "F")
            pdf.set_fill_color(*prim); pdf.rect(bx, by, max(1.0, bw * (sc / mx)), 3.0, "F")
            pdf.set_x(bx + bw); pdf.set_text_color(90, 90, 90)
            pdf.cell(22, 5.5, _lat1(f"{sc}/{int(mx)}"), align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)
        # Volle Aussagen-Liste je Kategorie
        for sec in spec.sections:
            ss = smap.get(sec.key, {})
            pdf.set_font("Helvetica", "B", 11); pdf.set_text_color(*prim)
            head = f"{sec.key}  {sec.title}"
            if ss:
                head += f"   ({ss.get('score')}/{ss.get('max')})"
            pdf.multi_cell(0, 6, _lat1(head), new_x="LMARGIN", new_y="NEXT")
            ans = req.answers.get(sec.key) or []
            for qi, q in enumerate(sec.questions):
                v = ans[qi] if qi < len(ans) else None
                pdf.set_font("Helvetica", "", 9); pdf.set_text_color(55, 55, 55)
                pdf.multi_cell(0, 4.6, _lat1(f"{qi + 1}. {q}"), new_x="LMARGIN", new_y="NEXT")
                pdf.set_font("Helvetica", "B", 9); pdf.set_text_color(*prim)
                pdf.multi_cell(0, 4.6, _lat1(f"      {label_for(v)}"), new_x="LMARGIN", new_y="NEXT")
                pdf.ln(0.6)
            pdf.ln(1.5)

    # ---- Report-Modus: alle Abschnitte + alle Felder (inkl. leer) ----
    else:
        for sec in spec.sections:
            pdf.set_font("Helvetica", "B", 11); pdf.set_text_color(*prim)
            pdf.multi_cell(0, 6, _lat1(sec.title), new_x="LMARGIN", new_y="NEXT")
            if sec.description:
                pdf.set_font("Helvetica", "", 8); pdf.set_text_color(120, 120, 120)
                pdf.multi_cell(0, 4.2, _lat1(sec.description), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(0.5)
            for f in sec.fields:
                raw = req.values.get(f.key, "")
                val = str(raw).strip()
                shown = val if val != "" else "-"
                if f.type == "textarea":
                    pdf.set_font("Helvetica", "B", 9.5); pdf.set_text_color(40, 40, 40)
                    pdf.multi_cell(0, 5, _lat1(f.label), new_x="LMARGIN", new_y="NEXT")
                    pdf.set_font("Helvetica", "", 9.5); pdf.set_text_color(70, 70, 70)
                    pdf.multi_cell(0, 5, _lat1(shown), new_x="LMARGIN", new_y="NEXT")
                    pdf.ln(1)
                else:
                    pdf.set_font("Helvetica", "", 9.5); pdf.set_text_color(40, 40, 40)
                    pdf.cell(92, 6, _lat1(f.label)[:58])
                    pdf.set_font("Helvetica", "B", 9.5)
                    pdf.cell(42, 6, _lat1(f"{shown} {f.unit}".strip()))
                    if f.prev:
                        pdf.set_font("Helvetica", "", 8); pdf.set_text_color(140, 140, 140)
                        pdf.cell(0, 6, _lat1(f"{f.prev_label or 'Vorq.'}: {f.prev}"),
                                 align="R", new_x="LMARGIN", new_y="NEXT")
                    else:
                        pdf.ln(6)
            pdf.ln(2)

    # ---- Narrative ----
    if req.narrative:
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 11); pdf.set_text_color(*prim)
        pdf.cell(0, 7, _lat1("Zusammenfassung" if score is None else "Einordnung & Handlungsfelder"),
                 new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10); pdf.set_text_color(50, 50, 50)
        pdf.multi_cell(0, 5.6, _lat1(req.narrative), new_x="LMARGIN", new_y="NEXT")

    # ---- Footer (auf jeder Seite) ----
    pdf.set_y(-14)
    pdf.set_font("Helvetica", "", 8); pdf.set_text_color(150, 150, 150)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    pdf.cell(0, 6, _lat1(f"Erstellt mit cNode - {wm} - {stamp} - belegt & lokal (EU)"), align="C")

    return bytes(pdf.output())


@app.post("/forms/{form_id}/pdf")
def form_pdf(form_id: str, req: FormPdfReq):
    """Vollständiger PDF-Export eines Formulars (Score ODER Report) — ALLE Daten."""
    from tenant_core.forms import is_scored, score_submission
    spec = _load_form(form_id)
    if spec is None:
        return {"ok": False, "reason": "form_not_found", "form_id": form_id}
    score = None
    if is_scored(spec):
        # answers können null enthalten (unbeantwortet) → für den Score als na_value werten.
        norm = {k: [(spec.scale.na_value if v is None else v) for v in (arr or [])]
                for k, arr in (req.answers or {}).items()}
        score = score_submission(spec, norm)
    try:
        data = _render_form_pdf(spec, req, score)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": "pdf_render_failed", "detail": str(e)[:200]}
    fname = _graph_slug(f"{form_id}-{req.subject or 'export'}-{req.period or ''}") or "export"
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{fname}.pdf"'})


@app.post("/synthesize")
async def synthesize(req: SynthesizeReq):
    """Belegte Synthese aus gelieferten (Web-)Fakten → Antwort mit [n]-Quellenverweisen."""
    prompt = (
        f"Web-Rechercheergebnisse (nummerierte Quellen):\n{req.facts}\n\n"
        f"Frage: {req.query}\n\nBeantworte die Frage NUR auf Basis dieser Quellen, "
        f"mit Quellenverweisen [n]:"
    )
    text, prov, mdl = await llm.generate(prompt, RESEARCH_SYSTEM, max_tokens=800,
                                         provider=req.provider)
    text, sugs = _split_suggestions(text)
    return {"result": text or "Die Quellen liefern dazu keine belastbare Antwort.",
            "suggestions": sugs, "provider": prov or "ollama", "model": mdl or ""}


GOVERNANCE_SYSTEM = (
    "Du bist der c:node Governance-Assistent (EU-AI-Act / DSGVO). Erstelle ein strukturiertes "
    "Compliance-/Audit-Memo auf Deutsch, AUSSCHLIESSLICH gestützt auf die gelieferten Fakten und "
    "die nummerierten Quellen. Erfinde KEINE Rechtsnormen, Artikelnummern, Fristen oder Pflichten "
    "— nenne eine konkrete Anforderung nur, wenn sie durch eine Quelle belegt ist, und verweise "
    "im Text mit [n]. Ist etwas nicht belegt, sag das offen statt zu raten. Struktur in Markdown: "
    "## Einordnung (mögliche Risikoklasse, mit Vorbehalt) · ## Einschlägige Anforderungen (belegt) "
    "· ## Lücken & offene Pflichten · ## Audit-Checkliste (konkret prüfbare Punkte) · ## Empfehlung "
    "& nächste Schritte. Beende das Memo mit dem Hinweis: 'Hinweis: keine Rechtsberatung.'"
    + _SUGGEST_INSTRUCTION
    + _SINGLE_TURN_GUARD
)


@app.post("/govern")
async def govern(req: GovernReq):
    """Belegtes Governance-/Compliance-Memo aus Kontext + (Web-)Quellen, mit [n]-Verweisen."""
    prompt = (
        f"### Zu bewertender Gegenstand / Frage\n{req.query}\n\n"
        f"### Interner Kontext (Mandant / Verlauf)\n{req.context or '(kein zusätzlicher Kontext)'}\n\n"
        f"### Belegte Quellen (nummeriert)\n{req.facts or '(keine externen Quellen verfügbar)'}\n\n"
        "Erstelle jetzt das Compliance-/Audit-Memo streng auf Basis des Belegten:"
    )
    text, prov, mdl = await llm.generate(prompt, GOVERNANCE_SYSTEM, max_tokens=1000,
                                         provider=req.provider, timeout=300.0)
    text, sugs = _split_suggestions(text)
    return {"result": text or "Die vorliegenden Quellen erlauben keine belastbare Bewertung.",
            "suggestions": sugs, "provider": prov or "ollama", "model": mdl or ""}


@app.get("/graph")
async def graph(client_id: str = "creativate", limit: int = 80,
                include_market: bool = False, include_mesh: bool = False,
                include_base: bool = False, include_preview: bool = False,
                dedup: bool = True, mode: str = "lexical", stitch: bool = True):
    """Mandanten-Graph. Mit `include_market=true` werden zusätzlich die geteilten
    Market-Knoten/-Kanten (group_id="market") einbezogen, mit `include_mesh=true`
    die tenant-unabhängigen Mesh-Knoten/-Kanten (group_id="mesh"). Jeder Knoten/jede
    Kante trägt `layer: "client"|"market"|"mesh"`. Default: nur Client. Die
    Mesh-Ebene ist anfangs leer → 0 zusätzliche Knoten, kein Fehler.
    """
    group_id = map_client_to_group(client_id)
    g, reachable = await nen.graph(group_id, limit=limit)
    if not reachable:
        g = nen.fallback_graph(group_id)
    for n in g["nodes"]:
        n["layer"] = "client"
    for e in g["edges"]:
        e["layer"] = "client"

    nodes = list(g["nodes"])
    edges = list(g["edges"])
    market_reachable = None
    if include_market:
        gm, market_reachable = await nen.graph(MARKET_GROUP, limit=limit)
        for n in gm["nodes"]:
            n["layer"] = "market"
        for e in gm["edges"]:
            e["layer"] = "market"
        nodes += gm["nodes"]
        edges += gm["edges"]

    mesh_reachable = None
    if include_mesh:
        gx, mesh_reachable = await nen.graph(MESH_GROUP, limit=limit)
        for n in gx["nodes"]:
            n["layer"] = "mesh"
        for e in gx["edges"]:
            e["layer"] = "mesh"
        nodes += gx["nodes"]
        edges += gx["edges"]

    # Basis-Ebene (Produkt-Identität + Demo) — IMMER Teil des Retrievals, daher auch hier
    # einblendbar, damit die Graph-Ansicht deckungsgleich mit den zitierten Quellen ist.
    if include_base:
        gb, _rb = await nen.graph(BASE_GROUP, limit=limit)
        for n in gb["nodes"]:
            n["layer"] = "base"
        for e in gb["edges"]:
            e["layer"] = "base"
        nodes += gb["nodes"]
        edges += gb["edges"]

    # NENA-Vorschau-Scheibe (Free-Sandbox-Teaser) — als eigener Layer "preview" einblendbar,
    # damit die Graph-Ansicht deckungsgleich mit den zitierten Vorschau-Quellen ist.
    preview_reachable = None
    if include_preview:
        gp, preview_reachable = await nen.graph(PREVIEW_GROUP, limit=limit)
        for n in gp["nodes"]:
            n["layer"] = "preview"
        for e in gp["edges"]:
            e["layer"] = "preview"
        nodes += gp["nodes"]
        edges += gp["edges"]

    # E2.2/E2.6: lexikalischer Dedup/Merge + einheitliche Provenienz (read-time Projektion).
    merge_stats = None
    if dedup:
        if mode == "embed":
            nodes, edges, merge_stats = await nen.dedup_graph_embed(nodes, edges)
        else:
            nodes, edges, merge_stats = nen.dedup_graph(nodes, edges)

    # E12: lose Knoten (Dokumente/Quellen ohne Kante) über erwähnte Entitäten anbinden.
    stitch_stats = None
    if stitch:
        edges, stitch_stats = nen.stitch_orphans(nodes, edges)

    return {"nodes": nodes, "edges": edges, "client_id": client_id,
            "group_id": group_id, "include_market": include_market,
            "include_mesh": include_mesh, "include_preview": include_preview,
            "market_reachable": market_reachable, "mesh_reachable": mesh_reachable,
            "preview_reachable": preview_reachable,
            "merge": merge_stats, "stitch": stitch_stats,
            "source": "nen-ai" if reachable else "engine-fallback"}


@app.post("/ingest")
async def ingest(req: IngestReq):
    """Level-aware Ingest (SCOPE v2/v3): schreibt in die group_ids der angeforderten
    Ebenen (client=map(client_id), market="market", mesh="mesh") und liefert das
    vereinigte graph_delta. Default nur ["client"].
    """
    client_group = map_client_to_group(req.client_id)
    level_map = {"client": client_group, "market": MARKET_GROUP, "mesh": MESH_GROUP}

    # Angeforderte Ebenen normalisieren: nur bekannte, dedupliziert, Reihenfolge erhalten.
    ordered: list[str] = []
    for lvl in req.levels:
        if lvl in level_map and lvl not in ordered:
            ordered.append(lvl)
    if not ordered:
        ordered = ["client"]

    payload = {"label": req.label, "type": req.type, "props": req.props,
               "links": req.links, "content": req.content}

    all_nodes: list[dict] = []
    all_edges: list[dict] = []
    per_level: list[dict] = []
    persisted_any = False

    for lvl in ordered:
        gid = level_map[lvl]
        raw, reachable = await nen.ingest(payload, gid)
        persisted_any = persisted_any or reachable

        new_id = raw.get("id") or raw.get("uuid") or f"ingested-{lvl}-{uuid.uuid4().hex[:8]}"
        all_nodes.append({
            "id": new_id, "label": req.label, "type": nen.map_node_type(req.type),
            "props": {**req.props, "type_raw": req.type, "group_id": gid},
            "layer": lvl,
        })
        for link in req.links:
            if isinstance(link, dict):
                all_edges.append({
                    "source": new_id,
                    "target": link.get("target") or link.get("id") or "",
                    "rel": link.get("rel", "RELATED_TO"),
                    "provenance": "engine:ingest", "layer": lvl,
                })
            elif isinstance(link, str):
                all_edges.append({
                    "source": new_id, "target": link, "rel": "RELATED_TO",
                    "provenance": "engine:ingest", "layer": lvl,
                })
        per_level.append({"level": lvl, "group_id": gid, "persisted": reachable})

    return {"graph_delta": {"nodes": all_nodes, "edges": all_edges},
            "persisted": persisted_any,
            "levels": per_level,
            "source": "nen-ai" if persisted_any else "engine-fallback"}


@app.post("/market/seed")
async def market_seed():
    """Befüllt die NENA-Markt-Ebene mit kuratiertem, quellenbelegtem Marktwissen (bezahlt).
    Idempotent-ish via Dedup. Nur über intel=true / SHARED_LAYERS im Chat sichtbar."""
    labels: list[str] = []
    persisted = False
    for e in MARKET_SEED:
        _raw, reachable = await nen.ingest(
            {"label": e["label"], "type": e["type"],
             "props": {**e.get("props", {}), "quelle": e.get("props", {}).get("quelle", "market-seed")},
             "links": []},
            MARKET_GROUP,
        )
        persisted = persisted or reachable
        labels.append(e["label"])
    return {"ok": True, "seeded": len(labels), "labels": labels, "persisted": persisted,
            "group": MARKET_GROUP}


@app.post("/preview/seed")
async def preview_seed():
    """Befüllt die NENA-Vorschau-Scheibe (Free-Sandbox-Teaser) mit kuratiertem, rein
    öffentlichem, quellenbelegtem Wissen. Wird NUR in PUBLIC_DEMO als Layer
    „NENA-Marktwissen · Vorschau" eingeblendet — die volle Tiefe bleibt intel=true.
    content=summary → semantische Treffer statt nur Label. Idempotent-ish via Dedup."""
    by_src: dict[str, list[dict]] = {}
    for s, t, rel in _PREVIEW_LINKS:
        by_src.setdefault(s, []).append({"target": t, "rel": rel})
    labels: list[str] = []
    persisted = False
    for e in PREVIEW_SEED:
        summary = e.get("props", {}).get("summary", "")
        _raw, reachable = await nen.ingest(
            {"label": e["label"], "type": e["type"],
             "props": {**e.get("props", {}), "preview": True,
                       "quelle": e.get("props", {}).get("quelle", "nena-vorschau")},
             "content": summary,
             "links": by_src.get(e["label"], [])},
            PREVIEW_GROUP,
        )
        persisted = persisted or reachable
        labels.append(e["label"])
    return {"ok": True, "seeded": len(labels), "labels": labels, "persisted": persisted,
            "group": PREVIEW_GROUP}


@app.post("/mesh/seed")
async def mesh_seed():
    """E2.5: befüllt die Mesh-Ebene mit generischem Makro-Wissen (idempotent-ish via Dedup)."""
    labels: list[str] = []
    persisted = False
    for e in MESH_SEED:
        _raw, reachable = await nen.ingest(
            {"label": e["label"], "type": e["type"],
             "props": {**e.get("props", {}), "quelle": "mesh-seed"}, "links": []},
            MESH_GROUP,
        )
        persisted = persisted or reachable
        labels.append(e["label"])
    return {"ok": True, "seeded": len(labels), "labels": labels, "persisted": persisted,
            "group": MESH_GROUP}


@app.post("/base/seed")
async def base_seed():
    """Befüllt die Produkt-Identitäts-Ebene (c:node/NENA) — IMMER mitgeliefert, read-only.
    Macht „Was ist c:node?" belegt (grounding: gedaechtnis) statt generisch. Idempotent-ish."""
    by_src: dict[str, list[dict]] = {}
    for s, t, rel in _BASE_LINKS:
        by_src.setdefault(s, []).append({"target": t, "rel": rel})
    labels: list[str] = []
    persisted = False
    for e in BASE_SEED:
        summary = e.get("props", {}).get("summary", "")
        _raw, reachable = await nen.ingest(
            {"label": e["label"], "type": e["type"],
             "props": {**e.get("props", {}), "quelle": e.get("props", {}).get("quelle", "base-seed")},
             # content = summary → graph-core bettet Label+Summary ein (semantische Treffer),
             # nicht nur das nackte Label.
             "content": summary,
             "links": by_src.get(e["label"], [])},
            BASE_GROUP,
        )
        persisted = persisted or reachable
        labels.append(e["label"])
    return {"ok": True, "seeded": len(labels), "labels": labels, "persisted": persisted,
            "group": BASE_GROUP}


@app.post("/demo/seed")
async def demo_seed():
    """Seedt das kohärente Demo-Szenario der Fach-Agenten in BASE_GROUP (immer abrufbar,
    als Demo gekennzeichnet). Gibt den A2A-Ketten im Sandbox-Demo belegbare Fakten."""
    by_src: dict[str, list[dict]] = {}
    for s, t, rel in _DEMO_LINKS:
        by_src.setdefault(s, []).append({"target": t, "rel": rel})
    labels: list[str] = []
    persisted = False
    for e in DEMO_DOMAIN_SEED:
        summary = e.get("props", {}).get("summary", "")
        _raw, reachable = await nen.ingest(
            {"label": e["label"], "type": e["type"],
             "props": {**e.get("props", {}), "quelle": "demo-beispiel"},
             "content": summary,
             "links": by_src.get(e["label"], [])},
            BASE_GROUP,
        )
        persisted = persisted or reachable
        labels.append(e["label"])
    return {"ok": True, "seeded": len(labels), "labels": labels, "persisted": persisted,
            "group": BASE_GROUP}


async def _mesh_contribute_group(group: str) -> dict:
    """Aggregiert einen Mandanten-Graph zu anonymen Makro-Signalen für den Mesh.

    GOVERNANCE: NUR Typ-Aggregate (Histogramm + Anteile) — NIEMALS Labels, Namen,
    Inhalte oder PII. Geteilt von manuellem /mesh/contribute und dem Auto-Trigger.
    """
    g, reachable = await nen.graph(group, limit=300)
    if not reachable and not g["nodes"]:
        g = nen.fallback_graph(group)
    hist = Counter((n.get("type") or "Unbekannt") for n in g["nodes"])
    total = sum(hist.values())
    written: list[dict] = []
    for typ, cnt in hist.most_common(10):
        await nen.ingest(
            {"label": f"Marktsignal · {typ}", "type": "Thought",
             "props": {"aggregat": True, "typ": typ, "count": cnt,
                       "anteil": round(cnt / total, 3) if total else 0.0,
                       "quelle": "mesh-aggregation"}, "links": []},
            MESH_GROUP,
        )
        written.append({"typ": typ, "count": cnt})
    return {"contributed": len(written), "aggregate": written, "total_nodes": total}


@app.post("/mesh/contribute")
async def mesh_contribute(req: ContributeReq):
    """E2.4: manueller Trigger der governance-sicheren Mesh-Aggregation eines Mandanten."""
    res = await _mesh_contribute_group(map_client_to_group(req.client_id))
    return {"ok": True, **res, "note": "nur Typ-Aggregate — keine Labels/Inhalte/PII im Mesh"}


@app.get("/mesh/status")
async def mesh_status():
    """Selbstlern-Status: Mesh-Größe + Auto-Contribution-Zähler je Group."""
    g, reachable = await nen.graph(MESH_GROUP, limit=300)
    signals = sum(1 for n in g["nodes"] if (n.get("props") or {}).get("aggregat"))
    return {"mesh_group": MESH_GROUP, "mesh_nodes": len(g["nodes"]),
            "market_signals": signals, "reachable": reachable,
            "auto_contrib": dict(_GROUNDED_COUNT), "auto_every": _MESH_EVERY}


@app.get("/queue")
async def queue():
    """NEN-Verarbeitungs-Queue-Snapshot (aus den letzten Ingest-Antworten). NEN hat kein
    eigenes Queue-GET → wir zeigen den zuletzt gesehenen Stand + aktuelle Mesh-Größe."""
    return {"nen": nen.LAST_QUEUE}


@app.get("/learn/weights")
async def learn_weights(client_id: str = "creativate", top: int = 20):
    """E2.3: Inspektion der gelernten Retrieval-Gewichte einer Group."""
    group = map_client_to_group(client_id)
    bag = LEARNED_WEIGHTS.get(group, {})
    ranked = sorted(bag.items(), key=lambda x: -x[1])[:top]
    return {"group": group, "terms": len(bag),
            "top": [{"term": t, "weight": round(w, 2)} for t, w in ranked]}


@app.post("/artifact")
async def artifact(req: ArtifactReq):
    group_id = map_client_to_group(req.client_id)
    instruction = artifacts.KIND_INSTRUCTIONS.get(req.kind, artifacts.KIND_INSTRUCTIONS["memo"])

    # Grounding: belegte Fakten aus der NEN AI holen (Kontext als Query).
    query = req.context or f"Erstelle ein {artifacts.kind_title(req.kind)} für {req.client_id}"
    _atext, sources, reachable = await nen.answer(query, group_id, limit=8)
    facts = artifacts.facts_from_sources(sources)

    system, prompt = artifacts.build_prompt(req.kind, req.context, facts)
    markdown, _prov, _mdl = await llm.generate(prompt, system, max_tokens=900,
                                               provider="ollama", timeout=300.0)
    if not markdown:
        markdown = artifacts.deterministic_markdown(req.kind, req.context, facts, req.client_id)

    return {
        "id": f"art-{uuid.uuid4().hex[:10]}",
        "kind": req.kind,
        "title": artifacts.kind_title(req.kind),
        "markdown": markdown,
        "client_id": req.client_id,
        "thread_id": req.thread_id,
        "created_at": _now(),
    }


@app.get("/models")
async def models():
    try:
        ollama_models = await llm.list_ollama_models()
        reachable = True
    except Exception:
        ollama_models, reachable = [], False
    return {
        "default": llm.OLLAMA_MODEL,
        "default_provider": llm.resolve_provider(""),   # welcher Provider standardmäßig läuft
        "ollama": {"reachable": reachable, "models": ollama_models},
        "claude": {"configured": bool(llm.ANTHROPIC_API_KEY),
                   "model": llm.ANTHROPIC_MODEL if llm.ANTHROPIC_API_KEY else None},
        "gemini": {"configured": bool(llm.GOOGLE_API_KEY),
                   "model": llm.GEMINI_MODEL if llm.GOOGLE_API_KEY else None},
        "providers": (["ollama"]
                      + (["gemini"] if llm.GOOGLE_API_KEY else [])
                      + (["claude"] if llm.ANTHROPIC_API_KEY else [])),
    }
