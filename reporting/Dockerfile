FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml /app/pyproject.toml
COPY shared-logic /app/shared-logic
COPY reporting /app/reporting
RUN pip install --no-cache-dir .[reporting]

RUN apt-get update && apt-get install -y --no-install-recommends gosu supervisor && \
    rm -rf /var/lib/apt/lists/*
RUN groupadd --system appuser && \
    useradd --system --create-home --no-log-init --gid appuser appuser
RUN mkdir -p /app/.dagster /app/.dagster-default /app/data
COPY reporting/workspace.yaml /app/.dagster-default/workspace.yaml
COPY reporting/dagster.yaml /app/.dagster-default/dagster.yaml

ENV PYTHONPATH=/app/shared-logic/src:/app/reporting/src
ENV DAGSTER_HOME=/app/.dagster
RUN chown -R appuser:appuser /app/.dagster /app/.dagster-default /app/data /home/appuser && \
    chmod 0750 /app/.dagster /app/.dagster-default /app/data /home/appuser

COPY reporting/entrypoint.sh /entrypoint.sh
COPY reporting/supervisord.conf /app/supervisord.conf
RUN chmod +x /entrypoint.sh
USER appuser:appuser
ENTRYPOINT ["/entrypoint.sh"]

EXPOSE 3000

# Production: supervisord runs dagster-webserver and dagster-daemon as independent processes
CMD ["supervisord", "-c", "/app/supervisord.conf"]
