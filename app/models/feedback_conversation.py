# app/models/feedback_conversation.py
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any
from datetime import datetime
from bson import ObjectId
from enum import Enum

class EngagementLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium" 
    LOW = "low"

class DeliveryStrategy(str, Enum):
    BATCH = "batch"  # Send 2-3 questions together
    WEAVE = "weave"  # One question at a time, natural transitions
    FOLLOW_UP = "follow_up"  # Following up on previous response
    WRAP_UP = "wrap_up"  # Concluding conversation

class ConversationStatus(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PAUSED = "paused"

class QuestionProgress(BaseModel):
    question_id: str
    question_text: str
    order: int
    status: str = "not_asked"  # not_asked, asked, partially_answered, fully_answered
    student_response: Optional[str] = None
    follow_up_needed: bool = False
    asked_at: Optional[datetime] = None
    answered_at: Optional[datetime] = None

class ResponseAnalysis(BaseModel):
    questions_addressed: List[str]  # Question IDs that were answered
    engagement_indicators: Dict[str, Any]  # Response length, enthusiasm, etc.
    partial_answers: Dict[str, str]  # Question ID -> partial response text
    suggested_follow_ups: List[str]  # Suggested follow-up questions
    next_strategy: DeliveryStrategy

class FeedbackConversationState(BaseModel):
    id: str = Field(default_factory=lambda: str(ObjectId()))
    student_id: str
    campaign_id: str
    
    # Question tracking
    questions: List[QuestionProgress] = []
    total_questions: int = 0
    questions_completed: int = 0
    
    # Conversation management
    status: ConversationStatus = ConversationStatus.NOT_STARTED
    current_strategy: DeliveryStrategy = DeliveryStrategy.WEAVE
    engagement_level: EngagementLevel = EngagementLevel.MEDIUM
    
    # Context and history
    conversation_context: str = ""
    last_response_analysis: Optional[ResponseAnalysis] = None
    priority_questions: List[str] = []  # Question IDs to focus on next
    
    # Metadata
    started_at: Optional[datetime] = None
    last_interaction: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Adaptive behavior
    student_response_pattern: Dict[str, Any] = {}  # Track response style for adaptation
    
    class Config:
        json_encoders = {ObjectId: str}
