# app/services/sendgrid_service.py
import logging
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
        
        Args:
            to_email: Recipient's email address
            subject: Email subject line
            message: Plain text message content
        """
        try:
            # Create a sender with name and email
            from_email = Email(self.from_email, self.from_name)
            
            # Create a simple mail object
            mail = Mail(
                from_email=from_email,
                to_emails=to_email,
                subject=subject,
                plain_text_content=message
            )
            
            # Send the email
            sg = SendGridAPIClient(self.api_key)
            response = sg.send(mail)
            
            logger.info(f"Email sent to {to_email} with status {response.status_code}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {str(e)}")
            raise Exception(f"Failed to send email: {str(e)}")