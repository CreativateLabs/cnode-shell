"""
Förder-Katalog der Verwaltungsleistungen.

Datenquelle (in dieser Reihenfolge):
  1. Echter data-foerder-Datensatz (SQLite `leistung`-Tabelle, ~10k/14k LeiKa-Leistungen).
     Pfad via env FOERDER_DB_PATH oder Auto-Discovery gängiger lokaler Orte.
     >> DAS ist der "echte 14k-Datensatz". Zum Einhängen einfach FOERDER_DB_PATH
        auf die foerder.sqlite zeigen lassen (oder die DB nach /data/foerder.sqlite mounten).
  2. Repräsentativer Seed-Katalog seed/verwaltungsleistungen.json (~200 Leistungen,
     aus dem echten Datensatz gezogen) als Stub-Fallback, damit die Demo auch ohne
     gemountete DB stabil läuft (De-Risking, SCOPE §4).

Die DB wird NICHT in den RAM geladen — Suche läuft direkt als LIKE-Query gegen SQLite
(read-only), effizient auch bei 14k Zeilen. Der Seed-Fallback wird einmalig indexiert.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Pfad-Auflösung
# ---------------------------------------------------------------------------
_DB_CANDIDATES = [
    os.getenv("FOERDER_DB_PATH", ""),
    "/data/foerder.sqlite",                 # empfohlener Docker-Mount
    "/app/data/foerder.sqlite",
    str(Path.home() / "Projects/git/data-foerder/db/foerder.sqlite"),
    str(Path.home() / "Projects/git/foerder/db/foerder.sqlite"),
    "./data-foerder/db/foerder.sqlite",
    "../data-foerder/db/foerder.sqlite",
    "../../data-foerder/db/foerder.sqlite",
    "../../../data-foerder/db/foerder.sqlite",
]

_SEED_CANDIDATES = [
    os.getenv("FOERDER_SEED_PATH", ""),
    "/app/seed/verwaltungsleistungen.json",
    str(Path(__file__).resolve().parent / "seed" / "verwaltungsleistungen.json"),
    "/seed/verwaltungsleistungen.json",
    "./seed/verwaltungsleistungen.json",
    "../../seed/verwaltungsleistungen.json",
]


def _first_existing(paths: list[str]) -> Optional[str]:
    for p in paths:
        if p and Path(p).is_file():
            return str(Path(p).resolve())
    return None


_WORD_RE = re.compile(r"[a-zäöüß0-9]+", re.IGNORECASE)


def _tokens(text: str) -> list[str]:
    return [t for t in _WORD_RE.findall((text or "").lower()) if len(t) > 2]


class Catalog:
    """Verwaltungsleistungs-Katalog mit DB- oder Seed-Backend."""

    def __init__(self) -> None:
        self.db_path: Optional[str] = _first_existing(_DB_CANDIDATES)
        self.seed_path: Optional[str] = _first_existing(_SEED_CANDIDATES)
        self.mode: str = "db" if self.db_path else "seed"
        self._seed_rows: list[dict[str, Any]] = []
        self._count: int = 0

        if self.mode == "db":
            try:
                self._count = self._db_count()
                if self._count == 0:  # leere/kaputte DB -> Seed
                    raise RuntimeError("leere leistung-Tabelle")
            except Exception:
                self.mode = "seed"

        if self.mode == "seed":
            self._load_seed()

    # ------------------------------------------------------------------ DB
    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, check_same_thread=False)
        con.row_factory = sqlite3.Row
        return con

    def _db_count(self) -> int:
        con = self._connect()
        try:
            return int(con.execute("SELECT COUNT(*) FROM leistung").fetchone()[0])
        finally:
            con.close()

    @staticmethod
    def _map_db_row(r: sqlite3.Row) -> dict[str, Any]:
        name = r["bezeichnung"] or r["bezeichnung_buergernah"] or r["title"] or "(ohne Titel)"
        kurz = r["teaser"] or r["bezeichnung_buergernah"] or name
        return {
            "leika": r["leistungsschluessel"],
            "name": name,
            "buergernah": r["bezeichnung_buergernah"] or name,
            "kategorie": r["ozg_themenfeld_label"] or "Querschnittsleistungen",
            "ebene": "Bund/Land/Kommune",
            "kurzbeschreibung": (kurz[:300] if kurz else name),
            "zielgruppe": "Bürger/Unternehmen",
            "leistungstyp": r["leistungstyp"] or "",
        }

    def _db_search(self, q: str, limit: int) -> list[dict[str, Any]]:
        con = self._connect()
        try:
            like = f"%{q.strip()}%"
            sql = """
                SELECT leistungsschluessel, title, bezeichnung, bezeichnung_buergernah,
                       ozg_themenfeld_label, leistungstyp, teaser
                FROM leistung
                WHERE bezeichnung IS NOT NULL AND bezeichnung != ''
                  AND ( bezeichnung LIKE ? OR bezeichnung_buergernah LIKE ?
                        OR ozg_themenfeld_label LIKE ? OR teaser LIKE ?
                        OR leistungsschluessel LIKE ? )
                ORDER BY
                  CASE WHEN bezeichnung LIKE ? THEN 0
                       WHEN bezeichnung_buergernah LIKE ? THEN 1 ELSE 2 END,
                  length(bezeichnung)
                LIMIT ?
            """
            rows = con.execute(sql, (like, like, like, like, like, like, like, int(limit))).fetchall()
            return [self._map_db_row(r) for r in rows]
        finally:
            con.close()

    def _db_all_for_match(self, hint: str, cap: int = 400) -> list[dict[str, Any]]:
        """Kandidaten-Menge für den Self-Check-Match (grober LIKE-Vorfilter)."""
        con = self._connect()
        try:
            toks = _tokens(hint)[:6]
            if toks:
                clauses = " OR ".join(
                    ["bezeichnung LIKE ? OR bezeichnung_buergernah LIKE ? OR ozg_themenfeld_label LIKE ?"] * len(toks)
                )
                params: list[Any] = []
                for t in toks:
                    params += [f"%{t}%", f"%{t}%", f"%{t}%"]
                sql = f"""SELECT leistungsschluessel, title, bezeichnung, bezeichnung_buergernah,
                                 ozg_themenfeld_label, leistungstyp, teaser
                          FROM leistung
                          WHERE bezeichnung IS NOT NULL AND bezeichnung != '' AND ({clauses})
                          LIMIT ?"""
                rows = con.execute(sql, (*params, cap)).fetchall()
            else:
                rows = con.execute(
                    """SELECT leistungsschluessel, title, bezeichnung, bezeichnung_buergernah,
                              ozg_themenfeld_label, leistungstyp, teaser
                       FROM leistung WHERE bezeichnung IS NOT NULL AND bezeichnung != '' LIMIT ?""",
                    (cap,),
                ).fetchall()
            return [self._map_db_row(r) for r in rows]
        finally:
            con.close()

    # ---------------------------------------------------------------- Seed
    def _load_seed(self) -> None:
        rows: list[dict[str, Any]] = []
        if self.seed_path:
            try:
                doc = json.loads(Path(self.seed_path).read_text(encoding="utf-8"))
                rows = doc.get("leistungen", [])
            except Exception:
                rows = []
        self._seed_rows = rows
        self._count = len(rows)

    def _seed_search(self, q: str, limit: int) -> list[dict[str, Any]]:
        ql = q.strip().lower()
        if not ql:
            return self._seed_rows[:limit]
        scored = []
        for row in self._seed_rows:
            hay = " ".join(str(row.get(k, "")) for k in ("name", "buergernah", "kategorie", "kurzbeschreibung", "leika"))
            if ql in hay.lower():
                scored.append(row)
        return scored[:limit]

    # -------------------------------------------------------------- Public
    def count(self) -> int:
        return self._count

    def source_label(self) -> str:
        if self.mode == "db":
            return f"data-foerder SQLite ({self.db_path})"
        return f"Seed ({self.seed_path or 'n/a'})"

    def search(self, q: str, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit or 20), 100))
        try:
            if self.mode == "db":
                return self._db_search(q, limit)
        except Exception:
            pass
        return self._seed_search(q, limit)

    def candidates(self, hint: str) -> list[dict[str, Any]]:
        try:
            if self.mode == "db":
                cands = self._db_all_for_match(hint)
                if cands:
                    return cands
        except Exception:
            pass
        return self._seed_rows


_CATALOG: Optional[Catalog] = None


def get_catalog() -> Catalog:
    global _CATALOG
    if _CATALOG is None:
        _CATALOG = Catalog()
    return _CATALOG
