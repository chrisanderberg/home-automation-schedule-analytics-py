#!/usr/bin/env python3
"""Bump a Dockerfile `python:X.Y.Z-slim` base image to latest patch for X.Y."""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

FROM_PATTERN = re.compile(r"^(FROM\s+python:)(\d+)\.(\d+)\.(\d+)(-slim(?:[^\r\n]*)?)$", re.MULTILINE)
TAG_PATTERN_TEMPLATE = r"^{major}\.{minor}\.(\d+)-slim$"
TAGS_API = "https://registry.hub.docker.com/v2/repositories/library/python/tags?page_size=100"


def _read_dockerfile(path: Path) -> tuple[str, int, int, int]:
    text = path.read_text(encoding="utf-8")
    match = FROM_PATTERN.search(text)
    if match is None:
        raise ValueError(f"no python base image tag found in {path}")
    major = int(match.group(2))
    minor = int(match.group(3))
    patch = int(match.group(4))
    return text, major, minor, patch


def _fetch_latest_patch(major: int, minor: int) -> int:
    regex = re.compile(TAG_PATTERN_TEMPLATE.format(major=major, minor=minor))
    latest_patch = -1
    next_url = TAGS_API

    while next_url:
        req = urllib.request.Request(next_url, headers={"User-Agent": "codex-python-base-bumper"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace").strip()
            except Exception:
                body = ""
            details = f"HTTP {exc.code} {exc.reason}"
            if body:
                details = f"{details}; body: {body}"
            raise RuntimeError(f"failed to fetch Docker Hub tags from {next_url}: {details}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"failed to fetch Docker Hub tags from {next_url}: {exc.reason}") from exc

        for result in payload.get("results", []):
            name = result.get("name", "")
            tag_match = regex.match(name)
            if tag_match is None:
                continue
            latest_patch = max(latest_patch, int(tag_match.group(1)))

        next_url = payload.get("next")

    if latest_patch < 0:
        raise RuntimeError(f"no tags found for python:{major}.{minor}.X-slim")
    return latest_patch


def _write_updated_dockerfile(path: Path, text: str, major: int, minor: int, patch: int) -> None:
    replacement = rf"\g<1>{major}.{minor}.{patch}\g<5>"
    updated_text, count = FROM_PATTERN.subn(replacement, text, count=1)
    if count != 1:
        raise RuntimeError(f"failed to replace FROM line in {path}")
    path.write_text(updated_text, encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: bump_python_base_tag.py <dockerfile-path>")
        return 2

    try:
        dockerfile = Path(sys.argv[1]).resolve()
        text, major, minor, current_patch = _read_dockerfile(dockerfile)
        latest_patch = _fetch_latest_patch(major, minor)

        if latest_patch == current_patch:
            print(f"{dockerfile}: already up to date at {major}.{minor}.{current_patch}")
            return 0

        if latest_patch < current_patch:
            print(
                f"{dockerfile}: current patch {current_patch} is newer than upstream {latest_patch}; skipping update"
            )
            return 0

        _write_updated_dockerfile(dockerfile, text, major, minor, latest_patch)
        print(f"{dockerfile}: updated python tag {major}.{minor}.{current_patch} -> {major}.{minor}.{latest_patch}")
        return 0
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
