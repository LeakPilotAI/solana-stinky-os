"""Minimal FastAPI surface for Feature Engine health and inspection."""

from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from feature_engine.config import settings
from feature_engine.definitions import FEATURE_DEF_VERSION, FEATURE_SET_HASH, FEATURE_DEFINITIONS

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "feature_engine.started",
        service=settings.service_name,
        feature_set=FEATURE_SET_HASH,
    )
    yield
    logger.info("feature_engine.stopped")


app = FastAPI(
    title="Stinky OS – Feature Engine",
    version="0.1.0",
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "service": settings.service_name,
        "feature_def_version": FEATURE_DEF_VERSION,
        "feature_set_hash": FEATURE_SET_HASH,
    }


@app.get("/v1/features/definitions")
async def list_definitions() -> dict:
    return {
        "feature_def_version": FEATURE_DEF_VERSION,
        "feature_set_hash": FEATURE_SET_HASH,
        "features": [
            {
                "name": fd.name,
                "description": fd.description,
                "dtype": fd.dtype,
                "version": fd.version,
            }
            for fd in FEATURE_DEFINITIONS
        ],
    }
