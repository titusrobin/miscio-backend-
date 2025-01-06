# app/models/admin.py
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime
import logging
from fastapi import APIRouter

router = APIRouter()
logger = logging.getLogger(__name__)


class AdminBase(BaseModel):
    username: str
    email: EmailStr
    is_active: bool = True


class AdminCreate(AdminBase):  # adding password field
    password: str


class Admin(AdminBase):
    id: str
    created_at: datetime
    assistant_id: Optional[str] = None
    thread_id: Optional[str] = None

    class Config:
        from_attributes = True

    def __init__(self, **data):
        super().__init__(**data)
        logger.info(f"Admin model initialized with data: {data}")
        logger.info(
            f"Admin ID: {self.id}, Assistant ID: {self.assistant_id}, Thread ID: {self.thread_id}"
        )
