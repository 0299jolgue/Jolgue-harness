FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATABASE_PATH=/data/agent.db WORKSPACE_PATH=/data/workspace
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
COPY static ./static
RUN mkdir -p /data/workspace && chown -R 10001:10001 /app /data
USER 10001:10001
EXPOSE 80
CMD ["uvicorn","app:app","--host","0.0.0.0","--port","80"]
