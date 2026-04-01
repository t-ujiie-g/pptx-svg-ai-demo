"""In-memory artifact store for generated files (PPTX, etc.)."""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Artifacts expire after 1 hour
_ARTIFACT_TTL = timedelta(hours=1)


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
    mime_type: str = "application/vnd.openxmlformats-officedocument.presentationml.presentation",
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


def _cleanup_expired() -> None:
    """Remove expired artifacts."""
    now = datetime.now()
    expired = [
        aid for aid, a in _artifacts.items() if now - a.created_at > _ARTIFACT_TTL
    ]
    for aid in expired:
        del _artifacts[aid]
