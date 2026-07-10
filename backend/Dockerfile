FROM python:3.12-slim AS builder

# virtualenvs.in-project puts the venv at /app/.venv so the runtime stage below can copy it out
# whole, instead of untangling app dependencies from poetry/pip itself in system site-packages.
RUN pip install --no-cache-dir poetry==2.3.4 \
    && poetry config virtualenvs.in-project true

WORKDIR /app

COPY pyproject.toml poetry.lock* ./
RUN poetry install --no-root --only main

FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /app/.venv ./.venv
ENV PATH="/app/.venv/bin:${PATH}"

COPY . .

RUN mkdir -p /data
ENV BBLOCKS_DATABASE_PATH=/data/meta-register.db
VOLUME ["/data"]

EXPOSE 8000

# Set at runtime (e.g. via docker-compose environment:) to the subpath this service is
# reverse-proxied under, such as "/meta-register-backend" -- left empty to serve at the host
# root. Only fixes up things the app itself generates (OpenAPI "servers" entry, /docs, the
# /.well-known/mcp.json URL); the reverse proxy must still strip the prefix before forwarding,
# since routes are still registered at "/", "/bblocks", etc.
ENV ROOT_PATH=""

# Migrations run in-process on startup (see app/main.py's lifespan), not as a separate step.
CMD ["bash", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --root-path \"${ROOT_PATH%/}\""]
