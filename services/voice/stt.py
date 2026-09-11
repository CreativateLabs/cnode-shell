"""
Lokale Speech-to-Text-Engine (WS-VOICE) — SCOPE v2.

100 % lokal / offline. Es gibt KEINEN Cloud-Call zur Inferenz:
`faster-whisper` (CTranslate2) läuft komplett auf CPU/Metal in diesem Container.

Das EINZIGE, was jemals das Netz berührt, ist der *einmalige* Modell-Download
von Hugging Face beim allerersten Laden. Danach liegt das Modell im Cache
(`HF_HOME=/models`, per Volume persistiert) und der Betrieb ist vollständig offline.

Offline-Vorab-Cache (empfohlen für air-gapped Betrieb) — siehe Dockerfile-Kopf:
    docker run --rm -e HF_HOME=/models -v cnode_voice_models:/models cnode-voice \\
        python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='auto', compute_type='int8')"
Danach kann der Container ohne Netzwerk laufen (HF_HUB_OFFLINE=1).
"""
from __future__ import annotations

import os
import threading
from typing import Any, Optional

# faster-whisper ist optional zur Import-Zeit: der Service muss auch dann starten
# und /health beantworten können, wenn das Paket/Modell (noch) nicht verfügbar ist.
try:
    from faster_whisper import WhisperModel  # type: ignore

    _IMPORT_ERROR: Optional[str] = None
except Exception as exc:  # pragma: no cover - defensive
    WhisperModel = None  # type: ignore
    _IMPORT_ERROR = f"{type(exc).__name__}: {exc}"


WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small")
WHISPER_COMPUTE = os.environ.get("WHISPER_COMPUTE", "int8")
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "auto")


class STTEngine:
    """Lazy, thread-sicherer Wrapper um ein faster-whisper WhisperModel.

    Das Modell wird erst geladen, wenn es gebraucht wird (oder per warmup()
    beim Startup versucht). Schlägt der Download/Load fehl (z. B. noch kein
    Netz / Modell nicht im Cache), bleibt der Service oben und meldet
    `loaded=false` + den letzten Fehler; /transcribe antwortet dann sauber 503.
    """

    def __init__(self) -> None:
        self.model_name = WHISPER_MODEL
        self.compute_type = WHISPER_COMPUTE
        self.device = WHISPER_DEVICE
        self._model: Optional["WhisperModel"] = None
        self._resolved_device: str = self.device
        self._lock = threading.Lock()
        self._last_error: Optional[str] = _IMPORT_ERROR

    # --------------------------------------------------------------- state
    @property
    def loaded(self) -> bool:
        return self._model is not None

    def status(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "voice",
            "port": 8060,
            "model": self.model_name,
            "compute_type": self.compute_type,
            "device": self._resolved_device,
            "loaded": self.loaded,
            "local_only": True,  # Inferenz zu 100 % lokal, kein Cloud-STT
            "error": self._last_error,
        }

    # --------------------------------------------------------------- load
    def load(self) -> "WhisperModel":
        """Lädt das Modell (idempotent). Wirft bei Fehler."""
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:  # doppelt geprüft nach Lock
                return self._model
            if WhisperModel is None:
                raise RuntimeError(
                    "faster-whisper ist nicht installiert: " + str(_IMPORT_ERROR)
                )
            try:
                model = WhisperModel(
                    self.model_name,
                    device=self.device,
                    compute_type=self.compute_type,
                )
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                raise
            # CTranslate2 löst device="auto" intern auf; best effort auslesen.
            self._resolved_device = getattr(model, "device", self.device) or self.device
            self._model = model
            self._last_error = None
            return model

    def warmup(self) -> bool:
        """Best-effort-Load beim Startup. Kein Crash bei Fehler."""
        try:
            self.load()
            return True
        except Exception:
            return False

    # ----------------------------------------------------------- transcribe
    def transcribe(self, audio_path: str) -> dict[str, Any]:
        """Transkribiert eine Audiodatei (webm/wav/m4a/ogg/...).

        faster-whisper dekodiert das Audio via PyAV/ffmpeg — es muss also kein
        WAV sein. language=None => Auto-Detect (Deutsch fähig).
        """
        model = self.load()
        segments, info = model.transcribe(audio_path, language=None)
        # segments ist ein Generator — hier materialisieren und Text sammeln.
        text = "".join(seg.text for seg in segments).strip()
        return {
            "text": text,
            "language": getattr(info, "language", None),
            "duration": round(float(getattr(info, "duration", 0.0) or 0.0), 3),
        }


_engine: Optional[STTEngine] = None


def get_engine() -> STTEngine:
    global _engine
    if _engine is None:
        _engine = STTEngine()
    return _engine
