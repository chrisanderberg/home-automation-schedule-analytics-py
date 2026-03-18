FROM python:3.11.14-slim

WORKDIR /app

COPY pyproject.toml /app/pyproject.toml
COPY uv.lock /app/uv.lock
COPY shared-logic /app/shared-logic
COPY aggregation /app/aggregation
COPY data /app/data

# Rebuild this image on a regular CI schedule to pick up upstream security patches.
RUN pip install --no-cache-dir uv && \
    uv export --frozen --no-dev --extra aggregation --format requirements-txt -o /tmp/requirements.txt && \
    pip install --no-cache-dir -r /tmp/requirements.txt

RUN groupadd --system app && \
    useradd --system --create-home --gid app app && \
    chown -R app:app /app

ENV PYTHONPATH=/app/shared-logic/src:/app/aggregation/src
ENV HAA_MAIN_PORT=8080
ENV HAA_TESTING_PORT=8081
# Required at runtime; startup fails fast if either is missing.
# ENV HAA_LATITUDE=...
# ENV HAA_LONGITUDE=...
ENV HOME=/home/app

EXPOSE 8080
EXPOSE 8081

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD sh -c 'python -c "import os, sys, urllib.request; port = os.getenv(\"HAA_MAIN_PORT\", \"8080\"); url = f\"http://127.0.0.1:{port}/v1/health\"; sys.exit(0 if urllib.request.urlopen(url, timeout=3).status == 200 else 1)"'

USER app

CMD ["python", "-m", "aggregation_service.main"]
