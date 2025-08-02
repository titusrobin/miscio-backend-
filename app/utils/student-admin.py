#!/usr/bin/env python
# scripts/migrate_students.py
import asyncio
import logging
from motor.motor_asyncio import AsyncIOMotorClient
import os
from datetime import datetime

# Setup logging
#logging.basicConfig(
#     level=logging.INFO,
#     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
# )
logger = logging.getLogger(__name__)

# Caleb's admin ID from the screenshot
CALEB_ADMIN_ID = "680f9da0a2a4e633103ed985"

async def migrate_students():
    """
    Adds admin_id field to all student records that don't have it,
    setting it to Caleb's admin ID.
    """
    # Get MongoDB URL from environment or use a default for local testing
    mongo_url = os.environ.get("MONGODB_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("MONGODB_DB_NAME", "MiscioP1")
    
    # logger.info(f"Connecting to MongoDB at {mongo_url}")
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    
    # Get count of students without admin_id
    count = await db.students.count_documents({"admin_id": {"$exists": False}})
    # logger.info(f"Found {count} students without admin_id")
    
    if count > 0:
        # Update all students without admin_id to use Caleb's admin ID
        result = await db.students.update_many(
            {"admin_id": {"$exists": False}},
            {"$set": {"admin_id": CALEB_ADMIN_ID}}
        )
        # logger.info(f"Updated {result.modified_count} students with Caleb's admin_id")
    
    # Log total student count after migration
    total_count = await db.students.count_documents({})
    caleb_students = await db.students.count_documents({"admin_id": CALEB_ADMIN_ID})
    # logger.info(f"Total students in database: {total_count}")
    # logger.info(f"Students assigned to Caleb: {caleb_students}")
    
    # logger.info("Migration completed successfully")

if __name__ == "__main__":
    logger.info("Starting student migration")
    start_time = datetime.now()
    asyncio.run(migrate_students())
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    logger.info(f"Migration completed in {duration} seconds")