"""cnode-domain-funding (Förder) — Förder-/Antrags-Domäne nach dem cNode-Contract.

Fach-Ontologie rund um öffentliche Förderung (Zuschuss/Darlehen/Bürgschaft), die
ausschreibende Stelle, förderfähige Antragsteller, Region und die zugehörige
Verwaltungsleistung (LeiKa). Zustandsloser Producer: liefert getypte Graph-Fragmente;
persistiert wird über den Engine-Adapter — hier i.d.R. in die geteilte market/mesh-Ebene.

Deterministisch-first (Record), Freitext-Fallback. G6 nutzt data-foerder als Loader
(LeiKa-Leistungen) → /enrich; die Ontologie ist die Schablone dafür.
"""
from __future__ import annotations

import re

from cnode_sdk.domain import (
    EnrichInput,
    GraphEdge,
    GraphFragment,
    GraphNode,
    OntologyPack,
    OntologyProperty,
    OntologyRelation,
    OntologyType,
    create_domain_app,
)

DOMAIN = "funding"

ONTOLOGY = OntologyPack(
    domain=DOMAIN,
    version="0.1.0",
    types=[
        OntologyType(
            name="FundingProgram", extends="schema:GovernmentService",
            description="Ein Förderprogramm (Zuschuss, Darlehen, Bürgschaft, Beteiligung).",
            properties=[
                OntologyProperty(name="name"),
                OntologyProperty(name="funding_type", value_type="enum",
                                 description="Zuschuss | Darlehen | Bürgschaft | Beteiligung"),
                OntologyProperty(name="max_amount", value_type="number"),
                OntologyProperty(name="deadline", value_type="date"),
            ],
        ),
        OntologyType(
            name="FundingBody", extends="schema:GovernmentOrganization",
            description="Ausschreibende Stelle (Bund/Land/EU/Förderbank, z.B. BMWK, KfW, ESF).",
            properties=[OntologyProperty(name="name"), OntologyProperty(name="level")],
        ),
        OntologyType(
            name="Applicant", extends="schema:Organization",
            description="Förderfähiger Antragstellertyp (KMU, Start-up, Solo-Selbstständige, Kommune).",
            properties=[OntologyProperty(name="name")],
        ),
        OntologyType(
            name="Region", extends="schema:AdministrativeArea",
            description="Geltungsraum (EU, Bund, Bundesland, Kommune).",
            properties=[OntologyProperty(name="name")],
        ),
        OntologyType(
            name="LeiKaService", extends="schema:GovernmentService",
            description="Verwaltungsleistung nach Leistungskatalog (LeiKa/data-foerder).",
            properties=[OntologyProperty(name="name"), OntologyProperty(name="leika_id")],
        ),
    ],
    relations=[
        OntologyRelation(**{"from": "FundingBody", "rel": "OFFERS", "to": "FundingProgram"},
                         description="Stelle vergibt das Programm."),
        OntologyRelation(**{"from": "FundingProgram", "rel": "TARGETS", "to": "Applicant"},
                         description="Programm richtet sich an Antragstellertyp."),
        OntologyRelation(**{"from": "FundingProgram", "rel": "APPLIES_IN", "to": "Region"},
                         description="Geltungsraum des Programms."),
        OntologyRelation(**{"from": "FundingProgram", "rel": "COVERS", "to": "LeiKaService"},
                         description="Programm bezieht sich auf eine Verwaltungsleistung."),
    ],
)


def _clean(s: object) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def enrich(inp: EnrichInput) -> GraphFragment:
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    rec = inp.record or {}

    program = _clean(rec.get("program") or rec.get("name") or inp.text)
    if not program and inp.text:
        m = re.search(r"\b([A-ZÄÖÜ][\wÄÖÜäöüß.&/-]+(?:\s+[A-ZÄÖÜ][\wÄÖÜäöüß.&/-]+){0,5})", inp.text)
        program = _clean(m.group(1)) if m else ""
    if not program:
        return GraphFragment(note="kein Förderprogramm erkennbar (record.program oder text nötig)")

    p_props = {}
    for k in ("funding_type", "max_amount", "deadline"):
        if rec.get(k) not in (None, ""):
            p_props[k] = _clean(rec.get(k)) if k != "max_amount" else rec.get(k)
    nodes.append(GraphNode(label=program[:120], type="FundingProgram", props=p_props))

    def link(field: str, typ: str, rel: str, reverse: bool = False) -> None:
        val = _clean(rec.get(field))
        if not val:
            return
        nodes.append(GraphNode(label=val[:120], type=typ, props={"name": val}))
        if reverse:
            edges.append(GraphEdge(source=val, target=program, rel=rel))
        else:
            edges.append(GraphEdge(source=program, target=val, rel=rel))

    link("provider", "FundingBody", "OFFERS", reverse=True)
    link("applicant", "Applicant", "TARGETS")
    link("region", "Region", "APPLIES_IN")
    leika = _clean(rec.get("leika") or rec.get("leika_service"))
    if leika:
        lid = _clean(rec.get("leika_id"))
        nodes.append(GraphNode(label=leika[:120], type="LeiKaService",
                               props={"name": leika, **({"leika_id": lid} if lid else {})}))
        edges.append(GraphEdge(source=program, target=leika, rel="COVERS"))

    return GraphFragment(nodes=nodes, edges=edges,
                         note=f"{len(nodes)} Knoten · {len(edges)} Kanten (funding)")


app = create_domain_app(domain=DOMAIN, name="Funding / Förder", enrich=enrich,
                        ontology=ONTOLOGY, version="0.1.0")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8091)
