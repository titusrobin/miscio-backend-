# app/api/v1/endpoints/webhook.py
from fastapi import APIRouter, HTTPException, Depends, Form, Request, status
from app.services.openai_service import OpenAIService
from app.services.twilio_service import TwilioService
from app.services.sendgrid_service import SendGridService   
from app.db.mongodb import db
from typing import Optional
import logging
from datetime import datetime

router = APIRouter()
logger = logging.getLogger(__name__)

def get_openai_service():
    return OpenAIService()

def get_twilio_service():
    return TwilioService()

def get_sendgrid_service():
    return SendGridService()

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
):
    """
    Handles incoming webhook requests from SendGrid for email responses.
    """
    start_time = datetime.utcnow()
    logger.info(f"Email webhook received at: {start_time}")
    try:
         # Parse the incoming SendGrid webhook form data
        body = await request.body()
        logger.info(f"Received email webhook raw body length: {len(body)}")
        
        form_data = await request.form()
        logger.info(f"Parsed form data keys: {list(form_data.keys())}")
        
        from_email = form_data.get("from")
        subject = form_data.get("subject", "")
        text_content = form_data.get("text", "")
        
        logger.info(f"Extracted email details - From: {from_email}, Subject: {subject}")
        
        # Fallback to alternate field names if primary fields are empty
        if not from_email and "envelope" in form_data: # envelope: The actual routing information used by mail servers
            try:
                import json
                envelope_raw = form_data["envelope"]
                logger.info(f"Parsing envelope: {envelope_raw}")
                envelope = json.loads(envelope_raw)
                from_email = envelope.get("from")
                logger.info(f"Extracted from_email from envelope: {from_email}")
            except Exception as e:
                logger.error(f"Failed to parse envelope JSON: {str(e)}")
        
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
        
        logger.info(f"Found student: {student.get('first_name')} {student.get('last_name')}")
        logger.info(f"Student thread_id: {student.get('thread_id')}")
        
        # Get active campaign
        campaign = await db.db.campaigns.find_one({"status": "active"})
        if not campaign:
            logger.warning("No active campaign found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="No active campaign found"
            )
        
        logger.info(f"Found active campaign: {campaign.get('description')}")
        logger.info(f"Campaign assistant_id: {campaign.get('assistant_id')}")

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
            
            # Check if campaign has assistant_id
            if not campaign.get('assistant_id'):
                assistant_id = "asst_re59LKPfW1Fya4rwuoxVHKOa"  # Default assistant ID
                
                await db.db.campaigns.update_one(
                    {"_id": campaign["_id"]},
                    {"$set": {"assistant_id": assistant_id}}
                )
                
                logger.info(f"Updated campaign with assistant_id: {assistant_id}")
            else:
                assistant_id = campaign["assistant_id"]
                logger.info(f"Using existing assistant_id: {assistant_id}")

            logger.info("Sending message to OpenAI for processing")   
            logger.info(f"Thread ID: {thread_id}, Assistant ID: {assistant_id}")
            logger.info(f"Message content (first 100 chars): {text_content[:100] if text_content else ''}")
            
            response = await openai_service.process_message(
                thread_id=thread_id,
                message=text_content.strip(),
                assistant_id=assistant_id,
            )
            
            # Send the response back to the student via email
            await sendgrid_service.send_message(
                to_email=email_address,
                subject=f"Re: {subject}",
                message=response
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
