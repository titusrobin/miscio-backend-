# app/models/chat.py
from datetime import datetime
from pydantic import BaseModel
from typing import List, Optional

class Message(BaseModel):
    role: str
    content: str
    timestamp: datetime

class Thread(BaseModel):
    id: str #TODO openai thread_id? 
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


#Notes
# 1. chat_history is a collection in mongodb that stores the chat history for each thread
# 2. threads is a collection in mongodb that stores the metadata for each thread