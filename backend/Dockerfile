FROM python:3.12-slim

RUN pip install --no-cache-dir poetry==2.3.4 \
    && poetry config virtualenvs.create false

WORKDIR /app

COPY pyproject.toml poetry.lock* ./
RUN poetry install --no-root --only main

COPY . .

RUN mkdir -p /data
ENV BBLOCKS_DATABASE_PATH=/data/meta-register.db
VOLUME ["/data"]

EXPOSE 8000


# Migrations run in-process on startup (see app/main.py's lifespan), not as a separate step.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
