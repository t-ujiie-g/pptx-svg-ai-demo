"""Configuration management for the backend."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Google Cloud
    google_cloud_project: str
    google_cloud_location: str = "global"
    genai_model: str = "gemini-3-flash-preview"
    pptx_agent_model: str = "gemini-3.1-pro-preview"

    # Server
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    cors_origins: str = "http://localhost:3000,http://frontend:3000"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
