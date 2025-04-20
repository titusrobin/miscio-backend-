# app/api/v1/endpoints/webhook.py
from fastapi import APIRouter, HTTPException, Depends, Form, Request, status
from app.services.openai_service import OpenAIService
from app.services.twilio_service import TwilioService
from app.services.sendgrid_service import SendGridService  # Add this import
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
    request: Request,
    openai_service: OpenAIService = Depends(get_openai_service),
    sendgrid_service: SendGridService = Depends(get_sendgrid_service),
):
    """
    Handles incoming webhook requests from SendGrid for email responses.
    """
    try:
        # Log the raw request for debugging
        body = await request.body()
        logger.info(f"Received email webhook raw body: {body}")
        
        # Parse the incoming SendGrid webhook form data
        form_data = await request.form()
        logger.info(f"Parsed form data keys: {list(form_data.keys())}")
        
        # Extract email information from SendGrid's Parse Webhook
        # According to SendGrid docs, these are the standard field names
        from_email = form_data.get("from")
        subject = form_data.get("subject", "")
        text_content = form_data.get("text", "")
        
        # Fallback to alternate field names if primary fields are empty
        if not from_email and "envelope" in form_data:
            try:
                import json
                envelope = json.loads(form_data["envelope"])
                from_email = envelope.get("from")
                logger.info(f"Extracted from_email from envelope: {from_email}")
            except Exception as e:
                logger.warning(f"Failed to parse envelope JSON: {str(e)}")
        
        if not text_content:
            text_content = form_data.get("body-plain", "") or form_data.get("plain", "")
        
        logger.info(f"Extracted email details - From: {from_email}, Subject: {subject}")
        logger.info(f"Text content first 100 chars: {text_content[:100] if text_content else ''}")
        
        if not from_email or not text_content:
            logger.error("Missing required email fields")
            # Log all available fields for debugging
            for key in form_data.keys():
                logger.info(f"Available field: {key}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid email payload format",
            )

        # Extract just the email address from the "from" field
        email_address = from_email
        if email_address and "<" in str(email_address) and ">" in str(email_address):
            email_address = str(email_address).split("<")[1].split(">")[0]
        
        logger.info(f"Looking up student with email: {email_address}")    
        # Find student with error handling
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
                logger.error("Student missing thread_id")
                # Create a thread if missing
                thread_data = await openai_service.create_thread()
                thread_id = thread_data["id"]
                
                # Update student with new thread_id
                await db.db.students.update_one(
                    {"_id": student["_id"]},
                    {"$set": {"thread_id": thread_id}}
                )
                
                logger.info(f"Created new thread for student: {thread_id}")
            else:
                thread_id = student["thread_id"]
            
            # Check if campaign has assistant_id
            if not campaign.get('assistant_id'):
                logger.error("Campaign missing assistant_id")
                # Use a default assistant ID or create one
                # For testing, we can use the admin's assistant ID from your logs
                assistant_id = "asst_re59LKPfW1Fya4rwuoxVHKOa"  # Default assistant ID
                
                # Update the campaign
                await db.db.campaigns.update_one(
                    {"_id": campaign["_id"]},
                    {"$set": {"assistant_id": assistant_id}}
                )
                
                logger.info(f"Updated campaign with assistant_id: {assistant_id}")
            else:
                assistant_id = campaign["assistant_id"]

            # Add context to help the OpenAI assistant understand this is a student reply
            enriched_message = f"""
            This is a reply from a student named {student.get('first_name')} {student.get('last_name')} 
            to our campaign about: {campaign.get('description')}

            Student's message:
            {text_content.strip()}

            Please respond naturally to the student's message. Do not mention that you're an AI or that you can't directly receive emails.
            """
                
            response = await openai_service.process_message(
                thread_id=thread_id,
                message=text_content.strip(),
                assistant_id=assistant_id,
            )
            logger.info("Successfully processed message with OpenAI")
            
            # Send the response back to the student via email
            logger.info(f"Sending email response to {email_address}")
            await sendgrid_service.send_message(
                to_email=email_address,
                subject=f"Re: {subject}",
                message=response
            )
            logger.info(f"Email response sent to {email_address}")
            
        except Exception as e:
            logger.error(f"OpenAI processing error: {str(e)}", exc_info=True)
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
            }
        )

        return {"status": "success"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Email webhook handling error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )