# app/main.py
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.db.mongodb import db
from app.api.v1.api import router as api_router
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.chat import router as chat_router  # Import the chat router

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description=settings.DESCRIPTION,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Events and resource management
@app.on_event("startup")
async def startup_event():
    logger.info("Starting up the application")
    await db.connect_to_database()


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down the application")
    await db.close_database_connection()


@app.get("/health")
async def health_check():
    logger.info("Health check endpoint hit")
    return {"status": "healthy"}


# Routes and endpoint organization
app.include_router(api_router, prefix=settings.API_V1_STR)
app.include_router(
    auth_router, prefix=f"{settings.API_V1_STR}/auth", tags=["authentication"]
)
app.include_router(
    chat_router, prefix=f"{settings.API_V1_STR}/chat", tags=["chat"]
)  # Include the chat router
