FROM python:3.11-slim

# libgomp1: ONNX-Runtime (CPU) braucht die OpenMP-Runtime.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# Modell-Cache persistiert im Volume (siehe compose), damit der ~140-MB-Download nur 1× läuft.
ENV FASTEMBED_CACHE_PATH=/models
EXPOSE 11434

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "11434"]
