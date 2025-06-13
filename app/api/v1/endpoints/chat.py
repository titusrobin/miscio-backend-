# app/api/v1/endpoints/chat.py
import json
import logging
from typing import Dict, List
from datetime import datetime
from app.db.mongodb import db
from app.models.admin import Admin
from app.core.security import get_current_admin_user
from app.services.openai_service import OpenAIService
from app.services.campaign_service import CampaignService
from app.services.twilio_service import TwilioService
from app.services.sendgrid_service import SendGridService
from fastapi import APIRouter, Depends, HTTPException, status
from app.schemas.campaign import CampaignDraftRequest


router = APIRouter()
logger = logging.getLogger(__name__)

def get_openai_service():
    return OpenAIService()

def get_twilio_service():
    return TwilioService()

def get_sendgrid_service():
    return SendGridService()

def get_campaign_service(
    openai_service: OpenAIService = Depends(get_openai_service),
    twilio_service: TwilioService = Depends(get_twilio_service),
    sendgrid_service: SendGridService = Depends(get_sendgrid_service)
):
    return CampaignService(openai_service, twilio_service, sendgrid_service, db.db)

# TODO: process_message() and create_message() are almost identical, 
# refactor to use a single function? abstract database operations acc to need 


# When a request comes in to /history/{thread_id}, it includes an Authorization: Bearer <token> header
# The oauth2_scheme dependency extracts this token
# When a user logs in, the server generates a token and sends it to the client and the client stores it in local storage. Client then includes this token in the Authorization header of all subsequent requests.
# The token is not part of the URL. It's sent in the HTTP request header. 
# GET /api/v1/history/thread_123456 HTTP/1.1
# Host: api.miscioapp.com (server domain)
# Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJqb2huLmRvZSIsImV4cCI6MTY5ODc2NTQzMn0.8Tj7Wt8lKS_MgD-hNHpPpB9hO5K0q6Jw2xZ3QFfaVYY
# Accept: application/json
@router.get("/history/{thread_id}")
async def get_chat_history(thread_id: str, 
                           current_admin: Admin = Depends(get_current_admin_user)): #dependency injection for current admin of existing token(just extracted from header)
    """
    Retrieve chat history for a specific thread.
    """
    logger.info(f"GET /history/{thread_id} - Retrieving chat history")
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
    message: Dict[str, str], #Type annotation to expect a dictionary with string keys and string values
    current_admin: Admin = Depends(get_current_admin_user),
    openai_service: OpenAIService = Depends(get_openai_service),
    campaign_service: CampaignService = Depends(get_campaign_service),
):
    """
    Process a message from an admin to their assistant
    """
    logger.info(f"POST /message - Processing admin message. Message data: {message}")
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

        # Generate loading messages immediately (for testing - just log them)
        try:
            loading_messages = await openai_service.generate_loading_messages(content)
            logger.info(f"Generated loading messages: {loading_messages}")
        except Exception as e:
            logger.error(f"Failed to generate loading messages: {str(e)}")
            loading_messages = openai_service._get_fallback_messages()
            logger.info(f"Using fallback messages: {loading_messages}")

        # Process the message with function calling support
        response = await openai_service.process_message(
            thread_id=current_admin.thread_id,
            message=content,
            assistant_id=current_admin.assistant_id,
            # Lambda function - compact way to define a function without naming it.
            run_handler = lambda tool_calls: handle_tool_calls( # defined but NOT executed unless called, this is not like depends(), we're passing the function itself 
                tool_calls, current_admin, campaign_service, current_admin.thread_id
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
    """
    Create a new chat thread for the current admin(when new threads on miscio admin dashboard are created)
    """
    logger.info(f"POST /threads - Creating new thread for admin {current_admin.id}")
    try:
        # Create OpenAI thread
        thread_data = await openai_service.create_thread()

        thread = { #create a new thread doc to be stored in mongodb
            "id": thread_data["id"], # Returns new thread id from openai 
            "title": "New Chat",
            "admin_id": str(current_admin.id),
            "assistant_id": current_admin.assistant_id,
            "created_at": datetime.utcnow(),
            "last_activity": datetime.utcnow(),
            "last_message": "",
        }

        result = await db.db.threads.insert_one(thread) # This _id is returned as part of the insert operation result
        thread["_id"] = str(result.inserted_id) # Convert _id ObjectId to string
        return thread
    
    except Exception as e:
        logger.error(f"Error creating thread: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/threads")
async def get_threads(current_admin: Admin = Depends(get_current_admin_user)):
    """
    Retrieves all conversation threads for the current admin user, 
    which would be used to populate the chat screen in an admin dashboard
    Note: Does not contain the messages, only the thread metadata
    """
    logger.info(f"GET /threads - Retrieving all threads for admin {current_admin.id}")
    try:
        cursor = db.db.threads.find({"admin_id": str(current_admin.id)})
        threads = await cursor.to_list(length=None) # retrieves all matching documents as a list

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
                "last_message": thread.get("last_message", ""), # safely handle cases where a thread might not have a last_message field
                "_id": str(thread["_id"]),  
            }
            formatted_threads.append(formatted_thread)

        formatted_threads.sort(key=lambda x: x["last_activity"], reverse=True) # Sort by last activity, most recent first

        return formatted_threads
    
    except Exception as e:
        logger.error(f"Error fetching threads: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/threads/{thread_id}/messages") # {thread_id} is a placeholder syntax that defines a path parameter
async def get_thread_messages(
    thread_id: str,
    current_admin: Admin = Depends(get_current_admin_user),
):
    """
    Retrieves all messages for a specific thread, 
    which would be used to populate a single chat conversation in the admin dashboard
    """
    logger.info(f"GET /threads/{thread_id}/messages - Retrieving messages for thread")
    try:
        chat_history = await db.db.chat_histories.find_one(
            {"thread_id": thread_id, "admin_id": str(current_admin.id)}
        )

        if chat_history:
            messages = chat_history["messages"]
            for message in messages:
                if isinstance(message["timestamp"], datetime):
                    message["timestamp"] = message["timestamp"].isoformat() # Convert datetime to ISO 8601 format

            return messages
        return [] # Return an empty list if no chat history is found

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
    logger.info(f"POST /threads/{thread_id}/messages - Creating new message in thread")
    try:
        content = message.get("content", "")
        
        # Generate loading messages immediately (for testing - just log them)
        try:
            loading_messages = await openai_service.generate_loading_messages(content)
            logger.info(f"Generated loading messages for thread message: {loading_messages}")
        except Exception as e:
            logger.error(f"Failed to generate loading messages: {str(e)}")
            loading_messages = openai_service._get_fallback_messages()
            logger.info(f"Using fallback messages: {loading_messages}")

        response = await openai_service.process_message(
            thread_id=thread_id,
            message=message["content"],
            assistant_id=current_admin.assistant_id,
            run_handler=lambda tool_calls: handle_tool_calls(
                tool_calls, current_admin, campaign_service, thread_id
            ),
        )

        messages = [ #create message array to be stored in mongodb
            {
                "role": "user",
                "content": message["content"],
                "timestamp": datetime.utcnow(),
            },
            {"role": "assistant", "content": response, "timestamp": datetime.utcnow()},
        ]
        # MongoDB transaction to ensure that both database updates succeed or fail together
        async with await db.db.client.start_session() as session:
            async with session.start_transaction():

                await db.db.chat_histories.update_one( # 1
                    {"thread_id": thread_id, "admin_id": str(current_admin.id)},
                    {
                        "$push": {"messages": {"$each": messages}},
                    },
                    upsert=True,
                    session=session,  # Important: Pass the session to the operation as part of transaction
                )
 
                await db.db.threads.update_one( # 2
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

@router.put("/threads/{thread_id}/title")
async def update_thread_title(
    thread_id: str,
    title_data: dict,
    current_admin: Admin = Depends(get_current_admin_user)
):
    """Update the title of a thread."""
    logger.info(f"PUT /threads/{thread_id}/title - Updating title")
    try:
        title = title_data.get("title")
        if not title:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Title is required"
            )
        
        result = await db.db.threads.update_one(
            {"id": thread_id, "admin_id": str(current_admin.id)},
            {"$set": {"title": title}}
        )
        
        if result.modified_count == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Thread not found or unauthorized"
            )
        
        return {"success": True, "title": title}
    
    except Exception as e:
        logger.error(f"Error updating thread title: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@router.post("/loading-messages")
async def generate_loading_messages_endpoint(
    message: Dict[str, str],
    current_admin: Admin = Depends(get_current_admin_user),
    openai_service: OpenAIService = Depends(get_openai_service),
):
    """
    Generate contextual loading messages for a user prompt - frontend endpoint
    """
    logger.info(f"POST /loading-messages - Generating loading messages")
    try:
        content = message.get("content")
        if not content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Message content is required",
            )

        # Generate loading messages
        try:
            loading_messages = await openai_service.generate_loading_messages(content)
            logger.info(f"Generated {len(loading_messages)} loading messages for frontend")
            return {"loading_messages": loading_messages}
        except Exception as e:
            logger.error(f"Failed to generate loading messages: {str(e)}")
            # Return fallback messages
            fallback_messages = openai_service._get_fallback_messages()
            return {"loading_messages": fallback_messages}

    except Exception as e:
        logger.error(f"Error in loading messages endpoint: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail=str(e)
        )



