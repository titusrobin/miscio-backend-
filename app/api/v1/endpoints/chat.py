# app/api/v1/endpoints/chat.py
from fastapi import APIRouter, Depends, HTTPException, status
from app.models.admin import Admin
from app.core.security import get_current_admin_user
from app.services.openai_service import OpenAIService
from app.services.campaign_service import CampaignService
from app.db.mongodb import db
from app.services.twilio_service import TwilioService
from typing import Dict, List
import logging
import json
from datetime import datetime

router = APIRouter()
logger = logging.getLogger(__name__)


def get_openai_service():
    return OpenAIService()


def get_campaign_service():
    openai_service = OpenAIService()
    twilio_service = TwilioService()
    return CampaignService(openai_service, twilio_service, db.db)


async def handle_tool_calls(
    tool_calls: List[Dict], current_admin: Admin, campaign_service: CampaignService
) -> List[Dict]:
    """Handle function calls from the OpenAI assistant"""
    logger.info(f"Received tool calls to process: {json.dumps(tool_calls, indent=2)}")

    tool_outputs = []

    for tool_call in tool_calls:
        try:
            function_name = tool_call["function"]["name"]
            arguments = json.loads(tool_call["function"]["arguments"])
            logger.info(
                f"Handling function call: {function_name} with arguments: {arguments}"
            )

            if function_name == "run_campaign":
                # Execute campaign
                result = await campaign_service.create_campaign(
                    campaign=arguments["campaign_description"],
                    admin_id=current_admin.id,
                )

                tool_outputs.append(
                    {
                        "tool_call_id": tool_call["id"],
                        "output": json.dumps(
                            {
                                "status": "success",
                                "message": f"Campaign started successfully with description: {arguments['campaign_description']}",
                            }
                        ),
                    }
                )

            elif function_name == "query_student_chats":
                # Query student chats
                chat_results = await campaign_service.query_student_chats(
                    query=arguments["query"]
                )

                tool_outputs.append(
                    {
                        "tool_call_id": tool_call["id"],
                        "output": json.dumps({"results": chat_results}),
                    }
                )

            logger.info(f"Function call handled successfully: {function_name}")

        except Exception as e:
            logger.error(f"Error handling tool call: {str(e)}")
            tool_outputs.append(
                {
                    "tool_call_id": tool_call["id"],
                    "output": json.dumps({"error": str(e)}),
                }
            )

    return tool_outputs


@router.get("/history/{thread_id}")
async def get_chat_history(
    thread_id: str,
    current_admin: Admin = Depends(get_current_admin_user),
):
    """
    Retrieve chat history for a specific thread.
    """
    try:
        chat_history = await db.db.admin_chats.find_one({"thread_id": thread_id})
        if not chat_history:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Chat history not found"
            )
        return chat_history["messages"]
    except Exception as e:
        logger.error(f"Error retrieving chat history: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve chat history",
        )


