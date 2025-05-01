# app/api/v1/endpoints/webhook.py
from fastapi import APIRouter, HTTPException, Depends, Form, Request, status
from app.services.openai_service import OpenAIService
from app.services.twilio_service import TwilioService
from app.services.sendgrid_service import SendGridService   
from app.db.mongodb import db
from typing import Optional
import logging
from datetime import datetime
import uuid
import json
from bson import ObjectId
from typing import Dict, List
from app.services.campaign_service import CampaignService
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

#TODO: Twilio webhook coverage 
@router.post("/webhook")
async def handle_webhook(
    request: Request,
    Body: str = Form(...),
    From: str = Form(...),
    openai_service: OpenAIService = Depends(get_openai_service),
    twilio_service: TwilioService = Depends(get_twilio_service),
):
    """
    Handles incoming webhook requests with improved validation and error handling.
    """
    try:
        # Log incoming request
        logger.info(f"Received webhook from {From}")

        # Validate and clean phone number
        phone = From.replace("whatsapp:", "").strip()
        if not phone:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid phone number format",
            )

        # Find student with error handling
        student = await db.db.students.find_one({"phone": phone})
        if not student:
            logger.warning(f"Unknown student phone number: {phone}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Student not found"
            )

        # Get active campaign
        campaign = await db.db.campaigns.find_one({"status": "active"})
        if not campaign:
            logger.warning("No active campaign found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="No active campaign found"
            )

        # Process message with OpenAI
        try:
            response = await openai_service.process_message(
                thread_id=student["thread_id"],
                message=Body.lower().strip(),
                assistant_id=campaign["assistant_id"],
            )
        except Exception as e:
            logger.error(f"OpenAI processing error: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to process message",
            )

        # Send response via Twilio
        try:
            await twilio_service.send_message(From, response)
        except Exception as e:
            logger.error(f"Twilio sending error: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to send response",
            )

        # Log successful interaction
        await db.db.interactions.insert_one(
            {
                "student_id": str(student["_id"]),
                "campaign_id": str(campaign["_id"]),
                "message": Body,
                "response": response,
                "timestamp": datetime.utcnow(),
            }
        )

        return {"status": "success"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Webhook handling error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.post("/email")
async def handle_email_webhook(
    request: Request, # access to the raw HTTP req 
    openai_service: OpenAIService = Depends(get_openai_service),
    sendgrid_service: SendGridService = Depends(get_sendgrid_service),
    campaign_service: CampaignService = Depends(get_campaign_service),
):
    """
    Handles incoming webhook requests from SendGrid for email responses.
    """
    start_time = datetime.utcnow()
    request_id = str(uuid.uuid4())[:8]  # Generate a short request ID for tracking this request in logs
    logger.info(f"[REQ-{request_id}] Email webhook received at: {start_time}")
    try:
        # Parse the incoming SendGrid webhook form data with detailed logging
        body = await request.body()
        body_size = len(body)
        logger.info(f"[REQ-{request_id}] Received email webhook raw body length: {body_size}")
        
        # Log headers for troubleshooting
        headers = dict(request.headers)
        sanitized_headers = {k: v for k, v in headers.items() 
                           if k.lower() not in ('authorization', 'cookie')}  # Remove sensitive headers
        logger.info(f"[REQ-{request_id}] Request headers: {json.dumps(sanitized_headers)}")
        
        # Parse form data with expanded logging
        form_data = await request.form()
        form_keys = list(form_data.keys())
        logger.info(f"[REQ-{request_id}] Parsed form data keys: {form_keys}")
        
        from_email = form_data.get("from")
        subject = form_data.get("subject", "")
        text_content = form_data.get("text", "")
        
        logger.info(f"[REQ-{request_id}] Extracted email details - From: {from_email}, Subject: {subject}")

        # Log message size
        text_length = len(text_content) if text_content else 0
        logger.info(f"[REQ-{request_id}] Text content length: {text_length}")
        
        # Enhanced fallback logging for email field extraction
        if not from_email and "envelope" in form_data:
            try:
                envelope_raw = form_data["envelope"]
                logger.info(f"[REQ-{request_id}] Parsing envelope: {envelope_raw}")
                envelope = json.loads(envelope_raw)
                from_email = envelope.get("from")
                logger.info(f"[REQ-{request_id}] Extracted from_email from envelope: {from_email}")
            except Exception as e:
                logger.error(f"[REQ-{request_id}] Failed to parse envelope JSON: {str(e)}")
                logger.error(f"[REQ-{request_id}] Raw envelope content: {form_data.get('envelope', 'N/A')}")
        
        if not text_content: # if no text content, use alternate content source
            alt_content = form_data.get("body-plain", "") or form_data.get("plain", "")
            logger.info(f"Using alternate content source - length: {len(alt_content) if alt_content else 0}")
            text_content = alt_content
         
        if not from_email or not text_content: # Log all available fields for debugging
            logger.error("Missing required email fields")
            for key in form_data.keys():
                logger.info(f"Available field: {key} with content: {str(form_data.get(key))[:50]}...")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid email payload format",
            )

        # Email addressing
        email_address = from_email
        if email_address and "<" in str(email_address) and ">" in str(email_address):
            email_address = str(email_address).split("<")[1].split(">")[0]
            
        student = await db.db.students.find_one({"email": email_address})
        if not student:
            logger.warning(f"Unknown student email: {email_address}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Student not found"
            )
        
        # Log student details for tracking
        student_id = str(student.get("_id", "unknown"))
        student_name = f"{student.get('first_name', '')} {student.get('last_name', '')}"
        student_thread_id = student.get("thread_id", "none")
        logger.info(f"[REQ-{request_id}] Found student: {student_name} (ID: {student_id})")
        logger.info(f"[REQ-{request_id}] Student thread_id: {student_thread_id}")
        
        # Get active campaign
        campaign = await db.db.campaigns.find_one({
            "status": "active", 
            "admin_id": str(student["admin_id"])
        })
        if not campaign:
            logger.warning("No active campaign found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="No active campaign found"
            )
        
        # Log campaign details
        campaign_id = str(campaign.get("_id", "unknown"))
        campaign_desc = campaign.get("description", "No description")
        campaign_assistant_id = campaign.get("assistant_id", "None")
        logger.info(f"[REQ-{request_id}] Found active campaign: {campaign_desc[:50]}...")
        logger.info(f"[REQ-{request_id}] Campaign ID: {campaign_id}")
        logger.info(f"[REQ-{request_id}] Campaign assistant_id: {campaign_assistant_id}")

        # Get admin associated with the campaign
        admin_id = campaign.get("admin_id")
        admin = await db.db.admin_users.find_one({"_id": ObjectId(admin_id)})
        
        if not admin:
            logger.error(f"Admin not found for campaign {campaign.get('_id')}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Admin not found for campaign"
            )
            
        # Get vector store ID from admin
        vector_store_id = admin.get("vector_store_id")
        logger.info(f"[REQ-{request_id}] Admin vector store ID: {vector_store_id}")

        # Process message with OpenAI
        try:
            if not student.get('thread_id'):
                thread_data = await openai_service.create_thread()
                thread_id = thread_data["id"]
                
                await db.db.students.update_one(
                    {"_id": student["_id"]},
                    {"$set": {"thread_id": thread_id}}
                )
                
                logger.info(f"Created new thread for student: {thread_id}")
            else:
                thread_id = student["thread_id"]
                logger.info(f"Using existing thread_id: {thread_id}")
            
            if not campaign_assistant_id:
                logger.warning(f"[REQ-{request_id}] Campaign has no assistant_id. Will need to create one.")
            
            # Get assistant ID with proper fallbacks
            assistant_id = campaign.get("assistant_id") or admin.get("assistant_id") or "asst_re59LKPfW1Fya4rwuoxVHKOa"
            logger.info(f"Using assistant ID: {assistant_id}")
            logger.info(f"Message content (first 100 chars): {text_content[:100] if text_content else ''}")
            
            # If vector store exists, attach it to the thread for this run
            thread_tool_resources = None
            if vector_store_id:
                logger.info(f"Attaching vector store {vector_store_id} to thread {thread_id}")
                thread_tool_resources = {
                    "file_search": {
                        "vector_store_ids": [vector_store_id]
                    }
                }
                
                # Update the thread with the vector store (ensures it's attached for this run)
                await openai_service.make_request(
                    method="POST",
                    url=f"{openai_service.base_url}/threads/{thread_id}",
                    headers=openai_service.headers,
                    data={"tool_resources": thread_tool_resources}
                )

            # Process message with OpenAI
            logger.info(f"Processing message with assistant {assistant_id} and thread {thread_id}")
            response = await openai_service.process_message(
                thread_id=thread_id,
                message=text_content.strip(),
                assistant_id=assistant_id,
                run_handler=lambda tool_calls: handle_student_tool_calls(
                    tool_calls, student, campaign_service
                ),
                thread_tool_resources=thread_tool_resources
            )
            
            # Send the response back to the student via email
            await sendgrid_service.send_message(
                to_email=email_address,
                subject=f"Re: {subject}",
                message=response,
                message_type="reply"
            )
            
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to process message",
            )

        # Log successful interaction in database
        await db.db.interactions.insert_one(
            {
                "student_id": str(student["_id"]),
                "campaign_id": str(campaign["_id"]),
                "message": text_content,
                "response": response,
                "contact_method": "email",
                "email_subject": subject,
                "type": "response",
                "status": "sent",
                "timestamp": datetime.utcnow(),
               # "assistant_id": campaign.get("assistant_id")  # Add the assistant_id here
                "vector_store_used": bool(vector_store_id)

            }
        )

        end_time = datetime.utcnow()
        processing_time = (end_time - start_time).total_seconds()
        logger.info(f"Email webhook processing completed in {processing_time} seconds")
        return {"success, processing time": processing_time}

    except HTTPException as http_ex:
        logger.error(f"HTTP Exception in email webhook: {http_ex.detail}")
        raise

    except Exception as e:
        logger.error(f"Email webhook handling error: {str(e)}")
        import traceback
        trace = traceback.format_exc()
        logger.error(f"Stack trace:\n{trace}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )

async def handle_student_tool_calls(
    tool_calls: List[Dict], student: Dict, campaign_service: CampaignService
) -> List[Dict]:
    """
    Processes tool calls for student interactions.
    Students should ONLY have access to file_search, not admin functions.
    Any function calls will be rejected with an appropriate error message.
    """
    logger.info(f"Handling student tool calls: {json.dumps(tool_calls, indent=2)}")
    
    tool_outputs = []
    for tool_call in tool_calls:
        try:
            tool_type = tool_call.get("type")
            tool_call_id = tool_call.get("id")
            
            logger.info(f"Processing student tool call type: {tool_type}, id: {tool_call_id}")
            
            # Handle file_search tool calls - these are fine for students to use
            if tool_type == "file_search":
                # Log that file search was used
                logger.info(f"File search tool used in student interaction")
                
                # For file_search, we don't need to provide outputs
                # The OpenAI API handles file search internally
                
                # Optionally record file search usage in the database if needed
                await db.db.interactions.update_one(
                    {"student_id": str(student["_id"])},
                    {"$set": {"used_file_search": True}},
                    upsert=False
                )
            
            # Reject any function calls - students shouldn't be able to use these
            elif tool_type == "function":
                function_name = tool_call.get("function", {}).get("name")
                logger.warning(f"Student attempted to use restricted function: {function_name}")
                
                # Return an error message indicating the function is not available to students
                tool_outputs.append(
                    {
                        "tool_call_id": tool_call_id,
                        "output": json.dumps({
                            "error": "This function is not available for student use.",
                            "status": "access_denied"
                        }),
                    }
                )
            
            # Handle any other tool types (future-proofing)
            else:
                logger.warning(f"Unknown tool type requested by student: {tool_type}")
                tool_outputs.append(
                    {
                        "tool_call_id": tool_call_id,
                        "output": json.dumps({
                            "error": "This tool is not available for student use.",
                            "status": "access_denied"
                        }),
                    }
                )
            
        except Exception as e:
            logger.error(f"Error handling student tool call: {str(e)}")
            # Always include the tool_call_id in the error response
            tool_call_id = tool_call.get("id", "unknown_id")
            tool_outputs.append(
                {
                    "tool_call_id": tool_call_id,
                    "output": json.dumps({"error": str(e)}),
                }
            )
    
    return tool_outputs