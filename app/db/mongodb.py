# app/db/mongodb.py
import logging
from motor.motor_asyncio import AsyncIOMotorClient  
from app.core.config import settings
from typing import Optional
from typing import no_type_check # Tells Python to ignore type checking for this class

log = logging.getLogger(__name__)

@no_type_check
class MongoDB:
    """Manages MongoDB connections"""
    # This is a special client for connecting to MongoDB that works with async/await code
    # "Awaited" - "wait for this task to finish, but let other tasks run while waiting."
    client: AsyncIOMotorClient = None  # class variable to hold the MongoDB client
    db = None # class variable to hold the database reference

    async def connect_to_database(self):
        # log.info("Connecting to MongoDB")
        self.client = AsyncIOMotorClient(settings.MONGODB_URL)
        self.db = self.client[settings.MONGODB_DB_NAME]
        # log.info("Connected to MongoDB")

    async def close_database_connection(self):
        if self.client:
            self.client.close()

db = MongoDB() # single instance of the MongoDB class that can be imported and used throughout the application.
