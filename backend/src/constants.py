"""Application constants.

All magic numbers, limits, timeouts, and MIME types live here so they can
be adjusted in one place. Keep this file flat — no nested config objects.
"""

from datetime import timedelta
from typing import Literal

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

# ──────────────────────────────────────────────────────────────────────
# PPTX context roles (Phase 1+: target / style_ref)
# ──────────────────────────────────────────────────────────────────────
# Used to label a PPTX artifact's purpose in the user message context block
# and in StyleSpec extraction. Anything that adds a new role must update both
# the Literal type and any role-aware rendering (chat._build_pptx_context_parts,
# style_schema.StyleSpec.to_compact_block).
PPTX_ROLE_TARGET = "target"
PPTX_ROLE_STYLE_REF = "style_ref"
PptxContextRole = Literal["target", "style_ref"]

# ──────────────────────────────────────────────────────────────────────
# Style extraction (Phase 2)
# ──────────────────────────────────────────────────────────────────────
# Truncation/cap constants for the StyleSpec extraction prompt and
# rendering. Tuned empirically — bumping these increases LLM cost.
STYLE_EXTRACT_TEXT_RUNS_PER_SHAPE = 6           # text runs sent per shape
STYLE_EXTRACT_RAW_TEXT_PREVIEW_CHARS = 500       # error log truncation for LLM raw text

# Default filename used when a styleRefFile upload lacks one.
STYLE_REF_DEFAULT_FILENAME = "style_ref.pptx"

# ──────────────────────────────────────────────────────────────────────
# Preservation check (Phase 3)
# ──────────────────────────────────────────────────────────────────────
# Per-intent thresholds for the entity preservation ratio. tweak/from-scratch
# are not checked (no target to preserve, or scope is too narrow). polish must
# preserve nearly everything; restructure permits more rewriting.
PRESERVATION_THRESHOLD_POLISH = 0.90
PRESERVATION_THRESHOLD_RESTRUCTURE = 0.70

# Number of text runs sent per shape when extracting entities. Higher captures
# more entities but lengthens the LLM input. Mirrors STYLE_EXTRACT_*.
ENTITY_EXTRACT_TEXT_RUNS_PER_SHAPE = 8

# Cap on the entity count we list in the user-facing context block — beyond
# this we truncate to keep the prompt tight (the full set still drives scoring).
ENTITY_BLOCK_MAX_ITEMS = 40

# ──────────────────────────────────────────────────────────────────────
# Critic (Phase 4)
# ──────────────────────────────────────────────────────────────────────
# Per-intent weights for the 5 critic axes. Each row sums to 1.0 — the LLM
# returns raw scores in [0,1], the service computes the weighted total.
# `tweak` weights preservation+intent_fit heavily (don't break the user's
# explicit ask). `from-scratch` weights design highest because there's no
# target to preserve. Keys must match CriticScores fields.
CRITIC_AXES = (
    "intent_fit", "design", "consistency", "info_density", "preservation",
)
CRITIC_WEIGHTS_BY_INTENT: dict[str, dict[str, float]] = {
    "tweak": {
        "intent_fit": 0.50, "design": 0.10, "consistency": 0.10,
        "info_density": 0.10, "preservation": 0.20,
    },
    "polish": {
        "intent_fit": 0.20, "design": 0.25, "consistency": 0.20,
        "info_density": 0.00, "preservation": 0.35,
    },
    "restructure": {
        "intent_fit": 0.20, "design": 0.35, "consistency": 0.25,
        "info_density": 0.00, "preservation": 0.20,
    },
    "from-scratch": {
        "intent_fit": 0.15, "design": 0.40, "consistency": 0.25,
        "info_density": 0.20, "preservation": 0.00,
    },
}

# Verdict thresholds applied to the weighted score (LLM-suggested verdict is
# also accepted but these clamp obvious miscategorizations).
CRITIC_ACCEPT_WEIGHTED = 0.70
CRITIC_REJECT_WEIGHTED = 0.40

# Cap on issues kept per critic call — beyond this the prompt becomes noisy
# and the agent has no chance of fixing them all in one retry.
CRITIC_ISSUES_MAX = 12

# ──────────────────────────────────────────────────────────────────────
# Critic retry & pairwise comparison (Phase 4.5)
# ──────────────────────────────────────────────────────────────────────
# Max additional generations triggered by `verdict=retry`. Set to 0 to
# disable the retry loop entirely (useful for cost-sensitive deployments).
# 1 is the recommended default — a second retry rarely improves things and
# doubles the cost again.
CRITIC_MAX_RETRIES = 1

# Pairwise comparison: how much v1 must exceed v2 (weighted) to overrule a
# pairwise tie. Small margin keeps ties out of the rollback path. v2 (retry)
# is preferred on ties because it represents the user's improvement intent.
PAIRWISE_TIE_BREAK_MARGIN = 0.03

# ──────────────────────────────────────────────────────────────────────
# Direct genai SDK retry (Phase 4.6 — quota mitigation)
# ──────────────────────────────────────────────────────────────────────
# Up to N retry attempts on 429 (RESOURCE_EXHAUSTED) / 5xx upstream errors.
# Backoff doubles each attempt, capped at MAX_DELAY, with jitter to avoid
# thundering herd when multiple concurrent calls retry the same quota.
#
# 1 request burst can issue ~10 LLM calls (style + entity + agent + critic +
# pairwise + retry path). Vertex AI quotas often clamp at 5-60 RPM per project
# per region, so retries are necessary in normal use.
GENAI_RETRY_MAX_ATTEMPTS = 5
GENAI_RETRY_BASE_DELAY_SECONDS = 2.0
GENAI_RETRY_MAX_DELAY_SECONDS = 30.0
GENAI_RETRY_JITTER_SECONDS = 1.5
