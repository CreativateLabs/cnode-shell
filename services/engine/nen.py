"""NEN-AI-Adapter — frontet die echte NEN AI (CIG) unter NEN_AI_URL.

Verifizierte NEN-AI-Endpunkte:
  GET  /api/v1/cig/health
  POST /api/v1/cig/answer            {query, group_id, limit} → {answer, sources:[{fact,source,uuid,...}]}
  GET  /api/v1/cig/graph?group_id=&limit=  → {nodes:[{id,label,type,summary}], edges:[...]}
  GET  /api/v1/cig/stats?group_id=
  GET  /api/v1/cig/suggestions?group_id=&n=
  POST /api/v1/cig/ingest
  GET  /api/v1/tenants

Alle Antworten werden auf die eingefrorenen Contracts (§2.2) normalisiert. Ist NEN
nicht erreichbar, liefern die Funktionen plausible deterministische Fallbacks in
derselben Contract-Form (De-Risking — Demo bleibt stabil, kein Crash/500).
"""
from __future__ import annotations

import math
import os
import re

import httpx

NEN_AI_URL = os.getenv("NEN_AI_URL", "http://host.docker.internal:8001").rstrip("/")

# Graph-Backend-Adapter: welche Runtime der Graph nutzt.
#   graph-core  → souveräne, synchrone Neo4j-Runtime im Repo (Default, air-gapped)
#   nen-cig   → externe NEN AI (CIG), async LLM-Extraktion (optional/advanced)
GRAPH_BACKEND = os.getenv("GRAPH_BACKEND", "nen-cig").lower()
GRAPH_CORE_URL = os.getenv("GRAPH_CORE_URL", "http://graph-core:8010").rstrip("/")

# NEN verarbeitet Ingests über eine asynchrone LLM-Extraktions-Queue. Es gibt kein
# Queue-GET — daher merken wir uns den letzten Snapshot aus den Ingest-Antworten
# ({status, pending, processing, processed, failed}), damit das UI ihn zeigen kann.
LAST_QUEUE: dict = {"pending": 0, "processed": 0, "failed": 0, "processing": None, "ts": None}

# NEN-Typen → §2.2 Node-Typ-Enum (Company|Product|Decision|Document|Person|FundingProgram|Lead|Thought)
TYPE_MAP = {
    "organisation": "Company",
    "organization": "Company",
    "company": "Company",
    "unternehmen": "Company",
    "product": "Product",
    "produkt": "Product",
    "project": "Product",
    "person": "Person",
    "people": "Person",
    "document": "Document",
    "dokument": "Document",
    "decision": "Decision",
    "entscheidung": "Decision",
    "fundingprogram": "FundingProgram",
    "förderprogramm": "FundingProgram",
    "lead": "Lead",
    "marketsegment": "Thought",
    "concept": "Thought",
    "thought": "Thought",
}


def map_node_type(raw: str | None) -> str:
    if not raw:
        return "Thought"
    return TYPE_MAP.get(str(raw).strip().lower(), "Thought")


# ---------------------------------------------------------------- normalisierung

def normalize_source(s: dict) -> dict:
    """NEN-Source → §2.1/§2.2-Source {id,label,type,props,provenance}."""
    if not isinstance(s, dict):
        return {"id": "", "label": str(s), "type": "Fact", "props": {}, "provenance": "nen-ai"}
    sid = s.get("uuid") or s.get("id") or ""
    label = s.get("fact") or s.get("label") or s.get("name") or s.get("summary") or ""
    stype = s.get("type") or "Fact"
    props = {k: v for k, v in s.items()
             if k not in ("uuid", "id", "fact", "label", "name", "type", "source")}
    provenance = s.get("source") or "nen-ai:graph"
    return {"id": sid, "label": label, "type": stype, "props": props, "provenance": provenance}


def normalize_node(n: dict) -> dict:
    """NEN-Node → §2.2 Node {id,label,type,props}."""
    props = {k: v for k, v in n.items() if k not in ("id", "label", "type")}
    props["type_raw"] = n.get("type")
    return {
        "id": n.get("id") or n.get("uuid") or "",
        "label": n.get("label") or n.get("name") or "",
        "type": map_node_type(n.get("type")),
        "props": props,
    }


