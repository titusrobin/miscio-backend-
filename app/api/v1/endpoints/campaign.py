# app/api/v1/endpoints/campaign.py
import logging
import json
from fastapi import APIRouter, HTTPException, Depends, status
from typing import List, Optional
from datetime import datetime
from app.schemas.campaign import CampaignCreate, CampaignResponse, CampaignUpdate
from app.services.campaign_service import CampaignService
from app.core.security import get_current_admin_user
from app.models.campaign import Campaign
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

 
@router.post("/", response_model=CampaignResponse) # / endpoint root of the mounted path "/" 
async def create_campaign(
    campaign: CampaignCreate, # FastAPI to automatically parse  JSON from request into CampaignCreate object
    campaign_service: CampaignService = Depends(get_campaign_service),
    current_admin=Depends(get_current_admin_user),
):
    """
    Creates a new campaign with the provided configuration.
    Includes comprehensive error handling and logging.
    """
    logger.info(f"POST / - Creating new campaign: {json.dumps(campaign.dict(), indent=2)}")
    validate_campaign(campaign) # Validate campaign data has description

    try:
        result = await campaign_service.create_campaign(
            campaign=campaign, admin_id=current_admin.id
        )
        logger.info(f"Campaign created successfully: {result}")
        return result

    except Exception as e:
        error_message = str(e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=error_message or "An unexpected error occurred during campaign creation",
        )


@router.get("/active", response_model=CampaignResponse)
async def get_active_campaign(
    campaign_service: CampaignService = Depends(get_campaign_service),
    current_admin=Depends(get_current_admin_user),
):
    """
    Retrieves the currently active campaign.
    Only one campaign can be active at a time.
    Requires admin authentication.
    """
    logger.info("GET /active - Retrieving active campaign")
    try:
        campaign = await campaign_service.get_active_campaign()
        if not campaign:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="No active campaign found"
            )
        return campaign
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@router.get("/{campaign_id}/stats")
async def get_campaign_stats(
    campaign_id: str,
    campaign_service: CampaignService = Depends(get_campaign_service),
    current_admin=Depends(get_current_admin_user),
):
    """
    Retrieves detailed statistics for a specific campaign, including:
    - Total number of students reached
    - Response rate
    - Average sentiment
    - Common themes in feedback

    Requires admin authentication and valid campaign ID.
    """
    logger.info(f"GET /{campaign_id}/stats - Retrieving stats for campaign")
    try:
        return await campaign_service.get_campaign_stats(campaign_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve campaign stats: {str(e)}",
        )



# ===================================================================
# ========================== Utils =============================
def validate_campaign(campaign: CampaignCreate):
    """Validates campaign data and raises appropriate HTTP exceptions if invalid."""
    if not campaign.description:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Campaign description is required",
        )