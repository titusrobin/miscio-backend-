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
from app.services.feedback_conversation import FeedbackConversationService
from app.models.feedback_conversation import ConversationStatus

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

def get_feedback_conversation_service(
    openai_service: OpenAIService = Depends(get_openai_service)
):
    return FeedbackConversationService(db.db, openai_service)


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
        # logger.info(f"CMP: PHONE? Received webhook from {From}")

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
    logger.warning(f"handle_email_webhook() Email webhook received -  [REQ-{request_id}] ")
    try:
        # Parse the incoming SendGrid webhook form data with detailed logging
        body = await request.body()
        body_size = len(body)
        
        # Log headers for troubleshooting
        headers = dict(request.headers)
        sanitized_headers = {k: v for k, v in headers.items() 
                           if k.lower() not in ('authorization', 'cookie')}  # Remove sensitive headers
        
        # Parse form data with expanded logging
        form_data = await request.form()
        form_keys = list(form_data.keys())
        logger.warning(f"handle_email_webhook() - Form data: {form_data}")
        
        from_email = form_data.get("from")
        subject = form_data.get("subject", "")
        text_content = form_data.get("text", "")

        # NEW: Capture email threading headers from incoming email
        headers_raw = form_data.get("headers", "")
        message_id = None
        references = None
        
        # Parse headers to extract Message-ID and References
        if headers_raw:
            # Headers come as a string, parse them
            for line in headers_raw.split('\n'):
                if line.startswith("Message-ID:"):
                    message_id = line.replace("Message-ID:", "").strip()
                elif line.startswith("References:"):
                    references = line.replace("References:", "").strip()
        
        # Alternative: Check if SendGrid provides these in a different format
        if not message_id:
            # Some webhook providers put it directly in form data
            message_id = form_data.get("message-id") or form_data.get("Message-ID")
        
        logger.warning(f"handle_email_webhook() - Incoming email Message-ID: {message_id}, References: {references}")
        
        # Log message size
        text_length = len(text_content) if text_content else 0
        
        # Enhanced fallback logging for email field extraction
        if not from_email and "envelope" in form_data:
            try:
                envelope_raw = form_data["envelope"]
                # logger.info(f"[REQ-{request_id}] Parsing envelope: {envelope_raw}")
                envelope = json.loads(envelope_raw)
                from_email = envelope.get("from")
             #   logger.info(f"[REQ-{request_id}] Extracted from_email from envelope: {from_email}")
            except Exception as e:
                logger.error(f"[REQ-{request_id}] Failed to parse envelope JSON: {str(e)}")
                logger.error(f"[REQ-{request_id}] Raw envelope content: {form_data.get('envelope', 'N/A')}")
        
        if not text_content: # if no text content, use alternate content source
            alt_content = form_data.get("body-plain", "") or form_data.get("plain", "")
            text_content = alt_content
         
        if not from_email or not text_content: # Log all available fields for debugging
            #logger.error("Missing required email fields")
            #for key in form_data.keys():
                #logger.info(f"Available field: {key} with content: {str(form_data.get(key))[:50]}...")
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
        #logger.info(f"[REQ-{request_id}] Found student: {student_name} (ID: {student_id})")
        #logger.info(f"[REQ-{request_id}] Student thread_id: {student_thread_id}")
        
        # Updated campaign query to handle new status system
        campaign = await db.db.campaigns.find_one({
            "admin_id": str(student["admin_id"]),
            "$or": [
                {"status": {"$in": ["executing", "completed"]}},
                {"status": "active"}  # Legacy support
            ]
        }, sort=[("created_at", -1)])

        if campaign:
            logger.warning(f"Found campaign: ID={str(campaign['_id'])}, status={campaign.get('status')}, type={campaign.get('type')}, created_at={campaign.get('created_at')}")
        else:
            logger.error("No active campaign found!")

            # Debug: Show all campaigns for this admin
        all_campaigns = await db.db.campaigns.find({"admin_id": str(student["admin_id"])}).to_list(length=None)
        logger.error(f"All campaigns for admin {student['admin_id']}: {[(str(c['_id']), c.get('status'), c.get('type'), c.get('created_at')) for c in all_campaigns]}")
        
        # Try to find ANY campaign for this admin (including draft status)
        any_campaign = await db.db.campaigns.find_one({
            "admin_id": str(student["admin_id"])
        }, sort=[("created_at", -1)])
        
        if any_campaign:
            logger.warning(f"Found DRAFT campaign, using it: ID={str(any_campaign['_id'])}, status={any_campaign.get('status')}")
            campaign = any_campaign
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail="No campaign found for this admin"
            )
        
        if not campaign:
            logger.warning("No active campaign found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="No active campaign found"
            )
        
        # Log campaign details
        campaign_id = str(campaign.get("_id", "unknown"))
        campaign_desc = campaign.get("description", "No description")
        campaign_assistant_id = campaign.get("assistant_id", "None")
        campaign_type = campaign.get("type", "messaging")
        logger.warning(f"handle_email_webhook() - Campaign details: {campaign_id}, {campaign_desc}, {campaign_assistant_id}, {campaign_type}")

        # Get admin associated with the campaign
        admin_id = campaign.get("admin_id")
        admin = await db.db.admin_users.find_one({"_id": ObjectId(admin_id)})
        logger.warning(f"handle_email_webhook() - Admin details: {admin_id}")
        
        if not admin:
            logger.error(f"Admin not found for campaign {campaign.get('_id')}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Admin not found for campaign"
            )
            
        # Get vector store ID from admin
        vector_store_id = admin.get("vector_store_id")
        #logger.info(f"[REQ-{request_id}] Admin vector store ID: {vector_store_id}")

        # Ensure student has thread_id
        if not student.get('thread_id'):
            thread_data = await openai_service.create_thread()
            thread_id = thread_data["id"]
            
            await db.db.students.update_one(
                {"_id": student["_id"]},
                {"$set": {"thread_id": thread_id}}
            )
            
            # logger.info(f"Created new thread for student: {thread_id}")
        else:
            thread_id = student["thread_id"]
            # logger.info(f"Using existing thread_id: {thread_id}")
        
        if not campaign_assistant_id:
            logger.warning(f"[REQ-{request_id}] Campaign has no assistant_id. Will need to create one.")
        
        # Get assistant ID with proper fallbacks
        assistant_id = campaign.get("assistant_id") or admin.get("assistant_id") or "asst_re59LKPfW1Fya4rwuoxVHKOa"
        logger.warning(f"handle_email_webhook() - Assistant ID: {assistant_id}")
        
        # If vector store exists, attach it to the thread for this run
        thread_tool_resources = None
        if vector_store_id:
            # logger.info(f"Attaching vector store {vector_store_id} to thread {thread_id}")
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

        # ================================================================
        # FEEDBACK CAMPAIGN HANDLING - NEW LOGIC
        # ================================================================
        if campaign_type == "feedback":
            logger.warning(f"handle_email_webhook() - Feedback campaign detected")
            
            # Get feedback conversation service
            feedback_service = FeedbackConversationService(db.db, openai_service)
            
            # Initialize or get existing conversation state
            conversation_state = await feedback_service.get_conversation_state(
                student_id=student_id,
                campaign_id=campaign_id
            )
            
            logger.warning(f"handle_email_webhook() - Conversation state: {conversation_state}")
            
            if not conversation_state:
                # logger.info(f"CMP: [REQ-{request_id}] Initializing new feedback conversation")
                conversation_state = await feedback_service.initialize_conversation(
                    student_id=student_id,
                    campaign_id=campaign_id
                )
            else:
                logger.warning(f"handle_email_webhook() - Conversation state found")
                pass 
            
            # Generate context-aware prompt for feedback conversation
            assistant_prompt = await feedback_service.generate_assistant_prompt(
                conversation_state=conversation_state,
                student_message=text_content,
                student_name=student_name
            )

            # NEW: Add minimal additional instructions
            feedback_metadata = campaign.get("feedback_metadata", {})
            #TODO: is this redundant?
            student_additional_instructions = f"STUDENT MODE: Speaking with {student_name} about {feedback_metadata.get('research_topic', 'feedback')}. Style: {feedback_metadata.get('conversation_style', 'friendly')}."

            logger.warning(f"handle_email_webhook() - calling openai with prompt: {assistant_prompt}, student_additional_instructions: {student_additional_instructions}, thread_id: {thread_id}, assistant_id: {assistant_id}")
            # Process with OpenAI using feedback-specific prompt
            try:
                response = await openai_service.process_message(
                    thread_id=thread_id,
                    message=assistant_prompt,
                    assistant_id=assistant_id,
                    run_handler=lambda tool_calls: handle_student_tool_calls(
                        tool_calls, student, campaign_service
                    ),
                    thread_tool_resources=thread_tool_resources,
                    additional_instructions=student_additional_instructions
                )
                
                # Analyze the student's response (not the assistant prompt)
                response_analysis = await feedback_service.analyze_student_response(
                    response=text_content,  # The student's actual message
                    conversation_state=conversation_state
                )
                
                # Update conversation state based on analysis
                updated_state = await feedback_service.update_conversation_state(
                    conversation_state=conversation_state,
                    response_analysis=response_analysis,
                    student_response=text_content
                )
                
                # logger.info(f"[REQ-{request_id}] Feedback conversation updated: {updated_state.questions_completed}/{updated_state.total_questions} questions completed, Strategy: {updated_state.current_strategy}")
                
                # Send the response back to the student via email
                await sendgrid_service.send_message(
                    to_email=email_address,
                    subject=format_reply_subject(subject),
                    message=response,
                    message_type="reply",
                    original_message_id=message_id,
                    thread_references=references
                )
                
            except Exception as e:
                logger.error(f"[REQ-{request_id}] Error processing feedback conversation: {str(e)}")
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Unable to process feedback message",
                )

        # ================================================================
        # MESSAGING CAMPAIGN HANDLING - EXISTING LOGIC
        # ================================================================
        else:
            logger.warning(f"handle_email_webhook() - Messaging campaign detected")
            
            try:
                # Process message with OpenAI (original logic)
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
                    subject=format_reply_subject(subject),
                    message=response,
                    message_type="reply",
                    original_message_id=message_id,
                    thread_references=references
                )
                
            except Exception as e:
                logger.error(f"[REQ-{request_id}] Error processing messaging interaction: {str(e)}")
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Unable to process message",
                )

        # ================================================================
        # INTERACTION LOGGING - ENHANCED FOR BOTH TYPES
        # ================================================================
        interaction_data = {
            "student_id": student_id,
            "campaign_id": campaign_id,
            "message": text_content,
            "response": response,
            "contact_method": "email",
            "email_subject": subject,
            "type": "response",
            "status": "sent",
            "timestamp": datetime.utcnow(),
            "vector_store_used": bool(vector_store_id),
            "campaign_type": campaign_type,
            "original_message_id": message_id,
            "thread_references": references
        }
        
        # Add feedback-specific fields if it's a feedback campaign
        if campaign_type == "feedback" and 'updated_state' in locals():
            interaction_data.update({
                "feedback_progress": f"{updated_state.questions_completed}/{updated_state.total_questions}",
                "conversation_strategy": updated_state.current_strategy,
                "engagement_level": updated_state.engagement_level
            })

        await db.db.interactions.insert_one(interaction_data)

        end_time = datetime.utcnow()
        processing_time = (end_time - start_time).total_seconds()
        # logger.info(f"[REQ-{request_id}] Email webhook processing completed in {processing_time} seconds")
        return {"status": "success", "processing_time": processing_time, "campaign_type": campaign_type}

    except HTTPException as http_ex:
        logger.error(f"[REQ-{request_id}] HTTP Exception in email webhook: {http_ex.detail}")
        raise

    except Exception as e:
        logger.error(f"[REQ-{request_id}] Email webhook handling error: {str(e)}")
        import traceback
        trace = traceback.format_exc()
        logger.error(f"[REQ-{request_id}] Stack trace:\n{trace}")
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
    # logger.info(f"CMP: Student tool calls received - Student: {str(student['_id'])}, Calls: {len(tool_calls)}")  # ADD THIS
    # logger.info(f"Handling student tool calls: {json.dumps(tool_calls, indent=2)}")
    
    tool_outputs = []
    for tool_call in tool_calls:
        try:
            tool_type = tool_call.get("type")
            tool_call_id = tool_call.get("id")
            
            # logger.info(f"Processing student tool call type: {tool_type}, id: {tool_call_id}")
            
            # Handle file_search tool calls - these are fine for students to use
            if tool_type == "file_search":
                # logger.info(f"File search tool used in student interaction")
                
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

def format_reply_subject(original_subject: str) -> str:
    """
    Format subject line for email replies according to RFC 5322 standards.
    
    Rules:
    - If subject already starts with "Re:", don't add another one
    - If subject doesn't start with "Re:", add it
    - Handle case variations (Re:, RE:, re:)
    - Preserve original subject content
    
    Args:
        original_subject: The subject from the incoming email
        
    Returns:
        Properly formatted reply subject
    """
    if not original_subject:
        return "Re: (no subject)"
    
    # Check if subject already has a reply prefix (case insensitive)
    subject_lower = original_subject.lower().strip()
    
    # If it already starts with "Re:" (any case), just return it as-is
    if subject_lower.startswith("re:"):
        return original_subject.strip()
    
    # Otherwise, add "Re:" prefix
    return f"Re: {original_subject.strip()}"