def normalize_edge(e: dict) -> dict:
    """NEN-Edge → §2.2 Edge {source,target,rel,provenance}."""
    source = e.get("source") or e.get("from") or e.get("start") or e.get("source_id") or ""
    target = e.get("target") or e.get("to") or e.get("end") or e.get("target_id") or ""
    rel = e.get("rel") or e.get("relation") or e.get("type") or e.get("label") or "RELATED_TO"
    provenance = e.get("provenance") or e.get("fact") or e.get("source_fact") or "nen-ai:graph"
    return {"source": source, "target": target, "rel": rel, "provenance": provenance}


# ---------------------------------------------------------------- dedup / merge (E2.2)

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+", re.UNICODE)


def _norm_label(s: str | None) -> str:
    """Kanonischer Label-Schlüssel für lexikalische Entity-Resolution."""
    return _WS_RE.sub(" ", _PUNCT_RE.sub(" ", (s or "").lower())).strip()


# Substantielle Anker-Typen, an die lose Knoten (Dokumente/Quellen/Gedanken) gehängt
# werden, wenn ihr Text die Entität erwähnt. Reihenfolge egal.
_ANCHOR_TYPES = {"Company", "Product", "Person", "FundingProgram", "Decision", "Lead", "Document"}
_MAX_STITCH_PER_NODE = 6
_MIN_ANCHOR_LEN = 4


def _node_text(n: dict) -> str:
    """Durchsuchbarer Text eines Knotens: Label + Summary/Props (normalisiert)."""
    props = n.get("props") or {}
    summary = props.get("summary") or ""
    extra = " ".join(str(v) for k, v in props.items() if k not in ("summary", "provenance", "type_raw"))
    return _norm_label(f"{n.get('label', '')} {summary} {extra}")


def stitch_orphans(nodes: list[dict], edges: list[dict]) -> tuple[list[dict], dict]:
    """Read-time Kanten-Projektion: verbindet lose Knoten (Grad 0) mit den Entitäten,
    die in ihrem Text/Summary erwähnt werden (`MENTIONS`, provenance `engine:stitch`).

    Nicht-mutierend gegenüber NEN — reine Projektion beim Lesen, damit der angezeigte
    Graph zusammenhängt statt in Dutzenden losen Dokument-/Quellknoten zu zerfallen.
    Es werden NUR Kanten ergänzt, bei denen mindestens ein Endpunkt sonst lose wäre;
    der bereits verbundene Kern wird nicht zusätzlich verrauscht.
    """
    ids = {n["id"] for n in nodes}
    deg: dict[str, int] = {i: 0 for i in ids}
    for e in edges:
        s, t = e.get("source"), e.get("target")
        if s in deg:
            deg[s] += 1
        if t in deg:
            deg[t] += 1
    orphan_ids = {i for i in ids if deg[i] == 0}
    orphans_before = len(orphan_ids)
    if not orphan_ids:
        return edges, {"orphans_before": 0, "orphans_after": 0, "edges_added": 0}

    # Anker mit vorkompiliertem Wortgrenzen-Muster (Substring-sicher, DE-Komposita ok).
    anchors = []
    for a in nodes:
        if a.get("type") not in _ANCHOR_TYPES:
            continue
        lbl = _norm_label(a.get("label"))
        if len(lbl) < _MIN_ANCHOR_LEN:
            continue
        pat = re.compile(r"(?<![a-z0-9])" + re.escape(lbl) + r"(?![a-z0-9])")
        anchors.append((a["id"], pat))

    existing = {(e.get("source"), e.get("rel"), e.get("target")) for e in edges}
    added: list[dict] = []
    per_node: dict[str, int] = {}
    for n in nodes:
        nid = n["id"]
        hay = _node_text(n)
        if not hay:
            continue
        for aid, pat in anchors:
            if aid == nid:
                continue
            # Nur stiften, wenn dadurch ein loser Knoten angebunden wird.
            if nid not in orphan_ids and aid not in orphan_ids:
                continue
            if per_node.get(nid, 0) >= _MAX_STITCH_PER_NODE:
                break
            key = (nid, "MENTIONS", aid)
            if key in existing or (aid, "MENTIONS", nid) in existing:
                continue
            if pat.search(hay):
                added.append({"source": nid, "target": aid, "rel": "MENTIONS",
                              "provenance": "engine:stitch", "layer": n.get("layer", "client")})
                existing.add(key)
                per_node[nid] = per_node.get(nid, 0) + 1
                # Endpunkte gelten nun als verbunden.
                deg[nid] = deg.get(nid, 0) + 1
                deg[aid] = deg.get(aid, 0) + 1
                orphan_ids.discard(nid)
                orphan_ids.discard(aid)

    stats = {
        "orphans_before": orphans_before,
        "orphans_after": len(orphan_ids),
        "edges_added": len(added),
    }
    return edges + added, stats


