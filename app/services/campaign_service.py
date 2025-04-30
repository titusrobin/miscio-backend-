# app/services/campaign_service.py
from typing import Optional, Dict, List
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi import HTTPException, status
from app.services.openai_service import OpenAIService
from app.services.twilio_service import TwilioService
from app.services.sendgrid_service import SendGridService  

import logging
logger = logging.getLogger(__name__)

# These service objects are "pseudo modules" that CampaignService 
# keeps on hand to use behaviorally like modules. 
class CampaignService: 
    def __init__( 
        self,
        openai_service: OpenAIService,
        twilio_service: TwilioService,
        sendgrid_service: SendGridService,
        database: AsyncIOMotorDatabase,  
    ):
        self.openai_service = openai_service # encapsulates all dependencies in one place
        self.twilio_service = twilio_service 
        self.sendgrid_service = sendgrid_service
        self.db = database

    async def _create_campaign_in_db(self, campaign: str, admin_id: str, thread_id: str, session) -> Dict:
        """
        Helper method to create a campaign in the database within a transaction.
        """
        # Deactivate existing campaigns
        await self.db.campaigns.update_many(
            {"status": "active"},
            {"$set": {"status": "inactive"}},
            session=session,
        )

        # Create campaign data
        campaign_data = {
            "description": campaign,
            "admin_id": admin_id,
            "thread_id": thread_id,
            "status": "active",
            "created_at": datetime.utcnow(),
        }
        
        # Insert the campaign
        result = await self.db.campaigns.insert_one(
            campaign_data, session=session
        )
        campaign_data["id"] = str(result.inserted_id)
        
        return campaign_data

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
        session = None
    ):
        """
        Helper method to record a student interaction in the database.
        """
        interaction_data = {
            "campaign_id": str(campaign_id),
            "student_id": str(student_id),
            "message": message,
            "type": interaction_type,
            "contact_method": contact_method,
            "status": status,
            "timestamp": datetime.utcnow(),
        }
        # Add email subject if provided or if contact method is email
        if email_subject or contact_method == "email":
            interaction_data["email_subject"] = email_subject or "Message from Miscio Assistant"
        
        # Add assistant ID if provided
        if assistant_id:
            interaction_data["assistant_id"] = assistant_id
        
        # Insert the interaction record
        await self.db.interactions.insert_one(interaction_data, session=session)
        
        logger.debug(f"Recorded {interaction_type} interaction for student {student_id}")
        return interaction_data

    async def create_campaign(self, campaign: str, admin_id: str, thread_id: str = None) -> Dict:
        """
        Creates a new campaign and initializes student outreach
        """
        logger.info(f"Creating new campaign: {campaign} in thread: {thread_id}")
        try:
            async with await self.db.client.start_session() as session:
                async with session.start_transaction():
                    campaign_data = await self._create_campaign_in_db(campaign, admin_id, thread_id, session)

                    # student outreach 
                    students = await self.db.students.find({"admin_id": admin_id, "status": "active"}, session=session).to_list(length=None) 
                    logger.info(f"Found {len(students)} active students for admin {admin_id}")

                    for student in students: 
                        try:
                            initial_message = f"Hi {student['first_name']}, {campaign}" #TODO: make this dynamic
                            logger.debug(f"Initial message for student {student['_id']}: '{initial_message}'")
                            
                            # mode of contact
                            if 'email' in student and student.get('preferred_contact_method') == 'email': 
                                await self.sendgrid_service.send_message(
                                    to_email=student["email"],
                                    subject="Message from Miscio Assistant",
                                    message=initial_message
                                )
                                contact_method = "email"
                            elif 'phone' in student:
                                await self.twilio_service.send_message(
                                    student["phone"], initial_message
                                )
                                contact_method = "whatsapp"
                            else:
                                logger.warning(f"No valid contact method for student {student['_id']}")
                                continue
                            
                            # Record the outreach in db
                            await self._record_student_interaction( 
                                campaign_id=str(campaign_data["id"]),
                                student_id=str(student["_id"]),
                                message=initial_message,
                                contact_method=contact_method,
                                email_subject="Message from Miscio Assistant" if contact_method == "email" else None,
                                assistant_id=campaign_data.get("assistant_id"),
                                session=session,
                                admin_id=admin_id
                            )
                        except Exception as e:
                            logger.error(f"Error processing student {student['_id']}: {str(e)}")
                            continue

                    return campaign_data

        except Exception as e:
            logger.error(f"Error creating campaign: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create campaign: {str(e)}",
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

    async def get_campaign_stats(self, campaign_id: str) -> Dict:
        """
        Get statistics for a specific campaign.
    
        Calculates key metrics including total students reached, number of responses 
        received, and the overall response rate as a percentage.
        
        Returns:
            Dictionary containing total_students, responses_received, and response_rate
        """
        try:
            stats = {
                "total_students": await self.db.interactions.count_documents(
                    {"campaign_id": campaign_id}
                ),
                "responses_received": await self.db.interactions.count_documents(
                    {"campaign_id": campaign_id, "type": "response"}
                ),
            }

            if stats["total_students"] > 0:
                stats["response_rate"] = (
                    stats["responses_received"] / stats["total_students"]
                ) * 100
            else:
                stats["response_rate"] = 0

            return stats

        except Exception as e:
            logger.error(f"Error getting campaign stats: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get campaign stats: {str(e)}",
            )
