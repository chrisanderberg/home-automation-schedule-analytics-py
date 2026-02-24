FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir dagster>=1.7.0

COPY shared-logic /app/shared-logic
COPY reporting /app/reporting
COPY data /app/data

ENV PYTHONPATH=/app/shared-logic/src:/app/reporting/src
ENV DAGSTER_HOME=/app/.dagster

EXPOSE 3000

CMD ["dagster", "dev", "-m", "reporting_service.definitions", "-h", "0.0.0.0", "-p", "3000"]