def dedup_graph(nodes: list[dict], edges: list[dict]) -> tuple[list[dict], list[dict], dict]:
    """Lexikalischer Dedup/Merge der Graph-Projektion (SCOPE E2.2, read-time).

    Merge-Schlüssel = (normalisiertes Label, Typ) — verhindert, dass z.B. eine Person
    und ein Produkt mit gleichem Namen verschmelzen. Kanonisch ist das längste Label;
    Aliase, Merge-Count und aggregierte Provenienz (E2.6) landen in props. Kanten werden
    auf die kanonischen IDs umgehängt, dedupliziert und Selbst-Schleifen entfernt.
    Provenienz-Erhalt: jede kanonische Node trägt props.provenance.
    """
    groups: dict[tuple, list[dict]] = {}
    ororder: list[tuple] = []
    for n in nodes:
        key = (_norm_label(n.get("label")), n.get("type") or "")
        if not key[0]:  # leeres Label → nicht mergen (eindeutig über id halten)
            key = (f"__empty__:{n.get('id', '')}", n.get("type") or "")
        if key not in groups:
            groups[key] = []
            ororder.append(key)
        groups[key].append(n)

    id_map: dict[str, str] = {}
    merged_nodes: list[dict] = []
    for key in ororder:
        grp = groups[key]
        canonical = max(grp, key=lambda x: len(str(x.get("label") or "")))
        cid = canonical.get("id")
        props = dict(canonical.get("props") or {})
        if len(grp) > 1:
            aliases = sorted({str(g.get("label")) for g in grp if g.get("label")})
            quellen = sorted(
                {str((g.get("props") or {}).get("quelle")
                     or (g.get("props") or {}).get("provenance") or "").strip()
                 for g in grp} - {""})
            props["merged_count"] = len(grp)
            if len(aliases) > 1:
                props["aliases"] = aliases
            if quellen:
                props["quellen"] = quellen
        props.setdefault("provenance", props.get("quelle") or "nen-ai:graph")
        merged_nodes.append({**canonical, "props": props})
        for g in grp:
            if g.get("id"):
                id_map[g["id"]] = cid

    seen: set[tuple] = set()
    merged_edges: list[dict] = []
    for e in edges:
        s = id_map.get(e.get("source"), e.get("source"))
        t = id_map.get(e.get("target"), e.get("target"))
        if not s or not t or s == t:
            continue  # Selbst-Schleife durch Merge → weglassen
        k = (s, e.get("rel"), t)
        if k in seen:
            continue
        seen.add(k)
        merged_edges.append({**e, "source": s, "target": t})

    stats = {
        "nodes_before": len(nodes), "nodes_after": len(merged_nodes),
        "edges_before": len(edges), "edges_after": len(merged_edges),
        "merged": len(nodes) - len(merged_nodes), "mode": "lexical",
    }
    return merged_nodes, merged_edges, stats


# ---- embedding-basiertes (semantisches) Dedup (E2.2-Upgrade) ---------------
_OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434").rstrip("/")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")


async def embed(texts: list[str]) -> list[list[float]]:
    """Label-Embeddings via lokalem Ollama (nomic-embed-text). Leere Liste bei Fehler."""
    if not texts:
        return []
    try:
        async with httpx.AsyncClient(timeout=45.0) as c:
            r = await c.post(f"{_OLLAMA_URL}/api/embed",
                             json={"model": EMBED_MODEL, "input": texts, "keep_alive": "30m"})
            r.raise_for_status()
            return r.json().get("embeddings", []) or []
    except Exception:
        return []


def _cos(a: list[float], b: list[float]) -> float:
    s = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return s / (na * nb) if na and nb else 0.0


