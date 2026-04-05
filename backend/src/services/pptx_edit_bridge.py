"""Python async wrapper for the pptx-svg Node.js JSON-RPC bridge."""

import asyncio
import base64
import json
import logging
import os
import pathlib
from typing import Any

from src.constants import BRIDGE_CALL_TIMEOUT, BRIDGE_STARTUP_TIMEOUT

logger = logging.getLogger(__name__)

_BRIDGE_SCRIPT = pathlib.Path(__file__).resolve().parent / "pptx_edit_bridge.js"
_NODE_PATH = os.environ.get("NODE_PATH", "/usr/lib/node_modules")


class PptxEditBridge:
    """Manages a long-running Node.js pptx-svg bridge process."""

    def __init__(self) -> None:
        self._proc: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self._counter = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._reader_task: asyncio.Task | None = None

    async def _ensure_started(self) -> None:
        if self._proc is not None and self._proc.returncode is None:
            return
        logger.info("Starting pptx-svg bridge process")
        self._proc = await asyncio.create_subprocess_exec(
            "node",
            str(_BRIDGE_SCRIPT),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "NODE_PATH": _NODE_PATH},
        )
        self._reader_task = asyncio.create_task(self._read_loop())
        # Wait for "ready" signal
        ready_future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[0] = ready_future  # id=null maps to 0 in our scheme
        try:
            await asyncio.wait_for(ready_future, timeout=BRIDGE_STARTUP_TIMEOUT)
        except asyncio.TimeoutError:
            logger.error("Bridge process did not signal ready in time")
            raise RuntimeError("pptx-svg bridge startup timeout")

    async def _read_loop(self) -> None:
        assert self._proc and self._proc.stdout
        try:
            while True:
                line = await self._proc.stdout.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg_id = msg.get("id")
                # null id from ready signal → use 0
                key = msg_id if msg_id is not None else 0
                future = self._pending.pop(key, None)
                if future and not future.done():
                    if "error" in msg:
                        future.set_exception(RuntimeError(msg["error"]))
                    else:
                        future.set_result(msg.get("result"))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Bridge reader error: {e}")

    async def _call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        async with self._lock:
            await self._ensure_started()
        assert self._proc and self._proc.stdin

        self._counter += 1
        req_id = self._counter
        req = json.dumps({"id": req_id, "method": method, "params": params or {}})

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future
        self._proc.stdin.write((req + "\n").encode())
        await self._proc.stdin.drain()

        try:
            return await asyncio.wait_for(future, timeout=BRIDGE_CALL_TIMEOUT)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise RuntimeError(f"Bridge call '{method}' timed out")

    async def load_pptx(self, session_id: str, pptx_bytes: bytes) -> dict:
        b64 = base64.b64encode(pptx_bytes).decode()
        return await self._call("load_pptx", {"session_id": session_id, "base64": b64})

    async def get_slide_info(self, session_id: str, slide_idx: int) -> dict:
        return await self._call("get_slide_info", {"session_id": session_id, "slide_idx": slide_idx})

    async def get_all_slides_info(self, session_id: str) -> dict:
        return await self._call("get_all_slides_info", {"session_id": session_id})

    async def update_shape_text(
        self, session_id: str, slide_idx: int, shape_idx: int,
        para_idx: int, run_idx: int, text: str,
    ) -> dict:
        return await self._call("update_shape_text", {
            "session_id": session_id, "slide_idx": slide_idx, "shape_idx": shape_idx,
            "para_idx": para_idx, "run_idx": run_idx, "text": text,
        })

    async def update_shape_fill(
        self, session_id: str, slide_idx: int, shape_idx: int,
        r: int, g: int, b: int,
    ) -> dict:
        return await self._call("update_shape_fill", {
            "session_id": session_id, "slide_idx": slide_idx, "shape_idx": shape_idx,
            "r": r, "g": g, "b": b,
        })

    async def update_shape_transform(
        self, session_id: str, slide_idx: int, shape_idx: int,
        x: int, y: int, cx: int, cy: int, rot: int,
    ) -> dict:
        return await self._call("update_shape_transform", {
            "session_id": session_id, "slide_idx": slide_idx, "shape_idx": shape_idx,
            "x": x, "y": y, "cx": cx, "cy": cy, "rot": rot,
        })

    async def export_pptx(self, session_id: str) -> bytes:
        result = await self._call("export_pptx", {"session_id": session_id})
        return base64.b64decode(result["base64"])

    async def unload(self, session_id: str) -> None:
        await self._call("unload", {"session_id": session_id})

    async def shutdown(self) -> None:
        if self._reader_task:
            self._reader_task.cancel()
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()


# Singleton bridge instance
bridge = PptxEditBridge()
