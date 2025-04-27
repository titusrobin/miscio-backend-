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
        Sends an email message to a student with proper formatting.
        """
        try:
            # Fix the multiple "Re:" issue
            # Remove all existing "Re:" prefixes (case insensitive) to avoid stacking
            clean_subject = re.sub(r'^(re:\s*)+', '', subject, flags=re.IGNORECASE).strip()
            
            # Add a single "Re:" prefix only if this is a reply to a non-default subject
            if clean_subject and clean_subject != "Message from Miscio Assistant":
                subject = f"Re: {clean_subject}"
            elif not clean_subject:
                subject = "Message from Miscio Assistant"
            else:
                subject = clean_subject
            
            # Format the message for both plain text and HTML
            plain_text_content, html_content = self.format_message_for_email(message)
            
            # Create sender and mail object 
            from_email = Email(self.from_email, self.from_name)
            
            # Create mail object with both content types as recommended by SendGrid
            mail = Mail(
                from_email=from_email,
                to_emails=to_email,
                subject=subject
            )
            
            # Add both plain text and HTML content
            mail.add_content(Content("text/plain", plain_text_content))
            mail.add_content(Content("text/html", html_content))
            
            # Set the Reply-To header
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
        Format the message for both plain text and HTML email versions following SendGrid best practices.
        Returns (plain_text_content, html_content)
        """
        # Plain text version - remove markdown formatting
        plain_text = message
        # Remove markdown-style bold formatting
        plain_text = re.sub(r'\*\*(.*?)\*\*', r'\1', plain_text)
        # Clean up citation references
        plain_text = re.sub(r'\[(.*?†.*?)\]', r'[reference]', plain_text)
        
        # HTML version - following SendGrid best practices
        html = message
        
        # Convert bold formatting using inline styles as recommended by SendGrid
        html = re.sub(r'\*\*(.*?)\*\*', r'<span style="font-weight: bold;">\1</span>', html)
        
        # Convert numbered lists with inline styles
        html = re.sub(r'^(\d+)\.\s(.*)$', r'<p style="margin: 10px 0;">\1. \2</p>', html, flags=re.MULTILINE)
        
        # Convert citation references to subtle formatting
        html = re.sub(r'\[(.*?†.*?)\]', r'<span style="font-size: 12px; color: #666;">[ref]</span>', html)
        
        # Convert line breaks and paragraphs with inline styles
        paragraphs = html.split('\n\n')
        formatted_paragraphs = []
        for para in paragraphs:
            if para.strip():
                para = para.replace('\n', '<br>')
                formatted_paragraphs.append(f'<p style="margin: 10px 0; line-height: 1.6;">{para}</p>')
        
        # Create the HTML email structure following SendGrid best practices
        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta http-equiv="Content-Type" content="text/html; charset=utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 0; background-color: #f5f5f5;">
    <table width="100%" border="0" cellspacing="0" cellpadding="0">
        <tr>
            <td align="center" style="padding: 20px;">
                <table width="600" border="0" cellspacing="0" cellpadding="0" style="background-color: #ffffff;">
                    <tr>
                        <td style="padding: 20px; font-family: Arial, sans-serif; font-size: 14px; line-height: 1.6; color: #333333;">
                            {''.join(formatted_paragraphs)}
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""
        
        return plain_text, html_content