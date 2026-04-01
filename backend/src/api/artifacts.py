"""Artifacts API - Download generated files (PPTX, etc.)."""

from fastapi import APIRouter
from fastapi.responses import Response

from src.services.artifact_store import get_artifact

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
