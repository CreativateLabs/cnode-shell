"""
Data / Assets-Service (WS-DATA) — SCOPE §2.5.

FastAPI, Python 3.11, Port 8030. Stub-first, kein Crash wenn externe Quellen fehlen.
Routen:
  GET  /health
  POST /leadscout/find     {icp, client_id}                     -> {leads:[...]}
  POST /foerder/match       {query, client_profile, client_id}   -> {programs:[...]}
  GET  /foerder/catalog?q=&limit=                                 -> {results:[...]}
  POST /library/upload     (multipart file)                      -> {ingested, graph_delta}
  POST /scrape             {url, client_id, levels}              -> {ok, ingested, graph_delta, chars}
  GET  /scrape/allowlist                                         -> {domains:[...]}
  PUT  /scrape/allowlist   {domains:[...]}                       -> {domains:[...]}
"""
from __future__ import annotations

from typing import Any, List, Optional

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from catalog import get_catalog
from foerder import get_matcher
from leadscout import get_leadscout
from startupscout import get_startupscout
from library import (
    delete_file,
    ingest_file,
    list_files,
    status as library_status,
)
from scrape import get_allowlist, scrape, status as scrape_status
from research import research as run_research, configured as research_configured

app = FastAPI(title="c:node Data / Assets-Service", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- models
class LeadScoutRequest(BaseModel):
    icp: Any = None            # dict ODER Freitext (Branche/Region/Größe/...)
    client_id: str = "default"
    limit: int = 5


class StartupScoutRequest(BaseModel):
    icp: Any = None            # dict ODER Freitext (Branche/Signale/Region/...)
    client_id: str = "default"
    limit: int = 6
    enrich: bool = False       # Impressum-Kontakt (E-Mail/Tel) für Top-Treffer nachziehen


class FörderMatchRequest(BaseModel):
    query: str = ""
    client_profile: Any = None  # dict ODER Freitext
    client_id: str = "default"
    limit: int = 5


class ScrapeRequest(BaseModel):
    url: str
    client_id: str = "default"
    levels: Any = None          # ["client"] | ["client","market"] (Contract v2)
    depth: int = 0              # MVP: 0 (kein Crawl über die eine Seite hinaus)


class AllowlistRequest(BaseModel):
    domains: List[str] = []


class ResearchRequest(BaseModel):
    query: str
    client_id: str = "default"
    max_results: int = 5
    ingest: bool = False


# --------------------------------------------------------------------------- health
@app.get("/health")
def health() -> dict[str, Any]:
    catalog = get_catalog()
    leadscout = get_leadscout()
    matcher = get_matcher()
    return {
        "status": "ok",
        "service": "assets",
        "port": 8030,
        "counts": {
            "leads": len(leadscout._leads),
            "foerderprogramme": len(matcher._programs),
            "katalog_leistungen": catalog.count(),
        },
        "sources": {
            "katalog": catalog.source_label(),
            "katalog_mode": catalog.mode,
            "leadscout_live": leadscout.live_enabled,
        },
        "scrape": scrape_status(),
        "library": library_status(),
    }


# --------------------------------------------------------------------------- leadscout
@app.post("/leadscout/find")
async def leadscout_find(req: LeadScoutRequest) -> dict[str, Any]:
    return await get_leadscout().find(req.icp, req.client_id, req.limit)


@app.post("/startupscout/find")
async def startupscout_find(req: StartupScoutRequest) -> dict[str, Any]:
    """Früh-Phase-Startups finden (GitHub-Live + Stub-Fallback) → {targets:[...]}."""
    return await get_startupscout().find(req.icp, req.client_id, req.limit, enrich=req.enrich)


# --------------------------------------------------------------------------- foerder match
@app.post("/foerder/match")
def foerder_match(req: FörderMatchRequest) -> dict[str, Any]:
    return get_matcher().match(req.query, req.client_profile, req.client_id, req.limit)


# --------------------------------------------------------------------------- foerder catalog
@app.get("/foerder/catalog")
def foerder_catalog(q: str = "", limit: int = 20) -> dict[str, Any]:
    catalog = get_catalog()
    results = catalog.search(q, limit)
    return {
        "query": q,
        "count": len(results),
        "total_available": catalog.count(),
        "source": catalog.source_label(),
        "results": results,
    }


# --------------------------------------------------------------------------- library upload
@app.post("/library/upload")
async def library_upload(
    file: UploadFile = File(...),
    client_id: str = Form("default"),
    levels: Optional[str] = Form(None),
    thread_id: Optional[str] = Form(None),
) -> dict[str, Any]:
    raw = await file.read()
    return await ingest_file(
        file.filename or "upload.bin",
        raw,
        client_id,
        content_type=file.content_type,
        levels=levels,
        thread_id=thread_id,
    )


# --------------------------------------------------------------------------- library files
@app.get("/library/files")
def library_files(client_id: str = "default", thread_id: Optional[str] = None) -> dict[str, Any]:
    return list_files(client_id, thread_id)


@app.delete("/library/files/{file_id}")
def library_delete(file_id: str, client_id: str = "default") -> dict[str, Any]:
    return delete_file(file_id, client_id)


# --------------------------------------------------------------------------- scrape / url-ingest
@app.post("/scrape")
async def scrape_url(req: ScrapeRequest) -> dict[str, Any]:
    return await scrape(req.url, req.client_id, req.levels, req.depth)


@app.post("/research")
async def research_web(req: ResearchRequest) -> dict[str, Any]:
    """Web-Recherche (SerpAPI) → priorisierte wiss./offizielle Treffer + Extrakte + Referenzen."""
    return await run_research(req.query, req.client_id, req.max_results, req.ingest)


@app.get("/scrape/allowlist")
def scrape_allowlist_get() -> dict[str, Any]:
    allow = get_allowlist()
    return {"domains": allow.domains, "store": allow.store_path}


@app.put("/scrape/allowlist")
def scrape_allowlist_put(req: AllowlistRequest) -> dict[str, Any]:
    allow = get_allowlist()
    domains = allow.replace(req.domains)
    return {"domains": domains, "store": allow.store_path}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8030)
