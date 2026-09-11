"""cNode Domain-Service-Contract — die Schablone für Domänen-Microservices.

Eine Domäne (funding/Förder, sales, legal …) ist ein zustandsloser Producer: sie
kennt ein Fach-Vokabular (Ontologie) und wandelt Input (Text/URL/Record) in ein
getyptes Graph-Fragment. Sie schreibt NIE selbst in den Graphen — das tut allein die
Engine über ihren Graph-Adapter (Provenienz + Layer erzwungen, EU-AI-Act-Audit-Trail).

Contract (jede Domäne erfüllt genau diese drei Routen):
  GET  /health    → {status, service, domain, version}
  GET  /ontology  → OntologyPack  (Typen + Relationen des Fachgebiets)
  POST /enrich    → GraphFragment (getypte Knoten/Kanten aus dem Input)

`create_domain_app(...)` verdrahtet die drei Routen und stempelt das Provenienz-Label
auf jedes Fragment — ein Domänen-Service ist damit ~30 Zeilen (siehe services/domain-example).
"""
from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel, Field


# --- Ontologie-Pack ----------------------------------------------------------
class OntologyProperty(BaseModel):
    name: str
    value_type: str = "string"        # string | number | date | url | enum
    description: str = ""


class OntologyType(BaseModel):
    name: str                          # Knoten-Typ (z.B. "FundingProgram")
    extends: str = ""                  # optionaler Basistyp (schema.org/FIBO-Anlehnung)
    description: str = ""
    properties: list[OntologyProperty] = Field(default_factory=list)


class OntologyRelation(BaseModel):
    from_type: str = Field(alias="from")
    rel: str                           # UPPER_SNAKE (z.B. "FUNDS", "ELIGIBLE_FOR")
    to_type: str = Field(alias="to")
    description: str = ""

    model_config = {"populate_by_name": True}


class OntologyPack(BaseModel):
    domain: str
    version: str = "0.1.0"
    provenance_label: str = ""         # Quelle-Label je Aussage (default: "domain:<id>")
    types: list[OntologyType] = Field(default_factory=list)
    relations: list[OntologyRelation] = Field(default_factory=list)


# --- Graph-Fragment (das Ergebnis von /enrich) -------------------------------
class GraphNode(BaseModel):
    id: str = ""                       # leer → Engine leitet aus label ab
    label: str
    type: str
    props: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    source: str                        # id ODER label (Engine löst auf)
    target: str
    rel: str = "RELATED_TO"
    provenance: str = ""


class GraphFragment(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    note: str = ""


# --- /enrich Eingabe ---------------------------------------------------------
class EnrichInput(BaseModel):
    text: str = ""
    url: str = ""
    record: dict[str, Any] = Field(default_factory=dict)
    hint: str = ""                     # freier Kontext-Hinweis (z.B. Region, Branche)


EnrichFn = Callable[[EnrichInput], GraphFragment]


def create_domain_app(
    *,
    domain: str,
    name: str,
    enrich: EnrichFn,
    ontology: OntologyPack,
    version: str = "0.1.0",
):
    """Baut die FastAPI-App eines Domänen-Services nach dem Contract.

    `enrich` ist die einzige Fachlogik, die eine Domäne mitbringt: EnrichInput →
    GraphFragment. Provenienz wird auf jedes Fragment gestempelt (falls leer)."""
    from fastapi import FastAPI  # lazy: SDK bleibt ohne FastAPI importierbar

    prov = ontology.provenance_label or f"domain:{domain}"
    ontology.provenance_label = prov
    ontology.domain = ontology.domain or domain
    ontology.version = ontology.version or version

    app = FastAPI(title=f"cnode-domain-{domain}", version=version)

    @app.get("/health")
    def health():
        return {"status": "ok", "service": name, "domain": domain, "version": version,
                "types": [t.name for t in ontology.types]}

    @app.get("/ontology")
    def get_ontology():
        return ontology.model_dump(by_alias=True)

    @app.post("/enrich")
    def post_enrich(inp: EnrichInput) -> GraphFragment:
        frag = enrich(inp)
        # Provenienz erzwingen: leere Kanten-Provenienz auf das Domänen-Label setzen,
        # Herkunft je Knoten sicherstellen (der finale Layer wird von der Engine gesetzt).
        for e in frag.edges:
            if not e.provenance:
                e.provenance = prov
        for n in frag.nodes:
            n.props.setdefault("provenance", prov)
        return frag

    return app


__all__ = [
    "OntologyProperty", "OntologyType", "OntologyRelation", "OntologyPack",
    "GraphNode", "GraphEdge", "GraphFragment", "EnrichInput", "EnrichFn",
    "create_domain_app",
]
