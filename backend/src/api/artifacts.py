"""Artifacts API - Download and update generated files (PPTX, etc.)."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from src.services.artifact_store import get_artifact, update_artifact

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
