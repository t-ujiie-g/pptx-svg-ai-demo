"""generate_pptx.py — Run a PptxGenJS script to create a new PPTX artifact.

Usage (via ADK run_skill_script):
    run_skill_script(
        skill_name="pptx",
        script_path="scripts/generate_pptx.py",
        script_args={
            "code": "<PptxGenJS JavaScript source>",
            "output_filename": "deck.pptx",
        },
    )

The JavaScript must:
  - wrap itself in an async IIFE: `(async () => { ... })();`
  - call `await pres.writeFile({ fileName: process.env.PPTX_OUTPUT_PATH })`

The generated PPTX is POSTed to the backend's /artifacts endpoint so it
becomes available for preview/download, matching the flow in edit_pptx.py.

Output (stdout, last line):
    __PPTX_ARTIFACT__ {"artifact_id":"...","filename":"...",
                       "size_bytes":N,"download_url":"/artifacts/..."}
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request

BASE_URL = os.environ.get("ARTIFACT_BASE_URL", "http://localhost:8000")
ARTIFACT_MARKER = "__PPTX_ARTIFACT__"
HTTP_TIMEOUT = 30
NODE_PATH = os.environ.get("NODE_PATH", "/usr/lib/node_modules")
NODE_TIMEOUT = 120


def post_artifact(data: bytes, filename: str) -> dict:
    url = f"{BASE_URL}/artifacts?filename={urllib.parse.quote(filename)}"
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/octet-stream"},
    )
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return json.loads(resp.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", required=True, help="PptxGenJS JavaScript source")
    ap.add_argument("--output-filename", default="presentation.pptx")
    args = ap.parse_args()

    filename = args.output_filename
    if not filename.endswith(".pptx"):
        filename += ".pptx"

    with tempfile.TemporaryDirectory() as tmpdir:
        script_path = os.path.join(tmpdir, "generate.js")
        output_path = os.path.join(tmpdir, filename)

        with open(script_path, "w") as f:
            f.write(args.code)

        try:
            result = subprocess.run(
                ["node", script_path],
                capture_output=True, text=True,
                timeout=NODE_TIMEOUT, cwd=tmpdir,
                env={
                    **os.environ,
                    "PPTX_OUTPUT_PATH": output_path,
                    "NODE_PATH": NODE_PATH,
                },
            )
        except subprocess.TimeoutExpired:
            print(f"ERROR: node timed out after {NODE_TIMEOUT}s", file=sys.stderr)
            sys.exit(3)
        except FileNotFoundError:
            print("ERROR: node is not installed", file=sys.stderr)
            sys.exit(4)

        if result.returncode != 0:
            err = result.stderr or result.stdout or "unknown error"
            print(f"ERROR: PptxGenJS script failed (exit {result.returncode})", file=sys.stderr)
            print(err[:2000], file=sys.stderr)
            sys.exit(result.returncode)

        if not os.path.exists(output_path):
            print(
                "ERROR: no .pptx was generated. Ensure the script calls "
                "pres.writeFile({ fileName: process.env.PPTX_OUTPUT_PATH })",
                file=sys.stderr,
            )
            sys.exit(5)

        with open(output_path, "rb") as f:
            data = f.read()

    info = post_artifact(data, filename)

    # Surface any script stdout (trimmed) so the agent can see logs.
    if result.stdout:
        sys.stderr.write(result.stdout[:500])

    print(f"{ARTIFACT_MARKER} {json.dumps(info)}")


if __name__ == "__main__":
    main()
