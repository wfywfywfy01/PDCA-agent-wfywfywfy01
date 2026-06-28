FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY frontend ./frontend
COPY migrations ./migrations
COPY run.py .

ENV PDCA_HOST=0.0.0.0
ENV PDCA_WORKBENCH_PORT=8767
ENV PDCA_MVP_ROOT=/mvp
ENV PDCA_REPO_ROOT=/repo

VOLUME ["/app/data", "/mvp", "/repo"]

EXPOSE 8767

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -f http://127.0.0.1:8767/health || exit 1

CMD ["python", "run.py"]
