# app/models/campaign.py
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from bson import ObjectId  # unique identifier for MongoDB documents


class Campaign(BaseModel):
    id: str = Field(default_factory=lambda: str(ObjectId()))
    description: str
    assistant_id: str
    thread_id: str
    status: str = "active"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    admin_id: str  # TODO - need? This does not exist in db schema for campaigns

    class Config:
        json_encoders = {ObjectId: str}