def _merge_clusters(nodes: list[dict], edges: list[dict], clusters: list[list[int]],
                    mode: str) -> tuple[list[dict], list[dict], dict]:
    """Gemeinsamer Merge-Schritt (kanonisch = längstes Label, Kanten umhängen/dedup)."""
    id_map: dict[str, str] = {}
    merged: list[dict] = []
    for idxs in clusters:
        grp = [nodes[i] for i in idxs]
        canonical = max(grp, key=lambda x: len(str(x.get("label") or "")))
        cid = canonical.get("id")
        props = dict(canonical.get("props") or {})
        if len(grp) > 1:
            aliases = sorted({str(g.get("label")) for g in grp if g.get("label")})
            props["merged_count"] = len(grp)
            if len(aliases) > 1:
                props["aliases"] = aliases
            props["merged_by"] = mode
        props.setdefault("provenance", props.get("quelle") or "nen-ai:graph")
        merged.append({**canonical, "props": props})
        for g in grp:
            if g.get("id"):
                id_map[g["id"]] = cid
    seen: set[tuple] = set()
    medges: list[dict] = []
    for e in edges:
        s = id_map.get(e.get("source"), e.get("source"))
        t = id_map.get(e.get("target"), e.get("target"))
        if not s or not t or s == t:
            continue
        k = (s, e.get("rel"), t)
        if k in seen:
            continue
        seen.add(k)
        medges.append({**e, "source": s, "target": t})
    stats = {"nodes_before": len(nodes), "nodes_after": len(merged),
             "edges_before": len(edges), "edges_after": len(medges),
             "merged": len(nodes) - len(merged), "mode": mode}
    return merged, medges, stats


async def dedup_graph_embed(nodes: list[dict], edges: list[dict],
                            threshold: float = 0.93) -> tuple[list[dict], list[dict], dict]:
    """Semantisches Dedup: Label-Embeddings, greedy-Cluster nach Cosine ≥ threshold,
    NUR innerhalb gleichen Typs (kein Person/Produkt-Merge). Fällt bei Embed-Ausfall
    sauber auf lexikalisches Dedup zurück."""
    labels = [str(n.get("label") or "") for n in nodes]
    vecs = await embed(labels)
    if len(vecs) != len(nodes):
        return dedup_graph(nodes, edges)  # Fallback
    clusters: list[list[int]] = []
    reps: list[tuple[list[float], str]] = []  # (vec, type) je Cluster
    for i, n in enumerate(nodes):
        ntype = n.get("type") or ""
        placed = False
        for ci, (rv, rt) in enumerate(reps):
            if rt == ntype and _cos(vecs[i], rv) >= threshold:
                clusters[ci].append(i)
                placed = True
                break
        if not placed:
            clusters.append([i])
            reps.append((vecs[i], ntype))
    return _merge_clusters(nodes, edges, clusters, "embed")


# ---------------------------------------------------------------- zwei-ebenen-retrieval

_WORD_RE = re.compile(r"\w+", re.UNICODE)

# Funktionswörter (de/en) zählen NICHT als inhaltliche Relevanz — sonst matcht schon
# ein generisches „einen"/„overview" ein beliebiges Artefakt in Small-Talk.
STOPWORDS = {
    # de – Artikel/Pronomen/Präpositionen/Hilfsverben/Frage- & Füllwörter
    "der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einer", "eines", "einem",
    "und", "oder", "aber", "mit", "für", "von", "vom", "zu", "im", "in", "an", "auf", "aus", "bei",
    "nach", "über", "unter", "vor", "zum", "zur", "beim", "ins", "durch", "gegen", "ohne", "um",
    "ist", "sind", "war", "waren", "bin", "bist", "sein", "seine", "seiner", "seinem", "hat", "habe",
    "haben", "hatte", "wird", "werden", "kann", "kannst", "können", "könnt", "soll", "sollen", "muss",
    "müssen", "will", "willst", "wollen", "mag", "würde", "wäre",
    "ich", "du", "er", "sie", "es", "wir", "ihr", "mich", "dich", "mir", "dir", "uns", "euch", "man",
    "mein", "meine", "dein", "deine", "unser", "unsere", "euer",
    "wie", "was", "wo", "wann", "warum", "wieso", "welche", "welcher", "welches", "wer", "wen", "wem",
    "nicht", "kein", "keine", "noch", "schon", "auch", "nur", "mehr", "sehr", "doch", "mal", "etwas",
    "etwa", "bitte", "dann", "also", "so", "als", "wenn", "weil", "dass", "damit", "dazu", "dabei",
    "daran", "hier", "dort", "gib", "gibt", "geben", "lass", "lasst", "allgemein", "kurz", "kurze",
    "kurzen", "überblick", "sprechen", "reden", "womit", "wobei", "worin", "gerne", "gern", "einfach",
    # en
    "the", "a", "an", "and", "or", "but", "with", "for", "of", "to", "in", "on", "at", "is", "are",
    "was", "were", "be", "can", "could", "would", "should", "i", "you", "we", "me", "my", "your",
    "us", "how", "what", "where", "when", "why", "which", "who", "give", "let", "overview", "please",
    "about", "tell", "just", "some", "more",
}

