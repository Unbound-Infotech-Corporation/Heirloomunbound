"""FastAPI entrypoint for the Digital Heirloom / AI Twin app."""
import logging
import os

from fastapi import APIRouter, FastAPI
from starlette.middleware.cors import CORSMiddleware

from deps import db  # noqa: F401  -- ensures Mongo client is initialised early
from routers import archive, auth, dashboard, heirs, interviewer, skills, social_import, twin, voice

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Digital Heirloom — AI Twin", version="0.1.0")

api_router = APIRouter(prefix="/api")


@api_router.get("/")
async def root():
    return {"app": "digital-heirloom", "status": "ok"}


api_router.include_router(auth.router)
api_router.include_router(archive.router)
api_router.include_router(interviewer.router)
api_router.include_router(voice.router)
api_router.include_router(twin.router)
api_router.include_router(social_import.router)
api_router.include_router(skills.router)
api_router.include_router(heirs.router)
api_router.include_router(dashboard.router)

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown_db_client():
    from deps import client
    client.close()
