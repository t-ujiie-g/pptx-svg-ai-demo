"""Subprocess wrapper for pptx-svg's inspect script (PNG rendering).

backend/skills/pptx/scripts/pptx_inspect.js renders each slide of a PPTX to
PNG and extracts the shape structure, so the chat request can attach a visual
+ structural context summary to the user message.

Editing itself lives in the skill as Python (scripts/edit_pptx.py, invoked via
ADK's run_skill_script), so no Node-side edit path is needed here.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import pathlib
from typing import Any

from src.constants import PPTX_INSPECT_TIMEOUT

logger = logging.getLogger(__name__)

_SCRIPTS_DIR = (
    pathlib.Path(__file__).resolve().parent.parent.parent
    / "skills" / "pptx" / "scripts"
)
_INSPECT_SCRIPT = _SCRIPTS_DIR / "pptx_inspect.js"
_NODE_PATH = os.environ.get("NODE_PATH", "/usr/lib/node_modules")


async def _run_node_script(
    script: pathlib.Path,
    stdin_data: bytes,
    extra_args: list[str] | None = None,
) -> dict[str, Any]:
    """Run a Node.js script, feed stdin, return parsed JSON from stdout."""
    cmd = ["node", str(script), *(extra_args or [])]
    env = {**os.environ, "NODE_PATH": _NODE_PATH}

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=stdin_data),
            timeout=PPTX_INSPECT_TIMEOUT,
        )
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(f"{script.name} timed out after {PPTX_INSPECT_TIMEOUT}s")

    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace")[:2000]
        logger.error(f"{script.name} exit={proc.returncode}\nstderr:\n{err}")
        raise RuntimeError(f"{script.name} failed (exit {proc.returncode}): {err}")

    try:
        return json.loads(stdout)
    except json.JSONDecodeError as e:
        err = stderr.decode("utf-8", errors="replace")[:2000]
        head = stdout[:500].decode("utf-8", errors="replace")
        logger.error(
            f"{script.name} non-JSON stdout (len={len(stdout)}): "
            f"head={head!r}\nstderr:\n{err}"
        )
        raise RuntimeError(f"{script.name} produced non-JSON output: {e}")


async def inspect_pptx(
    pptx_bytes: bytes,
    *,
    with_png: bool = True,
    png_width: int = 960,
    png_height: int = 540,
) -> dict[str, Any]:
    """Run pptx_inspect.js on the given PPTX bytes.

    Returns:
        {
            "slide_count": int,
            "slide_width_emu": int, "slide_height_emu": int,
            "slides": [
                {"slide_idx": int, "shapes": [...], "png_base64"?: str}
            ]
        }
    """
    args = [f"--width={png_width}", f"--height={png_height}"]
    if not with_png:
        args.append("--no-png")
    b64 = base64.b64encode(pptx_bytes)
    return await _run_node_script(_INSPECT_SCRIPT, b64, args)
