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
from app.schemas.feedback import FeedbackDraftRequest, GeneratedQuestion
from app.models.campaign import FeedbackQuestion

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

    # NEW DRAFT-APPROVAL WORKFLOW METHODS
    async def create_messaging_draft(
        self, 
        draft_request: CampaignDraftRequest, 
        admin_id: str, 
        thread_id: str = None
    ) -> Dict:
        """Create a draft messaging campaign that requires admin approval"""
        
        try:
            # Generate sample message
            sample_message = await self._generate_sample_message(draft_request, admin_id)
            
            # Create draft content #TODO: What if trigger two drafts recurringly 
            draft_content = DraftContent(
                message=sample_message,
                subject=await self._generate_subject(draft_request),
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

    async def create_feedback_draft(
    self, 
    draft_request: FeedbackDraftRequest, 
    admin_id: str, 
    thread_id: str = None
) -> Dict:
        """Create a draft feedback campaign with research questions that requires admin approval"""
        
        try:
            # Generate or process questions
            if draft_request.admin_provided_questions:
                # Admin provided questions - format them
                questions = await self._process_admin_questions(
                    draft_request.admin_provided_questions,
                    draft_request.conversation_style
                )
                question_source = "admin_provided"
            else:
                # Generate questions using AI
                questions = await self._generate_research_questions(
                    draft_request, 
                    admin_id
                )
                question_source = "ai_generated"
            
            # Create campaign data
            campaign_data = {
                "type": CampaignType.FEEDBACK.value,
                "status": CampaignStatus.DRAFT.value,
                "description": draft_request.research_topic,
                "admin_id": admin_id,
                "thread_id": thread_id,
                "questions": [q.dict() for q in questions],
                "feedback_metadata": {
                    "research_topic": draft_request.research_topic,
                    "conversation_style": draft_request.conversation_style,
                    "target_audience": draft_request.target_audience,
                    "question_source": question_source,
                    "total_questions": len(questions)
                },
                "approval_history": [{
                    "action": "created_draft",
                    "timestamp": datetime.utcnow(),
                    "admin_id": admin_id,
                    "notes": f"Feedback draft created for: {draft_request.campaign_purpose}"
                }],
                "created_at": datetime.utcnow()
            }
            
            # Store in database
            result = await self.db.campaigns.insert_one(campaign_data)
            campaign_data["id"] = str(result.inserted_id)
            
            logger.info(f"Created feedback draft campaign with ID: {campaign_data['id']}")
            return campaign_data
            
        except Exception as e:
            logger.error(f"Error creating feedback draft: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create feedback draft: {str(e)}"
            )



    async def approve_and_execute_campaign(
        self,
        approval_request: CampaignApprovalRequest,
        admin_id: str
    ) -> Dict:
        """Approve a draft campaign and execute it"""
        #logger.info(f"CMP: Processing approval request for campaign: {approval_request.campaign_id}")
        
        try:
            # Get the campaign
            campaign = await self.db.campaigns.find_one({"_id": safe_object_id(approval_request.campaign_id)})
            
            if not campaign:
                raise HTTPException(status_code=404, detail="Campaign not found")
            
            if campaign["admin_id"] != admin_id:
                raise HTTPException(status_code=403, detail="Not authorized")
            
            if campaign["status"] != CampaignStatus.DRAFT.value:
                raise HTTPException(status_code=400, detail=f"Campaign is not in draft status")
            
            logger.info(f"CMP: Campaign execution start - ID: {approval_request.campaign_id}, Type: {campaign.get('type')}, Status: {campaign.get('status')}")  # ADD THIS

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
        """Generate a sample message using direct OpenAI API call"""
        try:
            # Create a simple message generation prompt
            prompt = f"""Create a professional, engaging message for students. 

    Purpose: {draft_request.campaign_purpose}
    Details: {draft_request.campaign_details}
    Key Points: {draft_request.key_points}
    Call to Action: {draft_request.call_to_action}
    Tone: {draft_request.tone_and_style}

    Requirements:
    - Keep it concise and student-friendly (2-3 paragraphs max)
    - Include the key points naturally
    - Use the specified tone
    - End with the call to action
    - No asterisks or markdown formatting
    - Make it personal and engaging

    Return only the message content, no extra text."""

            # Use OpenAI Chat Completions API directly (not assistants)
            headers = {
                "Authorization": f"Bearer {self.openai_service.headers['Authorization'].split(' ')[1]}",
                "Content-Type": "application/json"
            }
            
            data = {
                "model": "gpt-4-turbo-preview",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 500,
                "temperature": 0.7
            }
            
            response = await self.openai_service.make_request(
                method="POST",
                url="https://api.openai.com/v1/chat/completions",
                headers=headers,
                data=data
            )
            
            if response and "choices" in response and len(response["choices"]) > 0:
                message = response["choices"][0]["message"]["content"].strip()
                logger.info(f"Generated sample message for campaign: {draft_request.campaign_purpose}")
                return message
            else:
                logger.warning("No response from OpenAI, using fallback")
                return self._generate_enhanced_fallback_message(draft_request)
                
        except Exception as e:
            logger.error(f"Error generating sample message: {str(e)}")
            return self._generate_enhanced_fallback_message(draft_request)

    def _generate_enhanced_fallback_message(self, draft_request: CampaignDraftRequest) -> str:
        """Generate a well-structured fallback message"""
        message = "Hi everyone,\n\n"
        
        # Add the main details
        message += f"{draft_request.campaign_details}\n\n"
        
        # Add key points if available
        if draft_request.key_points:
            points = [p.strip() for p in draft_request.key_points.split(',') if p.strip()]
            if len(points) > 1:
                message += "Key details:\n"
                for point in points:
                    message += f"• {point}\n"
                message += "\n"
            else:
                message += f"{draft_request.key_points}\n\n"
        
        # Add call to action
        if draft_request.call_to_action:
            message += f"{draft_request.call_to_action.capitalize()}.\n\n"
        
        # Add closing
        message += "Thank you for your understanding!"
        
        return message

    def _generate_fallback_message(self, draft_request: CampaignDraftRequest) -> str:
        """Generate a simple fallback message when OpenAI fails"""
        message = f"Hi there!\n\n{draft_request.campaign_details}\n\n"
        
        if draft_request.key_points:
            message += f"{draft_request.key_points}\n\n"
            
        if draft_request.call_to_action:
            message += f"{draft_request.call_to_action}\n\n"
            
        message += "If you have any questions, feel free to reach out!"
        
        return message

    async def _generate_subject(self, draft_request: CampaignDraftRequest) -> str:
        """Generate an AI-powered email subject line for messaging campaigns"""
        try:
            # Use OpenAI to generate a contextual subject line
            prompt = f"""Create an engaging email subject line for a school messaging campaign.

    Campaign Purpose: {draft_request.campaign_purpose}
    Campaign Details: {draft_request.campaign_details}
    Tone: {draft_request.tone_and_style}
    Target Audience: {draft_request.target_audience}

    Requirements:
    - Keep it under 50 characters
    - Make it clear and actionable
    - Match the specified tone ({draft_request.tone_and_style})
    - Make students want to open and read
    - Be specific enough to convey importance

    Return only the subject line, no quotes or extra text."""

            headers = {
                "Authorization": f"Bearer {self.openai_service.headers['Authorization'].split(' ')[1]}",
                "Content-Type": "application/json"
            }
            
            data = {
                "model": "gpt-4-turbo-preview",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 100,
                "temperature": 0.7
            }
            
            response = self.openai_service.make_request(
                method="POST",
                url="https://api.openai.com/v1/chat/completions",
                headers=headers,
                data=data
            )
            
            if response and "choices" in response and len(response["choices"]) > 0:
                subject = response["choices"][0]["message"]["content"].strip()
                subject = subject.strip('"').strip("'")
                logger.info(f"Generated messaging subject: {subject}")
                return subject
            else:
                return self._generate_fallback_subject(draft_request)
                
        except Exception as e:
            logger.error(f"Error generating messaging subject: {str(e)}")
            return self._generate_fallback_subject(draft_request)

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
        """Approve and execute a campaign (messaging or feedback)"""
        try:
            async with await self.db.client.start_session() as session:
                async with session.start_transaction():
                    
                    campaign_type = campaign.get("type", CampaignType.MESSAGING.value)
                    
                    if campaign_type == CampaignType.FEEDBACK.value:
                        # FEEDBACK CAMPAIGN EXECUTION - ENHANCED WITH EMAIL SENDING
                        logger.info(f"CMP: Executing feedback campaign: {campaign['_id']}")

                        # Generate dynamic initial conversation starter message
                        feedback_metadata = campaign.get("feedback_metadata", {})
                        research_topic = feedback_metadata.get("research_topic", "feedback")
                        campaign_purpose = campaign.get("description", "check in with you")
                        conversation_style = feedback_metadata.get("conversation_style", "casual and friendly")
                        target_audience = feedback_metadata.get("target_audience", "students")
                        
                        # Generate dynamic subject line based on campaign purpose
                        subject_line = await self._generate_feedback_subject(campaign_purpose, research_topic, target_audience)
                        
                        # Generate dynamic initial message based on campaign context
                        initial_message = await self._generate_feedback_initial_message(
                            campaign_purpose, research_topic, conversation_style, target_audience
                        )
                        
                        # Create approved content for feedback campaigns
                        approved_content = ApprovedContent(
                            message="Feedback campaign initiated",  # Placeholder message
                            subject=subject_line,
                            approved_by=admin_id,
                            modifications_from_draft=None
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
                                        "notes": approval_request.notes or "Feedback campaign approved and executing"
                                    }
                                }
                            },
                            session=session
                        )
                        
                        # GET ALL ACTIVE STUDENTS AND SEND INITIAL EMAILS
                        students = await self.db.students.find(
                            {"admin_id": admin_id, "status": "active"}, 
                            session=session
                        ).to_list(length=None)
                        
                        logger.info(f"Executing feedback campaign for {len(students)} students")
                        

                        # Send initial emails to start conversations
                        successful_messages = 0
                        failed_messages = 0
                        
                        for student in students:
                            try:
                                contact_method = student.get('preferred_contact_method', 'email')
                                
                                if contact_method == 'email' and student.get('email'):
                                    await self.sendgrid_service.send_message(
                                        to_email=student["email"],
                                        subject=subject_line,
                                        message=initial_message,
                                        message_type="initial"
                                    )
                                    contact_used = "email"
                                    
                                elif student.get('phone'):
                                    await self.twilio_service.send_message(
                                        student["phone"], 
                                        initial_message
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
                                    message=initial_message,
                                    contact_method=contact_used,
                                    interaction_type="feedback_initial",
                                    email_subject=subject_line if contact_used == "email" else None,
                                    session=session,
                                    admin_id=admin_id
                                )
                                
                                successful_messages += 1

                                logger.info(f"CMP: Feedback campaign {campaign['_id']} initiated: {successful_messages} sent, {failed_messages} failed")
                                
                            except Exception as e:
                                logger.error(f"Error sending to student {student['_id']}: {str(e)}")
                                failed_messages += 1
                        
                        # Create execution summary for feedback campaigns
                        execution_summary = {
                            "total_students": len(students),
                            "successful_messages": successful_messages,
                            "failed_messages": failed_messages,
                            "feedback_questions": len(campaign.get("questions", [])),
                            "execution_date": datetime.utcnow(),
                            "campaign_type": "feedback",
                            "status": "conversations_initiated"
                        }
                        
                        # Update campaign to completed (ready state)
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
                        
                        logger.info(f"Feedback campaign {campaign['_id']} initiated: {successful_messages} sent, {failed_messages} failed")
                        
                        return {
                            "status": "success",
                            "message": f"Feedback campaign initiated! Sent initial messages to {successful_messages} students to start conversations.",
                            "campaign_id": str(campaign["_id"]),
                            "execution_summary": execution_summary
                        }
                    
                    else:
                        # MESSAGING CAMPAIGN EXECUTION (existing logic - unchanged)
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
                        
                        logger.info(f"Executing messaging campaign for {len(students)} students")
                        
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
                        
                        logger.info(f"Messaging campaign {campaign['_id']} completed successfully: {successful_messages} sent, {failed_messages} failed")
                        
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
    
    async def query_student_chats(self, query: str = None, thread_id: str = None, limit: int = 25) -> List[Dict]:
        """
        Get student chat histories for campaigns associated with a thread.
        Returns the latest interactions without status filtering.
        """
        try:
            filter_query = {}
            
            if thread_id:
                # Find ALL campaigns associated with this thread (regardless of status)
                campaigns = await self.db.campaigns.find({"thread_id": thread_id}).to_list(length=None)
                
                if campaigns:
                    campaign_ids = [str(campaign["_id"]) for campaign in campaigns]
                    logger.info(f"Found {len(campaign_ids)} campaigns for thread {thread_id}")
                    filter_query["campaign_id"] = {"$in": campaign_ids}
                else:
                    logger.warning(f"No campaigns found for thread {thread_id}")
                    # Return empty list if no campaigns found for this thread
                    return []
            
            # Simple time-based retrieval of latest interactions
            cursor = self.db.interactions.find(filter_query).sort("timestamp", -1).limit(limit)
            
            results = []
            async for interaction in cursor:
                # Safely get student and campaign information
                student = None
                campaign = None
                
                if "student_id" in interaction and interaction["student_id"]:
                    student = await self.db.students.find_one(
                        {"_id": interaction["student_id"]}
                    )
                
                if "campaign_id" in interaction and interaction["campaign_id"]:
                    campaign = await self.db.campaigns.find_one(
                        {"_id": interaction["campaign_id"]}
                    )
                
                # Build result with proper null checks
                result = {
                    "message": interaction.get("message", ""),
                    "timestamp": interaction.get("timestamp", datetime.utcnow()).isoformat(),
                    "type": interaction.get("type", "unknown"),
                    "contact_method": interaction.get("contact_method", "unknown"),
                    "status": interaction.get("status", "unknown"),
                }
                
                # Add student info if available
                if student:
                    result["student_name"] = f"{student.get('first_name', '')} {student.get('last_name', '')}".strip()
                else:
                    result["student_name"] = "Unknown Student"
                
                # Add campaign info if available
                if campaign:
                    result["campaign_description"] = campaign.get("description", "Unknown Campaign")
                else:
                    result["campaign_description"] = "Unknown Campaign"
                
                results.append(result)
            
            # Return results in chronological order (oldest to newest)
            return results[::-1]

        except Exception as e:
            logger.error(f"Error querying student chats: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to query student chats: {str(e)}",
            )
        
    async def _generate_personalized_message(
    self, 
    campaign: dict, 
    student: dict, 
    assistant_id: str,
    admin_id: str
) -> str:
        """
        Generate a personalized message for a student based on comprehensive campaign details.
        Uses the OpenAI assistant to create a well-formatted, contextually relevant message.
        
        Args:
            campaign: Dictionary containing comprehensive campaign information
            student: Dictionary containing student information
            assistant_id: ID of the OpenAI assistant to use for generation
            admin_id: ID of the admin creating the campaign
        
        Returns:
            Personalized message text
        """
        try:
            # Extract student information
            student_name = student.get('first_name', 'Student')
            student_id = str(student.get('_id', ''))
            
            # Create a temporary thread for this message generation
            thread_data = await self.openai_service.create_thread()
            thread_id = thread_data["id"]
            
            # Fetch student interaction history
            student_interactions = await self.db.interactions.find({
                "student_id": student_id
            }).sort("timestamp", -1).limit(3).to_list(length=None)
            
            # Format interaction history if available
            history_text = ""
            has_history = len(student_interactions) > 0
            
            if has_history:
                history_text = "Previous conversation history:\n"
                for interaction in reversed(student_interactions):  # Oldest to newest
                    if interaction.get("type") == "response":
                        history_text += f"Student: {interaction.get('message', '')}\n"
                    else:
                        history_text += f"Assistant: {interaction.get('message', '')}\n"
            
            # Construct the prompt for message generation
            prompt = f"""
            You are writing a personal message to {student_name}. Do NOT call any functions other than the file search. 
            Only respond with the message text that should be sent to the student.
            
            CAMPAIGN INFORMATION:
            Purpose: {campaign.get('purpose', '')}
            Details: {campaign.get('details', '')}
            Target audience: {campaign.get('audience', 'all students')}
            Tone to use: {campaign.get('tone', 'friendly and helpful')}
            Key points to include: {campaign.get('key_points', '')}
            Call to action: {campaign.get('call_to_action', '')}
            
            {"" if not has_history else history_text}
            
            Write a personalized message that:
            1. Addresses the student by name
            2. {'' if has_history else 'Introduces yourself and your purpose'}
            3. {'' if not has_history else 'References previous interactions naturally'}
            4. Communicates the key campaign information clearly
            5. Uses the specified tone ({campaign.get('tone', 'friendly and helpful')})
            
            No need for any formal sign-offs. DO NOT include any signature, sign-off, or name at the end. 
            """
            
            # Process the message with the OpenAI assistant
            response = await self.openai_service.process_message(
                thread_id=thread_id,
                message=prompt,
                assistant_id=assistant_id,
                run_handler=self._message_generation_handler
            )
            
            # Clean up the response if needed
            message = response.strip()
            
            logger.info(f"Generated personalized message for {student_name}")
            return message
            
        except Exception as e:
            logger.error(f"Error generating personalized message: {str(e)}")
            # Fall back to basic message if generation fails
            fallback_message = f"Hi {student.get('first_name', 'Student')}, "
            
            if campaign.get('purpose'):
                fallback_message += f"I'm reaching out about {campaign.get('purpose')}. "
                
            if campaign.get('key_points'):
                fallback_message += f"{campaign.get('key_points')} "
                
            if campaign.get('call_to_action'):
                fallback_message += f"Please {campaign.get('call_to_action')}."
            
            return fallback_message
        
    
    async def _message_generation_handler(self, tool_calls):
        """Simple handler for function calls during message generation.
        Just logs what was called and returns empty outputs to avoid errors."""
        
        logger.info(f"Function called during message generation: {json.dumps(tool_calls, indent=2)}")
        
        # Return minimal valid outputs to satisfy the API
        return [{"tool_call_id": call["id"], "output": "{}"} for call in tool_calls]


    async def _process_admin_questions(
        self, 
        admin_questions: List[str], 
        conversation_style: str
    ) -> List[GeneratedQuestion]:
        """Process admin-provided questions into structured format"""
        try:
            processed_questions = []
            
            for i, question_text in enumerate(admin_questions):
                # Create structured question object
                question = GeneratedQuestion(
                    text=question_text.strip(),
                    question_type="open_ended",  # Default type for admin questions
                    order=i + 1
                )
                processed_questions.append(question)
            
            logger.info(f"Processed {len(processed_questions)} admin-provided questions")
            return processed_questions
            
        except Exception as e:
            logger.error(f"Error processing admin questions: {str(e)}")
            raise Exception(f"Failed to process admin questions: {str(e)}")

    async def _generate_research_questions(
        self, 
        draft_request: FeedbackDraftRequest, 
        admin_id: str
    ) -> List[GeneratedQuestion]:
        """Generate research questions using OpenAI based on the feedback request"""
        try:
            # Create a question generation prompt
            prompt = f"""Generate 4-6 comprehensive research questions for gathering student feedback.

    Research Topic: {draft_request.research_topic}
    Purpose: {draft_request.campaign_purpose}
    Conversation Style: {draft_request.conversation_style}
    Target Audience: {draft_request.target_audience}

    Requirements:
    - Create questions that will gather actionable insights
    - Mix question types: ratings with explanations, open-ended, specific examples
    - Frame questions conversationally (not robotic survey style)
    - Include follow-up prompts where helpful
    - Cover both current state and improvement suggestions
    - Ensure comprehensive coverage of the research topic

    Return ONLY a JSON array of questions in this format:
    [
    {{
        "text": "Rate your overall satisfaction with [topic] from 1-10",
        "question_type": "rating",
        "follow_up_prompt": "Please explain your rating"
    }},
    {{
        "text": "What specific aspects of [topic] work well for you?",
        "question_type": "open_ended",
        "follow_up_prompt": "Can you give specific examples?"
    }}
    ]

    Generate 4-6 questions that comprehensively cover: {draft_request.research_topic}"""

            # Use OpenAI Chat Completions API directly
            headers = {
                "Authorization": f"Bearer {self.openai_service.headers['Authorization'].split(' ')[1]}",
                "Content-Type": "application/json"
            }
            
            data = {
                "model": "gpt-4-turbo-preview",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1000,
                "temperature": 0.7
            }
            
            response = await self.openai_service.make_request(
                method="POST",
                url="https://api.openai.com/v1/chat/completions",
                headers=headers,
                data=data
            )
            
            if response and "choices" in response and len(response["choices"]) > 0:
                questions_json = response["choices"][0]["message"]["content"].strip()
                
                # Parse JSON response
                try:
                    import json
                    questions_data = json.loads(questions_json)
                    
                    # Convert to GeneratedQuestion objects
                    generated_questions = []
                    for i, q_data in enumerate(questions_data):
                        question = GeneratedQuestion(
                            text=q_data.get("text", ""),
                            question_type=q_data.get("question_type", "open_ended"),
                            follow_up_prompt=q_data.get("follow_up_prompt"),
                            order=i + 1
                        )
                        generated_questions.append(question)
                    
                    logger.info(f"Generated {len(generated_questions)} research questions")
                    return generated_questions
                    
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse questions JSON: {str(e)}")
                    logger.error(f"Raw response: {questions_json}")
                    return self._generate_fallback_questions(draft_request)
            else:
                logger.warning("No response from OpenAI for question generation")
                return self._generate_fallback_questions(draft_request)
                
        except Exception as e:
            logger.error(f"Error generating research questions: {str(e)}")
            return self._generate_fallback_questions(draft_request)

    def _generate_fallback_questions(self, draft_request: FeedbackDraftRequest) -> List[GeneratedQuestion]:
        """Generate basic fallback questions when AI generation fails"""
        topic = draft_request.research_topic
        
        fallback_questions = [
            GeneratedQuestion(
                text=f"How would you rate your overall experience with {topic} on a scale of 1-10?",
                question_type="rating",
                follow_up_prompt="Please explain your rating",
                order=1
            ),
            GeneratedQuestion(
                text=f"What aspects of {topic} work well for you?",
                question_type="open_ended",
                follow_up_prompt="Can you give specific examples?",
                order=2
            ),
            GeneratedQuestion(
                text=f"What would you change or improve about {topic}?",
                question_type="open_ended",
                follow_up_prompt="What would make the biggest difference?",
                order=3
            ),
            GeneratedQuestion(
                text=f"Would you recommend {topic} to other students?",
                question_type="open_ended",
                follow_up_prompt="Why or why not?",
                order=4
            )
        ]
        
        logger.info(f"Using {len(fallback_questions)} fallback questions")
        return fallback_questions
    
    async def _generate_feedback_subject(
    self, 
    campaign_purpose: str, 
    research_topic: str, 
    target_audience: str
) -> str:
        """Generate a friendly subject line for feedback campaign emails"""
        try:
            # Use OpenAI to generate a contextual subject line
            prompt = f"""Create a friendly, engaging email subject line for a feedback campaign.

    Campaign Purpose: {campaign_purpose}
    Research Topic: {research_topic}
    Target Audience: {target_audience}

    Requirements:
    - Keep it under 50 characters
    - Make it feel personal and inviting
    - Avoid formal language
    - Don't use "Survey" or "Feedback" in the subject
    - Make students want to open and respond

    Return only the subject line, no quotes or extra text."""

            headers = {
                "Authorization": f"Bearer {self.openai_service.headers['Authorization'].split(' ')[1]}",
                "Content-Type": "application/json"
            }
            
            data = {
                "model": "gpt-4-turbo-preview",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 100,
                "temperature": 0.7
            }
            
            response = await self.openai_service.make_request(
                method="POST",
                url="https://api.openai.com/v1/chat/completions",
                headers=headers,
                data=data
            )
            
            if response and "choices" in response and len(response["choices"]) > 0:
                subject = response["choices"][0]["message"]["content"].strip()
                # Remove quotes if AI added them
                subject = subject.strip('"').strip("'")
                logger.info(f"Generated feedback subject: {subject}")
                return subject
            else:
                return self._generate_fallback_feedback_subject(campaign_purpose, research_topic)
                
        except Exception as e:
            logger.error(f"Error generating feedback subject: {str(e)}")
            return self._generate_fallback_feedback_subject(campaign_purpose, research_topic)

    async def _generate_feedback_initial_message(
        self, 
        campaign_purpose: str, 
        research_topic: str, 
        conversation_style: str, 
        target_audience: str
    ) -> str:
        """Generate the initial conversation starter message for feedback campaigns"""
        try:
            prompt = f"""Create a warm, conversational email to start a feedback conversation with students.

    Campaign Purpose: {campaign_purpose}
    Research Topic: {research_topic}
    Conversation Style: {conversation_style}
    Target Audience: {target_audience}

    Requirements:
    - Keep it warm and conversational (2-3 paragraphs max)
    - Don't mention "survey" or make it feel formal
    - Explain that you'd love to chat and hear their thoughts
    - Let them know they can just reply to this email
    - Make it feel like a genuine check-in from someone who cares
    - Use the specified conversation style
    - End with an encouraging note about responding

    Return only the message content, no subject line or signature."""

            headers = {
                "Authorization": f"Bearer {self.openai_service.headers['Authorization'].split(' ')[1]}",
                "Content-Type": "application/json"
            }
            
            data = {
                "model": "gpt-4-turbo-preview",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 400,
                "temperature": 0.7
            }
            
            response = await self.openai_service.make_request(
                method="POST",
                url="https://api.openai.com/v1/chat/completions",
                headers=headers,
                data=data
            )
            
            if response and "choices" in response and len(response["choices"]) > 0:
                message = response["choices"][0]["message"]["content"].strip()
                logger.info(f"Generated feedback initial message")
                return message
            else:
                return self._generate_fallback_feedback_message(campaign_purpose, research_topic, conversation_style)
                
        except Exception as e:
            logger.error(f"Error generating feedback initial message: {str(e)}")
            return self._generate_fallback_feedback_message(campaign_purpose, research_topic, conversation_style)


    #####PREV#######
    async def _execute_legacy_campaign(self, campaign_data: dict, campaign_context: dict, session):
        """Execute a legacy campaign immediately"""
        logger.info(f"CMP: Executing legacy campaign: {campaign_data}")
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

    # KEEP EXISTING METHODS FOR BACKWARD COMPATIBILITY
    async def create_campaign(self, campaign: dict, admin_id: str, thread_id: str = None) -> Dict:
        """
        LEGACY METHOD - Creates a campaign using the old workflow
        Maintained for backward compatibility
        """
        logger.info(f"CMP: Creating legacy campaign: {campaign} in thread: {thread_id}")
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