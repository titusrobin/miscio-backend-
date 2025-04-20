# add_test_student.py
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
from bson import ObjectId

async def add_student():
    # Connect to MongoDB - update with your connection string
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    db = client.MiscioP1
    
    # Create test student
    student = {
        "first_name": "Test",
        "last_name": "Student",
        "email": "test@example.com",
        "preferred_contact_method": "email",
        "status": "active",
        "thread_id": "thread_123456",  # Replace with a real thread ID if needed
        "created_at": datetime.utcnow()
    }
    
    # Insert student
    result = await db.students.insert_one(student)
    print(f"Inserted student with ID: {result.inserted_id}")

if __name__ == "__main__":
    asyncio.run(add_student())