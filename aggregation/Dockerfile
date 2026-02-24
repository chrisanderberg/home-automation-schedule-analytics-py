FROM python:3.11-slim

WORKDIR /app

COPY shared-logic /app/shared-logic
COPY aggregation /app/aggregation
COPY data /app/data
COPY pyproject.toml /app/pyproject.toml

RUN pip install --no-cache-dir ".[aggregation]"

ENV PYTHONPATH=/app/shared-logic/src:/app/aggregation/src
ENV HAA_MAIN_PORT=8080
ENV HAA_TESTING_PORT=8081

EXPOSE 8080

CMD ["python", "-m", "aggregation_service.main"]
