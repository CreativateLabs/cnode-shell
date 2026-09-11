# c:node Data / Assets-Service (WS-DATA) — SCOPE §2.5
#
# Build-Kontext = Repo-Root (damit sowohl der Service als auch seed/ hineinkommen):
#   docker build -f services/assets/Dockerfile -t cnode-assets .
# Im docker-compose (WS-INT) entsprechend:
#   build: { context: ., dockerfile: services/assets/Dockerfile }
#
# Der ECHTE ~14k data-foerder-Datensatz kann zur Laufzeit gemountet werden:
#   -v /pfad/zu/data-foerder/db/foerder.sqlite:/data/foerder.sqlite
#   -e FOERDER_DB_PATH=/data/foerder.sqlite
# Ohne Mount greift der repräsentative Seed-Katalog (seed/verwaltungsleistungen.json).
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY services/assets/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Service-Code
COPY services/assets/ /app/

# Seed (Stub-first Fallback): leads.json, verwaltungsleistungen.json, foerderprogramme.json
COPY seed/ /app/seed/

EXPOSE 8030

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8030"]
