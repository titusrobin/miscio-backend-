# app/models/student.py
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from bson import ObjectId # unique identifier for MongoDB documents


# Student class is primarily a data model that defines the structure of student data
# No students are initialized in app 
class Student(BaseModel):
    id: str = Field(default_factory=lambda: str(ObjectId()))
    first_name: str
    last_name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    preferred_contact_method: str = "email"  # Default to email
    status: str = "active"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    thread_id: Optional[str] = None
    #TODO: mongodb has thread_id - need? 