# app/models/admin.py
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime
import logging
from fastapi import APIRouter

router = APIRouter()
logger = logging.getLogger(__name__)

# model is a blueprint or template that defines the structure of data.
# What BaseModel provides: Data validation, conversion, 
# and error handling. Checks if the information is correct.
class AdminBase(BaseModel):
    username: str
    email: EmailStr #Pydantic that validates email addresses
    is_active: bool = True #TODO: checks at login endpoint for soft delete 


class AdminCreate(AdminBase):  # Sep of concerns for registration 
    password: str


class Admin(AdminBase):
    id: str
    created_at: datetime
    assistant_id: Optional[str] = None #TODO: should not be None 
    thread_id: Optional[str] = None

    class Config:
        from_attributes = True # tell Pydantic to read data from dict or object(enabled by this setting)

    def __init__(self, **data):
        super().__init__(**data) # Construct AdminBase with data dict 
        #logger.info(f"Admin model initialized with data: {data}")
