# app/services/campaign_service.py - FIXED VERSION
from typing import Optional, Dict, List
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi import HTTPException, status
from bson import ObjectId
import json
from app.services.openai_service import OpenAIService
from app.services.twilio_service import TwilioService
from app.services.sendgrid_service import SendGridService  
from app.models.campaign import CampaignType, CampaignStatus, DraftContent, ApprovedContent, ApprovalAction
from app.schemas.campaign import CampaignDraftRequest, CampaignApprovalRequest

import logging
logger = logging.getLogger(__name__)

def safe_object_id(id_value):
    """Safely convert string to ObjectId if needed"""
    if isinstance(id_value, str):
        try:
            return ObjectId(id_value)
        except:
            return id_value
    return id_value

def safe_string_id(id_value):
    """Safely convert ObjectId to string if needed"""
    if isinstance(id_value, ObjectId):
        return str(id_value)
    return id_value

class CampaignService: 
    def __init__( 
        self,
        openai_service: OpenAIService,
        twilio_service: TwilioService,
        sendgrid_service: SendGridService,
        database: AsyncIOMotorDatabase,  
    ):
        self.openai_service = openai_service
        self.twilio_service = twilio_service 
        self.sendgrid_service = sendgrid_service
        self.db = database

    # KEEP EXISTING METHODS FOR BACKWARD COMPATIBILITY
    async def create_campaign(self, campaign: dict, admin_id: str, thread_id: str = None) -> Dict:
        """
        LEGACY METHOD - Creates a campaign using the old workflow
        Maintained for backward compatibility
        """
        logger.info(f"Creating legacy campaign: {campaign} in thread: {thread_id}")
        try:
            async with await self.db.client.start_session() as session:
                async with session.start_transaction():
                    # Use old campaign structure but with new status
                    campaign_data = {
                        "type": CampaignType.MESSAGING.value,
                        "status": CampaignStatus.COMPLETED.value,  # Legacy campaigns execute immediately
                        "description": campaign.get("details", ""),
                        "purpose": campaign.get("purpose", ""),
                        "audience": campaign.get("audience", "all students"),
                        "tone": campaign.get("tone", "friendly and helpful"),
                        "key_points": campaign.get("key_points", ""),
                        "call_to_action": campaign.get("call_to_action", ""),
                        "admin_id": admin_id,
                        "thread_id": thread_id,
                        "created_at": datetime.utcnow(),
                        "executed_at": datetime.utcnow(),
                        "completed_at": datetime.utcnow(),
                        # Keep old status for compatibility
                        "legacy_status": "active"
                    }
                    
                    # Deactivate existing legacy campaigns
                    await self.db.campaigns.update_many(
                        {"legacy_status": "active", "admin_id": admin_id},
                        {"$set": {"legacy_status": "inactive"}},
                        session=session,
                    )

                    # Insert the campaign
                    result = await self.db.campaigns.insert_one(campaign_data, session=session)
                    campaign_data["id"] = str(result.inserted_id)
                    
                    # Get admin data
                    admin_data = await self._get_admin_data(admin_id, session)
                    assistant_id = admin_data.get("assistant_id") if admin_data else None

                    if assistant_id:
                        # Update with assistant_id
                        await self.db.campaigns.update_one(
                            {"_id": result.inserted_id},
                            {"$set": {"assistant_id": assistant_id}},
                            session=session
                        )
                        campaign_data["assistant_id"] = assistant_id

                    # Execute campaign immediately (legacy behavior)
                    await self._execute_legacy_campaign(campaign_data, campaign, session)

                    return campaign_data

        except Exception as e:
            logger.error(f"Error creating legacy campaign: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create legacy campaign: {str(e)}",
            )

    async def _execute_legacy_campaign(self, campaign_data: dict, campaign_context: dict, session):
        """Execute a legacy campaign immediately"""
        # Get students
        students = await self.db.students.find(
            {"admin_id": campaign_data["admin_id"], "status": "active"}, 
            session=session
        ).to_list(length=None)

        successful_messages = 0
        failed_messages = 0

        for student in students:
            try:
                # Generate personalized message using legacy context
                if campaign_data.get("assistant_id"):
                    initial_message = await self._generate_personalized_message(
                        campaign=campaign_context,
                        student=student,
                        assistant_id=campaign_data["assistant_id"],
                        admin_id=campaign_data["admin_id"]
                    )
                else:
                    student_name = student.get('first_name', 'Student')
                    initial_message = f"Hi {student_name}, \n\n{campaign_context.get('key_points', '')} {campaign_context.get('call_to_action', 'let us know if you have questions')}"
                
                # Send message
                if student.get('email') and student.get('preferred_contact_method') == 'email': 
                    await self.sendgrid_service.send_message(
                        to_email=student["email"],
                        subject=campaign_context.get("title", "Message from Miscio Assistant"),
                        message=initial_message,
                        message_type="initial"
                    )
                    contact_method = "email"
                elif student.get('phone'):
                    await self.twilio_service.send_message(
                        student["phone"], initial_message
                    )
                    contact_method = "whatsapp"
                else:
                    logger.warning(f"No valid contact method for student {student['_id']}")
                    failed_messages += 1
                    continue
                
                # Record interaction with proper ObjectId handling
                await self._record_student_interaction( 
                    campaign_id=str(campaign_data["id"]),
                    student_id=str(student["_id"]),
                    message=initial_message,
                    contact_method=contact_method,
                    email_subject=campaign_context.get("title", "Message from Miscio Assistant") if contact_method == "email" else None,
                    assistant_id=campaign_data.get("assistant_id"),
                    session=session,
                    admin_id=campaign_data["admin_id"]
                )
                
                successful_messages += 1
                
            except Exception as e:
                logger.error(f"Error processing student {student['_id']}: {str(e)}")
                failed_messages += 1

        # Update with execution summary
        execution_summary = {
            "total_students": len(students),
            "successful_messages": successful_messages,
            "failed_messages": failed_messages
        }

        await self.db.campaigns.update_one(
            {"_id": safe_object_id(campaign_data["id"])},
            {"$set": {"execution_summary": execution_summary}},
            session=session
        )

        campaign_data["summary"] = execution_summary

    # NEW DRAFT-APPROVAL WORKFLOW METHODS
    async def create_messaging_draft(
        self, 
        draft_request: CampaignDraftRequest, 
        admin_id: str, 
        thread_id: str = None
    ) -> Dict:
        """Create a draft messaging campaign that requires admin approval"""
        logger.info(f"Creating messaging campaign draft: {draft_request.campaign_purpose}")
        
        try:
            # Generate sample message
            sample_message = await self._generate_sample_message(draft_request, admin_id)
            
            # Create draft content
            draft_content = DraftContent(
                message=sample_message,
                subject=self._generate_subject(draft_request),
                generation_context={
                    "purpose": draft_request.campaign_purpose,
                    "details": draft_request.campaign_details,
                    "tone": draft_request.tone_and_style,
                    "key_points": draft_request.key_points,
                    "call_to_action": draft_request.call_to_action
                }
            )
            
            # Create campaign data
            campaign_data = {
                "type": CampaignType.MESSAGING.value,
                "status": CampaignStatus.DRAFT.value,
                "description": draft_request.campaign_details,
                "admin_id": admin_id,
                "thread_id": thread_id,
                "draft_content": draft_content.dict(),
                "approval_history": [{
                    "action": "created_draft",
                    "timestamp": datetime.utcnow(),
                    "admin_id": admin_id,
                    "notes": f"Draft created for: {draft_request.campaign_purpose}"
                }],
                "created_at": datetime.utcnow()
            }
            
            # Store in database
            result = await self.db.campaigns.insert_one(campaign_data)
            campaign_data["id"] = str(result.inserted_id)
            
            logger.info(f"Created draft campaign with ID: {campaign_data['id']}")
            return campaign_data
            
        except Exception as e:
            logger.error(f"Error creating messaging draft: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create messaging draft: {str(e)}"
            )

    async def approve_and_execute_campaign(
        self,
        approval_request: CampaignApprovalRequest,
        admin_id: str
    ) -> Dict:
        """Approve a draft campaign and execute it"""
        logger.info(f"Processing approval request for campaign: {approval_request.campaign_id}")
        
        try:
            # Get the campaign
            campaign = await self.db.campaigns.find_one({"_id": safe_object_id(approval_request.campaign_id)})
            
            if not campaign:
                raise HTTPException(status_code=404, detail="Campaign not found")
            
            if campaign["admin_id"] != admin_id:
                raise HTTPException(status_code=403, detail="Not authorized")
            
            if campaign["status"] != CampaignStatus.DRAFT.value:
                raise HTTPException(status_code=400, detail=f"Campaign is not in draft status")
            
            # Handle actions
            if approval_request.action == "cancel":
                return await self._cancel_campaign(campaign, approval_request, admin_id)
            elif approval_request.action == "modify":
                return await self._modify_draft(campaign, approval_request, admin_id)
            elif approval_request.action == "approve":
                return await self._approve_and_execute(campaign, approval_request, admin_id)
            else:
                raise HTTPException(status_code=400, detail=f"Invalid action: {approval_request.action}")
                
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error processing approval request: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to process approval: {str(e)}")

    # Helper methods with proper ObjectId handling
    async def _record_student_interaction(
        self,
        campaign_id: str,
        student_id: str,
        message: str,
        contact_method: str,
        interaction_type: str = "initial",
        status: str = "sent",
        email_subject: Optional[str] = None,
        assistant_id: Optional[str] = None,
        session = None,
        admin_id: Optional[str] = None
    ):
        """Record student interaction with proper ID handling"""
        interaction_data = {
            "campaign_id": safe_string_id(campaign_id),
            "student_id": safe_string_id(student_id),
            "message": message,
            "type": interaction_type,
            "contact_method": contact_method,
            "status": status,
            "timestamp": datetime.utcnow(),
        }
        
        if email_subject or contact_method == "email":
            interaction_data["email_subject"] = email_subject or "Message from Miscio Assistant"
        
        if assistant_id:
            interaction_data["assistant_id"] = assistant_id

        if admin_id:
            interaction_data["admin_id"] = admin_id
        
        await self.db.interactions.insert_one(interaction_data, session=session)
        logger.debug(f"Recorded {interaction_type} interaction for student {student_id}")
        return interaction_data

    async def _get_admin_data(self, admin_id: str, session=None):
        """Get admin data with proper ObjectId handling"""
        # Try string first
        admin_data = await self.db.admin_users.find_one({"_id": admin_id}, session=session)
        
        # If not found, try ObjectId
        if not admin_data:
            try:
                admin_data = await self.db.admin_users.find_one({"_id": safe_object_id(admin_id)}, session=session)
            except Exception as e:
                logger.error(f"Error with ObjectId conversion: {str(e)}")
        
        return admin_data

    # Keep other existing methods like query_student_chats, get_campaign_stats, etc.
    # with proper ObjectId handling...