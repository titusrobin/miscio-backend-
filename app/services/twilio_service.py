# app/services/twilio_service.py
from app.core.config import settings
from typing import Optional
import asyncio
from twilio.rest import Client


class TwilioService:
    def __init__(self):
        self.client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        self.whatsapp_number = settings.TWILIO_WHATSAPP_NUMBER

    async def send_message(self, to_number: str, message: str):
        """Sends a WhatsApp message to a student."""
        try:
            self.client.messages.create(
                body=message, from_=self.whatsapp_number, to=f"whatsapp:{to_number}"
            )
        except Exception as e:
            # Log the error
            raise Exception(f"Failed to send WhatsApp message: {str(e)}")