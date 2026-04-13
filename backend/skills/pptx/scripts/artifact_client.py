"""Shared artifact HTTP client for skill scripts (edit_pptx / generate_pptx).

Centralises the base URL, HTTP timeout, artifact marker, and the
fetch/post helpers so they are defined in exactly one place.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

BASE_URL = os.environ.get("ARTIFACT_BASE_URL", "http://localhost:8000")
ARTIFACT_MARKER = "__PPTX_ARTIFACT__"
HTTP_TIMEOUT = 30


def fetch_artifact(artifact_id: str) -> bytes:
    """Download an artifact's raw bytes from the backend."""
    req = urllib.request.Request(f"{BASE_URL}/artifacts/{artifact_id}")
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return resp.read()


def post_artifact(
    data: bytes,
    filename: str,
    source_artifact_id: str | None = None,
) -> dict:
    """Upload bytes as a new artifact and return the JSON response."""
    params = f"filename={urllib.parse.quote(filename)}"
    if source_artifact_id:
        params += f"&source_artifact_id={urllib.parse.quote(source_artifact_id)}"
    url = f"{BASE_URL}/artifacts?{params}"
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/octet-stream"},
    )
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return json.loads(resp.read())


def print_artifact_marker(info: dict) -> None:
    """Print the marker line that chat.py uses to detect new artifacts."""
    print(f"{ARTIFACT_MARKER} {json.dumps(info)}")
