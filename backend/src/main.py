"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.artifacts import router as artifacts_router
from src.api.chat import router as chat_router
from src.api.health import router as health_router
from src.api.prompts import router as prompts_router
from src.config import settings
from src.constants import APP_VERSION

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown."""
    logger.info("Starting PPTX Slide Creator API...")
    yield
    logger.info("Shutting down...")


app = FastAPI(
    title="PPTX Slide Creator API",
    description="AI-powered presentation creation system",
    version=APP_VERSION,
    lifespan=lifespan,
)

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health_router)
app.include_router(chat_router)
app.include_router(prompts_router)
app.include_router(artifacts_router)


@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "PPTX Slide Creator API", "version": APP_VERSION}
