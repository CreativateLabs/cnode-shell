"""Ontology-Studio — Auto-Ontologie-Pipeline (cNode Kern-Differenzierer, Ebene 4).

Quelle (Tabellen-Spalten / Text) → getypte Ontologie-Vorschlag, gebenchmarkt gegen
schema.org / FIBO / ISO — deterministisch-first (läuft ohne LLM). `apply` schreibt die
bestätigte Ontologie mit Provenienz in den TENANT-Graph (über die Engine).

Endpoints:
  GET  /health
  POST /ontology/suggest   {columns?, text?, sample_rows?, entity_hint?}  → Ontologie-Vorschlag + Benchmark
  POST /ontology/apply     {entity_type, label_column, properties, rows, client_id}  → in den Graph
"""
from __future__ import annotations

import os

import httpx
from fastapi import FastAPI
from pydantic import BaseModel, Field

from vocab import ENTITY_LIKE, REFERENCE, match_type, value_type

ENGINE_URL = os.getenv("ENGINE_URL", "http://engine:8020").rstrip("/")

app = FastAPI(title="ontology-studio", version="0.1.0")


class SuggestReq(BaseModel):
    columns: list[str] = Field(default_factory=list)
    text: str = ""
    sample_rows: list[list[str]] = Field(default_factory=list)
    entity_hint: str = ""          # z.B. Dateiname/Domäne, hilft beim Haupttyp
    client_id: str = "default"


class ApplyReq(BaseModel):
    entity_type: str
    label_column: str = ""         # welche Spalte den Knoten-Namen liefert (sonst erste)
    properties: list[dict] = Field(default_factory=list)  # aus /suggest, ggf. editiert
    rows: list[dict] = Field(default_factory=list)         # [{col: value}]
    client_id: str = "default"


@app.get("/health")
def health():
    return {"status": "ok", "service": "ontology-studio",
            "reference_types": sorted(REFERENCE.keys()),
            "ontologies": sorted({m["onto"] for m in REFERENCE.values()})}


@app.get("/ontology/vocabulary")
async def vocabulary(client_id: str = "default"):
    """Benchmark-Vokabular: statische Referenz (schema.org/FIBO/ISO) + die Ontologie-Packs
    der aktiven Domänen dieses Tenants (via Engine /domains). So fließen Fach-Typen der
    Domänen (funding/sales/legal …) in die Ontologie-Vorschläge ein (G5.3)."""
    reference = {t: {"onto": m["onto"]} for t, m in REFERENCE.items()}
    domain_types: dict[str, dict] = {}
    domains_seen: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            data = (await c.get(f"{ENGINE_URL}/domains")).json()
        for d in data.get("domains", []):
            onto = d.get("ontology") or {}
            dom = onto.get("domain") or d.get("id")
            if onto.get("types"):
                domains_seen.append(dom)
            for t in onto.get("types", []):
                domain_types[t["name"]] = {
                    "onto": f"domain:{dom}", "extends": t.get("extends", ""),
                    "description": t.get("description", ""),
                }
    except Exception:  # noqa: BLE001
        pass
    return {
        "reference": reference,
        "domain_types": domain_types,
        "domains": domains_seen,
        "total_types": len(reference) + len(domain_types),
    }


def _keywords_from_text(text: str) -> list[str]:
    """Sehr grobe Begriffs-Extraktion aus Freitext (deterministisch): Groß-/Fachbegriffe."""
    import re
    toks = re.findall(r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß\-]{3,}", text or "")
    seen, out = set(), []
    for t in toks:
        k = t.lower()
        if k not in seen:
            seen.add(k); out.append(t)
    return out[:40]


