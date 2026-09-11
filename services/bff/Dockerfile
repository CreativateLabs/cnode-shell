FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py db.py auth.py agents.py domain_agents.py altcha_gate.py api_keys.py ratelimit.py ./
# Governance-Store lebt in Postgres (SCOPE v2). Kein lokales Volume mehr nötig.
ENV DATABASE_URL=postgresql://cnode:cnode@postgres:5432/cnode
EXPOSE 8080
CMD ["uvicorn","app:app","--host","0.0.0.0","--port","8080"]
