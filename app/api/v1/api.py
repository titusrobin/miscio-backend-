from fastapi import APIRouter
from app.api.v1.endpoints import auth, chat, webhook, rag, campaign

router = APIRouter()
router.include_router(auth.router, prefix="/auth", tags=["auth"])
router.include_router(chat.router, prefix="/chat", tags=["chat"])
router.include_router(webhook.router, prefix="/webhook", tags=["webhook"])
router.include_router(campaign.router, prefix="/campaign", tags=["campaign"])
router.include_router(rag.router, prefix="/rag", tags=["rag"])
