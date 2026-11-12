FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir . \
    && groupadd --gid 10001 raptor \
    && useradd --uid 10001 --gid raptor --no-create-home raptor \
    && mkdir -p /archive /database \
    && chown raptor:raptor /archive /database

ENV RAPTOR_ARCHIVE_DIR=/archive \
    RAPTOR_DB_PATH=/database/bronze.db \
    PYTHONUNBUFFERED=1
VOLUME ["/archive", "/database"]
USER raptor
ENTRYPOINT ["raptor-etl", "schedule"]
