# app/models/student.py
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from bson import ObjectId


# app/models/student.py
class Student(BaseModel):
    id: str = Field(default_factory=lambda: str(ObjectId()))
    first_name: str
    last_name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    preferred_contact_method: str = "whatsapp"  # Default to WhatsApp
    status: str = "active"
    created_at: datetime = Field(default_factory=datetime.utcnow)
