"""cnode-domain-legal — Regulatorik/Legal-Domäne nach dem cNode-Contract (G8.2).

Fach-Ontologie rund um Regulierung: Vorschrift, Pflicht, Behörde, Dokument, Frist.
Zustandsloser Producer (Record-first, Freitext-Fallback) — die Engine persistiert.
"""
from __future__ import annotations

import re

from cnode_sdk.domain import (
    EnrichInput, GraphEdge, GraphFragment, GraphNode,
    OntologyPack, OntologyProperty, OntologyRelation, OntologyType, create_domain_app,
)

DOMAIN = "legal"

ONTOLOGY = OntologyPack(
    domain=DOMAIN, version="0.1.0",
    types=[
        OntologyType(name="Regulation", extends="schema:Legislation",
                     description="Rechtsnorm / Vorschrift (Gesetz, Verordnung, Richtlinie).",
                     properties=[OntologyProperty(name="name"), OntologyProperty(name="reference")]),
        OntologyType(name="Obligation", extends="schema:Thing",
                     description="Konkrete Pflicht/Anforderung aus einer Vorschrift."),
        OntologyType(name="Authority", extends="schema:GovernmentOrganization",
                     description="Zuständige Behörde/Aufsicht."),
        OntologyType(name="LegalDocument", extends="schema:DigitalDocument",
                     description="Rechtsdokument (Vertrag, Policy, Nachweis)."),
        OntologyType(name="Deadline", extends="schema:Event",
                     description="Frist/Termin einer Pflicht.",
                     properties=[OntologyProperty(name="date", value_type="date")]),
    ],
    relations=[
        OntologyRelation(**{"from": "Authority", "rel": "ISSUES", "to": "Regulation"}),
        OntologyRelation(**{"from": "Regulation", "rel": "IMPOSES", "to": "Obligation"}),
        OntologyRelation(**{"from": "Obligation", "rel": "HAS_DEADLINE", "to": "Deadline"}),
        OntologyRelation(**{"from": "LegalDocument", "rel": "REFERENCES", "to": "Regulation"}),
    ],
)


def _clean(s: object) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def enrich(inp: EnrichInput) -> GraphFragment:
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    rec = inp.record or {}
    regulation = _clean(rec.get("regulation") or rec.get("norm") or inp.text)
    authority = _clean(rec.get("authority") or rec.get("behoerde"))
    obligation = _clean(rec.get("obligation") or rec.get("pflicht"))
    deadline = _clean(rec.get("deadline") or rec.get("frist"))

    if not regulation:
        return GraphFragment(note="keine Vorschrift erkennbar (record.regulation oder text nötig)")

    rp = {"name": regulation}
    if rec.get("reference"):
        rp["reference"] = _clean(rec.get("reference"))
    nodes.append(GraphNode(label=regulation[:140], type="Regulation", props=rp))

    if authority:
        nodes.append(GraphNode(label=authority[:120], type="Authority", props={"name": authority}))
        edges.append(GraphEdge(source=authority, target=regulation, rel="ISSUES"))
    if obligation:
        nodes.append(GraphNode(label=obligation[:160], type="Obligation", props={}))
        edges.append(GraphEdge(source=regulation, target=obligation, rel="IMPOSES"))
        if deadline:
            nodes.append(GraphNode(label=deadline[:120], type="Deadline",
                                   props={"date": deadline}))
            edges.append(GraphEdge(source=obligation, target=deadline, rel="HAS_DEADLINE"))
    return GraphFragment(nodes=nodes, edges=edges,
                         note=f"{len(nodes)} Knoten · {len(edges)} Kanten (legal)")


app = create_domain_app(domain=DOMAIN, name="Legal / Regulatorik", enrich=enrich,
                        ontology=ONTOLOGY, version="0.1.0")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8093)
