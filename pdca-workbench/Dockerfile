ARG NODE_RUNTIME_IMAGE=node:22-bookworm-slim
FROM ${NODE_RUNTIME_IMAGE} AS node-runtime

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

# vertu-cli 2.x 需要 Node.js >= 20；只复制运行时与 npm，避免把完整 Node 镜像带入生产层。
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && npm install -g vertu-cli@2.1.10 @vertu-tech/vps-cli@0.1.12 --omit=optional \
    && vertu-cli --version \
    && vertu --version

COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
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
ENV VERTU_COMMAND=vertu-cli

VOLUME ["/app/data", "/mvp", "/repo"]

EXPOSE 8767

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import json,urllib.request; assert json.load(urllib.request.urlopen('http://127.0.0.1:8767/health'))['status'] == 'ok'" || exit 1

CMD ["python", "run.py"]
