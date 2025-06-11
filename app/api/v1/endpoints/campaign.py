# app/api/v1/endpoints/campaign.py - Updated endpoints for new workflow

import logging
import json
from fastapi import APIRouter, HTTPException, Depends, status
from typing import List, Optional
from datetime import datetime
from app.schemas.campaign import (
    CampaignCreate, CampaignResponse, CampaignUpdate, CampaignDraftRequest, 
    CampaignApprovalRequest, CampaignListResponse
)
from app.services.campaign_service import CampaignService
from app.core.security import get_current_admin_user
from app.models.campaign import Campaign, CampaignStatus
from app.services.openai_service import OpenAIService
from app.services.twilio_service import TwilioService
from app.services.sendgrid_service import SendGridService
from app.db.mongodb import db

router = APIRouter()
logger = logging.getLogger(__name__)

def get_campaign_service() -> CampaignService:
    openai_service = OpenAIService()
    twilio_service = TwilioService()
    sendgrid_service = SendGridService()
    return CampaignService(openai_service, twilio_service, sendgrid_service, db.db)

# ===================================================================
# NEW DRAFT-APPROVAL WORKFLOW ENDPOINTS
# ===================================================================

@router.post("/draft", response_model=CampaignResponse)
async def create_campaign_draft(
    draft_request: CampaignDraftRequest,
    campaign_service: CampaignService = Depends(get_campaign_service),
    current_admin=Depends(get_current_admin_user),
):
    """
    Create a draft messaging campaign that requires admin approval.
    This is the new workflow for messaging campaigns.
    """
    logger.info(f"POST /draft - Creating campaign draft: {draft_request.campaign_purpose}")
    
    try:
        result = await campaign_service.create_messaging_draft(
            draft_request=draft_request,
            admin_id=current_admin.id,
            thread_id=draft_request.thread_id
        )
        logger.info(f"Draft campaign created successfully: {result['id']}")
        return result

    except Exception as e:
        logger.error(f"Error creating campaign draft: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create campaign draft: {str(e)}"
        )

@router.post("/approve", response_model=dict)
async def approve_campaign(
    approval_request: CampaignApprovalRequest,
    campaign_service: CampaignService = Depends(get_campaign_service),
    current_admin=Depends(get_current_admin_user),
):
    """
    Approve, modify, or cancel a draft campaign.
    
    Actions:
    - "approve": Execute the campaign as-is
    - "modify": Update the message/subject and keep as draft
    - "cancel": Cancel the campaign
    """
    logger.info(f"POST /approve - Processing approval for campaign: {approval_request.campaign_id}")
    
    try:
        result = await campaign_service.approve_and_execute_campaign(
            approval_request=approval_request,
            admin_id=current_admin.id
        )
        logger.info(f"Campaign approval processed: {result}")
        return result

    except Exception as e:
        logger.error(f"Error processing campaign approval: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process approval: {str(e)}"
        )

@router.get("/pending", response_model=List[CampaignListResponse])
async def get_pending_campaigns(
    campaign_service: CampaignService = Depends(get_campaign_service),
    current_admin=Depends(get_current_admin_user),
):
    """
    Get all campaigns waiting for admin approval.
    """
    logger.info("GET /pending - Retrieving pending campaigns")
    
    try:
        campaigns = await campaign_service.get_pending_campaigns(admin_id=current_admin.id)
        logger.info(f"Retrieved {len(campaigns)} pending campaigns")
        return campaigns

    except Exception as e:
        logger.error(f"Error retrieving pending campaigns: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve pending campaigns: {str(e)}"
        )

@router.get("/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(
    campaign_id: str,
    campaign_service: CampaignService = Depends(get_campaign_service),
    current_admin=Depends(get_current_admin_user),
):
    """
    Get a specific campaign by ID with full details.
    """
    logger.info(f"GET /{campaign_id} - Retrieving campaign details")
    
    try:
        campaign = await campaign_service.get_campaign_by_id(
            campaign_id=campaign_id,
            admin_id=current_admin.id
        )
        return campaign

    except Exception as e:
        logger.error(f"Error retrieving campaign: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve campaign: {str(e)}"
        )

@router.get("/", response_model=List[CampaignListResponse])
async def list_campaigns(
    status_filter: Optional[str] = None,
    limit: int = 50,
    campaign_service: CampaignService = Depends(get_campaign_service),
    current_admin=Depends(get_current_admin_user),
):
    """
    List all campaigns for the current admin with optional status filtering.
    
    Query parameters:
    - status_filter: Filter by campaign status (draft, completed, etc.)
    - limit: Maximum number of campaigns to return
    """
    logger.info(f"GET / - Listing campaigns with filter: {status_filter}")
    
    try:
        # Build query
        query = {"admin_id": current_admin.id}
        if status_filter:
            query["status"] = status_filter
        
        # Get campaigns
        cursor = db.db.campaigns.find(query).sort("created_at", -1).limit(limit)
        campaigns = await cursor.to_list(length=None)
        
        # Format response
        formatted_campaigns = []
        for campaign in campaigns:
            # Get preview message
            preview_message = None
            if campaign.get("approved_content"):
                preview_message = campaign["approved_content"]["message"][:100] + "..."
            elif campaign.get("draft_content"):
                preview_message = campaign["draft_content"]["message"][:100] + "..."
            
            formatted_campaign = {
                "id": str(campaign["_id"]),
                "type": campaign.get("type", "messaging"),
                "status": campaign.get("status", "completed"),
                "description": campaign.get("description", ""),
                "created_at": campaign.get("created_at"),
                "admin_id": campaign.get("admin_id"),
                "preview_message": preview_message,
                "total_questions": len(campaign.get("questions", []))
            }
            formatted_campaigns.append(formatted_campaign)
        
        logger.info(f"Retrieved {len(formatted_campaigns)} campaigns")
        return formatted_campaigns

    except Exception as e:
        logger.error(f"Error listing campaigns: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list campaigns: {str(e)}"
        )

