from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from bson import ObjectId


class FeedbackDraftRequest(BaseModel):
    """Schema for requesting a feedback campaign draft"""
    campaign_purpose: str
    research_topic: str
    target_audience: str = "all students"
    conversation_style: str = "casual and friendly"
    admin_provided_questions: Optional[List[str]] = []
    thread_id: Optional[str] = None

class GeneratedQuestion(BaseModel):
    """Schema for a generated research question"""
    id: str = Field(default_factory=lambda: str(ObjectId()))
    text: str
    question_type: str = "open_ended"  # open_ended, rating, multiple_choice
    follow_up_prompt: Optional[str] = None  # "Please explain why" or "Can you give an example?"
    order: int

class FeedbackQuestionSet(BaseModel):
    """Schema for a set of approved feedback questions"""
    questions: List[GeneratedQuestion]
    research_topic: str
    conversation_style: str
    total_questions: int = 0

class FeedbackApprovalRequest(BaseModel):
    """Schema for approving/modifying feedback questions"""
    campaign_id: str
    action: str  # "approve", "modify", "add_questions", "remove_questions", "cancel"
    modified_questions: Optional[List[str]] = None
    additional_questions: Optional[List[str]] = None
    questions_to_remove: Optional[List[int]] = None  # indices of questions to remove
    notes: Optional[str] = None