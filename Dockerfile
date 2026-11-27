# Stage 1: Build Tailwind CSS + DaisyUI 5
FROM node:22-slim AS css-builder
WORKDIR /build
RUN npm init -y && npm install -D tailwindcss @tailwindcss/cli daisyui@latest
COPY src/metashelf/web/static/input.css ./input.css
COPY src/metashelf/web/templates ./templates
RUN npx @tailwindcss/cli -i ./input.css -o ./app.css --minify

# Stage 2: Python runtime
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    METASHELF_CONFIG_DIR=/config \
    METASHELF_MEDIA_ROOTS=/media

RUN apt-get update && apt-get install -y --no-install-recommends \
    gosu \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -g 1000 metashelf && useradd -u 1000 -g 1000 -m -s /bin/bash metashelf

WORKDIR /app
COPY pyproject.toml README.md alembic.ini ./
COPY src ./src
COPY --from=css-builder /build/app.css ./src/metashelf/web/static/app.css

RUN pip install --no-cache-dir .

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

VOLUME ["/config", "/media"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "metashelf.main:app", "--host", "0.0.0.0", "--port", "8000"]
