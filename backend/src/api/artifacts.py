"""Artifacts API - Download, create, and update generated files (PPTX, etc.)."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from src.constants import DEFAULT_ARTIFACT_FILENAME, SKILL_ARTIFACT_THREAD_ID
from src.services.artifact_store import get_artifact, store_artifact, update_artifact

router = APIRouter(tags=["artifacts"])


@router.get("/artifacts/{artifact_id}")
async def download_artifact(artifact_id: str) -> Response:
    """Download a generated artifact file."""
    artifact = get_artifact(artifact_id)
    if not artifact:
        return Response(content="Artifact not found", status_code=404)

    return Response(
        content=artifact.data,
        media_type=artifact.mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{artifact.filename}"',
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


@router.put("/artifacts/{artifact_id}")
async def update_artifact_endpoint(artifact_id: str, request: Request) -> JSONResponse:
    """Update an existing artifact with new data (e.g. edited PPTX from frontend)."""
    data = await request.body()
    if not data:
        return JSONResponse({"error": "Empty body"}, status_code=400)

    if not update_artifact(artifact_id, data):
        return JSONResponse({"error": "Artifact not found"}, status_code=404)

    return JSONResponse({"ok": True, "artifact_id": artifact_id})


@router.post("/artifacts")
async def create_artifact_endpoint(request: Request) -> JSONResponse:
    """Create a new artifact from raw body bytes.

    Query params:
        filename: name of the file (default: DEFAULT_ARTIFACT_FILENAME)
        source_artifact_id: if given, inherit thread_id from the source
        thread_id: explicit thread_id override (default: SKILL_ARTIFACT_THREAD_ID)
    """
    data = await request.body()
    if not data:
        return JSONResponse({"error": "Empty body"}, status_code=400)

    filename = request.query_params.get("filename", DEFAULT_ARTIFACT_FILENAME)
    thread_id = request.query_params.get("thread_id", SKILL_ARTIFACT_THREAD_ID)
    source_id = request.query_params.get("source_artifact_id")
    if source_id:
        source = get_artifact(source_id)
        if source:
            thread_id = source.thread_id

    artifact_id = store_artifact(
        thread_id=thread_id, filename=filename, data=data,
    )
    return JSONResponse({
        "artifact_id": artifact_id,
        "filename": filename,
        "size_bytes": len(data),
        "download_url": f"/artifacts/{artifact_id}",
    })
