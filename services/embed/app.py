"""Schlanker CPU-Embedding-Service — Ollama-kompatibles /api/embed für graph-core.

Ersetzt das schwere offizielle Ollama-Image (~5 GB GPU-Ballast) durch einen winzigen
ONNX-CPU-Embedder (fastembed). Liefert 768-dim-Vektoren von nomic-embed-text-v1.5,
exakt das Format, das graph-core erwartet: {"embeddings": [[...768...]]}.
"""
from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastembed import TextEmbedding
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("embed")

MODEL_NAME = os.getenv("EMBED_MODEL_NAME", "nomic-ai/nomic-embed-text-v1.5")  # 768-dim
app = FastAPI(title="embed", version="0.1.0")
_model: TextEmbedding | None = None


def _get() -> TextEmbedding:
    global _model
    if _model is None:
        log.info("loading embedding model %s …", MODEL_NAME)
        _model = TextEmbedding(model_name=MODEL_NAME)
        log.info("model ready")
    return _model


@app.on_event("startup")
def _warm() -> None:
    # Modell beim Start laden (Download+Init einmalig), damit die erste echte Anfrage schnell ist.
    try:
        list(_get().embed(["warmup"]))
    except Exception as e:  # noqa: BLE001
        log.warning("warmup failed (will retry on first request): %s", e)


class EmbedReq(BaseModel):
    model: str | None = None
    input: str | list[str] | None = None
    prompt: str | None = None  # Ollama akzeptiert auch 'prompt'


def _texts(req: EmbedReq) -> list[str]:
    if isinstance(req.input, list):
        return [str(t) for t in req.input]
    single = req.input if isinstance(req.input, str) else (req.prompt or "")
    return [single]


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "embed", "model": MODEL_NAME}


@app.post("/api/embed")
def embed(req: EmbedReq) -> dict:
    """Ollama /api/embed: {model,input} → {embeddings:[[...]]}."""
    vecs = [v.tolist() for v in _get().embed(_texts(req))]
    return {"model": req.model or MODEL_NAME, "embeddings": vecs}


@app.post("/api/embeddings")
def embeddings(req: EmbedReq) -> dict:
    """Ältere Ollama-Route: {prompt} → {embedding:[...]}."""
    text = req.prompt or (req.input if isinstance(req.input, str) else "")
    v = next(iter(_get().embed([text]))).tolist()
    return {"embedding": v}
