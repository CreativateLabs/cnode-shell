"""asset-scout — Scout-Adapter (LeadScout-Proxy/Stub) für die Dev-Shell.

Demo-Stub: liefert feste, plausible Leads aus seed/assets.json. Läuft als
eigener Microservice (compose-Netz, /health), damit die Architektur echt ist —
im Hosted-Modus später gegen die Live-LeadScout-API austauschbar.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

ASSETS_PATH = Path(os.getenv("ASSETS_PATH", "/seed/assets.json"))
app = FastAPI(title="asset-scout", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _data() -> dict:
    try:
        return json.loads(ASSETS_PATH.read_text(encoding="utf-8")).get("scout", {})
    except Exception:
        return {}


class FindReq(BaseModel):
    text: str = ""
    segment: str | None = None


@app.get("/health")
def health():
    return {"status": "ok", "service": "asset-scout", "leads_available": len(_data().get("leads", []))}


@app.post("/find")
def find(req: FindReq):
    d = _data()
    leads = d.get("leads", [])
    seg = (req.segment or req.text or "").lower()
    if seg:
        filtered = [l for l in leads if seg in l.get("segment", "").lower() or seg in l.get("region", "").lower()]
        leads = filtered or leads
    return {"source": "asset-scout (stub)", "query": req.text, "leads": leads}