# Generische Verwaltungs-/Dokument-Wörter: kommen quer durch die 9.950 LeiKa-Labels vor.
# Sie zählen auf den GETEILTEN Ebenen (market/mesh) NICHT als spezifischer Treffer — sonst
# zieht schon „Unterlagen"/„Antrag" themenfremdes LeiKa-Rauschen in unrelated Kontexte.
_GENERIC_SHARED = {
    "antrag", "anträge", "antragstellung", "unterlagen", "unterlage", "bericht", "berichte",
    "dokument", "dokumente", "formular", "formulare", "verfahren", "leistung", "leistungen",
    "online", "entgegennahme", "veröffentlichung", "bescheid", "genehmigung", "erteilung",
    "nachweis", "erklärung", "anmeldung", "meldung", "zulassung", "gebühr", "gebühren",
    "behörde", "amt", "daten", "information", "informationen", "auskunft", "bescheinigung",
    "rahmen", "sowie", "bzw", "document", "form", "application", "report", "data",
}


def _content_terms(query: str) -> set[str]:
    """Inhaltliche Query-Terme: >2 Zeichen, keine Funktionswörter."""
    return {t for t in _WORD_RE.findall(query.lower()) if len(t) > 2 and t not in STOPWORDS}


def rank_sources(query: str, sources: list[dict],
                 weights: dict[str, float] | None = None) -> list[dict]:
    """Merged Client+Market-Quellen nach lexischer Relevanz sortieren (SCOPE v2).

    Score = Term-Überlappung(Query ↔ Source-Label) + Layer-Boost + gelernter Boost.
    Der Client-Boost sorgt dafür, dass eigene Mandanten-Quellen bei Gleichstand vor
    geteilten Market-Quellen ranken. `weights` (E2.3) hebt Terme, die in belegten
    Antworten wiederholt genutzt wurden — der Graph „lernt", welche Entitäten für den
    Mandanten zählen. `sorted` ist stabil → Ties behalten die NEN-Reihenfolge.
    """
    terms = _content_terms(query)
    w = weights or {}

    def score(s: dict) -> float:
        label = str(s.get("label") or "").lower()
        words = set(_WORD_RE.findall(label))
        overlap = float(len(terms & words))
        layer_boost = 0.5 if s.get("layer") == "client" else 0.0
        # Gelernter Boost: Summe der Term-Gewichte der Source, sanft gedeckelt.
        learned = min(sum(w.get(x, 0.0) for x in words), 3.0) * 0.4
        return overlap + layer_boost + learned

    return sorted(sources, key=score, reverse=True)


def relevant_sources(query: str, sources: list[dict]) -> list[dict]:
    """Nur Quellen mit tatsächlichem lexischem Bezug zur Frage — Basis dafür, dass
    Quellen/Rechenweg NUR gezeigt werden, wenn wirklich Fakten genutzt werden.

    Funktionswörter zählen nicht (STOPWORDS). Bei sehr kurzen, gezielten Fragen
    (≤2 inhaltliche Terme) reicht 1 Treffer; sonst sind mind. 2 inhaltliche
    Überlappungen nötig, damit ein einzelnes generisches Wort keine irrelevanten
    Artefakte in ein eigentlich beratendes Gespräch zieht.
    """
    terms = _content_terms(query)
    if not terms:
        return []
    min_overlap = 1 if len(terms) <= 2 else 2
    out = []
    for s in sources:
        layer = str(s.get("layer") or "client").strip().lower()
        # Heuhaufen: für den eigenen Mandanten-Graph (client) reich — Label + Typ + Prop-Werte
        # (wenige, dichte Knoten). Für die GETEILTEN Ebenen (market/mesh, viele generische
        # Knoten wie LeiKa) NUR Label + Typ — sonst matchen generische Wörter aus langen
        # Props (buergernah/rechtsgrundlagen) und ziehen Rauschen in unspezifische Fragen.
        parts = [str(s.get("label") or ""), str(s.get("type") or ""),
                 str(s.get("fact") or s.get("text") or "")]
        if layer == "client":
            props = s.get("props")
            if isinstance(props, dict):
                parts.extend(f"{k} {v}" for k, v in props.items())
        words = set(_WORD_RE.findall(" ".join(parts).lower()))
        # Getypte Graph-Entities sind semantisch vorgefiltert → 1 Term-Treffer reicht;
        # generische „Fact"-Quellen strenger. Bei market/mesh matcht nur das Label (s.o.),
        # daher trägt eine geteilte Quelle nur bei, wenn die Frage die Entität wirklich
        # benennt — generische Fragen ziehen kein LeiKa-Rauschen mehr.
        stype = str(s.get("type") or "").strip().lower()
        if layer in ("market", "mesh"):
            # Geteilte Ebenen: nur bei ≥2 SPEZIFISCHEN Term-Treffern (generische
            # Verwaltungs-Wörter zählen nicht). Auch getypte Knoten (z.B. LeiKaService)
            # brauchen hier den starken Treffer — sonst zieht 1 generisches Wort LeiKa.
            specific = (terms - _GENERIC_SHARED) & words
            if len(specific) >= 2:
                out.append(s)
            continue
        need = 1 if stype and stype != "fact" else min_overlap
        if len(terms & words) >= need:
            out.append(s)
    return out


