FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py .
# Hosting-Default: streamable-http auf :8090 (für lokale Clients stattdessen stdio nutzen).
ENV MCP_TRANSPORT=streamable-http MCP_HOST=0.0.0.0 MCP_PORT=8090
EXPOSE 8090
CMD ["python", "server.py"]
