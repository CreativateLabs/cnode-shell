"""asset-foerder — Förder-Adapter (Förder-Stub) für die Dev-Shell.

Demo-Stub: matcht Vorhaben grob gegen Förderprogramme aus seed/assets.json.
Eigener Microservice (compose-Netz, /health) — im Hosted-Modus später gegen
die Live-Förder-Engine austauschbar.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

ASSETS_PATH = Path(os.getenv("ASSETS_PATH", "/seed/assets.json"))
app = FastAPI(title="asset-foerder", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _data() -> dict:
    try:
        return json.loads(ASSETS_PATH.read_text(encoding="utf-8")).get("foerder", {})
    except Exception:
        return {}


class MatchReq(BaseModel):
    text: str = ""


@app.get("/health")
def health():
    return {"status": "ok", "service": "asset-foerder", "programs_available": len(_data().get("programs", []))}


@app.post("/match")
def match(req: MatchReq):
    programs = sorted(_data().get("programs", []), key=lambda p: p.get("fit", 0), reverse=True)
    return {"source": "asset-foerder (stub)", "query": req.text, "programs": programs}
