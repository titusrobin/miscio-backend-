# app/core/security.py
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt  # create and decode JWT tokens
from passlib.context import CryptContext  # hash passwords
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer  # OAuth2 password flow
from app.core.config import settings
from app.db.mongodb import db
from app.models.admin import Admin

# Password hashing configuration
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2 configuration for token handling
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Creates a JWT token for authentication.
    The token contains encoded user information and an expiration time.
    """
    to_encode = data.copy()
    # Set token expiration
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )

    to_encode.update({"exp": expire})
    # Create JWT token using our secret key
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm="HS256")
    return encoded_jwt


async def get_current_admin_user(token: str = Depends(oauth2_scheme)) -> Admin:
    """
    Validates the JWT token and returns the current admin user.
    This function transforms MongoDB's _id to our expected id format.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        # Decode and validate the token
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception

        # Get user from database
        admin = await db.db.admin_users.find_one({"username": username})
        if admin is None:
            raise credentials_exception

        # Transform MongoDB _id to id for our model
        admin_dict = {
            "id": str(admin["_id"]),  # Convert ObjectId to string
            "username": admin["username"],
            "email": admin["email"],
            "is_active": admin.get("is_active", True),
            "created_at": admin["created_at"],
            "assistant_id": admin.get("assistant_id"),
            "thread_id": admin.get("thread_id"),
        }

        return Admin(**admin_dict)
    except JWTError:
        raise credentials_exception


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Creates a hash from a password."""
    return pwd_context.hash(password)
