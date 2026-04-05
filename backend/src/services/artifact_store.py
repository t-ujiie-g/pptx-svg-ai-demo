"""In-memory artifact store for generated files (PPTX, etc.)."""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from src.constants import ARTIFACT_TTL, PPTX_MIME_TYPE

logger = logging.getLogger(__name__)


@dataclass
class Artifact:
    """A stored file artifact."""

    id: str
    thread_id: str
    filename: str
    mime_type: str
    data: bytes
    created_at: datetime = field(default_factory=datetime.now)


# Global in-memory store: artifact_id -> Artifact
_artifacts: dict[str, Artifact] = {}


def store_artifact(
    thread_id: str,
    filename: str,
    data: bytes,
    mime_type: str = PPTX_MIME_TYPE,
) -> str:
    """Store a file artifact and return its ID."""
    _cleanup_expired()
    artifact_id = str(uuid.uuid4())
    _artifacts[artifact_id] = Artifact(
        id=artifact_id,
        thread_id=thread_id,
        filename=filename,
        mime_type=mime_type,
        data=data,
    )
    logger.info(f"Stored artifact {artifact_id}: {filename} ({len(data)} bytes)")
    return artifact_id


def get_artifact(artifact_id: str) -> Artifact | None:
    """Retrieve an artifact by ID."""
    _cleanup_expired()
    return _artifacts.get(artifact_id)


def update_artifact(artifact_id: str, data: bytes, filename: str | None = None) -> bool:
    """Update an existing artifact's data (and optionally filename).

    Returns True if the artifact was found and updated, False otherwise.
    """
    artifact = _artifacts.get(artifact_id)
    if artifact is None:
        return False
    artifact.data = data
    if filename:
        artifact.filename = filename
    artifact.created_at = datetime.now()  # refresh TTL
    logger.info(f"Updated artifact {artifact_id}: {artifact.filename} ({len(data)} bytes)")
    return True


def _cleanup_expired() -> None:
    """Remove expired artifacts."""
    now = datetime.now()
    expired = [
        aid for aid, a in _artifacts.items() if now - a.created_at > ARTIFACT_TTL
    ]
    for aid in expired:
        del _artifacts[aid]
