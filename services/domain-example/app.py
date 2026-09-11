"""cnode-domain-example ("market-signals") — Referenz-Domäne nach dem cNode-Contract.

Zeigt, wie eine Domäne mit ~einer Funktion (enrich) auskommt. Deterministisch-first:
läuft ohne LLM. Wandelt einen Record ({organization, signal, topic, ...}) oder Freitext
in getypte Knoten + Kanten: Organization -EMITS-> Signal -ABOUT-> Topic.

Als G6-Vorlage gedacht: für eine echte Domäne nur `ONTOLOGY` + `enrich()` ersetzen.
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

DOMAIN = "market-signals"

ONTOLOGY = OntologyPack(
    domain=DOMAIN,
    version="0.1.0",
    types=[
        OntologyType(
            name="Organization", extends="schema:Organization",
            description="Ein am Markt handelnder Akteur (Firma, Behörde, Institution).",
            properties=[OntologyProperty(name="name"), OntologyProperty(name="sector")],
        ),
        OntologyType(
            name="Signal", extends="schema:Event",
            description="Ein Marktsignal/Ereignis (Ankündigung, Finanzierung, Launch, Regulierung).",
            properties=[OntologyProperty(name="summary"),
                        OntologyProperty(name="kind", value_type="enum")],
        ),
        OntologyType(
            name="Topic", extends="schema:DefinedTerm",
            description="Ein Themen-/Marktsegment, auf das sich ein Signal bezieht.",
            properties=[OntologyProperty(name="name")],
        ),
    ],
    relations=[
        OntologyRelation(**{"from": "Organization", "rel": "EMITS", "to": "Signal"},
                         description="Akteur ist Urheber des Signals."),
        OntologyRelation(**{"from": "Signal", "rel": "ABOUT", "to": "Topic"},
                         description="Signal bezieht sich auf ein Thema."),
    ],
)


def _clean(s: object) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def enrich(inp: EnrichInput) -> GraphFragment:
    """Record-first (deterministisch), Freitext als Fallback."""
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    rec = inp.record or {}

    org = _clean(rec.get("organization") or rec.get("org") or rec.get("name"))
    signal = _clean(rec.get("signal") or rec.get("summary") or inp.text)
    topic = _clean(rec.get("topic") or inp.hint)
    kind = _clean(rec.get("kind")) or "announcement"

    # Freitext-Fallback: erstes großgeschriebenes Mehrwort-Token als Organization raten.
    if not org and inp.text:
        m = re.search(r"\b([A-ZÄÖÜ][\wÄÖÜäöüß.&-]+(?:\s+[A-ZÄÖÜ][\wÄÖÜäöüß.&-]+){0,3})", inp.text)
        org = _clean(m.group(1)) if m else ""

    if not signal:
        return GraphFragment(note="kein Signal erkennbar (record.signal oder text nötig)")

    sig_label = signal[:80]
    nodes.append(GraphNode(label=sig_label, type="Signal",
                           props={"summary": signal[:400], "kind": kind}))
    if org:
        nodes.append(GraphNode(label=org, type="Organization",
                               props={"name": org, **({"sector": _clean(rec.get("sector"))} if rec.get("sector") else {})}))
        edges.append(GraphEdge(source=org, target=sig_label, rel="EMITS"))
    if topic:
        nodes.append(GraphNode(label=topic, type="Topic", props={"name": topic}))
        edges.append(GraphEdge(source=sig_label, target=topic, rel="ABOUT"))

    return GraphFragment(nodes=nodes, edges=edges,
                         note=f"{len(nodes)} Knoten · {len(edges)} Kanten (market-signals)")


app = create_domain_app(domain=DOMAIN, name="Market Signals", enrich=enrich,
                        ontology=ONTOLOGY, version="0.1.0")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8090)
