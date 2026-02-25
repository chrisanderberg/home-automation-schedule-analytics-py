FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir "dagster>=1.7.0,<2.0.0" "dagster-webserver>=1.7.0,<2.0.0"

COPY shared-logic /app/shared-logic
COPY reporting /app/reporting

RUN groupadd --system appuser && \
    useradd --system --create-home --gid appuser appuser

ENV PYTHONPATH=/app/shared-logic/src:/app/reporting/src
ENV DAGSTER_HOME=/app/.dagster
RUN mkdir -p /app/.dagster /app/data && \
    chown -R appuser:appuser /app /home/appuser && \
    chmod 0750 /app/.dagster /app/data

USER appuser

EXPOSE 3000

CMD ["dagster-webserver", "-m", "reporting_service.definitions", "-h", "0.0.0.0", "-p", "3000"]
