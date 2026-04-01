"""Health check endpoint."""

from fastapi import APIRouter

from src.constants import APP_NAME, APP_VERSION

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """Health check endpoint for container orchestration."""
    return {
        "status": "healthy",
        "service": APP_NAME,
        "version": APP_VERSION,
    }
