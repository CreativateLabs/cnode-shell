"""
LeadScout-Adapter (ICP-basiert).

Primär: echte LeadScout-API https://api.leadscout.creativate.tech
  - env LEADSCOUT_API_URL (default oben), LEADSCOUT_API_KEY.
  - Ohne Key / nicht erreichbar -> plausible Stub-Leads passend zum ICP aus seed/leads.json.

`icp` darf ein Objekt (branche/region/groesse/keywords/...) ODER ein Freitext sein.
Der Stub matcht die Seed-Leads gegen die ICP-Kriterien und liefert die Top-Treffer in
Contract-Form: {leads:[{name,segment,score,reason,contact}]}.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Optional

import httpx

_LEADSCOUT_URL = os.getenv("LEADSCOUT_API_URL", "https://api.leadscout.creativate.tech").rstrip("/")
_LEADSCOUT_KEY = os.getenv("LEADSCOUT_API_KEY", "").strip()

_SEED_CANDIDATES = [
    os.getenv("LEADS_SEED_PATH", ""),
    "/app/seed/leads.json",
    str(Path(__file__).resolve().parent / "seed" / "leads.json"),
    "/seed/leads.json",
    "./seed/leads.json",
    "../../seed/leads.json",
]

_WORD_RE = re.compile(r"[a-zäöüß0-9]+", re.IGNORECASE)


def _first_existing(paths: list[str]) -> Optional[str]:
    for p in paths:
        if p and Path(p).is_file():
            return str(Path(p).resolve())
    return None


def _tokens(text: str) -> set[str]:
    return {t for t in _WORD_RE.findall((text or "").lower()) if len(t) > 2}


def _icp_to_text(icp: Any) -> str:
    """ICP (dict oder str) in einen durchsuchbaren Text normalisieren."""
    if icp is None:
        return ""
    if isinstance(icp, str):
        return icp
    if isinstance(icp, dict):
        parts: list[str] = []
        for v in icp.values():
            if isinstance(v, (list, tuple)):
                parts.append(" ".join(str(x) for x in v))
            else:
                parts.append(str(v))
        return " ".join(parts)
    return str(icp)


class LeadScout:
    def __init__(self) -> None:
        self.seed_path = _first_existing(_SEED_CANDIDATES)
        self._leads: list[dict[str, Any]] = []
        if self.seed_path:
            try:
                doc = json.loads(Path(self.seed_path).read_text(encoding="utf-8"))
                self._leads = doc.get("leads", [])
            except Exception:
                self._leads = []
        self.live_enabled = bool(_LEADSCOUT_KEY)

    # ---------------------------------------------------------------- live
    async def _try_live(self, icp: Any, client_id: str) -> Optional[list[dict[str, Any]]]:
        if not _LEADSCOUT_KEY:
            return None
        headers = {"Authorization": f"Bearer {_LEADSCOUT_KEY}", "X-API-Key": _LEADSCOUT_KEY}
        payload = {"icp": icp, "client_id": client_id}
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(f"{_LEADSCOUT_URL}/v1/leadscout/find", json=payload, headers=headers)
                if resp.status_code != 200:
                    return None
                data = resp.json()
                leads = data.get("leads") if isinstance(data, dict) else None
                if not isinstance(leads, list):
                    return None
                out = []
                for l in leads:
                    out.append({
                        "name": l.get("name", ""),
                        "segment": l.get("segment") or l.get("branche") or "",
                        "score": float(l.get("score", 0.0) or 0.0),
                        "reason": l.get("reason") or l.get("reasoning") or "",
                        "contact": l.get("contact") or l.get("email") or "",
                    })
                return out or None
        except Exception:
            return None

    # ---------------------------------------------------------------- stub
    def _stub(self, icp: Any, limit: int) -> list[dict[str, Any]]:
        icp_text = _icp_to_text(icp)
        icp_tokens = _tokens(icp_text)

        # explizite Felder aus dict-ICP stärker gewichten
        d = icp if isinstance(icp, dict) else {}
        want_branche = str(d.get("branche") or d.get("industry") or "").lower()
        want_region = str(d.get("region") or d.get("bundesland") or "").lower()
        want_seg = str(d.get("segment") or d.get("groesse") or d.get("size") or "").lower()

        scored: list[tuple[float, dict[str, Any]]] = []
        for lead in self._leads:
            hay_tokens = _tokens(" ".join([
                lead.get("name", ""), lead.get("segment", ""), lead.get("branche", ""),
                lead.get("region", ""), lead.get("groesse", ""), " ".join(lead.get("keywords", [])),
                lead.get("reason", ""),
            ]))
            overlap = len(icp_tokens & hay_tokens)
            base = overlap / (len(icp_tokens) + 1)
            bonus = 0.0
            if want_branche and want_branche in lead.get("branche", "").lower():
                bonus += 0.30
            if want_region and (want_region in lead.get("region", "").lower()):
                bonus += 0.20
            if want_seg and (want_seg in lead.get("segment", "").lower() or want_seg in lead.get("groesse", "").lower()):
                bonus += 0.15
            score = min(0.98, round(0.45 + base * 0.4 + bonus, 2))
            scored.append((score, lead))

        # Wenn ICP leer/kein Signal: alle Leads mit Default-Score zurückgeben
        scored.sort(key=lambda x: x[0], reverse=True)
        out: list[dict[str, Any]] = []
        for score, lead in scored[:limit]:
            out.append({
                "name": lead.get("name", ""),
                "segment": lead.get("segment", ""),
                "score": score,
                "reason": lead.get("reason", ""),
                "contact": lead.get("contact", ""),
            })
        return out

    # -------------------------------------------------------------- public
    async def find(self, icp: Any, client_id: str, limit: int = 5) -> dict[str, Any]:
        limit = max(1, min(int(limit or 5), 25))
        live = await self._try_live(icp, client_id)
        if live is not None:
            return {"leads": live[:limit], "source": "live", "provider": "leadscout-api"}
        return {"leads": self._stub(icp, limit), "source": "stub", "provider": "seed"}


_LEADSCOUT: Optional[LeadScout] = None


def get_leadscout() -> LeadScout:
    global _LEADSCOUT
    if _LEADSCOUT is None:
        _LEADSCOUT = LeadScout()
    return _LEADSCOUT
