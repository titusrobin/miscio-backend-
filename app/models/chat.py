# app/models/chat.py
from datetime import datetime
from pydantic import BaseModel
from typing import List, Optional

class Message(BaseModel):
    role: str
    content: str
    timestamp: datetime

class Thread(BaseModel):
    id: str
    title: str
    admin_id: str
    assistant_id: str
    created_at: datetime
    last_message: Optional[str]
    last_activity: datetime

class ChatHistory(BaseModel):
    thread_id: str
    admin_id: str
    assistant_id: str
    messages: List[Message]