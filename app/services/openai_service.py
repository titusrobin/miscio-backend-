# app/services/openai_service.py
from app.core.config import settings
from typing import Dict, Any, Optional, List
from .base_service import BaseAPIService
import json
import asyncio
import logging

logger = logging.getLogger(__name__)

class OpenAIService(BaseAPIService):
    def __init__(self):
        super().__init__()
        self.base_url = "https://api.openai.com/v1"
        self.headers = {
            "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
            "OpenAI-Beta": "assistants=v2",
            "Content-Type": "application/json",
        }
        
    async def create_admin_assistant(self, admin_id: str) -> dict:
        """Creates a dedicated assistant for an admin with function calling capabilities"""
        try:
            # Define available functions
            tools = [
                {
                    "type": "function",
                    "function": {
                        "name": "run_campaign",
                        "description": "Run a campaign to send messages to students",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "campaign_type": {
                                    "type": "string",
                                    "enum": ["feedback", "reminder", "announcement"],
                                    "description": "The type of campaign to run"
                                },
                                "campaign_description": {
                                    "type": "string",
                                    "description": "A brief description of what the campaign is about"
                                }
                            },
                            "required": ["campaign_description"]
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "query_student_chats",
                        "description": "Search through student chat histories",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "The search query for filtering chat histories"
                                },
                                "campaign_id": {
                                    "type": "string",
                                    "description": "Optional campaign ID to filter chats"
                                }
                            },
                            "required": ["query"]
                        }
                    }
                }
            ]

            # Create assistant with the defined tools
            assistant_data = {
                "name": f"Admin Assistant - {admin_id}",
                "instructions": """You are an administrative assistant for Miscio. Your role is to help admins manage student communications and analyze feedback. You can:
                1. Run campaigns to reach out to students using the run_campaign function
                2. Query and analyze student chat histories using query_student_chats
                Keep responses professional but friendly. Always use the appropriate function when the admin wants to start a campaign or analyze student feedback.""",
                "model": settings.OPENAI_ASSISTANT_MODEL,
                "tools": tools
            }

            # Create assistant
            response = await self.make_request(
                method="POST",
                url=f"{self.base_url}/assistants",
                headers=self.headers,
                data=assistant_data
            )
            
            # Create thread
            thread_response = await self.make_request(
                method="POST",
                url=f"{self.base_url}/threads",
                headers=self.headers
            )

            return {
                "assistant_id": response["id"],
                "thread_id": thread_response["id"]
            }
        except Exception as e:
            logger.error(f"Error creating admin assistant: {str(e)}")
            raise

    async def process_message(
        self,
        thread_id: str,
        message: str,
        assistant_id: str,
        run_handler: Optional[callable] = None
    ) -> str:
        """
        Process a message with support for function calling
        """
        try:
            # First, list and cancel any active runs
            runs_response = await self.make_request(
                method="GET",
                url=f"{self.base_url}/threads/{thread_id}/runs",
                headers=self.headers
            )
            
            # Cancel any in_progress or queued runs
            for run in runs_response.get("data", []):
                if run["status"] in ["in_progress", "queued"]:
                    try:
                        await self.make_request(
                            method="POST",
                            url=f"{self.base_url}/threads/{thread_id}/runs/{run['id']}/cancel",
                            headers=self.headers
                        )
                        logger.info(f"Cancelled run {run['id']}")
                    except Exception as e:
                        logger.warning(f"Failed to cancel run {run['id']}: {str(e)}")

            # Wait a short time for cancellation to take effect
            await asyncio.sleep(1)

            # Create message
            await self.make_request(
                method="POST",
                url=f"{self.base_url}/threads/{thread_id}/messages",
                headers=self.headers,
                data={"role": "user", "content": message}
            )

            # Create run
            run_response = await self.make_request(
                method="POST",
                url=f"{self.base_url}/threads/{thread_id}/runs",
                headers=self.headers,
                data={"assistant_id": assistant_id}
            )

            # Monitor run status
            while True:
                status_response = await self.make_request(
                    method="GET",
                    url=f"{self.base_url}/threads/{thread_id}/runs/{run_response['id']}",
                    headers=self.headers
                )

                if status_response["status"] == "requires_action":
                    if run_handler:
                        tool_outputs = await run_handler(
                            status_response["required_action"]["submit_tool_outputs"]["tool_calls"]
                        )
                        
                        # Submit tool outputs
                        await self.make_request(
                            method="POST",
                            url=f"{self.base_url}/threads/{thread_id}/runs/{run_response['id']}/submit_tool_outputs",
                            headers=self.headers,
                            data={"tool_outputs": tool_outputs}
                        )
                    else:
                        logger.error("Function call required but no run_handler provided")
                        raise Exception("Function execution not supported")

                elif status_response["status"] == "completed":
                    messages_response = await self.make_request(
                        method="GET",
                        url=f"{self.base_url}/threads/{thread_id}/messages",
                        headers=self.headers,
                        params={"limit": 1, "order": "desc"}
                    )
                    return messages_response["data"][0]["content"][0]["text"]["value"]

                elif status_response["status"] in ["failed", "cancelled", "expired"]:
                    raise Exception(f"Run failed with status: {status_response['status']}")

                await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"Error processing message: {str(e)}")
            raise

    async def __aenter__(self):
        """Support for async context manager."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Ensure proper cleanup of resources."""
        await self.close()