# =====================================================================
#================================Utils=================================
async def handle_tool_calls(
    tool_calls: List[Dict], current_admin: Admin, campaign_service: CampaignService, thread_id: str
) -> List[Dict]:
    """
    Processes function calls requested by the OpenAI assistant and returns the results.
    Updated to handle the new draft-approval workflow.
    """
    
    tool_outputs = []
    for tool_call in tool_calls:
        try:
            function_name = tool_call["function"]["name"]
            arguments = json.loads(tool_call["function"]["arguments"])
            logger.info(
                f"Handling function call: {function_name} with arguments: {arguments}"
            )

            if function_name == "create_messaging_draft":
                # Create draft campaign using new workflow
                try:
                    # Create CampaignDraftRequest from arguments
                    draft_request = CampaignDraftRequest(
                        campaign_purpose=arguments.get("campaign_purpose", ""),
                        campaign_details=arguments.get("campaign_details", ""),
                        target_audience=arguments.get("target_audience", "all students"),
                        tone_and_style=arguments.get("tone_and_style", "friendly and helpful"),
                        key_points=arguments.get("key_points", ""),
                        call_to_action=arguments.get("call_to_action", "respond with any questions"),
                        thread_id=thread_id
                    )
                    
                    # Create the draft campaign
                    result = await campaign_service.create_messaging_draft(
                        draft_request=draft_request,
                        admin_id=current_admin.id,
                        thread_id=thread_id
                    )
                    
                    # Get the generated draft content
                    draft_content = result.get("draft_content", {})
                    draft_message = draft_content.get("message", "Draft message not available")
                    
                    # Format response for the assistant
                    response_message = f"""Draft created successfully! Here's the message I generated:

{draft_message}

The draft has been saved and is ready for your review."""
                    
                    tool_outputs.append(
                        {
                            "tool_call_id": tool_call["id"],
                            "output": json.dumps(
                                {
                                    "status": "success",
                                    "message": response_message,
                                    "campaign_id": result.get("id"),
                                    "draft_content": draft_content,
                                    "thread_id": thread_id
                                }
                            ),
                        }
                    )
                    
                    logger.info(f"Successfully created draft campaign: {result.get('id')}")
                    
                except Exception as e:
                    logger.error(f"Error creating messaging draft: {str(e)}")
                    tool_outputs.append(
                        {
                            "tool_call_id": tool_call["id"],
                            "output": json.dumps({
                                "status": "error",
                                "message": f"Failed to create draft: {str(e)}"
                            }),
                        }
                    )

            elif function_name == "query_student_chats":
                # Keep existing query_student_chats functionality
                try:
                    chat_results = await campaign_service.query_student_chats(
                        query=arguments.get("query", ""),
                        thread_id=thread_id
                    )
                    tool_outputs.append(
                        {
                            "tool_call_id": tool_call["id"],
                            "output": json.dumps({"results": chat_results}),
                        }
                    )
                except Exception as e:
                    logger.error(f"Error querying student chats: {str(e)}")
                    tool_outputs.append(
                        {
                            "tool_call_id": tool_call["id"],
                            "output": json.dumps({
                                "status": "error",
                                "message": f"Failed to query chats: {str(e)}"
                            }),
                        }
                    )

            # Handle legacy function name for backward compatibility
            elif function_name == "run_campaign":
                logger.warning("Legacy run_campaign function called - redirecting to create_messaging_draft")
                # Map old parameters to new format
                try:
                    draft_request = CampaignDraftRequest(
                        campaign_purpose=arguments.get("campaign_purpose", arguments.get("title", "")),
                        campaign_details=arguments.get("campaign_details", ""),
                        target_audience=arguments.get("target_audience", "all students"),
                        tone_and_style=arguments.get("tone_and_style", "friendly and helpful"),
                        key_points=arguments.get("key_points", ""),
                        call_to_action=arguments.get("call_to_action", "respond with any questions"),
                        thread_id=thread_id
                    )
                    
                    result = await campaign_service.create_messaging_draft(
                        draft_request=draft_request,
                        admin_id=current_admin.id,
                        thread_id=thread_id
                    )
                    
                    tool_outputs.append(
                        {
                            "tool_call_id": tool_call["id"],
                            "output": json.dumps({
                                "status": "success",
                                "message": f"Draft created (legacy mode). Campaign ID: {result.get('id')}",
                                "campaign_id": result.get("id")
                            }),
                        }
                    )
                except Exception as e:
                    tool_outputs.append(
                        {
                            "tool_call_id": tool_call["id"],
                            "output": json.dumps({
                                "status": "error", 
                                "message": f"Legacy campaign creation failed: {str(e)}"
                            }),
                        }
                    )

            else:
                logger.warning(f"Unknown function called: {function_name}")
                tool_outputs.append(
                    {
                        "tool_call_id": tool_call["id"],
                        "output": json.dumps({
                            "status": "error",
                            "message": f"Unknown function: {function_name}"
                        }),
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

    return tool_outputs # return tool_outputs so that OpenAI can incorporate the results of the function calls into its response to the admin
