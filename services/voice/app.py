"""
Voice / Speech-to-Text-Service (WS-VOICE) — SCOPE v2, Port 8060.

Lokaler, Open-Source STT-Service auf Basis von `faster-whisper` (CTranslate2).
KEIN Cloud-STT: die Transkription läuft zu 100 % offline in diesem Container.
Nur der einmalige Modell-Download stammt von Hugging Face (danach im /models-Cache).

Routen:
  GET  /health                         -> {status, model, device, loaded, ...}
  POST /transcribe  (multipart file)   -> {text, language, duration}

Env:
  WHISPER_MODEL    (default "small")   z. B. tiny|base|small|medium|large-v3
  WHISPER_COMPUTE  (default "int8")    CTranslate2 compute_type
  WHISPER_DEVICE   (default "auto")    cpu|cuda|auto
  HF_HOME          (default /models)   Cache-Verzeichnis (Volume) für Offline-Betrieb
"""
from __future__ import annotations

import os
import tempfile
from typing import Any

from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from stt import get_engine

app = FastAPI(title="c:node Voice / STT-Service", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Zulässige Upload-Endungen (faster-whisper/PyAV dekodiert diese Formate).
_ALLOWED_SUFFIXES = {".webm", ".wav", ".m4a", ".ogg", ".mp3", ".flac", ".mp4", ".oga"}


@app.on_event("startup")
def _startup() -> None:
    # Best-effort: Modell beim Start laden (füllt den /models-Cache, wärmt vor).
    # Schlägt es fehl (kein Netz / noch nicht gecacht), bleibt der Service oben
    # und /health meldet loaded=false — /transcribe versucht dann lazy erneut.
    get_engine().warmup()


@app.get("/health")
def health() -> dict[str, Any]:
    return get_engine().status()


@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...)) -> Any:
    engine = get_engine()

    data = await file.read()
    if not data:
        return JSONResponse(status_code=400, content={"error": "empty file"})

    # Suffix bestimmen (aus Dateiname), sonst .webm als sinnvoller Default.
    _, ext = os.path.splitext(file.filename or "")
    ext = ext.lower()
    if ext not in _ALLOWED_SUFFIXES:
        ext = ".webm"

    # Bytes in temporäre Datei — faster-whisper dekodiert via PyAV/ffmpeg.
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        try:
            result = engine.transcribe(tmp_path)
        except Exception as exc:
            # Modell (noch) nicht ladbar => sauberer 503-Hinweis (kein Crash).
            if not engine.loaded:
                return JSONResponse(
                    status_code=503,
                    content={
                        "error": "stt model not loaded",
                        "detail": str(exc),
                        "hint": (
                            "Modell noch nicht im Cache. Einmaliger Download nötig "
                            "(HF_HOME=/models). Danach läuft der Service offline. "
                            "Siehe Dockerfile-Kopf für Vorab-Cache-Befehl."
                        ),
                        "model": engine.model_name,
                    },
                )
            # Modell geladen, aber Dekodierung/Transkription fehlgeschlagen.
            return JSONResponse(
                status_code=422,
                content={"error": "transcription failed", "detail": str(exc)},
            )

        return result
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
