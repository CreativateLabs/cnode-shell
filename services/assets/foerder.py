"""
Förder Self-Check-Match.

Ranked Förderprogramme (seed/foerderprogramme.json) nach Passung zum client_profile
+ query und reichert die Begründung mit passenden Verwaltungsleistungen aus dem
data-foerder-Katalog an (catalog.candidates). Liefert Contract-Form:
  {programs:[{name,fit,max_foerderung,reason,frist}]}

Hintergrund: die foerderprogramm-Tabelle im data-foerder-Datensatz ist derzeit leer,
daher der kuratierte Förder-Seed als Match-Grundlage. Wird ein echter Förder-Import
verfügbar (z.B. foerderdatenbank.de), kann er den Seed 1:1 ersetzen.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Optional

from catalog import get_catalog

_SEED_CANDIDATES = [
    os.getenv("FOERDER_SEED_PATH", ""),
    "/app/seed/foerderprogramme.json",
    str(Path(__file__).resolve().parent / "seed" / "foerderprogramme.json"),
    "/seed/foerderprogramme.json",
    "./seed/foerderprogramme.json",
    "../../seed/foerderprogramme.json",
]

_WORD_RE = re.compile(r"[a-zäöüß0-9]+", re.IGNORECASE)


def _first_existing(paths: list[str]) -> Optional[str]:
    for p in paths:
        if p and Path(p).is_file():
            return str(Path(p).resolve())
    return None


def _tokens(text: str) -> set[str]:
    return {t for t in _WORD_RE.findall((text or "").lower()) if len(t) > 2}


def _profile_to_text(profile: Any) -> str:
    if profile is None:
        return ""
    if isinstance(profile, str):
        return profile
    if isinstance(profile, dict):
        parts = []
        for v in profile.values():
            if isinstance(v, (list, tuple)):
                parts.append(" ".join(str(x) for x in v))
            else:
                parts.append(str(v))
        return " ".join(parts)
    return str(profile)


class FoerderMatcher:
    def __init__(self) -> None:
        self.seed_path = _first_existing(_SEED_CANDIDATES)
        self._programs: list[dict[str, Any]] = []
        if self.seed_path:
            try:
                doc = json.loads(Path(self.seed_path).read_text(encoding="utf-8"))
                self._programs = doc.get("programs", [])
            except Exception:
                self._programs = []

    def match(self, query: str, client_profile: Any, client_id: str, limit: int = 5) -> dict[str, Any]:
        limit = max(1, min(int(limit or 5), 20))
        prof_text = _profile_to_text(client_profile)
        signal = f"{query or ''} {prof_text}".strip()
        sig_tokens = _tokens(signal)

        d = client_profile if isinstance(client_profile, dict) else {}
        want_berechtigt = str(d.get("rechtsform") or d.get("typ") or d.get("segment") or "").lower()

        scored: list[tuple[float, dict[str, Any]]] = []
        for prog in self._programs:
            hay = _tokens(" ".join([
                prog.get("name", ""),
                " ".join(prog.get("bereich", [])),
                " ".join(prog.get("berechtigte", [])),
                prog.get("foerderart", ""),
                prog.get("gebiet", ""),
                prog.get("reason", ""),
            ]))
            overlap = len(sig_tokens & hay)
            base = overlap / (len(sig_tokens) + 1)
            bonus = 0.0
            if want_berechtigt:
                for b in prog.get("berechtigte", []):
                    if want_berechtigt in b.lower() or b.lower() in want_berechtigt:
                        bonus += 0.20
                        break
            fit = min(0.98, round(0.45 + base * 0.45 + bonus, 2))
            scored.append((fit, prog))

        scored.sort(key=lambda x: x[0], reverse=True)

        # passende Verwaltungsleistungen als Beleg beziehen
        catalog = get_catalog()
        cat_hits = catalog.candidates(signal)[:3] if signal else []
        cat_note = ""
        if cat_hits:
            names = ", ".join(h["name"][:60] for h in cat_hits)
            cat_note = f" Passende Verwaltungsleistungen im Förder-Katalog: {names}."

        top_prog = scored[0][1] if scored else None
        out: list[dict[str, Any]] = []
        for fit, prog in scored[:limit]:
            reason = prog.get("reason", "")
            if prog is top_prog and cat_note:
                reason = (reason + cat_note).strip()
            out.append({
                "name": prog.get("name", ""),
                "fit": fit,
                "max_foerderung": prog.get("max_foerderung", "auf Anfrage"),
                "reason": reason,
                "frist": prog.get("frist", "laufend"),
            })
        return {"programs": out, "source": "seed", "catalog_source": catalog.source_label()}


_MATCHER: Optional[FoerderMatcher] = None


def get_matcher() -> FoerderMatcher:
    global _MATCHER
    if _MATCHER is None:
        _MATCHER = FoerderMatcher()
    return _MATCHER