@app.post("/ontology/suggest")
def suggest(req: SuggestReq):
    # Kandidaten-Spalten: explizit übergeben, sonst aus Text abgeleitet.
    columns = req.columns or _keywords_from_text(req.text)
    props, entity_votes, used_onto = [], {}, {}
    for col in columns:
        m = match_type(col)
        vt = value_type(col)
        props.append({"name": col, "maps_to": m["type"], "onto": m["onto"],
                      "confidence": m["confidence"], "role": m["role"], "value_type": vt})
        if m["role"] == "entity" and m["confidence"] > 0:
            entity_votes[m["type"]] = entity_votes.get(m["type"], 0) + m["confidence"]
        if m["confidence"] > 0:
            used_onto[m["onto"]] = used_onto.get(m["onto"], 0) + 1

    # Haupt-Entitätstyp: Hint > stärkstes Entity-Voting > 'Thing'.
    hint = match_type(req.entity_hint) if req.entity_hint else None
    if hint and hint["type"] in ENTITY_LIKE and hint["confidence"] > 0:
        entity_type = hint["type"]
    elif entity_votes:
        entity_type = max(entity_votes, key=entity_votes.get)
    else:
        entity_type = "Thing"

    # Relationen: Spalten, die auf ANDERE Entitätstypen zeigen → getypte Kanten.
    relations = [
        {"from": entity_type, "rel": f"HAS_{p['maps_to'].upper()}", "to": p["maps_to"],
         "via_column": p["name"]}
        for p in props
        if p["role"] == "entity" and p["maps_to"] != entity_type and p["confidence"] > 0
    ]

    mapped = sum(1 for p in props if p["confidence"] > 0)
    coverage = round(mapped / len(props), 2) if props else 0.0
    return {
        "entity_type": entity_type,
        "properties": props,
        "relations": relations,
        "benchmark": {"coverage": coverage, "mapped": mapped, "total": len(props),
                      "ontologies": used_onto},
    }


async def _ingest_node(c: httpx.AsyncClient, label: str, ntype: str, props: dict,
                       content: str, client_id: str, links: list[dict]) -> bool:
    try:
        r = await c.post(f"{ENGINE_URL}/ingest", json={
            "label": label[:160], "type": ntype, "props": props, "content": content,
            "links": links, "client_id": client_id, "levels": ["client"]})
        return r.status_code < 300
    except Exception:
        return False


@app.post("/ontology/apply")
async def apply(req: ApplyReq):
    """Schreibt die bestätigte Ontologie als getypte Knoten (+ Relationen) in den
    Tenant-Graph. Jede Zeile → ein Knoten vom entity_type; Entity-Spalten → verlinkte
    Knoten ihres Referenz-Typs. Provenienz: ontology-studio."""
    if not req.rows:
        return {"ok": False, "reason": "no_rows"}
    label_col = req.label_column or (req.properties[0]["name"] if req.properties else "")
    entity_props = {p["name"]: p for p in req.properties}
    relation_cols = [p["name"] for p in req.properties
                     if p.get("role") == "entity" and p.get("maps_to") != req.entity_type
                     and p.get("confidence", 0) > 0]

    written, edges, seen_targets = 0, 0, set()
    async with httpx.AsyncClient(timeout=60.0) as c:
        for row in req.rows[:2000]:
            label = str(row.get(label_col) or next(iter(row.values()), "Eintrag"))
            content = "; ".join(f"{k}: {v}" for k, v in row.items() if v not in (None, ""))
            # Verlinkte Entitäten (dedupliziert) aus Relation-Spalten.
            links = []
            for rc in relation_cols:
                val = str(row.get(rc) or "").strip()
                if not val:
                    continue
                tgt_type = entity_props[rc]["maps_to"]
                if (val, tgt_type) not in seen_targets:
                    seen_targets.add((val, tgt_type))
                    await _ingest_node(c, val, tgt_type,
                                       {"provenance": "ontology-studio"}, val, req.client_id, [])
                links.append({"target": val, "rel": f"HAS_{tgt_type.upper()}",
                              "provenance": "ontology-studio"})
                edges += 1
            props = {"provenance": "ontology-studio", "ontology": req.entity_type,
                     **{k: str(v) for k, v in row.items() if v not in (None, "")}}
            if await _ingest_node(c, label, req.entity_type, props, content, req.client_id, links):
                written += 1

    return {"ok": True, "entity_type": req.entity_type, "nodes_written": written,
            "relations": edges, "client_id": req.client_id,
            "note": "asynchrone NEN-Extraktion — Materialisierung folgt beim Draining"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8070)
