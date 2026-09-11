# c:node Voice / STT-Service (WS-VOICE) — SCOPE v2 §Voice, Port 8060.
#
# Lokales OSS-Speech-to-Text (faster-whisper / CTranslate2). Die Transkription
# läuft zu 100 % OFFLINE in diesem Container — es gibt KEINEN Cloud-STT-Call.
# Das einzige, was jemals das Netz berührt, ist der EINMALIGE Modell-Download
# von Hugging Face beim ersten Laden. Danach liegt das Modell im Volume-Cache
# (HF_HOME=/models) und der Betrieb ist komplett offline (HF_HUB_OFFLINE=1).
#
# Build (Kontext = dieses Verzeichnis):
#   docker build -t cnode-voice services/voice
#
# Run (mit persistentem Modell-Cache-Volume):
#   docker run --rm -p 8060:8060 \
#     -e WHISPER_MODEL=small -e HF_HOME=/models \
#     -v cnode_voice_models:/models cnode-voice
#
# ── Modell VORAB cachen (für air-gapped / offline Betrieb) ──────────────────
# Einmalig mit Netz ausführen, füllt das /models-Volume:
#   docker run --rm -e HF_HOME=/models -v cnode_voice_models:/models cnode-voice \
#     python -c "from faster_whisper import WhisperModel; \
#                WhisperModel('small', device='auto', compute_type='int8')"
# Danach kann der Service ohne Netzwerk laufen — optional erzwingen mit:
#   -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    WHISPER_MODEL=small \
    WHISPER_COMPUTE=int8 \
    HF_HOME=/models

WORKDIR /app

# ffmpeg-Libs für PyAV-Audio-Dekodierung (webm/m4a/ogg). PyAV bringt eigene
# ffmpeg-Binaries als Wheel mit; ffmpeg wird hier als Absicherung installiert.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/

# Modell-Cache-Verzeichnis (per Volume überschreibbar/persistierbar).
RUN mkdir -p /models

EXPOSE 8060

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8060"]
