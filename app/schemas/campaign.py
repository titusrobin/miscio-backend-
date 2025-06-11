# app/schemas/campaign.py
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from app.models.campaign import CampaignType, CampaignStatus, FeedbackQuestion

class CampaignBase(BaseModel):
    description: str
    type: CampaignType = CampaignType.MESSAGING
    focus_areas: Optional[List[str]] = []
    settings: Optional[Dict[str, Any]] = {}
    target_completion_date: Optional[datetime] = None

class CampaignCreate(CampaignBase):
    thread_id: Optional[str] = None
    # For messaging campaigns
    draft_message: Optional[str] = None
    draft_subject: Optional[str] = None
    # For feedback campaigns  
    questions: Optional[List[str]] = None  # Simple string questions that will be converted to FeedbackQuestion objects

class CampaignDraftRequest(BaseModel):
    """Schema for requesting a campaign draft"""
    campaign_purpose: str
    campaign_details: str
    target_audience: str = "all students"
    tone_and_style: str = "friendly and helpful"
    key_points: str
    call_to_action: str = "respond with any questions"
    thread_id: Optional[str] = None

class CampaignApprovalRequest(BaseModel):
    """Schema for approving/modifying a campaign"""
    campaign_id: str
    action: str  # "approve", "modify", "cancel"
    modified_message: Optional[str] = None
    modified_subject: Optional[str] = None
    notes: Optional[str] = None

class CampaignUpdate(CampaignBase):
    status: Optional[CampaignStatus] = None
    thread_id: Optional[str] = None

class CampaignResponse(BaseModel):
    id: str
    type: CampaignType
    status: CampaignStatus
    description: str
    
    # Content fields
    draft_content: Optional[Dict[str, Any]] = None
    approved_content: Optional[Dict[str, Any]] = None
    
    # Metadata
    assistant_id: Optional[str] = None
    thread_id: Optional[str] = None
    admin_id: str
    
    # Timestamps
    created_at: datetime
    executed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Execution data
    execution_summary: Optional[Dict[str, Any]] = None
    approval_history: List[Dict[str, Any]] = []
    
    # For feedback campaigns
    questions: List[Dict[str, Any]] = []

    class Config:
        from_attributes = True

class CampaignListResponse(BaseModel):
    """Response for listing campaigns with essential info"""
    id: str
    type: CampaignType
    status: CampaignStatus
    description: str
    created_at: datetime
    admin_id: str
    
    # Quick preview of content
    preview_message: Optional[str] = None  # First 100 chars of draft/approved message
    total_questions: Optional[int] = None  # For feedback campaigns
    
    class Config:
        from_attributes = True