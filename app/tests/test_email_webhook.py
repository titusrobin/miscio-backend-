# test_email_webhook.py
import requests
import json

# Your local API endpoint
webhook_url = "http://localhost:8000/api/v1/webhook/email"

# Sample data that mimics SendGrid's inbound parse webhook
test_data = {
    "from": "teststudent@example.com",
    "subject": "Re: Your message",
    "text": "This is a test reply from a student.",
    # Add other fields that SendGrid would send
}

# Send a test request
response = requests.post(webhook_url, data=test_data)
print(f"Status code: {response.status_code}")
print(f"Response: {response.json()}")