def compose_two_level_answer(text_c: str, src_c: list[dict],
                             text_m: str, src_m: list[dict]) -> str:
    """Kombiniert die belegten NEN-Antworten beider Ebenen zu einem Antworttext.

    Market-Text wird NUR angehängt, wenn die Market-Ebene tatsächlich Quellen
    lieferte (sonst gibt NEN einen "keine Infos"-Platzhalter zurück, der nicht in
    die Antwort gehört). Ist die Market-Ebene leer → reine Client-Antwort.
    """
    has_c, has_m = bool(src_c), bool(src_m)
    market_block = f"**Marktintelligenz (geteilt):** {text_m}"
    if has_c and has_m:
        return f"{text_c}\n\n---\n\n{market_block}"
    if has_c:
        return text_c
    if has_m:
        return market_block
    # Keine der beiden Ebenen hat belegte Quellen → NENs Platzhalter durchreichen.
    return text_c or text_m


# ---------------------------------------------------------------- graph-core backend

async def _core_health() -> dict:
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"{GRAPH_CORE_URL}/health")
            r.raise_for_status()
            return {"reachable": True, "backend": "graph-core", **r.json()}
    except Exception as e:
        return {"reachable": False, "backend": "graph-core", "error": str(e)}


async def _core_retrieve(query: str, group_id: str, limit: int) -> tuple[list[dict], bool]:
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.get(f"{GRAPH_CORE_URL}/retrieve",
                            params={"group": group_id, "q": query, "limit": limit})
            r.raise_for_status()
            # graph-core liefert Sources BEREITS in §2.1-Form {id,label,type,props,provenance}.
            # NICHT durch normalize_source schicken — das ist für die rohe nen-cig-Form und
            # würde die echten props (inkl. summary) unter props["props"] verschachteln →
            # facts_from_sources fände keine summary → dünne, ausweichende Antworten.
            out = [{"id": s.get("id", ""), "label": s.get("label", ""),
                    "type": s.get("type", "Fact"), "props": s.get("props") or {},
                    "provenance": s.get("provenance") or f"graph-core:{group_id}"}
                   for s in (r.json().get("sources") or [])]
            return out, True
    except Exception:
        return [], False


async def _core_graph(group_id: str, limit: int) -> tuple[dict, bool]:
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.get(f"{GRAPH_CORE_URL}/graph", params={"group": group_id, "limit": limit})
            r.raise_for_status()
            data = r.json()
        return {"nodes": [normalize_node(n) for n in (data.get("nodes") or [])],
                "edges": [normalize_edge(e) for e in (data.get("edges") or [])]}, True
    except Exception:
        return {"nodes": [], "edges": []}, False


async def _core_ingest(payload: dict, group_id: str) -> tuple[dict, bool]:
    """Synchroner Ingest in die graph-core-Runtime (schreibt Knoten+Kanten sofort)."""
    body = {
        "label": payload.get("label", ""), "type": payload.get("type", "Document"),
        "props": payload.get("props") or {}, "content": payload.get("content") or "",
        "links": payload.get("links") or [], "group": group_id,
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post(f"{GRAPH_CORE_URL}/ingest", json=body)
            r.raise_for_status()
            return r.json(), True
    except Exception:
        return {}, False


async def seed(group_id: str, nodes: list[dict], edges: list[dict], replace: bool = False) -> tuple[dict, bool]:
    """Batch-Write getypter Knoten+Kanten in die graph-core-Runtime (synchron, append/replace)."""
    if GRAPH_BACKEND != "graph-core":
        return {"ok": False, "reason": "seed nur mit graph-core-Backend"}, False
    try:
        async with httpx.AsyncClient(timeout=60.0) as c:
            r = await c.post(f"{GRAPH_CORE_URL}/seed",
                             json={"group": group_id, "nodes": nodes, "edges": edges, "replace": replace})
            r.raise_for_status()
            return r.json(), True
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:200]}, False


