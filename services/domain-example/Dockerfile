FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py ./
# Das cnode-sdk (Domain-Contract) wird per Volume unter /pkg/cnode-sdk gemountet.
ENV PYTHONPATH=/pkg/cnode-sdk
EXPOSE 8090
CMD ["uvicorn","app:app","--host","0.0.0.0","--port","8090"]
