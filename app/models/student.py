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
    phone: str
    created_at: datetime = Field(
        default_factory=datetime.utcnow
    )  # TODO - need? Does not exist
