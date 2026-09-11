#!/usr/bin/env python3
"""data-foerder-Bulk-Loader (G6.3) — LeiKa-Verwaltungsleistungen → geteilte market-Ebene.

Liest die data-foerder-SQLite (`leistung`, 9.945 Zeilen) und seedet je Leistung einen
getypten `LeiKaService`-Knoten (Funding-Ontologie) in die **market**-Group des Graphen.
market ist die geteilte Ebene → ALLE Tenants erben das Wissen über ihr 3-Ebenen-Retrieval
(client + market + mesh), ohne Extra-Config.

Reine Standardbibliothek (sqlite3 + urllib), damit es überall läuft — insbesondere im
`assets`-Container, der die DB gemountet hat UND graph-core im Compose-Netz erreicht.

ENV:
  DATAFOERDER_DB   Pfad zur SQLite (default /data/foerder.sqlite — Mount im assets-Container)
  GRAPH_CORE_URL    default http://graph-core:8010
  MARKET_GROUP    default market
  LIMIT           max. Leistungen (default 500; 0 = alle 9.945)
  BATCH           Knoten je /seed-Request (default 100)
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import urllib.request

DB = os.getenv("DATAFOERDER_DB", "/data/foerder.sqlite")
NEN = os.getenv("GRAPH_CORE_URL", "http://graph-core:8010").rstrip("/")
GROUP = os.getenv("MARKET_GROUP", "market")
LIMIT = int(os.getenv("LIMIT", "500"))
BATCH = int(os.getenv("BATCH", "100"))
PROV = "datafoerder:leika"


def _slug(s: str) -> str:
    out = "".join(c if c.isalnum() else "_" for c in (s or "").lower()).strip("_")
    while "__" in out:
        out = out.replace("__", "_")
    return out[:120]


def _post_seed(nodes: list[dict]) -> bool:
    body = json.dumps({"group": GROUP, "nodes": nodes, "edges": [], "replace": False}).encode()
    req = urllib.request.Request(f"{NEN}/seed", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status < 300
    except Exception as e:  # noqa: BLE001
        print(f"  ! seed-Fehler: {str(e)[:160]}", flush=True)
        return False


def main() -> int:
    if not os.path.isfile(DB):
        print(f"DB nicht gefunden: {DB}", file=sys.stderr)
        return 2
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    # Name = title (nur ~600 gesetzt) → bezeichnung (alle 9.945) → bürgernah.
    NAME = "COALESCE(NULLIF(title,''), NULLIF(bezeichnung,''), NULLIF(bezeichnung_buergernah,''))"
    total = con.execute(f"SELECT COUNT(*) FROM leistung WHERE {NAME} IS NOT NULL").fetchone()[0]
    q = (f"SELECT leistungsschluessel, {NAME} AS name, bezeichnung_buergernah, leistungstyp, "
         f"ozg_themenfeld_label, rechtsgrundlagen FROM leistung WHERE {NAME} IS NOT NULL "
         f"ORDER BY name")
    if LIMIT > 0:
        q += f" LIMIT {LIMIT}"
    rows = con.execute(q).fetchall()
    print(f"data-foerder: {total} Leistungen gesamt · lade {len(rows)} "
          f"(LIMIT={LIMIT or 'alle'}) → Group '{GROUP}' @ {NEN}", flush=True)

    seen: set[str] = set()
    batch: list[dict] = []
    loaded = ok_batches = 0
    for r in rows:
        key = str(r["leistungsschluessel"] or "").strip()
        title = str(r["name"] or "").strip()
        if not title:
            continue
        nid = f"leika_{key or _slug(title)}"
        if nid in seen:
            continue
        seen.add(nid)
        props = {"provenance": PROV, "domain": "funding", "layer": "market",
                 "leika_id": key, "leistungstyp": r["leistungstyp"] or ""}
        if r["ozg_themenfeld_label"]:
            props["themenfeld"] = str(r["ozg_themenfeld_label"])[:120]
        if r["bezeichnung_buergernah"]:
            props["buergernah"] = str(r["bezeichnung_buergernah"])[:200]
        if r["rechtsgrundlagen"]:
            props["rechtsgrundlagen"] = str(r["rechtsgrundlagen"]).replace("\n", "; ")[:300]
        batch.append({"id": nid, "label": title[:160], "type": "LeiKaService", "props": props})
        if len(batch) >= BATCH:
            if _post_seed(batch):
                loaded += len(batch); ok_batches += 1
            print(f"  … {loaded}/{len(rows)} geseedet", flush=True)
            batch = []
    if batch:
        if _post_seed(batch):
            loaded += len(batch); ok_batches += 1

    print(f"FERTIG: {loaded} LeiKaService-Knoten in market geladen "
          f"({ok_batches} Batches). {total - loaded} von {total} noch offen "
          f"(LIMIT anheben für Vollimport: LIMIT=0).", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
