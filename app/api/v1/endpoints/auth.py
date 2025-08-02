# app/api/v1/endpoints/auth.py
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from datetime import datetime, timedelta
from app.core import security
from app.models.admin import Admin, AdminCreate
from app.core.config import settings
from app.db.mongodb import db
from app.services.openai_service import OpenAIService
import logging

logger = logging.getLogger(__name__)
# All authentication-related endpoints (login, register, me) are grouped together
# and attach endpoint handlers to it e.g. @router.post("/login")
router = APIRouter() 

def get_openai_service():
    return OpenAIService()


@router.post("/login") # When user client sends a login post request with form data 
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(), # extracts and validates username and password from form data
    openai_service: OpenAIService = Depends(get_openai_service), # for new admins if they don't already have assistant
):
    # logger.info("Login endpoint entered")

    admin = await authenticate_admin(form_data.username, form_data.password)
    
    admin = await ensure_admin_has_assistant(admin, openai_service) #TODO: keep at registartion? what if admin refresh assistant 

    return await create_admin_token_response(admin) # Create and return token response


@router.post("/register", response_model=Admin) # Ensures the return data matches the Admin model structure
async def register_admin(admin: AdminCreate): # Pydantic type: Inherits from AdminBase (getting username and email fields)
    """
    Creates a new admin user account.
    This endpoint should be protected in production.
    """
    existing_admin = await db.db.admin_users.find_one({"username": admin.username})
    if existing_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered",
        )

    hashed_password = security.get_password_hash(admin.password)
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
async def read_users_me(current_admin: Admin = Depends(security.get_current_admin_user)):
    """
    Returns information about the currently logged-in admin user.
    This endpoint is protected and requires a valid JWT token.
    """
    return current_admin


#TODO: need? 
@router.get("/protected-endpoint") # health check to verify authentication is working
async def protected_endpoint(current_admin: Admin = Depends(security.get_current_admin_user)):
    # Only authenticated admins can access this endpoint
    return {"message": "You have access to this protected resource"}




#=====================================================================
#================================Utils================================
async def authenticate_admin(username: str, password: str):
    """
    Authenticates an admin user by username and password.
    Returns the admin document if authentication succeeds.
    Raises HTTPException if authentication fails.
    """
    admin = await db.db.admin_users.find_one({"username": username})
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not security.verify_password(password, admin["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return admin

async def ensure_admin_has_assistant(admin: dict, openai_service: OpenAIService) -> dict:
    """
    Ensures an admin has an OpenAI assistant and thread.
    Creates them if they don't exist and updates the admin record.
    """
    if not admin.get("assistant_id") or not admin.get("thread_id"):
        try:
           # logger.info(f"Creating new assistant for admin {admin['_id']}")
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
           # logger.info(f"Assistant created for admin {admin['_id']}")

        except Exception as e:
            logger.error(f"Error creating assistant: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error setting up admin assistant",
            )
    
    #logger.info(
        #f"Admin assistant_id: {admin['assistant_id']}, thread_id: {admin['thread_id']}"
    #)
    
    return admin

async def create_admin_token_response(admin: dict) -> dict:
    """
    Creates an access token for an admin and returns the token response.
    """
    # Create access token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = security.create_access_token(
        data={
            "sub": admin["username"],
            "assistant_id": admin["assistant_id"],
            "thread_id": admin["thread_id"], #TODO: need? 
        },
        expires_delta=access_token_expires,
    )
    #logger.info(f"Access token created for admin {admin['username']}")

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "assistant_id": admin["assistant_id"],
        "thread_id": admin["thread_id"],
    }
