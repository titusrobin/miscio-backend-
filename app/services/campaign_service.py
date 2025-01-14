# app/services/campaign_service.py
from typing import Optional, Dict, List
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi import HTTPException, status
from .openai_service import OpenAIService
from .twilio_service import TwilioService
import logging

logger = logging.getLogger(__name__)


class CampaignService:
    def __init__(
        self,
        openai_service: OpenAIService,
        twilio_service: TwilioService,
        database: AsyncIOMotorDatabase,  # type: ignore
    ):
        self.openai_service = openai_service
        self.twilio_service = twilio_service
        self.db = database

    async def create_campaign(self, campaign: str, admin_id: str) -> Dict:
        """
        Creates a new campaign and initializes student outreach
        """
        logger.info(f"Creating new campaign: {campaign}")
        try:
            # Start a MongoDB session for transaction
            async with await self.db.client.start_session() as session:
                async with session.start_transaction():
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

                    # Insert campaign
                    result = await self.db.campaigns.insert_one(
                        campaign_data, session=session
                    )
                    campaign_data["id"] = str(result.inserted_id)

                    # Get all active students
                    students = await self.db.students.find({}, session=session).to_list(length=None)
                    logger.info(f"Found {len(students)} active students")

                    # Start student outreach
                    for student in students:
                        try:
                            initial_message = f"Hi {student['first_name']}, {campaign}"
                            logger.debug(f"Sending message to student {student['_id']}: {initial_message}")
                            await self.twilio_service.send_message(
                                student["phone"], initial_message
                            )

                            # Record the outreach
                            logger.debug(f"Recording outreach for student {student['_id']}")
                            await self.db.interactions.insert_one(
                                {
                                    "campaign_id": str(result.inserted_id),
                                    "student_id": str(student["_id"]),
                                    "message": initial_message,
                                    "type": "initial",
                                    "status": "sent",
                                    "timestamp": datetime.utcnow(),
                                },
                                session=session,
                            )

                        except Exception as e:
                            logger.error(
                                f"Error processing student {student['_id']}: {str(e)}"
                            )
                            continue

                    return campaign_data

        except Exception as e:
            logger.error(f"Error creating campaign: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create campaign: {str(e)}",
            )

    async def query_student_chats(self, query: str, limit: int = 100) -> List[Dict]:
        """
        Search through student chat histories
        """
        try:
            # Create text search index if it doesn't exist
            await self.db.interactions.create_index([("message", "text")])

            # Perform text search
            cursor = (
                self.db.interactions.find(
                    {"$text": {"$search": query}}, {"score": {"$meta": "textScore"}}
                )
                .sort([("score", {"$meta": "textScore"})])
                .limit(limit)
            )

            results = []
            async for interaction in cursor:
                # Get student details
                student = await self.db.students.find_one(
                    {"_id": interaction["student_id"]}
                )

                # Get campaign details
                campaign = await self.db.campaigns.find_one(
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

    async def get_campaign_stats(self, campaign_id: str) -> Dict:
        """
        Get statistics for a specific campaign
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
