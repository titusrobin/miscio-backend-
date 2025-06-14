# app/api/v1/endpoints/feedback.py -- Testing 2 
from fastapi import APIRouter, HTTPException, Depends, status
from typing import List, Optional
from app.services.feedback_conversation import FeedbackConversationService
from app.services.openai_service import OpenAIService
from app.core.security import get_current_admin_user
from app.db.mongodb import db
from bson import ObjectId
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

def get_feedback_conversation_service():
    openai_service = OpenAIService()
    return FeedbackConversationService(db.db, openai_service)

@router.get("/conversations/{campaign_id}")
async def get_campaign_conversations(
    campaign_id: str,
    current_admin=Depends(get_current_admin_user),
    feedback_service: FeedbackConversationService = Depends(get_feedback_conversation_service)
):
    """Get all conversation states for a feedback campaign"""
    try:
        # Verify campaign belongs to admin
        campaign = await db.db.campaigns.find_one({
            "_id": ObjectId(campaign_id),
            "admin_id": current_admin.id,
            "type": "feedback"
        })
        
        if not campaign:
            raise HTTPException(status_code=404, detail="Feedback campaign not found")
        
        # Get all conversations for this campaign
        conversations = await db.db.feedback_conversations.find({
            "campaign_id": campaign_id
        }).to_list(length=None)
        
        # Add student names
        for conv in conversations:
            student = await db.db.students.find_one({"_id": conv["student_id"]})
            if student:
                conv["student_name"] = f"{student.get('first_name', '')} {student.get('last_name', '')}".strip()
            else:
                conv["student_name"] = "Unknown Student"
        
        return {
            "campaign_id": campaign_id,
            "total_conversations": len(conversations),
            "conversations": conversations
        }
        
    except Exception as e:
        logger.error(f"Error getting campaign conversations: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/conversations/{campaign_id}/progress")
async def get_campaign_progress(
    campaign_id: str,
    current_admin=Depends(get_current_admin_user)
):
    """Get progress summary for a feedback campaign"""
    try:
        # Verify campaign belongs to admin
        campaign = await db.db.campaigns.find_one({
            "_id": ObjectId(campaign_id),
            "admin_id": current_admin.id,
            "type": "feedback"
        })
        
        if not campaign:
            raise HTTPException(status_code=404, detail="Feedback campaign not found")
        
        # Get conversation statistics
        total_students = await db.db.students.count_documents({"admin_id": current_admin.id, "status": "active"})
        
        conversations = await db.db.feedback_conversations.find({
            "campaign_id": campaign_id
        }).to_list(length=None)
        
        started_conversations = len(conversations)
        completed_conversations = len([c for c in conversations if c.get("status") == "completed"])
        
        # Calculate average completion rate
        total_questions = len(campaign.get("questions", []))
        if conversations:
            avg_completion = sum(c.get("questions_completed", 0) for c in conversations) / len(conversations)
            avg_completion_percent = (avg_completion / total_questions * 100) if total_questions > 0 else 0
        else:
            avg_completion_percent = 0
        
        return {
            "campaign_id": campaign_id,
            "total_students": total_students,
            "conversations_started": started_conversations,
            "conversations_completed": completed_conversations,
            "participation_rate": (started_conversations / total_students * 100) if total_students > 0 else 0,
            "completion_rate": (completed_conversations / started_conversations * 100) if started_conversations > 0 else 0,
            "average_question_completion": round(avg_completion_percent, 1),
            "total_questions": total_questions
        }
        
    except Exception as e:
        logger.error(f"Error getting campaign progress: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
