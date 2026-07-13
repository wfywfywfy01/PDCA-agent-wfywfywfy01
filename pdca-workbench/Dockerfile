FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl gnupg \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
       | gpg --dearmor -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.gpg \
    && . /etc/os-release \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.gpg] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" \
       > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update && apt-get install -y --no-install-recommends postgresql-client-18 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m playwright install --with-deps chromium

COPY app ./app
COPY frontend ./frontend
COPY migrations ./migrations
COPY run.py .

ENV PDCA_HOST=0.0.0.0
ENV PDCA_WORKBENCH_PORT=8767
ENV PDCA_MVP_ROOT=/mvp
ENV PDCA_REPO_ROOT=/repo
ENV PDCA_PG_DUMP_COMMAND=/usr/lib/postgresql/18/bin/pg_dump
ENV PDCA_TRACKING_HEADLESS=1

VOLUME ["/app/data", "/mvp", "/repo"]

EXPOSE 8767

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -f http://127.0.0.1:8767/health || exit 1

CMD ["python", "run.py"]
