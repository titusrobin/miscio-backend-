# app/services/campaign_service.py
from typing import Optional, Dict, List
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorDatabase # engine that drives your MongoDB operations 
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

    async def create_campaign(self, campaign: str, admin_id: str) -> Dict: # campaign: extracted from campaign description when openai makes tool call
        """
        Creates a new campaign and initializes student outreach
        """
        logger.info(f"Creating new campaign: {campaign}")
        try:
            async with await self.db.client.start_session() as session: # Start a MongoDB session for transaction
                async with session.start_transaction():
                    campaign_data = await self._create_campaign_in_db(campaign, admin_id, session) # helper to create campaign in db

                    # student outreach 
                    students = await self.db.students.find({}, session=session).to_list(length=None) 
                    logger.info(f"Found {len(students)} active students")

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
                                session=session
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

    # limit number of docs returned from db
    # query: words lookup as args 
    async def query_student_chats(self, query: str, limit: int = 100) -> List[Dict]:  ###TODO: summarize results using openai? 
        """
        Search through student chat histories
        """
        try:
            await self.db.interactions.create_index([("message", "text")]) # organized refs: search through message field, organize it for text searching: separate data structure
 
            # Perform text search
            cursor = ( # cursor: a pointer to the first doc in the db
                self.db.interactions.find(
                    {"$text": {"$search": query}}, {"score": {"$meta": "textScore"}} # get a relevance score based on match to query 
                )
                .sort([("score", {"$meta": "textScore"})])
                .limit(limit) # limit number of docs returned from db
            )

            results = []
            async for interaction in cursor:
                student = await self.db.students.find_one( # get student details
                    {"_id": interaction["student_id"]}
                )

                campaign = await self.db.campaigns.find_one( # get campaign details
                    {"_id": interaction["campaign_id"]}
                )

                results.append(
                    {
                        "student_name": f"{student['first_name']} {student['last_name']}",
                        "campaign_description": (
                            campaign["description"] if campaign else "Unknown Campaign"
                        ),
                        "message": interaction["message"],
                        "timestamp": interaction["timestamp"],
                        "type": interaction["type"],
                    }
                )

            return results

        except Exception as e:
            logger.error(f"Error querying student chats: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to query student chats: {str(e)}",
            )

    # get statistics for a specific campaign
    async def get_campaign_stats(self, campaign_id: str) -> Dict: ###TODO: is interaction the right schema to use? 
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


# ===================================================================
# ========================== Utils ==================================
async def _create_campaign_in_db(self, campaign: str, admin_id: str, session) -> Dict:
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