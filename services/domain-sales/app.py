"""cnode-domain-sales — Sales/CRM-Domäne nach dem cNode-Contract (G8.1).

Fach-Ontologie rund um Vertrieb: Unternehmen, Kontakte, Leads, Deals, Aktivitäten.
Zustandsloser Producer (Record-first, Freitext-Fallback) — die Engine persistiert.
"""
from __future__ import annotations

import re

from cnode_sdk.domain import (
    EnrichInput, GraphEdge, GraphFragment, GraphNode,
    OntologyPack, OntologyProperty, OntologyRelation, OntologyType, create_domain_app,
)

DOMAIN = "sales"

ONTOLOGY = OntologyPack(
    domain=DOMAIN, version="0.1.0",
    types=[
        OntologyType(name="Company", extends="schema:Organization",
                     description="Ziel-/Kundenunternehmen.",
                     properties=[OntologyProperty(name="name"), OntologyProperty(name="industry")]),
        OntologyType(name="Contact", extends="schema:Person",
                     description="Ansprechpartner beim Unternehmen.",
                     properties=[OntologyProperty(name="name"), OntologyProperty(name="role")]),
        OntologyType(name="Lead", extends="schema:Thing",
                     description="Qualifizierter Interessent (vor dem Deal)."),
        OntologyType(name="Deal", extends="schema:Order",
                     description="Verkaufschance/Opportunity.",
                     properties=[OntologyProperty(name="stage", value_type="enum"),
                                 OntologyProperty(name="value", value_type="number")]),
        OntologyType(name="Activity", extends="schema:Event",
                     description="Vertriebsaktivität (Call, Mail, Meeting)."),
    ],
    relations=[
        OntologyRelation(**{"from": "Contact", "rel": "WORKS_AT", "to": "Company"}),
        OntologyRelation(**{"from": "Deal", "rel": "WITH", "to": "Company"}),
        OntologyRelation(**{"from": "Lead", "rel": "CONVERTS_TO", "to": "Deal"}),
        OntologyRelation(**{"from": "Activity", "rel": "ABOUT", "to": "Deal"}),
    ],
)


def _clean(s: object) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def enrich(inp: EnrichInput) -> GraphFragment:
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    rec = inp.record or {}
    company = _clean(rec.get("company") or rec.get("account"))
    contact = _clean(rec.get("contact") or rec.get("person"))
    deal = _clean(rec.get("deal") or rec.get("opportunity") or inp.text)

    if not company and not deal and inp.text:
        m = re.search(r"\b([A-ZÄÖÜ][\wÄÖÜäöüß.&-]+(?:\s+[A-ZÄÖÜ][\wÄÖÜäöüß.&-]+){0,3})", inp.text)
        company = _clean(m.group(1)) if m else ""

    if company:
        nodes.append(GraphNode(label=company[:120], type="Company",
                               props={"name": company, **({"industry": _clean(rec.get("industry"))} if rec.get("industry") else {})}))
    if contact:
        nodes.append(GraphNode(label=contact[:120], type="Contact",
                               props={"name": contact, **({"role": _clean(rec.get("role"))} if rec.get("role") else {})}))
        if company:
            edges.append(GraphEdge(source=contact, target=company, rel="WORKS_AT"))
    if deal:
        dp = {}
        if rec.get("stage"):
            dp["stage"] = _clean(rec.get("stage"))
        if rec.get("value") not in (None, ""):
            dp["value"] = rec.get("value")
        nodes.append(GraphNode(label=deal[:120], type="Deal", props=dp))
        if company:
            edges.append(GraphEdge(source=deal, target=company, rel="WITH"))
    if not nodes:
        return GraphFragment(note="kein Sales-Objekt erkennbar (company/contact/deal)")
    return GraphFragment(nodes=nodes, edges=edges,
                         note=f"{len(nodes)} Knoten · {len(edges)} Kanten (sales)")


app = create_domain_app(domain=DOMAIN, name="Sales / CRM", enrich=enrich,
                        ontology=ONTOLOGY, version="0.1.0")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8092)
