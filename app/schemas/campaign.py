# app/schemas/campaign.py
from pydantic import BaseModel
from typing import List
from datetime import datetime
from typing import Optional


class CampaignBase(BaseModel):
    description: str
    focus_areas: Optional[List[str]] = (
        []
    )  # Making it optional with a default empty list
    settings: Optional[dict] = {}  # Adding settings field that might be needed
    target_completion_date: Optional[datetime] = None


class CampaignCreate(CampaignBase):
    pass


class CampaignUpdate(CampaignBase):
    status: Optional[str]


class CampaignResponse(CampaignBase):
    id: str
    assistant_id: str
    status: str
    created_at: datetime
    admin_id: str

    class Config:
        from_attributes = True
