"""Configuration management for the backend."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Gemini backend selection
    # - Vertex AI: set google_genai_use_vertexai=True and google_cloud_project
    # - Gemini API: set google_genai_use_vertexai=False and google_api_key
    google_genai_use_vertexai: bool = False
    google_api_key: str | None = None
    google_cloud_project: str | None = None
    google_cloud_location: str = "global"

    # ──────────────────────────────────────────────────────────────────
    # Model tiers
    # ──────────────────────────────────────────────────────────────────
    # Three Gemini tiers. Override per-environment to swap model versions
    # without touching agent code. Each agent points at one of these tiers
    # (or a direct override) below.
    model_tier_high: str = "gemini-3.1-pro-preview"
    model_tier_mid: str = "gemini-3-flash-preview"
    model_tier_lite: str = "gemini-3.1-flash-lite-preview"

    # ──────────────────────────────────────────────────────────────────
    # Per-agent model assignment
    # ──────────────────────────────────────────────────────────────────
    # Each agent_*_model can be:
    #   - "tier:high" / "tier:mid" / "tier:lite"  → resolves to the tier above
    #   - any concrete model id (e.g. "gemini-3.1-pro-preview")
    # Use resolve_model() to get the final model id.
    agent_root_model: str = "tier:mid"
    agent_pptx_model: str = "tier:high"
    # Reserved for upcoming phases; safe to leave defaulted.
    agent_style_model: str = "tier:lite"          # Phase 2: style extraction
    agent_critic_model: str = "tier:mid"        # Phase 4: critic
    agent_preservation_model: str = "tier:lite"  # Phase 3: entity extraction

    # ──────────────────────────────────────────────────────────────────
    # Backwards-compat shims (do not remove without migrating callers)
    # ──────────────────────────────────────────────────────────────────
    # Existing code reads `settings.genai_model` and `settings.pptx_agent_model`
    # directly. Those properties below resolve to the tiered config so old
    # call sites keep working while new code uses resolve_model() explicitly.
    @property
    def genai_model(self) -> str:
        return self.resolve_model(self.agent_root_model)

    @property
    def pptx_agent_model(self) -> str:
        return self.resolve_model(self.agent_pptx_model)

    def resolve_model(self, ref: str) -> str:
        """Resolve a model reference like "tier:high" to a concrete model id."""
        if ref.startswith("tier:"):
            tier = ref.split(":", 1)[1]
            mapping = {
                "high": self.model_tier_high,
                "mid": self.model_tier_mid,
                "lite": self.model_tier_lite,
            }
            if tier not in mapping:
                raise ValueError(f"Unknown model tier: {tier!r} (in {ref!r})")
            return mapping[tier]
        return ref

    # ──────────────────────────────────────────────────────────────────
    # Pipeline feature flags (Phase 2-4.5)
    # ──────────────────────────────────────────────────────────────────
    # Toggle each post-pipeline stage independently. Disabling cuts LLM
    # calls per request — useful when running near a quota limit (429).
    #
    # Cost per request (approximate, when all enabled):
    #   style:        +1 LLM call (Layer A+B extraction)
    #   preservation: +1 LLM call pre + 1 post (entity extraction)
    #   critic:       +1 LLM call post
    #   critic retry: +1 agent run + 1 entity + 1 critic + 1 pairwise
    feature_style_extraction: bool = True
    feature_preservation_check: bool = True
    feature_critic_review: bool = True
    feature_critic_retry: bool = True       # only effective if critic enabled

    # Server
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    cors_origins: str = "http://localhost:3000,http://frontend:3000"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
