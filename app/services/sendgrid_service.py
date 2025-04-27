# app/services/sendgrid_service.py
import logging
from typing import Optional
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email, Content
from app.core.config import settings
import re

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
            # Ensure subject has Re: prefix if it's a reply and doesn't already have it
            if not subject.startswith("Re:") and subject.strip() != "": #TODO: fix multiple RE's 
                subject = f"Re: {subject}"
            elif subject.strip() == "":
                subject = "Message from Miscio Assistant"

            plain_text_content, html_content = self.format_message_for_email(message)
                
            # Create sender and mail object 
            from_email = Email(self.from_email, self.from_name)
            
            mail = Mail(
                from_email=from_email,
                to_emails=to_email,
                subject=subject,
                plain_text_content=plain_text_content,
                html_content=html_content
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
    
    def format_message_for_email(self, message: str) -> tuple[str, str]:
        """
        Format the message for both plain text and HTML email versions.
        Returns (plain_text_content, html_content)
        """
        # Plain text version
        plain_text = message
        # Remove markdown-style formatting
        plain_text = re.sub(r'\*\*(.*?)\*\*', r'\1', plain_text)
        # Clean up citation references
        plain_text = re.sub(r'\[(.*?†.*?)\]', r'(see citation)', plain_text)
        
        # HTML version
        html = message
        # Convert bold formatting
        html = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', html)
        # Convert numbered lists
        html = re.sub(r'^(\d+)\.\s(.*)$', r'<p>\1. \2</p>', html, flags=re.MULTILINE)
        # Convert citation references to superscript
        html = re.sub(r'\[(.*?†.*?)\]', r'<sup><small>[citation]</small></sup>', html)
        # Convert line breaks
        html = html.replace('\n\n', '</p><p>').replace('\n', '<br>')
        # Wrap in paragraph tags
        html = f'<p>{html}</p>'
        
        return plain_text, html