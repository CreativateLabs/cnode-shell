"""model-router — LLM-Abstraktion für die Creativate Dev-Shell.

Default: lokales OSS-Modell via Ollama (EU-souverän, on-prem). Umschaltbar auf
Claude (provider=claude), sofern ANTHROPIC_API_KEY gesetzt ist. Ein Endpunkt,
zwei Provider — der Live-Beweis für "modell-agnostisch, kein Lock-in".
"""
from __future__ import annotations

import os

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")

app = FastAPI(title="model-router", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class CompleteReq(BaseModel):
    prompt: str
    system: str | None = None
    provider: str = "ollama"       # "ollama" | "claude"
    model: str | None = None
    max_tokens: int = 700


@app.get("/health")
async def health():
    ollama_ok = False
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"{OLLAMA_BASE_URL}/api/version")
            ollama_ok = r.status_code == 200
    except Exception:
        ollama_ok = False
    return {
        "status": "ok",
        "service": "model-router",
        "ollama": {"reachable": ollama_ok, "base_url": OLLAMA_BASE_URL, "model": OLLAMA_MODEL},
        "claude": {"configured": bool(ANTHROPIC_API_KEY), "model": ANTHROPIC_MODEL},
    }


@app.get("/models")
async def models():
    out = {"ollama": [], "claude": []}
    try:
        async with httpx.AsyncClient(timeout=4.0) as c:
            r = await c.get(f"{OLLAMA_BASE_URL}/api/tags")
            out["ollama"] = [m["name"] for m in r.json().get("models", [])]
    except Exception:
        pass
    if ANTHROPIC_API_KEY:
        out["claude"] = [ANTHROPIC_MODEL]
    return out


async def _ollama(prompt: str, system: str | None, model: str, max_tokens: int) -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    async with httpx.AsyncClient(timeout=120.0) as c:
        r = await c.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json={"model": model, "messages": messages, "stream": False,
                  "options": {"num_predict": max_tokens}},
        )
        r.raise_for_status()
        return (r.json().get("message") or {}).get("content", "").strip()


async def _claude(prompt: str, system: str | None, model: str, max_tokens: int) -> str:
    async with httpx.AsyncClient(timeout=120.0) as c:
        r = await c.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": model, "max_tokens": max_tokens,
                  **({"system": system} if system else {}),
                  "messages": [{"role": "user", "content": prompt}]},
        )
        r.raise_for_status()
        parts = r.json().get("content", [])
        return "".join(p.get("text", "") for p in parts).strip()


@app.post("/complete")
async def complete(req: CompleteReq):
    provider = req.provider
    if provider == "claude" and not ANTHROPIC_API_KEY:
        provider = "ollama"  # graceful fallback — Demo bleibt stabil
    try:
        if provider == "claude":
            model = req.model or ANTHROPIC_MODEL
            text = await _claude(req.prompt, req.system, model, req.max_tokens)
        else:
            model = req.model or OLLAMA_MODEL
            text = await _ollama(req.prompt, req.system, model, req.max_tokens)
        return {"text": text, "provider": provider, "model": model, "ok": True}
    except Exception as e:
        return {"text": "", "provider": provider, "model": req.model or "", "ok": False, "error": str(e)}