# ---------------------------------------------------------------- calls

async def health() -> dict:
    """Graph-Backend-Health (Adapter). Gibt {reachable, ...} zurück (nie Exception)."""
    if GRAPH_BACKEND == "graph-core":
        return await _core_health()
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"{NEN_AI_URL}/api/v1/cig/health")
            r.raise_for_status()
            data = r.json()
        return {"reachable": True, **data}
    except Exception as e:
        return {"reachable": False, "error": str(e)}


async def answer(query: str, group_id: str, limit: int = 8) -> tuple[str, list[dict], bool]:
    """POST /api/v1/cig/answer. Returns (answer_text, normalized_sources, reachable)."""
    if GRAPH_BACKEND == "graph-core":
        return "", [], False  # graph-core hat kein LLM → Engine synthetisiert selbst aus retrieve
    try:
        async with httpx.AsyncClient(timeout=120.0) as c:
            r = await c.post(f"{NEN_AI_URL}/api/v1/cig/answer",
                             json={"query": query, "group_id": group_id, "limit": limit})
            r.raise_for_status()
            data = r.json()
        text = data.get("answer") or ""
        sources = [normalize_source(s) for s in (data.get("sources") or [])]
        return text, sources, True
    except Exception:
        return "", [], False


async def retrieve(query: str, group_id: str, limit: int = 8) -> tuple[list[dict], bool]:
    """RETRIEVAL-ONLY (kein LLM → schnell). Returns (normalized_sources, reachable)."""
    if GRAPH_BACKEND == "graph-core":
        return await _core_retrieve(query, group_id, limit)
    try:
        async with httpx.AsyncClient(timeout=20.0) as c:
            r = await c.post(f"{NEN_AI_URL}/api/v1/cig/query",
                             json={"query": query, "group_id": group_id, "limit": limit})
            r.raise_for_status()
            data = r.json()
        results = data.get("results") or data.get("sources") or []
        return [normalize_source(s) for s in results], True
    except Exception:
        return [], False


async def graph(group_id: str, limit: int = 80) -> tuple[dict, bool]:
    """Returns ({nodes,edges} normalisiert, reachable) — via aktivem Graph-Backend."""
    if GRAPH_BACKEND == "graph-core":
        return await _core_graph(group_id, limit)
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.get(f"{NEN_AI_URL}/api/v1/cig/graph",
                            params={"group_id": group_id, "limit": limit})
            r.raise_for_status()
            data = r.json()
        nodes = [normalize_node(n) for n in (data.get("nodes") or [])]
        edges = [normalize_edge(e) for e in (data.get("edges") or data.get("links") or [])]
        return {"nodes": nodes, "edges": edges}, True
    except Exception:
        return {"nodes": [], "edges": []}, False


async def ingest(payload: dict, group_id: str) -> tuple[dict, bool]:
    """POST /api/v1/cig/ingest. Returns (raw_response, reachable).

    Mappt das Shell-Ingest-Contract {label,type,props,links} auf NENs
    IngestRequest {name, content, source, group_id}. `content` wird als natürlicher
    Text aufbereitet, damit die NEN-Extraction Entitäten/Kanten ableiten kann.
    """
    if GRAPH_BACKEND == "graph-core":
        return await _core_ingest(payload, group_id)
    label = payload.get("label", "")
    ntype = payload.get("type", "Document")
    props = payload.get("props") or {}
    links = payload.get("links") or []
    doc_text = (payload.get("content") or "").strip()

    # Meta-Sätze aus Label/Props/Links — geben NEN den Kontext, wer die Quelle ist.
    # Der eigentliche Dokumenttext (falls vorhanden) steht VORAN, damit der NEN-Extraktor
    # daraus Entitäten + Kanten zieht und die Quelle mit ihnen verbindet (kein Stub).
    lines = [f"{label} ist vom Typ {ntype}."]
    for k, v in props.items():
        if k in ("excerpt",) and doc_text:
            continue  # Volltext ersetzt den Excerpt — nicht doppelt einspeisen.
        lines.append(f"{label}: {k} = {v}.")
    for link in links:
        if isinstance(link, dict):
            tgt = link.get("target") or link.get("id") or ""
            rel = link.get("rel", "steht in Beziehung zu")
            if tgt:
                lines.append(f"{label} {rel} {tgt}.")
        elif isinstance(link, str):
            lines.append(f"{label} steht in Beziehung zu {link}.")
    meta = "\n".join(lines)
    content = f"Quelle „{label}\":\n{doc_text}\n\n{meta}" if doc_text else meta

    # Provenienz NEN-seitig als `source` mitgeben (statt pauschal „engine-shell"),
    # damit belegte Antworten die echte Quelle nennen (Gmail/Drive/Artefakt/Chat …).
    source = str(props.get("quelle") or props.get("provenance") or "engine-shell")
    body = {"name": label, "content": content, "source": source, "group_id": group_id}
    try:
        async with httpx.AsyncClient(timeout=120.0) as c:
            r = await c.post(f"{NEN_AI_URL}/api/v1/cig/ingest", json=body)
            r.raise_for_status()
            data = r.json()
        # Queue-Snapshot merken (für /queue-Sichtbarkeit im UI).
        if isinstance(data, dict) and any(k in data for k in ("pending", "processed", "failed")):
            import time as _t
            LAST_QUEUE.update({
                "pending": data.get("pending", LAST_QUEUE.get("pending", 0)),
                "processed": data.get("processed", LAST_QUEUE.get("processed", 0)),
                "failed": data.get("failed", LAST_QUEUE.get("failed", 0)),
                "processing": data.get("processing"),
                "ts": _t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime()),
            })
        return data, True
    except Exception:
        return {}, False


