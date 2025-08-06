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
        
    async def send_message(self, to_email: str, subject: str, message: str, message_type: str = "initial"):
        """
        Sends an email message to a student.
        
        """
        try:
            # logger.info(f"CMP: Email send - To: {to_email}, Type: {message_type}, Subject: {subject[:50]}...")  # ADD THIS

            # Only use Re: prefix for replies to student messages, not for new campaigns
            if subject.strip() == "":
                subject = "Message from Miscio Assistant" #TODO: better approach needed
            #`elif message_type == "reply" and not subject.startswith("Re:"):
                # Only add Re: if this is a reply to a student message
                #subject = f"Re: {subject}" #TODO: Causing to problematic Re in Outlook? -- no visible issues on Gmail, need to test Yahoo?
            
            # Fix the asterisks issue - simply remove them from the message
            message_plain = re.sub(r'\*\*(.*?)\*\*', r'\1', message) 
            ##TODO: Can we personalize formatting via sendgrid? 
            ##TODO: Can we take off header #'s and format accordingly 

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