@router.post("/message")
async def process_message(
    message: Dict[str, str],
    current_admin: Admin = Depends(get_current_admin_user),
    openai_service: OpenAIService = Depends(get_openai_service),
    campaign_service: CampaignService = Depends(get_campaign_service),
):
    """
    Process a message from an admin to their assistant
    """
    logger.info("Received request to process message")
    try:
        content = message.get("content")
        if not content:
            logger.error("Message content is missing")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Message content is required",
            )

        logger.info(f"Processing message: {content}")
        logger.info(
            f"Admin ID: {current_admin.id}, Thread ID: {current_admin.thread_id}, Assistant ID: {current_admin.assistant_id}"
        )

        # Process the message with function calling support
        response = await openai_service.process_message(
            thread_id=current_admin.thread_id,
            message=content,
            assistant_id=current_admin.assistant_id,
            run_handler=lambda tool_calls: handle_tool_calls(
                tool_calls, current_admin, campaign_service
            ),
        )

        logger.info(f"Received response: {response}")
        return {"response": response}

    except Exception as e:
        logger.error(f"Error processing message: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@router.post("/threads")
async def create_thread(
    current_admin: Admin = Depends(get_current_admin_user),
    openai_service: OpenAIService = Depends(get_openai_service),
):
    try:
        # Create OpenAI thread
        thread_data = await openai_service.create_thread()

        thread = {
            "id": thread_data["id"],
            "title": "New Chat",
            "admin_id": str(current_admin.id),
            "assistant_id": current_admin.assistant_id,
            "created_at": datetime.utcnow(),
            "last_activity": datetime.utcnow(),
            "last_message": "",
        }

        result = await db.db.threads.insert_one(thread)
        thread["_id"] = str(result.inserted_id)
        return thread
    except Exception as e:
        logger.error(f"Error creating thread: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/threads")
async def get_threads(current_admin: Admin = Depends(get_current_admin_user)):
    try:
        # Get threads from database
        cursor = db.db.threads.find({"admin_id": str(current_admin.id)})
        threads = await cursor.to_list(length=None)

        # Convert ObjectIds to strings and format response
        formatted_threads = []
        for thread in threads:
            formatted_thread = {
                "id": thread["id"],
                "title": thread["title"],
                "admin_id": thread["admin_id"],
                "assistant_id": thread["assistant_id"],
                "created_at": thread["created_at"],
                "last_activity": thread["last_activity"],
                "last_message": thread.get("last_message", ""),
                "_id": str(thread["_id"]),  # Convert ObjectId to string
            }
            formatted_threads.append(formatted_thread)

        # Sort by last activity, most recent first
        formatted_threads.sort(key=lambda x: x["last_activity"], reverse=True)

        return formatted_threads
    except Exception as e:
        logger.error(f"Error fetching threads: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/threads/{thread_id}/messages")
async def get_thread_messages(
    thread_id: str,
    current_admin: Admin = Depends(get_current_admin_user),
):
    try:
        # Get chat history
        chat_history = await db.db.chat_histories.find_one(
            {"thread_id": thread_id, "admin_id": str(current_admin.id)}
        )

        if chat_history:
            # Convert ObjectId to string if present
            if "_id" in chat_history:
                chat_history["_id"] = str(chat_history["_id"])

            # Format message timestamps
            messages = chat_history["messages"]
            for message in messages:
                if isinstance(message["timestamp"], datetime):
                    message["timestamp"] = message["timestamp"].isoformat()

            return messages
        return []

    except Exception as e:
        logger.error(f"Error fetching messages: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/threads/{thread_id}/messages")
async def create_message(
    thread_id: str,
    message: dict,
    current_admin: Admin = Depends(get_current_admin_user),
    openai_service: OpenAIService = Depends(get_openai_service),
    campaign_service: CampaignService = Depends(get_campaign_service),
):
    try:
        # Pass the run handler for function calling
        response = await openai_service.process_message(
            thread_id=thread_id,
            message=message["content"],
            assistant_id=current_admin.assistant_id,
            run_handler=lambda tool_calls: handle_tool_calls(
                tool_calls, current_admin, campaign_service
            ),
        )

        messages = [
            {
                "role": "user",
                "content": message["content"],
                "timestamp": datetime.utcnow(),
            },
            {"role": "assistant", "content": response, "timestamp": datetime.utcnow()},
        ]

        # Now handle database updates within a transaction
        async with await db.db.client.start_session() as session:
            async with session.start_transaction():
                # Update chat history
                await db.db.chat_histories.update_one(
                    {"thread_id": thread_id, "admin_id": str(current_admin.id)},
                    {
                        "$push": {"messages": {"$each": messages}},
                    },
                    upsert=True,
                    session=session,  # Important: Pass the session to the operation
                )

                # Update thread last activity
                await db.db.threads.update_one(
                    {"id": thread_id},
                    {
                        "$set": {
                            "last_message": message["content"],
                            "last_activity": datetime.utcnow(),
                        }
                    },
                    session=session,  # Important: Pass the session to the operation
                )

        return {"messages": messages}

    except Exception as e:
        logger.error(f"Error processing message: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )
