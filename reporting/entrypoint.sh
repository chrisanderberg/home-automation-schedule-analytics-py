#!/bin/sh
# Ensure DAGSTER_HOME (and /app/data) are writable by appuser when using volume mounts.
# Named volumes are typically root-owned; chown so dagster can persist run history.
set -e
for dir in /app/.dagster /app/data; do
  if [ -d "$dir" ]; then
    chown -R appuser:appuser "$dir" 2>/dev/null || true
    chmod 0750 "$dir" 2>/dev/null || true
  fi
done
exec gosu appuser "$@"