async def artifact_stream(kind: str, instruction: str, group_id: str,
                          limit: int = 8) -> tuple[str, dict, bool]:
    """POST /api/v1/cig/artifact/stream (SSE) — sammelt Tokens.

    Returns (markdown, meta, reachable). Robust gegen `data: `-Präfix und rohe JSON-Zeilen.
    """
    import json as _json

    body = {"kind": kind, "instruction": instruction, "group_id": group_id, "limit": limit}
    text_parts: list[str] = []
    meta: dict = {}
    try:
        async with httpx.AsyncClient(timeout=180.0) as c:
            async with c.stream("POST", f"{NEN_AI_URL}/api/v1/cig/artifact/stream", json=body) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line:
                        continue
                    payload = line[5:].strip() if line.startswith("data:") else line.strip()
                    if not payload or payload == "[DONE]":
                        continue
                    try:
                        evt = _json.loads(payload)
                    except Exception:
                        continue
                    if evt.get("type") == "token":
                        text_parts.append(evt.get("text", ""))
                    elif evt.get("type") == "meta":
                        meta = evt
        return "".join(text_parts), meta, True
    except Exception:
        return "".join(text_parts), meta, False


async def list_tenants() -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(f"{NEN_AI_URL}/api/v1/tenants")
            r.raise_for_status()
            return r.json().get("tenants", [])
    except Exception:
        return []


# ---------------------------------------------------------------- fallbacks (De-Risking)

def fallback_answer(query: str, group_id: str) -> tuple[str, list[dict]]:
    """Deterministische, plausible Antwort wenn NEN-AI offline ist."""
    text = (
        f"**Hinweis:** Der NEN-Gedächtnis ist derzeit nicht erreichbar — dies ist eine "
        f"deterministische Fallback-Antwort (Demo bleibt stabil).\n\n"
        f"Zur Anfrage *\"{query}\"* im Mandanten-Kontext `{group_id}` liegen offline keine "
        f"belegten Fakten vor. Sobald die NEN AI (Port 8001) verfügbar ist, wird diese Antwort "
        f"mit Quellen aus dem Gedächtnis beantwortet."
    )
    sources = [{
        "id": "fallback", "label": "NEN-AI offline — kein Quellnachweis verfügbar",
        "type": "Note", "props": {"group_id": group_id}, "provenance": "engine:fallback",
    }]
    return text, sources


def fallback_graph(group_id: str) -> dict:
    """Deterministischer Mini-Graph als Fallback."""
    nodes = [
        {"id": f"{group_id}-org", "label": group_id.capitalize(), "type": "Company",
         "props": {"note": "Fallback-Knoten (NEN-AI offline)"}},
        {"id": f"{group_id}-decision", "label": "Offene Entscheidung", "type": "Decision",
         "props": {"note": "Fallback-Knoten"}},
        {"id": f"{group_id}-doc", "label": "Gedächtnis", "type": "Document",
         "props": {"note": "Fallback-Knoten"}},
    ]
    edges = [
        {"source": f"{group_id}-org", "target": f"{group_id}-decision",
         "rel": "TRIFFT", "provenance": "engine:fallback"},
        {"source": f"{group_id}-decision", "target": f"{group_id}-doc",
         "rel": "GESTÜTZT_AUF", "provenance": "engine:fallback"},
    ]
    return {"nodes": nodes, "edges": edges}
