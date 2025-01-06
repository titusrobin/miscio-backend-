from fastapi import APIRouter
from app.api.v1.endpoints import auth, chat

router = APIRouter()
router.include_router(auth.router, prefix="/auth", tags=["auth"])
router.include_router(chat.router, prefix="/chat", tags=["chat"])
