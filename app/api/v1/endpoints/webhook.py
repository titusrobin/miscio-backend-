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


@router.post("/email")  # Fix the indentation here
async def handle_email_webhook(
    request: Request,
    openai_service: OpenAIService = Depends(get_openai_service),
    sendgrid_service: SendGridService = Depends(get_sendgrid_service),
):
    """
    Handles incoming webhook requests from SendGrid for email responses.
    """
    try:
        # Parse the incoming SendGrid webhook payload
        payload = await request.json()
        logger.info(f"Received email webhook")
        
        # Extract the email information from the payload
        # Note: The exact payload structure depends on how SendGrid formats its webhooks
        from_email = payload.get("from")
        text_content = payload.get("text")
        
        if not from_email or not text_content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid email payload format",
            )

        # Find student with error handling
        student = await db.db.students.find_one({"email": from_email})
        if not student:
            logger.warning(f"Unknown student email: {from_email}")
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
                message=text_content.strip(),
                assistant_id=campaign["assistant_id"],
            )
        except Exception as e:
            logger.error(f"OpenAI processing error: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to process message",
            )

        # Send response via SendGrid
        try:
            await sendgrid_service.send_message(
                to_email=from_email,
                subject=f"Re: {payload.get('subject', 'Your message to Miscio')}",
                message=response
            )
        except Exception as e:
            logger.error(f"SendGrid sending error: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to send response",
            )

        # Log successful interaction
        await db.db.interactions.insert_one(
            {
                "student_id": str(student["_id"]),
                "campaign_id": str(campaign["_id"]),
                "message": text_content,
                "response": response,
                "contact_method": "email",
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