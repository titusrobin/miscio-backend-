# app/db/mongodb.py
from motor.motor_asyncio import AsyncIOMotorClient  # type: ignore
from app.core.config import settings
from typing import Optional
from typing import no_type_check
import logging

logger = logging.getLogger(__name__)


@no_type_check
class MongoDB:
    client: AsyncIOMotorClient = None  # type: ignore
    db = None

    async def connect_to_database(self):
        logger.info("Connecting to MongoDB")
        print(
            f"Connecting to MongoDB with URL: {settings.MONGODB_URL}"
        )  # Add this line
        self.client = AsyncIOMotorClient(settings.MONGODB_URL)
        self.db = self.client[settings.MONGODB_DB_NAME]
        logger.info("Connected to MongoDB")

    async def close_database_connection(self):
        if self.client:
            self.client.close()


db = MongoDB()
