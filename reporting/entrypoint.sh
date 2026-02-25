#!/bin/sh
# Ensure DAGSTER_HOME (and /app/data) are writable by appuser when using volume mounts.
# Named volumes are typically root-owned; chown so dagster can persist run history.
# Seed DAGSTER_HOME from .dagster-default if files are missing (empty volume or upgrade).
# DAGSTER_HOME defaults to /app/.dagster if unset; operators may override via env.
set -e
dagster_home="${DAGSTER_HOME:-/app/.dagster}"
mkdir -p "$dagster_home"
for f in workspace.yaml dagster.yaml; do
  if [ ! -f "$dagster_home/$f" ] && [ -f "/app/.dagster-default/$f" ]; then
    cp "/app/.dagster-default/$f" "$dagster_home/$f"
  fi
done
for f in workspace.yaml dagster.yaml; do
  if [ ! -f "$dagster_home/$f" ]; then
    echo "error: $dagster_home/$f missing after init" >&2
    exit 1
  fi
done
for dir in "$dagster_home" /app/data; do
  if [ -d "$dir" ]; then
    if [ "$(id -u)" -eq 0 ]; then
      chown -R appuser:appuser "$dir" || { _ec=$?; echo "error: chown -R appuser:appuser $dir failed (exit $_ec)" >&2; exit "$_ec"; }
    fi
    find "$dir" -type d -exec chmod 0750 {} + || { _ec=$?; echo "error: chmod 0750 on directories under $dir failed (exit $_ec)" >&2; exit "$_ec"; }
    find "$dir" -type f -exec chmod 0640 {} + || { _ec=$?; echo "error: chmod 0640 on files under $dir failed (exit $_ec)" >&2; exit "$_ec"; }
  fi
done
if [ "$(id -u)" -eq 0 ]; then
  exec gosu appuser "$@"
fi
exec "$@"
