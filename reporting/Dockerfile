FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml /app/pyproject.toml
COPY shared-logic /app/shared-logic
COPY reporting /app/reporting
RUN pip install --no-cache-dir .[reporting]

RUN apt-get update && apt-get install -y --no-install-recommends gosu && \
    rm -rf /var/lib/apt/lists/*
RUN groupadd --system appuser && \
    useradd --system --create-home --no-log-init --gid appuser appuser
RUN mkdir -p /app/.dagster /app/data

ENV PYTHONPATH=/app/shared-logic/src:/app/reporting/src
ENV DAGSTER_HOME=/app/.dagster
RUN chown -R appuser:appuser /app/.dagster /app/data /home/appuser && \
    chmod 0750 /app/.dagster /app/data /home/appuser

COPY reporting/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]

EXPOSE 3000

# dagster dev runs both dagster-webserver and dagster-daemon so schedules/sensors work
CMD ["dagster", "dev", "-m", "reporting_service.definitions", "-h", "0.0.0.0", "-p", "3000"]
