# app/services/sendgrid_service.py
import logging
import re
from typing import Optional
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email, Content
from app.core.config import settings

logger = logging.getLogger(__name__)

class SendGridService:
    """Service for sending emails using SendGrid."""
    
    def __init__(self):
        """Initialize the SendGrid service with configuration."""
        self.api_key = settings.SENDGRID_API_KEY
        self.from_email = settings.SENDGRID_FROM_EMAIL
        self.from_name = settings.SENDGRID_FROM_NAME
    
    async def send_message(self, to_email: str, subject: str, message: str):
        """
        Sends an email message to a student.
        """
        try:
            # Fix the multiple "Re:" issue
            # First, remove all existing "Re:" prefixes (case insensitive)
            clean_subject = re.sub(r'^(re:\s*)+', '', subject, flags=re.IGNORECASE).strip()
            
            # Only add "Re:" if the subject is not empty and not the default
            if clean_subject and clean_subject != "Message from Miscio Assistant":
                subject = f"Re: {clean_subject}"
            else:
                subject = clean_subject or "Message from Miscio Assistant"
            
            # Fix the asterisks issue - simply remove them from the message
            message_plain = re.sub(r'\*\*(.*?)\*\*', r'\1', message)
            
            # Also remove citation references to make the email cleaner
            message_plain = re.sub(r'\[(.*?†.*?)\]', '', message_plain)
            
            # Create sender and mail object 
            from_email = Email(self.from_email, self.from_name)
            
            mail = Mail(
                from_email=from_email,
                to_emails=to_email,
                subject=subject,
                plain_text_content=message_plain
            )
            
            # Set the Reply-To header to reply@miscioapp.com
            mail.reply_to = Email("reply@reply.miscioapp.com", "Miscio Assistant")
            
            # Send the email
            sg = SendGridAPIClient(self.api_key)
            response = sg.send(mail)
            
            logger.info(f"Email sent to {to_email} with status {response.status_code}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {str(e)}")
            raise Exception(f"Failed to send email: {str(e)}")