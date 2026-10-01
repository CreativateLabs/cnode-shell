FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py ./
EXPOSE 8020
# host.docker.internal → Host (Ollama :11434; optional externer c:node Graph :8001) wird per compose
#   `extra_hosts: ["host.docker.internal:host-gateway"]` erreichbar gemacht.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8020"]
