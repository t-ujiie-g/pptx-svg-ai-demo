"""Application constants.

All magic numbers, limits, timeouts, and MIME types live here so they can
be adjusted in one place. Keep this file flat — no nested config objects.
"""

from datetime import timedelta

# ──────────────────────────────────────────────────────────────────────
# Application metadata
# ──────────────────────────────────────────────────────────────────────
APP_NAME = "pptx-slide-creator"
APP_VERSION = "0.1.0"

# ──────────────────────────────────────────────────────────────────────
# Identifiers
# ──────────────────────────────────────────────────────────────────────
DEFAULT_USER_ID = "anonymous"
DEFAULT_THREAD_ID = "default"

# ──────────────────────────────────────────────────────────────────────
# File size limits (bytes)
# ──────────────────────────────────────────────────────────────────────
MAX_UPLOAD_SIZE = 20 * 1024 * 1024          # 20 MB — chat attachments
MAX_READ_FILE_SIZE = 1 * 1024 * 1024        # 1 MB — agent-read files

# ──────────────────────────────────────────────────────────────────────
# Timeouts (seconds)
# ──────────────────────────────────────────────────────────────────────
SKILL_SCRIPT_TIMEOUT = 600                  # skill code executor
PPTX_INSPECT_TIMEOUT = 120                  # pptx_inspect.js subprocess

# ──────────────────────────────────────────────────────────────────────
# Artifact store
# ──────────────────────────────────────────────────────────────────────
ARTIFACT_TTL = timedelta(hours=1)
DEFAULT_ARTIFACT_FILENAME = "presentation.pptx"
SKILL_ARTIFACT_THREAD_ID = "skill"          # thread_id for artifacts posted by skills

# ──────────────────────────────────────────────────────────────────────
# PPTX artifact marker
# ──────────────────────────────────────────────────────────────────────
# Marker line printed by skill scripts (edit_pptx.py, generate_pptx.py) on
# stdout so chat.py can surface the new artifact via SSE.
PPTX_ARTIFACT_MARKER = "__PPTX_ARTIFACT__"

# ──────────────────────────────────────────────────────────────────────
# File bridge
# ──────────────────────────────────────────────────────────────────────
FILE_ID_LENGTH = 8                          # truncated UUID length
TEXT_MIME_TYPES = frozenset({
    "text/plain",
    "text/html",
    "text/csv",
    "application/json",
    "application/xml",
})

# ──────────────────────────────────────────────────────────────────────
# MIME types
# ──────────────────────────────────────────────────────────────────────
PPTX_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)
ALLOWED_UPLOAD_MIME_TYPES = frozenset({
    # Images
    "image/png", "image/jpeg", "image/webp", "image/heic", "image/heif",
    # Documents
    "application/pdf",
    PPTX_MIME_TYPE,
    # Text
    "text/plain", "text/html", "text/csv",
    # Audio
    "audio/wav", "audio/mp3", "audio/mpeg", "audio/ogg", "audio/webm",
    # Video
    "video/mp4", "video/webm", "video/mpeg",
})
