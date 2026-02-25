FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir .[reporting]

RUN groupadd --system appuser && \
    useradd --system --create-home --no-log-init --gid appuser appuser
RUN mkdir -p /app/.dagster /app/data

COPY shared-logic /app/shared-logic
COPY reporting /app/reporting

ENV PYTHONPATH=/app/shared-logic/src:/app/reporting/src
ENV DAGSTER_HOME=/app/.dagster
RUN chown -R appuser:appuser /app/.dagster /app/data /home/appuser && \
    chmod 0750 /app/.dagster /app/data

USER appuser

EXPOSE 3000

CMD ["dagster-webserver", "-m", "reporting_service.definitions", "-h", "0.0.0.0", "-p", "3000"]