# ===================================================================
# BACKWARD COMPATIBILITY ENDPOINTS (Keep existing functionality)
# ===================================================================

@router.post("/legacy", response_model=CampaignResponse)
async def create_legacy_campaign(
    campaign: CampaignCreate,
    campaign_service: CampaignService = Depends(get_campaign_service),
    current_admin=Depends(get_current_admin_user),
):
    """
    Legacy endpoint for immediate campaign execution (backward compatibility).
    This maintains the old workflow for existing integrations.
    """
    logger.info(f"POST /legacy - Creating legacy campaign: {campaign.description}")
    
    try:
        # Use the existing create_campaign method for immediate execution
        result = await campaign_service.create_campaign(
            campaign=campaign.dict(),
            admin_id=current_admin.id,
            thread_id=campaign.thread_id
        )
        logger.info(f"Legacy campaign created successfully: {result}")
        return result

    except Exception as e:
        logger.error(f"Error creating legacy campaign: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create legacy campaign: {str(e)}"
        )

@router.get("/active", response_model=CampaignResponse)
async def get_active_campaign(
    campaign_service: CampaignService = Depends(get_campaign_service),
    current_admin=Depends(get_current_admin_user),
):
    """
    Get the currently active campaign (legacy endpoint).
    Updated to work with new status system.
    """
    logger.info("GET /active - Retrieving active campaign")
    
    try:
        # Look for executing or completed campaigns (new system)
        campaign = await db.db.campaigns.find_one({
            "admin_id": current_admin.id,
            "status": {"$in": [CampaignStatus.EXECUTING.value, CampaignStatus.COMPLETED.value]}
        }, sort=[("created_at", -1)])
        
        if not campaign:
            # Fallback to old system
            campaign = await db.db.campaigns.find_one({
                "admin_id": current_admin.id,
                "status": "active"
            })
        
        if not campaign:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No active campaign found"
            )
        
        # Format response
        campaign["id"] = str(campaign["_id"])
        del campaign["_id"]
        
        return campaign

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving active campaign: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve active campaign: {str(e)}"
        )

@router.get("/{campaign_id}/stats")
async def get_campaign_stats(
    campaign_id: str,
    campaign_service: CampaignService = Depends(get_campaign_service),
    current_admin=Depends(get_current_admin_user),
):
    """
    Get detailed statistics for a specific campaign.
    """
    logger.info(f"GET /{campaign_id}/stats - Retrieving campaign stats")
    
    try:
        return await campaign_service.get_campaign_stats(campaign_id)
    except Exception as e:
        logger.error(f"Error retrieving campaign stats: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve campaign stats: {str(e)}"
        )

# ===================================================================
# UTILITY ENDPOINTS
# ===================================================================

@router.get("/status/summary")
async def get_campaign_status_summary(
    current_admin=Depends(get_current_admin_user),
):
    """
    Get a summary of campaign statuses for the dashboard.
    """
    logger.info("GET /status/summary - Retrieving campaign status summary")
    
    try:
        # Aggregate campaigns by status
        pipeline = [
            {"$match": {"admin_id": current_admin.id}},
            {"$group": {"_id": "$status", "count": {"$sum": 1}}},
            {"$sort": {"_id": 1}}
        ]
        
        results = await db.db.campaigns.aggregate(pipeline).to_list(length=None)
        
        # Format response
        summary = {
            "total": 0,
            "draft": 0,
            "executing": 0,
            "completed": 0,
            "cancelled": 0
        }
        
        for result in results:
            status_name = result["_id"]
            count = result["count"]
            summary["total"] += count
            
            if status_name in summary:
                summary[status_name] = count
        
        return summary

    except Exception as e:
        logger.error(f"Error retrieving campaign summary: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve campaign summary: {str(e)}"
        )

# ===================================================================
# VALIDATION UTILITIES
# ===================================================================

def validate_campaign_create(campaign: CampaignCreate):
    """Enhanced validation for campaign creation."""
    if not campaign.description:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Campaign description is required"
        )

def validate_campaign_draft(draft_request: CampaignDraftRequest):
    """Validation for draft creation."""
    if not draft_request.campaign_purpose:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Campaign purpose is required"
        )
    
    if not draft_request.key_points:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Key points are required"
        )