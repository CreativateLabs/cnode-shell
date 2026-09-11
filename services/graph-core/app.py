"""graph-core — souveräne, tenant-aware Graph-Runtime auf Postgres + pgvector.

Zero-cost, permissiv, air-gapped. Multi-tenant über `grp` (client/market/mesh laufen
als eigene groups). **Synchron & getypt**: /ingest schreibt Knoten + Relationen sofort
und legt fehlende Zielknoten an — kein async Extraktions-Queue. `/retrieve` kombiniert
**semantische** Vektor-Suche (pgvector, Embeddings via Ollama) mit lexikalischem Fallback.
Jede Kante trägt `provenance` (belegbar).
"""
from __future__ import annotations

import json
import logging
import os
import re

import httpx
import psycopg
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("graph-core")

PG_DSN = os.getenv("PG_DSN", "postgresql://cnode:cnode@graph-db:5432/graph")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434").rstrip("/")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
EMBED_DIM = int(os.getenv("EMBED_DIM", "768"))
SEED_PATH = os.getenv("SEED_PATH", "/seed/graph.json")
SEED_GROUP = os.getenv("SEED_GROUP", "creativate")

app = FastAPI(title="graph-core", version="0.3.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _conn():
    return psycopg.connect(PG_DSN, autocommit=True)


def _slug(s: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in (s or "")).strip("_")[:60] or "node"


def _embed(text: str) -> list[float] | None:
    """Embedding via Ollama (nomic-embed-text). None bei Fehler → lexikalischer Fallback."""
    t = (text or "").strip()
    if not t:
        return None
    try:
        r = httpx.post(f"{OLLAMA_URL}/api/embed", json={"model": EMBED_MODEL, "input": t[:2000]}, timeout=20.0)
        r.raise_for_status()
        embs = r.json().get("embeddings") or []
        return embs[0] if embs and len(embs[0]) == EMBED_DIM else None
    except Exception:
        return None


def _vec_literal(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


class IngestReq(BaseModel):
    label: str
    type: str = "Document"
    props: dict = {}
    content: str = ""
    links: list[dict] = []          # [{"target","rel","type"?,"provenance"?}]
    group: str = "creativate"
    id: str | None = None


def _init_db() -> None:
    with _conn() as c:
        c.execute("CREATE EXTENSION IF NOT EXISTS vector")
        c.execute(f"""
            CREATE TABLE IF NOT EXISTS nodes (
              grp text NOT NULL, id text NOT NULL, label text, type text,
              props jsonb DEFAULT '{{}}'::jsonb, embedding vector({EMBED_DIM}),
              PRIMARY KEY (grp, id)
            )""")
        c.execute("""
            CREATE TABLE IF NOT EXISTS edges (
              grp text NOT NULL, source text NOT NULL, target text NOT NULL,
              rel text NOT NULL, provenance text,
              PRIMARY KEY (grp, source, target, rel)
            )""")
        c.execute("CREATE INDEX IF NOT EXISTS nodes_grp_idx ON nodes(grp)")
        c.execute("CREATE INDEX IF NOT EXISTS edges_grp_idx ON edges(grp)")


def _upsert_node(c, grp: str, nid: str, label: str, ntype: str, props: dict, embed: bool) -> None:
    # Embedding zuerst holen, dann NUR bei Erfolg als Vektor-Literal formatieren. Ohne
    # Embedding-Backend (kein Ollama) liefert _embed None → Knoten wird ohne Embedding
    # gespeichert (lexikalischer Retrieval-Fallback greift), statt hart zu crashen.
    emb = _embed(f"{label}. {props.get('content','')}") if embed else None
    vec = _vec_literal(emb) if emb is not None else None
    if vec is not None:
        c.execute(
            "INSERT INTO nodes (grp,id,label,type,props,embedding) VALUES (%s,%s,%s,%s,%s,%s::vector) "
            "ON CONFLICT (grp,id) DO UPDATE SET label=EXCLUDED.label, type=EXCLUDED.type, "
            "props=EXCLUDED.props, embedding=EXCLUDED.embedding",
            (grp, nid, label, ntype, json.dumps(props, ensure_ascii=False), vec))
    else:
        c.execute(
            "INSERT INTO nodes (grp,id,label,type,props) VALUES (%s,%s,%s,%s,%s) "
            "ON CONFLICT (grp,id) DO UPDATE SET label=EXCLUDED.label, type=EXCLUDED.type, props=EXCLUDED.props",
            (grp, nid, label, ntype, json.dumps(props, ensure_ascii=False)))


def load_seed(group: str = SEED_GROUP) -> int:
    if not os.path.exists(SEED_PATH):
        log.warning("seed missing at %s", SEED_PATH)
        return 0
    data = json.loads(open(SEED_PATH, encoding="utf-8").read())
    nodes, edges = data.get("nodes", []), data.get("edges", [])
    with _conn() as c:
        for n in nodes:
            _upsert_node(c, group, n["id"], n["label"], n.get("type", "Entity"), n.get("props", {}), embed=True)
        for e in edges:
            c.execute("INSERT INTO edges (grp,source,target,rel,provenance) VALUES (%s,%s,%s,%s,%s) "
                      "ON CONFLICT DO NOTHING",
                      (group, e["source"], e["target"], e.get("rel", "REL"), e.get("provenance", "")))
    log.info("seed loaded into grp=%s: %d nodes, %d edges", group, len(nodes), len(edges))
    return len(nodes)


@app.on_event("startup")
def _startup():
    try:
        _init_db()
        with _conn() as c:
            cnt = c.execute("SELECT count(*) FROM nodes WHERE grp=%s", (SEED_GROUP,)).fetchone()[0]
        if cnt == 0:
            load_seed()
    except Exception as e:
        log.warning("startup skipped: %s", e)


@app.get("/health")
def health():
    try:
        with _conn() as c:
            nodes = c.execute("SELECT count(*) FROM nodes").fetchone()[0]
            edges = c.execute("SELECT count(*) FROM edges").fetchone()[0]
            groups = [r[0] for r in c.execute("SELECT DISTINCT grp FROM nodes").fetchall()]
        return {"status": "ok", "service": "graph-core", "store": "postgres+pgvector",
                "nodes": nodes, "edges": edges, "groups": groups, "embed_model": EMBED_MODEL}
    except Exception as e:
        return {"status": "degraded", "service": "graph-core", "error": str(e)}


_REQS: dict[tuple, int] = {}


@app.middleware("http")
async def _count_requests(request, call_next):
    resp = await call_next(request)
    try:
        _REQS[(request.method, resp.status_code)] = _REQS.get((request.method, resp.status_code), 0) + 1
    except Exception:  # noqa: BLE001
        pass
    return resp


def _esc(s: str) -> str:
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


@app.get("/metrics")
def metrics():
    """Prometheus-Metriken (zero-dep Text-Exposition): Graph-Kennzahlen je Group + HTTP."""
    lines = [
        "# HELP cnode_up Service erreichbar (1).",
        "# TYPE cnode_up gauge",
        'cnode_up{service="graph-core"} 1',
        "# HELP cnode_graph_nodes Knoten je Graph-Group.",
        "# TYPE cnode_graph_nodes gauge",
        "# HELP cnode_graph_edges Kanten je Graph-Group.",
        "# TYPE cnode_graph_edges gauge",
        "# HELP cnode_graph_orphan_rate Anteil loser Knoten je Group (Ziel < 0.15).",
        "# TYPE cnode_graph_orphan_rate gauge",
    ]
    try:
        with _conn() as c:
            rows = c.execute(
                "SELECT n.grp, count(*) AS nodes, "
                "  count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM edges e "
                "     WHERE e.grp=n.grp AND (e.source=n.id OR e.target=n.id))) AS orphans "
                "FROM nodes n GROUP BY n.grp").fetchall()
            edge_rows = dict(c.execute("SELECT grp, count(*) FROM edges GROUP BY grp").fetchall())
        for r in rows:
            g = _esc(r[0]); nodes = r[1]; orphans = r[2]
            rate = round(orphans / nodes, 4) if nodes else 0.0
            lines.append(f'cnode_graph_nodes{{service="graph-core",group="{g}"}} {nodes}')
            lines.append(f'cnode_graph_edges{{service="graph-core",group="{g}"}} {edge_rows.get(r[0], 0)}')
            lines.append(f'cnode_graph_orphan_rate{{service="graph-core",group="{g}"}} {rate}')
    except Exception:  # noqa: BLE001
        pass
    lines += [
        "# HELP cnode_http_requests_total HTTP-Requests nach Methode/Status.",
        "# TYPE cnode_http_requests_total counter",
    ]
    for (method, status), n in _REQS.items():
        lines.append(f'cnode_http_requests_total{{service="graph-core",method="{_esc(method)}",status="{status}"}} {n}')
    return PlainTextResponse("\n".join(lines) + "\n")


@app.get("/stats")
def stats(group: str = "creativate"):
    """Konnektivitäts-Metrik je group: Knoten/Kanten + Orphan-Rate (Ziel < 15 %)."""
    with _conn() as c:
        nodes = c.execute("SELECT count(*) FROM nodes WHERE grp=%s", (group,)).fetchone()[0]
        edges = c.execute("SELECT count(*) FROM edges WHERE grp=%s", (group,)).fetchone()[0]
        orphans = c.execute(
            "SELECT count(*) FROM nodes n WHERE n.grp=%s AND NOT EXISTS "
            "(SELECT 1 FROM edges e WHERE e.grp=n.grp AND (e.source=n.id OR e.target=n.id))",
            (group,)).fetchone()[0]
    rate = round(orphans / nodes, 3) if nodes else 0.0
    return {"group": group, "nodes": nodes, "edges": edges,
            "orphans": orphans, "orphan_rate": rate, "target": 0.15}


def _rows_to_nodes(rows) -> list[dict]:
    return [{"id": r[0], "label": r[1], "type": r[2], "props": r[3] or {}} for r in rows]


@app.get("/graph")
def graph(group: str = "creativate", limit: int = 300):
    with _conn() as c:
        nrows = c.execute("SELECT id,label,type,props FROM nodes WHERE grp=%s LIMIT %s",
                          (group, limit)).fetchall()
        erows = c.execute("SELECT source,target,rel,provenance FROM edges WHERE grp=%s LIMIT %s",
                          (group, limit * 3)).fetchall()
    edges = [{"source": r[0], "target": r[1], "rel": r[2], "provenance": r[3]} for r in erows]
    return {"nodes": _rows_to_nodes(nrows), "edges": edges, "group": group}


def _lexical(c, group: str, q: str, limit: int) -> list[dict]:
    ql = f"%{(q or '').lower()}%"
    rows = c.execute(
        "SELECT id,label,type,props FROM nodes WHERE grp=%s AND "
        "(lower(label) LIKE %s OR lower(type) LIKE %s OR lower(props::text) LIKE %s) LIMIT %s",
        (group, ql, ql, ql, limit)).fetchall()
    return _rows_to_nodes(rows)


@app.get("/search")
def search(group: str = "creativate", q: str = "", limit: int = 10):
    with _conn() as c:
        return {"results": _lexical(c, group, q, limit)}


# Häufige (deutsche/englische) Funktionswörter — zählen nicht als inhaltlicher Bezug.
_STOP = {
    "und", "oder", "der", "die", "das", "den", "dem", "des", "ein", "eine", "einer", "eines",
    "für", "mit", "von", "vom", "auf", "aus", "bei", "zum", "zur", "ist", "sind", "war",
    "hat", "haben", "wird", "werden", "kann", "auch", "nicht", "mein", "meine", "unser",
    "unsere", "dein", "deine", "the", "and", "for", "with", "this", "that", "welche", "welcher",
    "was", "wie", "wer", "wo", "warum", "ergeben", "sich", "einen", "einem",
}


def _content_terms_q(q: str) -> list[str]:
    """Inhaltliche Query-Terme: ≥4 Zeichen, keine Funktionswörter."""
    return [t for t in re.findall(r"[\wäöüÄÖÜß]+", (q or "").lower())
            if len(t) >= 4 and t not in _STOP]


def _lexical_ranked(c, group: str, q: str, limit: int) -> list[dict]:
    """Präzise lexische Treffer NUR über das Label (nicht den ganzen props-Text — sonst
    matchen bei vielen Knoten wie LeiKa generische Wörter aus buergernah/rechtsgrundlagen).
    Score = Anzahl getroffener inhaltlicher Terme im Label."""
    terms = _content_terms_q(q)
    if not terms:
        return []
    likes = [f"%{t}%" for t in terms]
    # Treffer-Anzahl je Label in SQL berechnen und danach ordnen — sonst schneidet das LIMIT
    # bei einem häufigen Term (z.B. „Erteilung") den präzisen Mehrwort-Treffer ab.
    hit_expr = " + ".join(["(CASE WHEN lower(label) LIKE %s THEN 1 ELSE 0 END)"] * len(terms))
    where = " OR ".join(["lower(label) LIKE %s"] * len(terms))
    rows = c.execute(
        f"SELECT id,label,type,props, ({hit_expr}) AS hits FROM nodes "
        f"WHERE grp=%s AND ({where}) ORDER BY hits DESC, length(label) ASC LIMIT %s",
        (*likes, group, *likes, limit)).fetchall()
    return [{"id": r[0], "label": r[1], "type": r[2], "props": r[3] or {}} for r in rows]


@app.get("/retrieve")
def retrieve(group: str = "creativate", q: str = "", limit: int = 8):
    """Lexisch zuerst (präzise Begriffstreffer, label-priorisiert), dann semantisch
    (pgvector) auffüllen → sources + facts + count. So bleiben exakte Term-Treffer
    sichtbar, auch wenn kurze Labels die Vektor-Suche schwach diskriminieren."""
    out: list[dict] = []
    seen: set[str] = set()
    with _conn() as c:
        for n in _lexical_ranked(c, group, q, limit):
            if n["id"] in seen:
                continue
            seen.add(n["id"])
            n["provenance"] = f"graph-core:{group}"
            n["score"] = 1.0
            out.append(n)
        qv = _embed(q) if q and len(out) < limit else None
        if qv is not None:
            rows = c.execute(
                "SELECT id,label,type,props, 1-(embedding <=> %s::vector) AS score "
                "FROM nodes WHERE grp=%s AND embedding IS NOT NULL "
                "ORDER BY embedding <=> %s::vector LIMIT %s",
                (_vec_literal(qv), group, _vec_literal(qv), limit)).fetchall()
            for r in rows:
                if r[0] in seen:
                    continue
                seen.add(r[0])
                out.append({"id": r[0], "label": r[1], "type": r[2], "props": r[3] or {},
                            "provenance": f"graph-core:{group}", "score": round(float(r[4]), 3)})
                if len(out) >= limit:
                    break
    out = out[:limit]
    facts = "\n".join(f"- {s['label']} ({s['type']})" for s in out)
    return {"sources": out, "facts": facts, "count": len(out), "group": group}


@app.post("/ingest")
def ingest(req: IngestReq):
    nid = req.id or _slug(req.label)
    g = req.group or "creativate"
    props = dict(req.props or {})
    if req.content:
        props["content"] = req.content[:8000]
    new_nodes, new_edges = [], []
    with _conn() as c:
        _upsert_node(c, g, nid, req.label, req.type, props, embed=True)
        new_nodes.append({"id": nid, "label": req.label, "type": req.type})
        for lk in req.links:
            tgt = lk.get("target")
            if not tgt:
                continue
            tid = _slug(str(tgt))
            # Zielknoten synchron anlegen, falls fehlend (kein async-Gap).
            c.execute("INSERT INTO nodes (grp,id,label,type) VALUES (%s,%s,%s,%s) "
                      "ON CONFLICT (grp,id) DO NOTHING",
                      (g, tid, str(tgt), lk.get("type", "Entity")))
            c.execute("INSERT INTO edges (grp,source,target,rel,provenance) VALUES (%s,%s,%s,%s,%s) "
                      "ON CONFLICT DO NOTHING",
                      (g, nid, tid, lk.get("rel", "MENTIONS"), lk.get("provenance", "graph-core")))
            new_edges.append({"source": nid, "target": tid, "rel": lk.get("rel", "MENTIONS")})
    return {"ok": True, "group": g, "graph_delta": {"nodes": new_nodes, "edges": new_edges},
            "synchronous": True}


class SeedReq(BaseModel):
    group: str = "creativate"
    nodes: list[dict] = []
    edges: list[dict] = []
    replace: bool = True


@app.post("/seed")
def seed(req: SeedReq):
    """Lädt einen Tenant-eigenen Seed (nodes/edges) in dessen group — je Kunde eigene Daten."""
    with _conn() as c:
        if req.replace:
            c.execute("DELETE FROM edges WHERE grp=%s", (req.group,))
            c.execute("DELETE FROM nodes WHERE grp=%s", (req.group,))
        for n in req.nodes:
            _upsert_node(c, req.group, n["id"], n.get("label", n["id"]),
                         n.get("type", "Entity"), n.get("props", {}), embed=True)
        for e in req.edges:
            c.execute("INSERT INTO edges (grp,source,target,rel,provenance) VALUES (%s,%s,%s,%s,%s) "
                      "ON CONFLICT DO NOTHING",
                      (req.group, e["source"], e["target"], e.get("rel", "REL"), e.get("provenance", "seed")))
    return {"ok": True, "group": req.group, "nodes": len(req.nodes), "edges": len(req.edges)}


@app.post("/reset-seed")
def reset_seed(group: str = SEED_GROUP):
    with _conn() as c:
        c.execute("DELETE FROM edges WHERE grp=%s", (group,))
        c.execute("DELETE FROM nodes WHERE grp=%s", (group,))
    n = load_seed(group)
    return {"ok": True, "group": group, "reloaded_nodes": n}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8010)
