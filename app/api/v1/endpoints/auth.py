# app/api/v1/endpoints/auth.py
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from datetime import datetime, timedelta
from app.core.security import (
    create_access_token,
    get_password_hash,
    verify_password,
    get_current_admin_user,
)
from app.models.admin import Admin, AdminCreate
from app.core.config import settings
from app.db.mongodb import db
from app.services.openai_service import OpenAIService
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


def get_openai_service():
    return OpenAIService()


@router.post("/login")
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    openai_service: OpenAIService = Depends(get_openai_service),
):
    logger.info("Login endpoint hit")

    # Find user in database
    admin = await db.db.admin_users.find_one({"username": form_data.username})
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verify password
    if not verify_password(form_data.password, admin["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check if admin has an assistant, create one if they don't
    if not admin.get("assistant_id") or not admin.get("thread_id"):
        try:
            logger.info(f"Creating new assistant for admin {admin['_id']}")
            assistant_data = await openai_service.create_admin_assistant(
                str(admin["_id"])
            )

            # Update admin with assistant info
            await db.db.admin_users.update_one(
                {"_id": admin["_id"]},
                {
                    "$set": {
                        "assistant_id": assistant_data["assistant_id"],
                        "thread_id": assistant_data["thread_id"],
                    }
                },
            )
            admin["assistant_id"] = assistant_data["assistant_id"]
            admin["thread_id"] = assistant_data["thread_id"]
            logger.info(f"Assistant created for admin {admin['_id']}")

        except Exception as e:
            logger.error(f"Error creating assistant: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error setting up admin assistant",
            )

    logger.info(
        f"Admin assistant_id: {admin['assistant_id']}, thread_id: {admin['thread_id']}"
    )
    # Create access token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={
            "sub": admin["username"],
            "assistant_id": admin["assistant_id"],
            "thread_id": admin["thread_id"],
        },
        expires_delta=access_token_expires,
    )
    logger.info(f"Access token created for admin {admin['username']}")

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "assistant_id": admin["assistant_id"],
        "thread_id": admin["thread_id"],
    }


@router.post("/register", response_model=Admin)
async def register_admin(admin: AdminCreate):
    """
    Creates a new admin user account.
    This endpoint should be protected in production.
    """
    # Check if username already exists
    existing_admin = await db.db.admin_users.find_one({"username": admin.username})
    if existing_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered",
        )

    # Create new admin user
    hashed_password = get_password_hash(admin.password)
    admin_dict = {
        "username": admin.username,
        "email": admin.email,
        "hashed_password": hashed_password,
        "is_active": True,
        "created_at": datetime.utcnow(),
    }

    result = await db.db.admin_users.insert_one(admin_dict)
    admin_dict["id"] = str(result.inserted_id)

    return admin_dict


@router.get("/me", response_model=Admin)
async def read_users_me(current_admin: Admin = Depends(get_current_admin_user)):
    """
    Returns information about the currently logged-in admin user.
    This endpoint is protected and requires a valid JWT token.
    """
    return current_admin


@router.get("/protected-endpoint")
async def protected_endpoint(current_admin: Admin = Depends(get_current_admin_user)):
    # Only authenticated admins can access this endpoint
    return {"message": "You have access to this protected resource"}
