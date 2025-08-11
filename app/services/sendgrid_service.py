# app/services/sendgrid_service.py
import logging
import re  # Add this import
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
        
    async def send_message(self, to_email: str, subject: str, message: str, message_type: str = "initial", student_name: str = None):
        """
        Sends an email message to a student.
        
        """
        try:
            logger.warning(f"send_message() - To: {to_email}, Type: {message_type}, Subject: {subject[:50]}, message: {message[:50]}, student_name: {student_name}")

            # Only use Re: prefix for replies to student messages, not for new campaigns
            if subject.strip() == "":
                subject = "Message from Miscio Assistant" #TODO: better approach needed
            
            # Fix the asterisks issue - simply remove them from the message
            message_plain = re.sub(r'\*\*(.*?)\*\*', r'\1', message) 
            ##TODO: Can we personalize formatting via sendgrid? 
            ##TODO: Can we take off header #'s and format accordingly 

            if student_name:
                message_plain = f"{student_name},\n\n{message_plain}\n\n{self.from_name}"

            # Create sender and mail object 
            from_email = Email(self.from_email, self.from_name)
            
            mail = Mail(
                from_email=from_email,
                to_emails=to_email,
                subject=subject,
                plain_text_content=message_plain  # Use the cleaned message
            )
            
            # Set the Reply-To header to reply@miscioapp.com
            mail.reply_to = Email("robin@em1650.miscioapp.com", "Robin Titus")
            
            # Send the email
            sg = SendGridAPIClient(self.api_key)
            response = sg.send(mail)
            
            # logger.info(f"Email sent to {to_email} with status {response.status_code}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {str(e)}")
            raise Exception(f"Failed to send email: {str(e)}")