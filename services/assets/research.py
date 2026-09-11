"""Web-Recherche mit Quellenangabe (SerpAPI) — E6.5.

Pipeline: SerpAPI-Suche → wissenschaftliche/offizielle Treffer priorisieren →
Top-Treffer scrapen (Haupttext) → strukturierte Treffer + Referenzen zurückgeben.
Die belegte Synthese macht die Engine (LLM) auf Basis der Extrakte; optional werden
die Quellen in den Graphen aufgenommen.

De-Risking: ohne SERPAPI_KEY oder bei Fehlern → sauberes {ok:False, reason}.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any
from urllib.parse import urlparse

import httpx

from scrape import _ssrf_check, extract_main_text, _ingest, _TIMEOUT, _USER_AGENT  # reuse

SERPAPI_KEY = os.getenv("SERPAPI_KEY", "").strip()
SERPAPI_URL = "https://serpapi.com/search.json"

# Domains, die als wissenschaftlich/offiziell (high-stake) gelten → werden priorisiert.
_SCI_HINTS = (
    ".gov", ".edu", ".ac.", "uni-", "europa.eu", "ec.europa.eu", "eur-lex", "doi.org",
    "scholar.google", "arxiv.org", "ncbi.nlm.nih.gov", "pubmed", "nature.com", "springer",
    "sciencedirect", "researchgate", "ieee.org", "acm.org", "jstor", "wiley",
    "tandfonline", "mdpi.com", "ssrn", "oecd.org", "worldbank.org", "destatis.de",
    "bmwk.de", "bmbf.de", "bundesregierung.de", "gesetze-im-internet.de", "iso.org",
    "who.int", "fraunhofer", "mpg.de", "semanticscholar", "academia.edu",
)


def configured() -> bool:
    return bool(SERPAPI_KEY)


def _domain(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _sci_score(url: str) -> int:
    d = _domain(url)
    if any(h in d for h in _SCI_HINTS):
        return 2
    if "wikipedia.org" in d:
        return 1
    return 0


class SerpError(Exception):
    """Trägt einen differenzierten Grund für die saubere Fehlerausgabe nach oben."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail[:200]


# HTTP-Stati, die als vorübergehend gelten → Retry lohnt sich.
_RETRY_STATUS = {429, 500, 502, 503, 504}
_ATTEMPTS = 3


def _parse_organic(data: dict) -> list[dict[str, Any]]:
    out = []
    for it in data.get("organic_results", []) or []:
        link = it.get("link") or ""
        if not link:
            continue
        out.append({
            "title": it.get("title") or link,
            "url": link,
            "snippet": it.get("snippet") or "",
            "domain": _domain(link),
            "scientific": _sci_score(link) >= 2,
            "score": _sci_score(link),
        })
    return out


async def _serpapi(query: str, n: int) -> list[dict[str, Any]]:
    """SerpAPI-Suche mit Retry + Backoff bei transienten Fehlern.

    Wirft SerpError mit differenziertem Grund (serpapi_auth / serpapi_rate_limit /
    serpapi_unavailable / serpapi_error), damit die intermittierenden Ausfälle nicht
    mehr pauschal als `serpapi_error` die ganze Recherche kippen.
    """
    params = {
        "engine": "google",
        "q": query,
        "api_key": SERPAPI_KEY,
        "num": max(5, min(n * 2, 20)),
        "hl": "de",
    }
    last: SerpError | None = None
    for attempt in range(_ATTEMPTS):
        try:
            async with httpx.AsyncClient(timeout=20.0) as c:
                r = await c.get(SERPAPI_URL, params=params)
        except (httpx.TimeoutException, httpx.TransportError) as e:
            last = SerpError("serpapi_unavailable", f"Netzwerk: {e}")
        else:
            sc = r.status_code
            if sc in (401, 403):
                raise SerpError("serpapi_auth", "SERPAPI_KEY ungültig oder Kontingent erschöpft.")
            if sc == 429:
                last = SerpError("serpapi_rate_limit", "SerpAPI-Ratenlimit erreicht.")
            elif sc in _RETRY_STATUS:
                last = SerpError("serpapi_unavailable", f"HTTP {sc}")
            elif sc != 200:
                raise SerpError("serpapi_error", f"HTTP {sc}")
            else:
                try:
                    data = r.json()
                except Exception:
                    last = SerpError("serpapi_error", "ungültige JSON-Antwort")
                else:
                    # SerpAPI meldet Fehler teils als HTTP 200 + "error"-Feld.
                    if data.get("error"):
                        raise SerpError("serpapi_error", str(data["error"]))
                    return _parse_organic(data)
        # Transienter Fehler → kurzer Backoff, dann erneut.
        if attempt < _ATTEMPTS - 1:
            await asyncio.sleep(0.6 * (attempt + 1))
    raise last or SerpError("serpapi_error", "unbekannter Fehler")


async def _fetch_text(url: str) -> str:
    """Öffentliche URL holen (SSRF-geprüft) + Haupttext extrahieren. Leer bei Fehler."""
    if _ssrf_check(url):  # blockt localhost/private IPs/ungültige Schemes
        return ""
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, follow_redirects=True,
            headers={"User-Agent": _USER_AGENT, "Accept": "text/html,*/*;q=0.8"},
        ) as c:
            r = await c.get(url)
            if r.status_code != 200 or "html" not in r.headers.get("content-type", "").lower():
                return ""
            _title, text = extract_main_text(r.text)
            return text
    except Exception:
        return ""


async def research(query: str, client_id: str = "default", max_results: int = 5,
                   ingest: bool = False) -> dict[str, Any]:
    """Web-Recherche: Suche → priorisieren → Top-Treffer scrapen → Extrakte + Referenzen."""
    query = (query or "").strip()
    if not query:
        return {"ok": False, "reason": "empty_query"}
    if not configured():
        return {"ok": False, "reason": "no_provider",
                "detail": "SERPAPI_KEY nicht gesetzt — Web-Recherche nicht verfügbar."}
    try:
        hits = await _serpapi(query, max_results)
    except SerpError as e:
        return {"ok": False, "reason": e.reason, "detail": e.detail}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": "serpapi_error", "detail": str(e)[:200]}
    if not hits:
        return {"ok": False, "reason": "no_results", "query": query}

    # wissenschaftlich/offiziell zuerst, dann nach Original-Reihenfolge (stabil).
    hits.sort(key=lambda h: h["score"], reverse=True)
    top = hits[: max(1, min(max_results, 6))]

    results: list[dict[str, Any]] = []
    for h in top:
        text = await _fetch_text(h["url"])
        excerpt = (text or h["snippet"])[:1400]
        rec = {**h, "chars": len(text), "extract": excerpt}
        results.append(rec)
        if ingest and text:
            try:
                await _ingest(h["title"], text[:4000], h["url"], client_id, ["client"])
            except Exception:
                pass

    references = [
        {"n": i + 1, "title": r["title"], "url": r["url"], "domain": r["domain"],
         "scientific": r["scientific"]}
        for i, r in enumerate(results)
    ]
    return {"ok": True, "query": query, "results": results, "references": references,
            "count": len(results)}
