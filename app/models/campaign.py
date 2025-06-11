# app/models/campaign.py
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from bson import ObjectId #Mongodb's object ID 
from enum import Enum 

class CampaignType(str, Enum):
    MESSAGING = "messaging"
    FEEDBACK = "feedback"

class CampaignStatus(str, Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    EXECUTING = "executing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class ApprovalAction(BaseModel):
    action: str  # "created_draft", "approved", "modified", "cancelled"
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    admin_id: str
    notes: Optional[str] = None

class DraftContent(BaseModel):
    message: str
    subject: Optional[str] = None
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    generation_context: Optional[Dict[str, Any]] = None  # Store original request context

class ApprovedContent(BaseModel):
    message: str
    subject: Optional[str] = None
    approved_at: datetime = Field(default_factory=datetime.utcnow)
    approved_by: str
    modifications_from_draft: Optional[str] = None  # Track what was changed

class FeedbackQuestion(BaseModel):
    id: str = Field(default_factory=lambda: str(ObjectId()))
    text: str
    order: int
    question_type: str = "open_ended"  # open_ended, rating, multiple_choice
    options: Optional[List[str]] = None  # For multiple choice questions
    required: bool = True

class Campaign(BaseModel):
    id: str = Field(default_factory=lambda: str(ObjectId()))
    
    # Enhanced campaign classification
    type: CampaignType = CampaignType.MESSAGING
    status: CampaignStatus = CampaignStatus.DRAFT
    
    # Backward compatibility - keep existing description field
    description: str
    
    # New content management
    draft_content: Optional[DraftContent] = None
    approved_content: Optional[ApprovedContent] = None
    
    # For FEEDBACK campaigns (future use)
    questions: List[FeedbackQuestion] = []
    
    # Enhanced metadata
    assistant_id: Optional[str] = None
    thread_id: Optional[str] = None
    admin_id: str
    
    # Execution tracking
    created_at: datetime = Field(default_factory=datetime.utcnow)
    executed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Approval workflow
    approval_history: List[ApprovalAction] = []
    
    # Execution metrics (enhanced)
    execution_summary: Optional[Dict[str, Any]] = None
    
    # Backward compatibility
    # Keep the old status field as a property for existing code
    @property
    def legacy_status(self) -> str:
        """Maps new status enum to old string format for backward compatibility"""
        if self.status in [CampaignStatus.COMPLETED]:
            return "active"  # Old system considered completed campaigns as "active"
        return "inactive"

    class Config:
        json_encoders = {ObjectId: str}
        use_enum_values = True  # Store enum values as strings in DB