"""E7 — Agenten-Orchestrierung (Sprint 7.0 Fundament + 7.1 Recherche-Agent).

Ein Agent ist Config über einer geteilten Engine: Ziel → sichtbarer Plan →
echte Tool-Aufrufe → belegtes Artefakt. Der LLM ist nur der Reasoner; der
Mehrwert kommt aus den Tools (Retrieval, Web-Recherche, Synthese).

Provider-/Modell-agnostisch: der Provider (`ollama` default, `claude` später)
wird pro Lauf durchgereicht und an die Engine weitergegeben; die Tool-Registry
bleibt gleich. Läufe + Schritte werden in Postgres persistiert (Source of Truth,
audit-fest) — der Graph ist die lesbare Projektion.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta
from typing import AsyncIterator

import httpx

import db

ENGINE_URL = os.getenv("ENGINE_URL", "http://engine:8020").rstrip("/")
ASSETS_URL = os.getenv("ASSETS_URL", "http://assets:8030").rstrip("/")


# --------------------------------------------------------------------------
# Agenten-Katalog (Familien; „more scouts to come" = weiterer Eintrag hier)
# --------------------------------------------------------------------------
AGENTS: dict[str, dict] = {
    "recherche": {
        "id": "recherche",
        "name": "Recherche-Agent",
        "family": "advisor",
        "description": ("Belegtes Briefing: gleicht das Gedächtnis ab, recherchiert bei "
                        "Lücken im Web (wissenschaftlich/offiziell priorisiert) und erstellt "
                        "ein Briefing mit [n]-Quellen."),
        "tier": "free",
        "artifact_kind": "briefing",
        "plan": [
            {"title": "Gedächtnis abgleichen", "tool": "graph.query"},
            {"title": "Web-Recherche (wiss./offiziell)", "tool": "web.research"},
            {"title": "Belegtes Briefing erstellen", "tool": "artifact.create"},
        ],
    },
    "memo": {
        "id": "memo",
        "name": "Memo-Agent",
        "family": "advisor",
        "description": ("Strukturiertes, belegtes Entscheidungs-Memo aus Gedächtnis + "
                        "Chat-Verlauf (Ausgangslage, Optionen, Empfehlung, Risiken) — keine "
                        "erfundenen Zahlen oder Bewertungen."),
        "tier": "free",
        "artifact_kind": "memo",
        "plan": [
            {"title": "Grundlage sammeln (Gedächtnis)", "tool": "graph.query"},
            {"title": "Verlauf & Fakten zusammenführen", "tool": "assemble"},
            {"title": "Entscheidungs-Memo erstellen", "tool": "artifact.create"},
        ],
    },
    # --- Scout-Familie: finden → bewerten → belegte Liste + Graph -------------
    # Template über `source` parametrisiert; weitere Scouts (Trend/Funding) = neuer Eintrag.
    "leadscout": {
        "id": "leadscout",
        "name": "Lead-Scout",
        "family": "scout",
        "description": ("Findet passende Leads über die LeadScout-Engine, bewertet sie mit "
                        "Score + Begründung und legt eine belegte Lead-Liste als Artefakt + "
                        "Knoten im Gedächtnis ab."),
        "tier": "free",
        "artifact_kind": "lead_list",
        "source": {
            "tool": "leadscout", "endpoint": "/leadscout/find",
            "payload": "icp", "item_key": "leads", "node_type": "Lead",
            "provenance": "LeadScout", "label": "Lead", "label_plural": "Leads",
            "rubric": ("So wird bewertet: Der Score ist der ICP-Fit aus der LeadScout-Engine "
                       "(Branchen-, Regions- und Größen-Match zum Zielprofil); die Einzel-"
                       "Begründung je Lead steht in der Liste. Keine erfundenen Werte."),
        },
        "plan": [
            {"title": "Leads finden (LeadScout-Engine)", "tool": "leadscout.find"},
            {"title": "Bewerten & ranken", "tool": "score"},
            {"title": "Lead-Liste + Gedächtnis ablegen", "tool": "artifact.create"},
        ],
    },
    "startup": {
        "id": "startup",
        "name": "Startup-Scout",
        "family": "scout",
        "description": ("Findet Früh-Phase-Startups & Hochschul-Ausgründungen über öffentliche, "
                        "rechtssichere Quellen (GitHub u.a.), bewertet sie 0–100 gegen euer "
                        "Suchprofil und legt eine belegte Startup-Liste als Artefakt + Knoten "
                        "im Gedächtnis ab — quellenbelegt und ansprechbar."),
        "tier": "free",
        "artifact_kind": "startup_list",
        "source": {
            "tool": "startupscout", "endpoint": "/startupscout/find",
            "payload": "icp", "item_key": "targets", "node_type": "Company",
            "provenance": "StartupScout", "label": "Startup", "label_plural": "Startups",
            "rubric": ("So wird bewertet (Score 0–98): Themen-Fit zum Suchprofil (Stichworte/"
                       "Topics), eigene Homepage als Produkt-Signal, Organisation statt Einzel-"
                       "Account, Domänen-Topic (z.B. fintech/health/ai), GitHub-Traktion (Sterne, "
                       "bewusst gedeckelt — Popularität dominiert nicht), Region-Treffer und "
                       "Früh-Phase-Bonus. Die Einzel-Begründung je Treffer steht in der Liste."),
        },
        "plan": [
            {"title": "Startups finden (StartupScout · GitHub live)", "tool": "startupscout.find"},
            {"title": "Gegen Suchprofil bewerten & ranken", "tool": "score"},
            {"title": "Startup-Liste + Gedächtnis ablegen", "tool": "artifact.create"},
        ],
    },
    "funding": {
        "id": "funding",
        "name": "Funding-Scout",
        "family": "scout",
        "description": ("Findet passende Förderprogramme über die Förder-Engine, bewertet Fit + "
                        "Frist und legt eine belegte Programm-Liste als Artefakt + Knoten im "
                        "Gedächtnis ab."),
        "tier": "free",
        "artifact_kind": "funding_list",
        "source": {
            "tool": "foerder", "node_type": "FundingProgram", "provenance": "Förder",
            "label": "Förderprogramm", "label_plural": "Förderprogramme",
            "rubric": ("So wird bewertet: Der Fit-Score stammt aus der Förder-Engine (Passung "
                       "des Programms zu Vorhaben/Profil, inkl. Frist-Nähe); die Einzel-"
                       "Begründung und die Frist je Programm stehen in der Liste."),
        },
        "plan": [
            {"title": "Programme finden (Förder-Engine)", "tool": "foerder.match"},
            {"title": "Fit bewerten & ranken", "tool": "score"},
            {"title": "Programm-Liste + Gedächtnis ablegen", "tool": "artifact.create"},
        ],
    },
    "trend": {
        "id": "trend",
        "name": "Trend-Scout",
        "family": "scout",
        "description": ("Scannt das Web (wissenschaftlich/offiziell priorisiert) nach Trend-"
                        "Signalen zum Thema, priorisiert die Quellen und legt eine belegte "
                        "Signal-Liste als Artefakt + Knoten im Gedächtnis ab."),
        "tier": "free",
        "artifact_kind": "trend_list",
        "source": {
            "tool": "research", "node_type": "TrendSignal", "provenance": "Web-Recherche",
            "label": "Trend-Signal", "label_plural": "Trend-Signale",
            "rubric": ("So wird bewertet: Der Score gewichtet die Quellen-Autorität — "
                       "wissenschaftliche/offizielle Quellen höher als allgemeine Web-Treffer; "
                       "jede Zeile verlinkt ihre Originalquelle (keine erfundenen Links)."),
        },
        "plan": [
            {"title": "Web-Signale sammeln (SerpAPI)", "tool": "web.research"},
            {"title": "Quellen priorisieren & ranken", "tool": "score"},
            {"title": "Signal-Liste + Gedächtnis ablegen", "tool": "artifact.create"},
        ],
    },
    # --- Governance-Familie: prüfen & auditieren (quellenbelegt) --------------
    "governance": {
        "id": "governance",
        "name": "Governance-Assistant",
        "family": "governance",
        "description": ("Prüft ein Vorhaben/System gegen EU-AI-Act & DSGVO: Einordnung, belegte "
                        "Anforderungen, Lücken und eine Audit-Checkliste — jede Aussage mit "
                        "Quelle, keine erfundenen Normen (keine Rechtsberatung)."),
        "tier": "free",
        "artifact_kind": "governance_memo",
        "plan": [
            {"title": "Kontext & Betroffenheit klären", "tool": "graph.query"},
            {"title": "Rechtsgrundlagen recherchieren (offiziell)", "tool": "web.research"},
            {"title": "Compliance-/Audit-Memo erstellen", "tool": "artifact.create"},
        ],
    },
    # --- Action-Familie: Seiteneffekt, IMMER Draft → Freigabe ----------------
    "outreach": {
        "id": "outreach",
        "name": "Outreach-Agent",
        "family": "action",
        "description": ("Verfasst aus dem Kontext eine personalisierte Outreach-E-Mail und legt "
                        "sie NUR nach deiner Freigabe als Entwurf an (Gmail) — nie automatisch "
                        "gesendet."),
        "tier": "free",
        "artifact_kind": "",
        "plan": [
            {"title": "Empfänger & Kontext klären", "tool": "graph.query"},
            {"title": "Nachricht verfassen", "tool": "generate"},
            {"title": "E-Mail-Entwurf zur Freigabe", "tool": "gmail_draft"},
            {"title": "Kalender-Slot vorschlagen", "tool": "gcal_event"},
        ],
    },
}


def _fmt_criteria(cr: dict | None) -> str:
    """Angewandte Suchkriterien für die Chat-/Artefakt-Anzeige verdichten."""
    if not cr:
        return ""
    bits: list[str] = []
    if cr.get("keywords"):
        bits.append("Stichworte: " + ", ".join(cr["keywords"]))
    if cr.get("topics"):
        bits.append("Topics: " + ", ".join(cr["topics"]))
    if cr.get("language"):
        bits.append("Tech: " + cr["language"])
    if cr.get("location"):
        bits.append("Region: " + cr["location"])
    if cr.get("min_stars"):
        bits.append(f"≥{cr['min_stars']}★")
    if cr.get("stage") == "early":
        bits.append("Früh-Phase")
    return " · ".join(bits)


def catalog() -> list[dict]:
    """Öffentlicher Katalog (ohne interne Plan-Templates)."""
    keys = ("id", "name", "family", "description", "tier")
    return [{k: a[k] for k in keys} for a in AGENTS.values()]


def get(agent_id: str) -> dict | None:
    return AGENTS.get(agent_id)


async def _scout_discover(c: httpx.AsyncClient, src: dict, goal: str,
                          tenant_id: str, meta: dict | None = None) -> list[dict]:
    """Ruft das echte Backend-Tool eines Scouts und normalisiert auf ein einheitliches
    Item-Schema {name, segment, score, reason, url?}. So teilt sich die ganze Scout-Familie
    Ranking + Artefakt + Graph-Ingest, egal ob LeadScout, Förder oder Web-Recherche.

    `meta` (optional, out): das Tool kann angewandte Suchkriterien/Query zurückmelden —
    der Chat-Flow macht damit sichtbar, WONACH gesucht wurde (Startup-Scout)."""
    tool = src.get("tool")
    if tool == "leadscout":
        r = await c.post(f"{ASSETS_URL}/leadscout/find",
                         json={"icp": goal, "client_id": g})
        return [
            {"name": l.get("name"), "segment": l.get("segment", ""),
             "score": l.get("score", 0), "reason": l.get("reason", "")}
            for l in (r.json().get("leads", []) or [])
        ]
    if tool == "startupscout":
        r = await c.post(f"{ASSETS_URL}/startupscout/find",
                         json={"icp": goal, "client_id": g, "limit": 10, "enrich": True})
        d = r.json()
        if meta is not None:
            meta["criteria"] = d.get("criteria") or {}
            meta["query"] = d.get("query") or ""
            meta["discovery_source"] = d.get("source") or ""
        return [
            {"name": t.get("name"), "segment": t.get("segment", ""),
             "score": t.get("score", 0),
             "reason": (t.get("reason", "") + (f" · {t.get('traction')}" if t.get("traction") else "")),
             "url": t.get("website", ""), "location": t.get("location", ""),
             "contact": t.get("contact", "")}
            for t in (d.get("targets", []) or [])
        ]
    if tool == "foerder":
        r = await c.post(f"{ASSETS_URL}/foerder/match",
                         json={"query": goal, "client_profile": {"client_id": g},
                               "client_id": g})
        out = []
        for p in (r.json().get("programs", []) or []):
            frist = p.get("frist", "")
            reason = p.get("reason", "")
            out.append({
                "name": p.get("name"),
                "segment": p.get("max_foerderung", "") or p.get("max_funding", ""),
                "score": p.get("fit", 0),
                "reason": reason + (f" · Frist: {frist}" if frist else ""),
            })
        return out
    if tool == "research":
        r = await c.post(f"{ASSETS_URL}/research",
                         json={"query": goal, "client_id": g,
                               "max_results": 6, "ingest": False})
        d = r.json()
        if not d.get("ok"):
            return []
        out = []
        for ref in (d.get("references", []) or []):
            sci = bool(ref.get("scientific"))
            out.append({
                "name": ref.get("title"),
                "segment": ref.get("domain", "") or ("wissenschaftlich/offiziell" if sci else "Web"),
                "score": 0.9 if sci else 0.5,
                "reason": ref.get("url", ""),
                "url": ref.get("url", ""),
            })
        return out
    return []


# --------------------------------------------------------------------------
# Run-Executor (Sprint 7.1: Recherche-Agent, deterministischer Plan)
# --------------------------------------------------------------------------
async def run_stream(
    c: httpx.AsyncClient,
    *,
    agent_id: str,
    goal: str,
    tenant_id: str,
    thread_id: str | None,
    provider: str,
    created_by: str,
    is_super: bool,
    history: list | None = None,
    graph_client: str | None = None,
) -> AsyncIterator[dict]:
    """Führt einen Agenten-Lauf aus und yieldet Events (plan → step* → done).

    Persistiert Lauf + Schritte in Postgres. Jeder Faktenclaim im Ergebnis ist
    an eine echte Quelle (Graph-Knoten oder Web-[n]) gebunden — keine erfundenen
    Fakten/Links (Anti-Halluzination, F1–F3 aus dem Transkript).
    """
    agent = get(agent_id)
    if not agent:
        yield {"type": "error", "error": f"unbekannter Agent: {agent_id}"}
        return

    # Graph-Namespace: in der Sandbox pro-User (ws:…) → isoliertes Gedächtnis; sonst == tenant_id.
    # DB (agent_runs/steps/artifacts) bleibt IMMER tenant_id-scoped.
    g = graph_client or tenant_id

    run = db.create_agent_run(
        tenant_id, agent_id, goal, agent["plan"],
        thread_id=thread_id, provider=provider, created_by=created_by, is_super=is_super,
    )
    run_id = run["id"]
    steps = run["steps"]
    yield {"type": "plan", "run_id": run_id, "agent": agent_id, "agent_name": agent["name"],
           "goal": goal, "steps": steps}

    db.set_agent_run_status(run_id, tenant_id, "running", is_super=is_super)

    def _step_evt(step: dict, status: str, **extra) -> dict:
        return {"type": "step", "run_id": run_id, "idx": step["idx"],
                "title": step["title"], "status": status, **extra}

    # ==================================================================
    # Memo-Agent (Advisor): Graph-Grundlage + Verlauf → belegtes Entscheidungs-Memo
    # ==================================================================
    if agent_id == "memo":
        m1, m2, m3 = steps[0], steps[1], steps[2]
        facts = ""
        gsources: list[dict] = []

        # Schritt 1: Grundlage aus dem Gedächtnis
        yield _step_evt(m1, "running")
        try:
            r = await c.post(f"{ENGINE_URL}/retrieve",
                             json={"text": goal, "client_id": g, "limit": 8})
            d = r.json()
            facts = d.get("facts", "") or ""
            gsources = d.get("sources", []) or []
            cnt = d.get("count", len(gsources))
            prov = [{"kind": "graph", "id": s.get("id"), "label": s.get("label"),
                     "layer": s.get("layer")} for s in gsources[:8]]
            summ = (f"{cnt} relevante Knoten im Gedächtnis" if cnt
                    else "keine relevanten Knoten — Memo stützt sich auf den Verlauf")
            db.update_agent_step(m1["id"], tenant_id, "done", summary=summ,
                                 provenance=prov, is_super=is_super)
            yield _step_evt(m1, "done", summary=summ, provenance=prov)
        except Exception as e:  # noqa: BLE001
            summ = f"Retrieval nicht erreichbar ({e.__class__.__name__})"
            db.update_agent_step(m1["id"], tenant_id, "failed", summary=summ, is_super=is_super)
            yield _step_evt(m1, "failed", summary=summ)

        # Schritt 2: Verlauf + Fakten zusammenführen (deterministisch, kein LLM)
        yield _step_evt(m2, "running")
        turns = [h for h in (history or []) if (h.get("content") or h.get("text"))]
        hist_txt = "\n".join(
            f"{'Nutzer' if h.get('role') == 'user' else 'Assistent'}: "
            f"{(h.get('content') or h.get('text') or '').strip()}"
            for h in turns[-8:]
        )
        summ2 = f"{len(turns)} Gesprächsbeiträge + {len(gsources)} Fakten zusammengeführt"
        db.update_agent_step(m2["id"], tenant_id, "done", summary=summ2, is_super=is_super)
        yield _step_evt(m2, "done", summary=summ2)

        # Schritt 3: Entscheidungs-Memo erstellen (engine /artifact, kind=memo)
        yield _step_evt(m3, "running")
        context = f"Entscheidungsfrage / Ziel: {goal}\n\n"
        if hist_txt:
            context += f"Gesprächsverlauf:\n{hist_txt}\n\n"
        if facts.strip():
            context += f"Relevante Fakten aus dem Gedächtnis:\n{facts}"
        title = "Entscheidungs-Memo"
        md = ""
        prov_used = provider
        try:
            ar = await c.post(f"{ENGINE_URL}/artifact",
                              json={"kind": "memo", "thread_id": thread_id or "",
                                    "client_id": g, "context": context})
            ad = ar.json()
            md = ad.get("markdown", "") or ""
            title = ad.get("title") or title
        except Exception:  # noqa: BLE001
            md = ""
        grounded = bool(facts.strip() or hist_txt.strip())
        if not md.strip():
            md = (f"## Entscheidungs-Memo: {goal[:70]}\n\n### Ausgangslage\n{goal}\n\n"
                  f"### Belegte Fakten\n{facts or '- (keine belegten Fakten verfügbar)'}\n\n"
                  f"### Hinweis\nUnvollständig — LLM/NEN offline oder unzureichende Faktenlage. "
                  f"Es wurde nichts erfunden.")
        title = f"Entscheidungs-Memo: {goal[:60]}"
        artifact = {
            "id": f"art-{uuid.uuid4().hex[:10]}", "kind": "memo", "title": title,
            "markdown": md, "client_id": tenant_id, "thread_id": thread_id or "",
            "created_at": db.now(),
        }
        prov3 = [{"kind": "artifact", "id": artifact["id"], "title": title}]
        summ3 = ("Entscheidungs-Memo erstellt (belegt)" if grounded
                 else "Memo-Entwurf ohne belegte Grundlage")
        db.update_agent_step(m3["id"], tenant_id, "done", summary=summ3,
                             provenance=prov3, is_super=is_super)
        yield _step_evt(m3, "done", summary=summ3, provenance=prov3)

        mem_sources = [
            {"id": s.get("id") or f"gn_{i}", "label": s.get("label", ""),
             "type": "GraphKnoten", "provenance": "Gedächtnis",
             "props": {"layer": s.get("layer")}}
            for i, s in enumerate(gsources)
        ]
        summary_msg = (
            f"**Memo-Agent abgeschlossen.** Grundlage: {len(gsources)} Knoten aus dem "
            f"Gedächtnis + {len(turns)} Gesprächsbeiträge. Das belegte Entscheidungs-Memo "
            "(Ausgangslage · Optionen · Empfehlung · Risiken) liegt rechts im Panel — mit "
            "*Speichern* wandert es audit-fest in die Bibliothek und das Gedächtnis. "
            "Es enthält keine erfundenen Zahlen oder Bewertungen."
        )
        db.finish_agent_run(run_id, tenant_id, "done", result=summary_msg,
                            artifact_id=artifact["id"], is_super=is_super)
        yield {"type": "done", "run_id": run_id, "result_text": summary_msg,
               "artifact": artifact, "sources": mem_sources, "provider": prov_used}
        return

    # ==================================================================
    # Scout-Familie (Template): finden → bewerten → belegte Liste + Graph
    # ==================================================================
    if agent.get("family") == "scout":
        src = agent.get("source", {})
        lbl = src.get("label", "Treffer")
        lbl_pl = src.get("label_plural", "Treffer")
        node_type = src.get("node_type", "Entity")
        prov_name = src.get("provenance", "Scout")
        s1, s2, s3 = steps[0], steps[1], steps[2]

        # Schritt 1: Discovery über das echte Backend-Tool (normalisiert)
        yield _step_evt(s1, "running")
        items: list[dict] = []
        disco_meta: dict = {}
        is_demo = False
        try:
            items = await _scout_discover(c, src, goal, g, meta=disco_meta)
            crit_txt = _fmt_criteria(disco_meta.get("criteria"))
            dsrc = disco_meta.get("discovery_source")
            is_demo = dsrc == "demo"
            src_note = {"github-live": "GitHub live", "demo": "Demo-/Beispieldaten"}.get(dsrc, "")
            summ = (f"{len(items)} {lbl_pl} " + ("(⚠️ Demo)" if is_demo else "gefunden")
                    + f" ({prov_name}" + (f" · {src_note}" if src_note else "") + ")"
                    + (f" — Kriterien: {crit_txt}" if crit_txt else "")) if items \
                else (f"keine Live-{lbl_pl} von {prov_name}"
                      + (f" für Kriterien: {crit_txt}" if crit_txt else "")
                      + " — Kriterien anpassen (oder GITHUB_TOKEN für Region setzen)")
            db.update_agent_step(s1["id"], tenant_id, "done", summary=summ, is_super=is_super)
            yield _step_evt(s1, "done", summary=summ)
        except Exception as e:  # noqa: BLE001
            summ = f"{prov_name} nicht erreichbar ({e.__class__.__name__})"
            db.update_agent_step(s1["id"], tenant_id, "failed", summary=summ, is_super=is_super)
            yield _step_evt(s1, "failed", summary=summ)

        def _name(it: dict) -> str:
            return str(it.get("name") or it.get("label") or it.get("title") or "?")

        def _score(it: dict):
            try:
                return float(it.get("score", 0) or 0)
            except Exception:  # noqa: BLE001
                return 0.0

        # Schritt 2: bewerten & ranken (deterministisch — Scores kommen vom Tool)
        yield _step_evt(s2, "running")
        items = sorted(items, key=_score, reverse=True)
        top = items[:10]
        n_strong = sum(1 for it in top if _score(it) >= 0.7)
        summ2 = (f"{len(top)} {lbl_pl} gerankt" + (f", {n_strong} stark (Score ≥ 0.7)"
                 if n_strong else "")) if top else "keine Treffer zum Ranken"
        db.update_agent_step(s2["id"], tenant_id, "done", summary=summ2, is_super=is_super)
        yield _step_evt(s2, "done", summary=summ2)

        # Schritt 3: Lead-Liste als Artefakt + Knoten in den Graphen (integrierend)
        yield _step_evt(s3, "running")
        stamp = db.now()
        lines, graph_nodes = [], []
        for i, it in enumerate(top, 1):
            nm = _name(it)
            seg = it.get("segment") or it.get("branche") or ""
            sc = it.get("score", "")
            reason = it.get("reason") or it.get("begruendung") or ""
            loc = it.get("location") or ""
            url = it.get("url") or it.get("website") or ""
            contact = it.get("contact") or ""
            lines.append(f"{i}. **{nm}**"
                         + (f" · {seg}" if seg else "")
                         + (f" · {loc}" if loc else "")
                         + (f" · Score {sc}" if sc != "" else "")
                         + (f" — {reason}" if reason else "")
                         + (f"  \n   ↳ {url}" if url else "")
                         + (f"  \n   ✉ {contact}" if contact else ""))
            # Demo-/Beispieldaten NIE ins Gedächtnis schreiben (kein Fake-Lead im echten Graphen).
            if is_demo:
                continue
            try:
                ir = await c.post(f"{ENGINE_URL}/ingest", json={
                    "label": nm, "type": node_type,
                    "props": {"score": sc, "segment": seg, "reason": reason, "location": loc,
                              "website": url, "kontakt": contact, "quelle": prov_name,
                              "mandant": tenant_id, "erstellt_am": stamp},
                    "links": [], "client_id": g, "levels": ["client"]})
                graph_nodes += ir.json().get("graph_delta", {}).get("nodes", [])
            except Exception:  # noqa: BLE001
                pass

        crit_line = _fmt_criteria(disco_meta.get("criteria")) if agent_id == "startup" else ""
        rubric = src.get("rubric", "")  # je Scout: belegt, wie der Score zustande kommt
        title = f"{lbl}-Liste: {goal[:56]}"
        demo_banner = (
            "> ⚠️ **Demo-/Beispieldaten** — für diese Kriterien gab es keine Live-Treffer. "
            "Diese Einträge sind illustrativ (keine verifizierten Leads) und wurden NICHT ins "
            "Gedächtnis geschrieben. Kriterien anpassen oder `GITHUB_TOKEN` für Region-Filter setzen.\n\n"
        )
        if top:
            md = (f"# {title}\n\n_Quelle: {prov_name} · {len(top)} {lbl_pl} · "
                  f"erzeugt {stamp}_\n\n"
                  + (demo_banner if is_demo else "")
                  + (f"**Angewandte Suchkriterien:** {crit_line}\n\n" if crit_line else "")
                  + (f"**{rubric}**\n\n" if rubric and not is_demo else "")
                  + "\n".join(lines))
        else:
            md = (f"# {title}\n\nKeine Live-{lbl_pl} für diese Kriterien. Präzisiere das ICP/Ziel, "
                  f"stelle eine Quelle bereit oder setze `GITHUB_TOKEN` für den Region-Filter — "
                  f"es wurde nichts erfunden.")
        artifact = {
            "id": f"art-{uuid.uuid4().hex[:10]}", "kind": agent["artifact_kind"],
            "title": title, "markdown": md, "client_id": tenant_id,
            "thread_id": thread_id or "", "created_at": stamp,
        }
        prov3 = [{"kind": "artifact", "id": artifact["id"], "title": title}]
        summ3 = (f"Liste + {len(graph_nodes)} Graph-Knoten abgelegt" if top
                 else "keine Treffer — nichts abgelegt")
        db.update_agent_step(s3["id"], tenant_id, "done", summary=summ3,
                             provenance=prov3, is_super=is_super)
        yield _step_evt(s3, "done", summary=summ3, provenance=prov3)

        scout_sources = [
            {"id": _name(it), "label": _name(it), "type": node_type,
             "provenance": prov_name, "props": it}
            for it in top
        ]
        if top and is_demo:
            summary_msg = (
                f"**{agent['name']} — Demo-Ergebnis.** Für dein Ziel gab es **keine Live-Treffer**; "
                f"rechts siehst du {len(top)} **Beispieldaten** (illustrativ, keine verifizierten "
                "Leads). Sie wurden NICHT ins Gedächtnis geschrieben. Bitte Kriterien anpassen "
                "oder `GITHUB_TOKEN` für den Region-Filter setzen."
            )
        elif top:
            summary_msg = (
                f"**{agent['name']} abgeschlossen.** {len(top)} {lbl_pl} über {prov_name} gefunden "
                f"und bewertet; die belegte {lbl}-Liste liegt rechts im Panel und {len(graph_nodes)} "
                f"Knoten sind ins Gedächtnis geschrieben (Provenienz: {prov_name}). "
                "Mit *Speichern* wandert die Liste zusätzlich audit-fest in die Bibliothek."
                + (f"\n\n_{rubric}_" if rubric else "")  # Score-Begründung belegt im Verlauf
            )
        else:
            summary_msg = (
                f"**{agent['name']} abgeschlossen.** Keine Live-{lbl_pl} für diese Kriterien — "
                "präzisiere das Ziel/ICP oder setze `GITHUB_TOKEN` für den Region-Filter. "
                "Es wurde nichts erfunden und nichts in den Graphen geschrieben."
            )
        # Bewertungslogik als retrievebaren Konzept-Knoten ablegen → belegte Score-Antworten.
        # NUR bei echten Live-Treffern (Demo-Läufe schreiben nichts ins Gedächtnis).
        if top and rubric and not is_demo:
            try:
                await c.post(f"{ENGINE_URL}/ingest", json={
                    "label": f"Bewertungslogik {lbl}-Scout", "type": "Konzept",
                    "props": {"summary": rubric, "quelle": prov_name, "mandant": tenant_id,
                              "erstellt_am": stamp},
                    "links": [], "client_id": g, "levels": ["client"]})
            except Exception:  # noqa: BLE001
                pass
        # Scout → Outreach-Handoff: ansprechbare Treffer (Firmen/Leads) sind mit Kontakt im
        # Gedächtnis → direkte Folge-Aktion. NICHT bei Demo-Daten (keine echten Leads).
        suggestions: list[str] = []
        if node_type in ("Company", "Lead") and top and not is_demo:
            for it in top[:2]:
                suggestions.append(f"starte outreach an {_name(it)}")
        done_evt = {"type": "done", "run_id": run_id, "result_text": summary_msg,
                    "artifact": artifact, "sources": scout_sources,
                    "graph_delta": {"nodes": graph_nodes, "edges": []}, "provider": provider}
        if suggestions:
            done_evt["suggestions"] = suggestions
        db.finish_agent_run(run_id, tenant_id, "done", result=summary_msg,
                            artifact_id=artifact["id"], is_super=is_super)
        yield done_evt
        return

    # ==================================================================
    # Governance-Assistant: Kontext → offizielle Rechtsquellen → Compliance-Memo
    # ==================================================================
    if agent_id == "governance":
        g1, g2, g3 = steps[0], steps[1], steps[2]
        gfacts = ""
        gsources: list[dict] = []
        web_results: list[dict] = []
        web_refs: list[dict] = []

        # Schritt 1: Kontext & Betroffenheit (Graph + Verlauf)
        yield _step_evt(g1, "running")
        try:
            r = await c.post(f"{ENGINE_URL}/retrieve",
                             json={"text": goal, "client_id": g, "limit": 8})
            d = r.json()
            gfacts = d.get("facts", "") or ""
            gsources = d.get("sources", []) or []
            cnt = d.get("count", len(gsources))
            summ = (f"{cnt} relevante Knoten im Mandanten-Kontext" if cnt
                    else "kein interner Kontext — Bewertung stützt sich auf offizielle Quellen")
            db.update_agent_step(g1["id"], tenant_id, "done", summary=summ, is_super=is_super)
            yield _step_evt(g1, "done", summary=summ)
        except Exception as e:  # noqa: BLE001
            summ = f"Retrieval nicht erreichbar ({e.__class__.__name__})"
            db.update_agent_step(g1["id"], tenant_id, "failed", summary=summ, is_super=is_super)
            yield _step_evt(g1, "failed", summary=summ)

        # Schritt 2: Rechtsgrundlagen recherchieren (offiziell/juristisch priorisiert)
        yield _step_evt(g2, "running")
        gov_note = ""
        legal_query = f"{goal} EU AI Act DSGVO Compliance Anforderungen offizielle Quelle"
        try:
            r = await c.post(f"{ASSETS_URL}/research",
                             json={"query": legal_query, "client_id": g,
                                   "max_results": 6, "ingest": False})
            d = r.json()
            if d.get("ok"):
                web_results = d.get("results", []) or []
                web_refs = d.get("references", []) or []
                n_off = sum(1 for ref in web_refs if ref.get("scientific"))
                summ = f"{len(web_refs)} Quellen ({n_off} offiziell/wissenschaftlich)"
                prov = [{"kind": "web", "n": ref.get("n"), "title": ref.get("title"),
                         "url": ref.get("url"), "scientific": ref.get("scientific")}
                        for ref in web_refs]
                db.update_agent_step(g2["id"], tenant_id, "done", summary=summ,
                                     provenance=prov, is_super=is_super)
                yield _step_evt(g2, "done", summary=summ, provenance=prov)
            else:
                reason = d.get("reason", "no_results")
                gov_note = ("Web-Recherche nicht konfiguriert (SERPAPI_KEY fehlt)."
                            if reason == "no_provider"
                            else f"Keine verwertbaren Rechtsquellen ({reason}).")
                db.update_agent_step(g2["id"], tenant_id, "skipped", summary=gov_note,
                                     is_super=is_super)
                yield _step_evt(g2, "skipped", summary=gov_note)
        except Exception as e:  # noqa: BLE001
            gov_note = f"Web-Recherche nicht erreichbar ({e.__class__.__name__})"
            db.update_agent_step(g2["id"], tenant_id, "failed", summary=gov_note,
                                 is_super=is_super)
            yield _step_evt(g2, "failed", summary=gov_note)

        # Schritt 3: Compliance-/Audit-Memo (engine /govern, streng belegt)
        yield _step_evt(g3, "running")
        turns = [h for h in (history or []) if (h.get("content") or h.get("text"))]
        hist_txt = "\n".join(
            f"{'Nutzer' if h.get('role') == 'user' else 'Assistent'}: "
            f"{(h.get('content') or h.get('text') or '').strip()}" for h in turns[-6:])
        web_facts = "\n\n".join(
            f"[{i + 1}] {r.get('title', '')} ({r.get('domain', '')}):\n{r.get('extract', '')}"
            for i, r in enumerate(web_results))
        context = (f"Interne Fakten (Mandant):\n{gfacts}\n\n" if gfacts.strip() else "")
        if hist_txt:
            context += f"Gesprächsverlauf:\n{hist_txt}"
        body = ""
        prov_used = provider
        try:
            gr = await c.post(f"{ENGINE_URL}/govern",
                              json={"query": goal, "facts": web_facts, "context": context,
                                    "provider": provider})
            gd = gr.json()
            body = gd.get("result", "") or ""
            prov_used = gd.get("provider", provider)
        except Exception:  # noqa: BLE001
            body = ""
        ref_block = "\n".join(
            f"[{ref['n']}] {ref['title']} — {ref['url']}"
            + ("  ·  offiziell/wissenschaftlich" if ref.get("scientific") else "")
            for ref in web_refs)
        grounded = bool(web_refs or gfacts.strip())
        if not body.strip():
            body = ("## Einordnung\nZu diesem Gegenstand liegen mir aktuell keine belegten "
                    "Rechtsquellen vor. " + (gov_note or "") + "\n\nIch rate nicht — bitte eine "
                    "offizielle Quelle bereitstellen oder die Web-Recherche aktivieren.\n\n"
                    "Hinweis: keine Rechtsberatung.")
        title = f"Governance-Memo: {goal[:56]}"
        markdown = f"# {title}\n\n{body}"
        if ref_block:
            markdown += f"\n\n## Quellen\n{ref_block}"
        artifact = {
            "id": f"art-{uuid.uuid4().hex[:10]}", "kind": agent["artifact_kind"],
            "title": title, "markdown": markdown, "client_id": tenant_id,
            "thread_id": thread_id or "", "created_at": db.now(),
        }
        prov3 = [{"kind": "artifact", "id": artifact["id"], "title": title}]
        summ3 = ("Compliance-/Audit-Memo erstellt (belegt)" if grounded
                 else "Memo-Entwurf ohne belegte Rechtsquellen")
        db.update_agent_step(g3["id"], tenant_id, "done", summary=summ3,
                             provenance=prov3, is_super=is_super)
        yield _step_evt(g3, "done", summary=summ3, provenance=prov3)

        web_sources = [
            {"id": ref["url"], "label": ref["title"], "type": "Rechtsquelle",
             "provenance": ref["url"],
             "props": {"domain": ref.get("domain"), "scientific": ref.get("scientific")}}
            for ref in web_refs]
        n_off = sum(1 for ref in web_refs if ref.get("scientific"))
        summary_msg = (
            f"**Governance-Assistant abgeschlossen.** Kontext: {len(gsources)} Knoten + "
            f"{len(web_refs)} Rechtsquellen ({n_off} offiziell/wissenschaftlich). Das "
            "quellenbelegte Compliance-/Audit-Memo (Einordnung · Anforderungen · Lücken · "
            "Audit-Checkliste) liegt rechts im Panel — mit *Speichern* wandert es audit-fest in "
            "Bibliothek + Graph. Keine erfundenen Normen; keine Rechtsberatung."
        )
        db.finish_agent_run(run_id, tenant_id, "done", result=summary_msg,
                            artifact_id=artifact["id"], is_super=is_super)
        yield {"type": "done", "run_id": run_id, "result_text": summary_msg,
               "artifact": artifact, "sources": web_sources, "provider": prov_used}
        return

    # ==================================================================
    # Outreach-Agent (Action): Kontext → Nachricht verfassen → Draft → FREIGABE
    # ==================================================================
    if agent_id == "outreach":
        o1, o2, o3, o4 = steps[0], steps[1], steps[2], steps[3]
        ofacts = ""

        # Schritt 1: Empfänger & Kontext (Graph + Verlauf)
        yield _step_evt(o1, "running")
        try:
            r = await c.post(f"{ENGINE_URL}/retrieve",
                             json={"text": goal, "client_id": g, "limit": 6})
            d = r.json()
            ofacts = d.get("facts", "") or ""
            cnt = d.get("count", 0)
            summ = (f"{cnt} relevante Knoten als Kontext" if cnt
                    else "kein interner Kontext — Entwurf aus dem Ziel")
            db.update_agent_step(o1["id"], tenant_id, "done", summary=summ, is_super=is_super)
            yield _step_evt(o1, "done", summary=summ)
        except Exception as e:  # noqa: BLE001
            summ = f"Retrieval nicht erreichbar ({e.__class__.__name__})"
            db.update_agent_step(o1["id"], tenant_id, "failed", summary=summ, is_super=is_super)
            yield _step_evt(o1, "failed", summary=summ)

        # Schritt 2: Nachricht verfassen (engine generiert — Verfassen ist KEIN Seiteneffekt)
        yield _step_evt(o2, "running")
        turns = [h for h in (history or []) if (h.get("content") or h.get("text"))]
        hist_txt = "\n".join(
            f"{'Nutzer' if h.get('role') == 'user' else 'Assistent'}: "
            f"{(h.get('content') or h.get('text') or '').strip()}" for h in turns[-6:])
        draft_prompt = (
            f"Entwirf eine kurze, professionelle deutsche Outreach-E-Mail. Ziel: {goal}.\n"
            + (f"\nKontext/Fakten (nur Belegtes nutzen, nichts erfinden):\n{ofacts}\n" if ofacts.strip() else "")
            + (f"\nGesprächsverlauf:\n{hist_txt}\n" if hist_txt else "")
            + "\nGib NUR den E-Mail-Text (Anrede, 2–4 knappe Absätze, Grußformel) — keine "
              "Betreffzeile, keine Erklärungen."
        )
        body = ""
        prov_used = provider
        try:
            ar = await c.post(f"{ENGINE_URL}/answer",
                              json={"text": draft_prompt, "client_id": g,
                                    "history": [], "provider": provider})
            ad = ar.json()
            body = (ad.get("result") or "").strip()
            prov_used = ad.get("provider", provider)
        except Exception:  # noqa: BLE001
            body = ""
        if not body:
            body = (f"Guten Tag,\n\n(Entwurf konnte nicht generiert werden — bitte ergänzen.)\n\n"
                    f"Anliegen: {goal}\n\nBeste Grüße")
        summ2 = f"E-Mail-Entwurf verfasst ({len(body)} Zeichen)"
        db.update_agent_step(o2["id"], tenant_id, "done", summary=summ2, is_super=is_super)
        yield _step_evt(o2, "done", summary=summ2)

        # Schritt 3: Entwurf zur FREIGABE (ActionCard) — nie automatisch senden
        yield _step_evt(o3, "running")
        # Betreff deterministisch aus dem Ziel ableiten.
        subject = goal.strip().rstrip(".!?")
        if len(subject) > 72:
            subject = subject[:69] + "…"
        action = {
            "id": f"act_{uuid.uuid4().hex[:10]}",
            "type": "gmail_draft",
            "connector": "gmail",
            "connected": False,  # ActionCard zieht den echten Status live nach
            "title": "Gmail-Entwurf anlegen",
            "summary": "Wird als Entwurf in deinem Gmail gespeichert — nichts wird automatisch gesendet.",
            "params": {"subject": subject, "body": body, "to": ""},
            "status": "pending",
        }
        summ3 = "E-Mail-Entwurf bereit — Freigabe erforderlich"
        db.update_agent_step(o3["id"], tenant_id, "done", summary=summ3, is_super=is_super)
        yield _step_evt(o3, "done", summary=summ3)

        # Schritt 4: Kalender-Slot vorschlagen (nächster Werktag 10:00, 30 Min) → FREIGABE
        yield _step_evt(o4, "running")
        slot = datetime.now() + timedelta(days=1)
        while slot.weekday() >= 5:  # Sa/So überspringen
            slot += timedelta(days=1)
        start_dt = slot.replace(hour=10, minute=0, second=0, microsecond=0)
        end_dt = start_dt + timedelta(minutes=30)
        start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%S")
        end_iso = end_dt.strftime("%Y-%m-%dT%H:%M:%S")
        calendar_action = {
            "id": f"act_{uuid.uuid4().hex[:10]}",
            "type": "gcal_event",
            "connector": "gcal",
            "connected": False,  # ActionCard zieht den echten Status live nach
            "title": "Kalender-Termin vorschlagen",
            "summary": "Wird erst nach deiner Freigabe im Google Kalender angelegt — nichts passiert automatisch.",
            "params": {
                "summary": f"Erstgespräch: {goal[:60]}",
                "description": "Vom c:node Outreach-Agent vorgeschlagen. Zeiten frei editierbar.",
                "start": start_iso, "end": end_iso, "timezone": "Europe/Berlin",
            },
            "status": "pending",
        }
        summ4 = f"Slot-Vorschlag: {start_dt.strftime('%a %d.%m. %H:%M')} (30 Min)"
        db.update_agent_step(o4["id"], tenant_id, "done", summary=summ4, is_super=is_super)
        yield _step_evt(o4, "done", summary=summ4)

        summary_msg = (
            "**Outreach-Agent abgeschlossen.** Ich habe einen **Gmail-Entwurf** und einen "
            "**Kalender-Terminvorschlag** vorbereitet — prüfe beide unten und gib sie einzeln "
            "frei. Ich sende/lege nichts automatisch an; erst nach deiner Bestätigung."
        )
        db.finish_agent_run(run_id, tenant_id, "done", result=summary_msg,
                            artifact_id=None, is_super=is_super)
        yield {"type": "done", "run_id": run_id, "result_text": summary_msg,
               "action": action, "calendar_action": calendar_action, "provider": prov_used}
        return

    graph_facts = ""
    graph_sources: list[dict] = []
    web_results: list[dict] = []
    web_refs: list[dict] = []

    # ---- Schritt 1: graph.query -----------------------------------------
    s1 = steps[0]
    yield _step_evt(s1, "running")
    try:
        r = await c.post(f"{ENGINE_URL}/retrieve",
                         json={"text": goal, "client_id": g, "limit": 8})
        d = r.json()
        graph_facts = d.get("facts", "") or ""
        graph_sources = d.get("sources", []) or []
        cnt = d.get("count", len(graph_sources))
        prov = [{"kind": "graph", "id": s.get("id"), "label": s.get("label"),
                 "layer": s.get("layer")} for s in graph_sources[:8]]
        summary = (f"{cnt} relevante Knoten im Gedächtnis"
                   if cnt else "keine relevanten Knoten — Web-Recherche folgt")
        db.update_agent_step(s1["id"], tenant_id, "done", summary=summary,
                             provenance=prov, is_super=is_super)
        yield _step_evt(s1, "done", summary=summary, provenance=prov)
    except Exception as e:  # noqa: BLE001
        summary = f"Retrieval nicht erreichbar ({e.__class__.__name__})"
        db.update_agent_step(s1["id"], tenant_id, "failed", summary=summary, is_super=is_super)
        yield _step_evt(s1, "failed", summary=summary)

    # ---- Schritt 2: web.research ----------------------------------------
    s2 = steps[1]
    yield _step_evt(s2, "running")
    research_note = ""
    try:
        r = await c.post(f"{ASSETS_URL}/research",
                         json={"query": goal, "client_id": g,
                               "max_results": 5, "ingest": False})
        d = r.json()
        if d.get("ok"):
            web_results = d.get("results", []) or []
            web_refs = d.get("references", []) or []
            n_sci = sum(1 for ref in web_refs if ref.get("scientific"))
            summary = f"{len(web_refs)} Quellen ({n_sci} wiss./offiziell)"
            prov = [{"kind": "web", "n": ref.get("n"), "title": ref.get("title"),
                     "url": ref.get("url"), "scientific": ref.get("scientific")}
                    for ref in web_refs]
            db.update_agent_step(s2["id"], tenant_id, "done", summary=summary,
                                 provenance=prov, is_super=is_super)
            yield _step_evt(s2, "done", summary=summary, provenance=prov)
        else:
            reason = d.get("reason", "no_results")
            research_note = ("Web-Recherche nicht konfiguriert (SERPAPI_KEY fehlt)."
                             if reason == "no_provider"
                             else f"Web-Recherche ohne verwertbare Treffer ({reason}).")
            db.update_agent_step(s2["id"], tenant_id, "skipped", summary=research_note,
                                 is_super=is_super)
            yield _step_evt(s2, "skipped", summary=research_note)
    except Exception as e:  # noqa: BLE001
        research_note = f"Web-Recherche nicht erreichbar ({e.__class__.__name__})"
        db.update_agent_step(s2["id"], tenant_id, "failed", summary=research_note,
                             is_super=is_super)
        yield _step_evt(s2, "failed", summary=research_note)

    # ---- Schritt 3: artifact.create (belegte Synthese) ------------------
    s3 = steps[2]
    yield _step_evt(s3, "running")

    web_facts = "\n\n".join(
        f"[{i + 1}] {r.get('title', '')} ({r.get('domain', '')}):\n{r.get('extract', '')}"
        for i, r in enumerate(web_results)
    )
    facts_block = ""
    if graph_facts.strip():
        facts_block += f"Interner Gedächtnis (Mandant, ohne externe Links):\n{graph_facts}\n\n"
    if web_facts.strip():
        facts_block += f"Web-Rechercheergebnisse (nummerierte Quellen):\n{web_facts}"

    body = ""
    prov_used = provider
    if facts_block.strip():
        try:
            sy = await c.post(f"{ENGINE_URL}/synthesize",
                              json={"query": goal, "facts": facts_block, "provider": provider})
            sd = sy.json()
            body = sd.get("result", "") or ""
            prov_used = sd.get("provider", provider)
        except Exception:  # noqa: BLE001
            body = ""

    # Referenz-Block (nur echte Web-URLs — keine erfundenen Links).
    ref_block = "\n".join(
        f"[{ref['n']}] {ref['title']} — {ref['url']}"
        + ("  ·  wissenschaftlich/offiziell" if ref.get("scientific") else "")
        for ref in web_refs
    )

    if not body.strip():
        # Deterministischer, belegter Fallback statt Halluzination.
        if graph_facts.strip():
            body = ("**Belegte Kurzfassung (Gedächtnis):**\n\n" + graph_facts)
        else:
            body = ("Zu diesem Ziel liegen mir aktuell keine belegten Quellen vor — weder im "
                    "Gedächtnis noch aus der Web-Recherche. "
                    + (research_note or "Bitte eine Quelle bereitstellen oder die Web-Recherche "
                       "aktivieren (SERPAPI_KEY)."))

    title = f"Briefing: {goal[:60]}"
    markdown = f"# {title}\n\n{body}"
    if ref_block:
        markdown += f"\n\n## Quellen (Web-Recherche)\n{ref_block}"
    if research_note and web_refs == []:
        markdown += f"\n\n> Hinweis: {research_note}"

    artifact = {
        "id": f"art-{uuid.uuid4().hex[:10]}",
        "kind": agent["artifact_kind"],
        "title": title,
        "markdown": markdown,
        "client_id": g,
        "thread_id": thread_id or "",
        "created_at": db.now(),
    }
    prov3 = [{"kind": "artifact", "id": artifact["id"], "title": title}]
    step3_summary = "Briefing erstellt (belegt)" if (web_refs or graph_facts.strip()) \
        else "Briefing-Entwurf ohne belegte Quellen"
    db.update_agent_step(s3["id"], tenant_id, "done", summary=step3_summary,
                         provenance=prov3, is_super=is_super)
    yield _step_evt(s3, "done", summary=step3_summary, provenance=prov3)

    # ---- Ergebnis: Envelope für den Chat + Artefakt für das Panel -------
    web_sources = [
        {"id": ref["url"], "label": ref["title"], "type": "WebQuelle",
         "provenance": ref["url"],
         "props": {"domain": ref.get("domain"), "scientific": ref.get("scientific")}}
        for ref in web_refs
    ]
    n_sci = sum(1 for ref in web_refs if ref.get("scientific"))
    summary_msg = (
        f"**Recherche-Agent abgeschlossen.** Ich habe das Gedächtnis abgeglichen "
        f"({len(graph_sources)} relevante Knoten) und "
        + (f"{len(web_refs)} Web-Quellen ausgewertet ({n_sci} wissenschaftlich/offiziell). "
           if web_refs else "keine Web-Quellen gefunden. ")
        + "Das belegte Briefing liegt rechts im Panel — mit *Speichern* wandert es "
          "audit-fest in die Bibliothek und das Gedächtnis."
    )

    db.finish_agent_run(run_id, tenant_id, "done", result=summary_msg,
                        artifact_id=artifact["id"], is_super=is_super)

    yield {
        "type": "done",
        "run_id": run_id,
        "result_text": summary_msg,
        "artifact": artifact,
        "sources": web_sources,
        "provider": prov_used,
    }
