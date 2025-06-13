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
        
        if email_subject:
            interaction_data["email_subject"] = email_subject
        
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

    async def _generate_sample_message(self, draft_request: CampaignDraftRequest, admin_id: str) -> str:
        """Generate a sample message using OpenAI based on the campaign request"""
        try:
            # Create a prompt for message generation
            prompt = f"""
            Create a professional, engaging message for students based on these details:
            
            Campaign Purpose: {draft_request.campaign_purpose}
            Details: {draft_request.campaign_details}
            Key Points: {draft_request.key_points}
            Call to Action: {draft_request.call_to_action}
            Tone: {draft_request.tone_and_style}
            Audience: {draft_request.target_audience}
            
            Requirements:
            - Keep it concise and student-friendly
            - Include the key points naturally
            - Use the specified tone and style
            - End with the call to action
            - Don't use asterisks for formatting
            - Make it personal and engaging
            """
            
            # Create a temporary thread for message generation
            thread_data = await self.openai_service.create_thread()
            thread_id = thread_data["id"]
            
            # Get admin data to find assistant
            admin_data = await self._get_admin_data(admin_id)
            assistant_id = admin_data.get("assistant_id") if admin_data else "asst_re59LKPfW1Fya4rwuoxVHKOa"
            
            # Generate message using OpenAI
            response = await self.openai_service.process_message(
                thread_id=thread_id,
                message=prompt,
                assistant_id=assistant_id
            )
            
            logger.info(f"Generated sample message for campaign: {draft_request.campaign_purpose}")
            return response.strip()
            
        except Exception as e:
            logger.error(f"Error generating sample message: {str(e)}")
            # Fallback message generation
            return self._generate_fallback_message(draft_request)

    def _generate_fallback_message(self, draft_request: CampaignDraftRequest) -> str:
        """Generate a simple fallback message when OpenAI fails"""
        message = f"Hi there!\n\n{draft_request.campaign_details}\n\n"
        
        if draft_request.key_points:
            message += f"{draft_request.key_points}\n\n"
            
        if draft_request.call_to_action:
            message += f"{draft_request.call_to_action}\n\n"
            
        message += "If you have any questions, feel free to reach out!"
        
        return message

    def _generate_subject(self, draft_request: CampaignDraftRequest) -> str:
        """Generate an email subject line based on campaign purpose"""
        purpose = draft_request.campaign_purpose.strip()
        
        # Simple subject generation logic
        if "deadline" in purpose.lower() or "reminder" in purpose.lower():
            return f"Reminder: {purpose}"
        elif "new" in purpose.lower() or "announcement" in purpose.lower():
            return f"Update: {purpose}"
        elif "important" in purpose.lower():
            return f"Important: {purpose}"
        else:
            # Capitalize first letter and ensure it's not too long
            subject = purpose[0].upper() + purpose[1:] if purpose else "Message from Your School"
            return subject[:50] + "..." if len(subject) > 50 else subject

    async def _cancel_campaign(self, campaign: dict, approval_request: CampaignApprovalRequest, admin_id: str) -> Dict:
        """Cancel a draft campaign"""
        try:
            # Update campaign status to cancelled
            await self.db.campaigns.update_one(
                {"_id": safe_object_id(campaign["_id"])},
                {
                    "$set": {
                        "status": CampaignStatus.CANCELLED.value,
                        "completed_at": datetime.utcnow()
                    },
                    "$push": {
                        "approval_history": {
                            "action": "cancelled",
                            "timestamp": datetime.utcnow(),
                            "admin_id": admin_id,
                            "notes": approval_request.notes or "Campaign cancelled by admin"
                        }
                    }
                }
            )
            
            logger.info(f"Campaign {campaign['_id']} cancelled by admin {admin_id}")
            
            return {
                "status": "success",
                "message": "Campaign cancelled successfully",
                "campaign_id": str(campaign["_id"])
            }
            
        except Exception as e:
            logger.error(f"Error cancelling campaign: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to cancel campaign: {str(e)}"
            )

    async def _modify_draft(self, campaign: dict, approval_request: CampaignApprovalRequest, admin_id: str) -> Dict:
        """Modify a draft campaign and keep it in draft status"""
        try:
            # Prepare updated draft content
            current_draft = campaign.get("draft_content", {})
            
            updated_draft = {
                "message": approval_request.modified_message or current_draft.get("message"),
                "subject": approval_request.modified_subject or current_draft.get("subject"),
                "generated_at": datetime.utcnow(),
                "generation_context": current_draft.get("generation_context")
            }
            
            # Update the campaign
            await self.db.campaigns.update_one(
                {"_id": safe_object_id(campaign["_id"])},
                {
                    "$set": {
                        "draft_content": updated_draft,
                        "status": CampaignStatus.DRAFT.value  # Keep in draft
                    },
                    "$push": {
                        "approval_history": {
                            "action": "modified",
                            "timestamp": datetime.utcnow(),
                            "admin_id": admin_id,
                            "notes": approval_request.notes or "Draft modified by admin"
                        }
                    }
                }
            )
            
            logger.info(f"Campaign {campaign['_id']} draft modified by admin {admin_id}")
            
            return {
                "status": "success", 
                "message": "Campaign draft updated successfully",
                "campaign_id": str(campaign["_id"]),
                "updated_content": updated_draft
            }
            
        except Exception as e:
            logger.error(f"Error modifying campaign draft: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to modify campaign draft: {str(e)}"
            )

    async def _approve_and_execute(self, campaign: dict, approval_request: CampaignApprovalRequest, admin_id: str) -> Dict:
        """Approve and execute a messaging campaign"""
        try:
            async with await self.db.client.start_session() as session:
                async with session.start_transaction():
                    
                    # Determine final content (modified or original draft)
                    draft_content = campaign.get("draft_content", {})
                    final_message = approval_request.modified_message or draft_content.get("message")
                    final_subject = approval_request.modified_subject or draft_content.get("subject")
                    
                    if not final_message:
                        raise Exception("No message content available for execution")
                    
                    # Create approved content
                    approved_content = ApprovedContent(
                        message=final_message,
                        subject=final_subject,
                        approved_by=admin_id,
                        modifications_from_draft=approval_request.modified_message or approval_request.modified_subject
                    )
                    
                    # Update campaign to executing status
                    await self.db.campaigns.update_one(
                        {"_id": safe_object_id(campaign["_id"])},
                        {
                            "$set": {
                                "status": CampaignStatus.EXECUTING.value,
                                "approved_content": approved_content.dict(),
                                "executed_at": datetime.utcnow()
                            },
                            "$push": {
                                "approval_history": {
                                    "action": "approved",
                                    "timestamp": datetime.utcnow(),
                                    "admin_id": admin_id,
                                    "notes": approval_request.notes or "Campaign approved and executing"
                                }
                            }
                        },
                        session=session
                    )
                    
                    # Get all active students for this admin
                    students = await self.db.students.find(
                        {"admin_id": admin_id, "status": "active"}, 
                        session=session
                    ).to_list(length=None)
                    
                    logger.info(f"Executing campaign for {len(students)} students")
                    
                    # Execute campaign - send to all students
                    successful_messages = 0
                    failed_messages = 0
                    
                    for student in students:
                        try:
                            contact_method = student.get('preferred_contact_method', 'email')
                            
                            if contact_method == 'email' and student.get('email'):
                                await self.sendgrid_service.send_message(
                                    to_email=student["email"],
                                    subject=final_subject or "Message from Your School",
                                    message=final_message,
                                    message_type="initial"
                                )
                                contact_used = "email"
                                
                            elif student.get('phone'):
                                await self.twilio_service.send_message(
                                    student["phone"], 
                                    final_message
                                )
                                contact_used = "whatsapp"
                                
                            else:
                                logger.warning(f"No valid contact method for student {student['_id']}")
                                failed_messages += 1
                                continue
                            
                            # Record interaction
                            await self._record_student_interaction(
                                campaign_id=str(campaign["_id"]),
                                student_id=str(student["_id"]),
                                message=final_message,
                                contact_method=contact_used,
                                interaction_type="initial",
                                email_subject=final_subject if contact_used == "email" else None,
                                session=session,
                                admin_id=admin_id
                            )
                            
                            successful_messages += 1
                            
                        except Exception as e:
                            logger.error(f"Error sending to student {student['_id']}: {str(e)}")
                            failed_messages += 1
                    
                    # Create execution summary
                    execution_summary = {
                        "total_students": len(students),
                        "successful_messages": successful_messages,
                        "failed_messages": failed_messages,
                        "execution_date": datetime.utcnow(),
                        "message_content": final_message[:100] + "..." if len(final_message) > 100 else final_message
                    }
                    
                    # Update campaign to completed
                    await self.db.campaigns.update_one(
                        {"_id": safe_object_id(campaign["_id"])},
                        {
                            "$set": {
                                "status": CampaignStatus.COMPLETED.value,
                                "completed_at": datetime.utcnow(),
                                "execution_summary": execution_summary
                            }
                        },
                        session=session
                    )
                    
                    logger.info(f"Campaign {campaign['_id']} completed successfully: {successful_messages} sent, {failed_messages} failed")
                    
                    return {
                        "status": "success",
                        "message": f"Campaign executed successfully! Sent to {successful_messages} students.",
                        "campaign_id": str(campaign["_id"]),
                        "execution_summary": execution_summary
                    }
        
        except Exception as e:
            logger.error(f"Error executing campaign: {str(e)}")
            
            # Update campaign to failed status
            try:
                await self.db.campaigns.update_one(
                    {"_id": safe_object_id(campaign["_id"])},
                    {
                        "$set": {
                            "status": CampaignStatus.CANCELLED.value,
                            "completed_at": datetime.utcnow()
                        },
                        "$push": {
                            "approval_history": {
                                "action": "failed",
                                "timestamp": datetime.utcnow(),
                                "admin_id": admin_id,
                                "notes": f"Execution failed: {str(e)}"
                            }
                        }
                    }
                )
            except:
                pass  # Don't fail if we can't update status
                
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to execute campaign: {str(e)}"
            )

    async def get_pending_campaigns(self, admin_id: str) -> List[Dict]:
        """Get all campaigns waiting for admin approval"""
        try:
            campaigns = await self.db.campaigns.find({
                "admin_id": admin_id,
                "status": CampaignStatus.DRAFT.value
            }).sort("created_at", -1).to_list(length=None)
            
            formatted_campaigns = []
            for campaign in campaigns:
                # Get preview of draft message
                draft_content = campaign.get("draft_content", {})
                preview_message = None
                if draft_content.get("message"):
                    preview_message = draft_content["message"][:100] + "..." if len(draft_content["message"]) > 100 else draft_content["message"]
                
                formatted_campaign = {
                    "id": str(campaign["_id"]),
                    "type": campaign.get("type", CampaignType.MESSAGING.value),
                    "status": campaign.get("status"),
                    "description": campaign.get("description", ""),
                    "created_at": campaign.get("created_at"),
                    "admin_id": campaign.get("admin_id"),
                    "preview_message": preview_message,
                    "draft_content": draft_content
                }
                formatted_campaigns.append(formatted_campaign)
            
            return formatted_campaigns
            
        except Exception as e:
            logger.error(f"Error retrieving pending campaigns: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve pending campaigns: {str(e)}"
            )

    async def get_campaign_by_id(self, campaign_id: str, admin_id: str) -> Dict:
        """Get a specific campaign by ID with full details"""
        try:
            campaign = await self.db.campaigns.find_one({
                "_id": safe_object_id(campaign_id),
                "admin_id": admin_id
            })
            
            if not campaign:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Campaign not found"
                )
            
            # Format response
            campaign["id"] = str(campaign["_id"])
            del campaign["_id"]
            
            return campaign
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error retrieving campaign: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve campaign: {str(e)}"
            )

    