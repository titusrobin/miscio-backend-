# app/services/openai_service.py
from app.core.config import settings
from typing import Dict, Any, Optional, List
from app.services.base_service import BaseAPIService
import json
import asyncio
import logging

logger = logging.getLogger(__name__)


class OpenAIService(BaseAPIService):  
    # constructor 
    def __init__(self): 
        super().__init__()
        self.base_url = "https://api.openai.com/v1"
        self.headers = {
            "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
            "OpenAI-Beta": "assistants=v2",
            "Content-Type": "application/json",
        }
        
    async def create_admin_assistant(self, admin_id: str) -> dict:
        """
        Creates a dedicated assistant for an admin with function calling capabilities.
        
        This method sets up an OpenAI assistant with predefined tools and instructions
        for handling student communications and feedback analysis.
        """
        try:
            tools = [ # list of dict
                {
                    "type": "function",
                    "function": {
                        "name": "run_campaign",
                        "description": "Run a campaign to send messages to students",
                        "parameters": {
                            "type": "object",
                            "properties": { # JSON Schema to define inputs function needs
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

            # Configure the assistant with instructions and tools
            assistant_data = {
                "name": f"Admin Assistant - {admin_id}",
                "instructions": """You are an administrative assistant for Miscio. Your role is to help admins manage student communications and analyze feedback. You can:
                1. Run campaigns to reach out to students using the run_campaign function
                2. Query and analyze student chat histories using query_student_chats
                Keep responses professional but friendly. Always use the appropriate function when the admin wants to start a campaign or analyze student feedback.""",
                "model": settings.OPENAI_ASSISTANT_MODEL,
                "tools": tools
            }

            # Create the assistant using the OpenAI API
            logger.info(f"Creating assistant for admin {admin_id} via endpoint: {self.base_url}/assistants")
            logger.info(f"Assistant configuration: {json.dumps(assistant_data, indent=2)}")
            response = await self.make_request(
                method="POST",
                url=f"{self.base_url}/assistants",
                headers=self.headers,
                data=assistant_data
            )
            
            # Create an initial thread for the assistant
            logger.info(f"Creating initial thread via endpoint: {self.base_url}/threads")            
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


    async def create_thread(self) -> dict:
        """Creates a new OpenAI thread for conversation management."""
        logger.info(f"Creating new thread via endpoint: {self.base_url}/threads")
        try:
            response = await self.make_request(
                method="POST",
                url=f"{self.base_url}/threads",
                headers=self.headers
            )
            return response
        
        except Exception as e:
            logger.error(f"Error creating thread: {str(e)}")
            raise

    async def process_message(
        self,
        thread_id: str,
        message: str,
        assistant_id: str,
        run_handler: Optional[callable] = None # optionalfunction to handle tool calls
    ) -> str:
        """
        Process a message with support for function calling.

        1. Thread is simply a container for storing messages
        2. Run actual execution of assistant's instructions
        """
        logger.info(f"Starting to process message in thread {thread_id}")
        logger.info(f"Assistant ID: {assistant_id}")
        logger.info(f"Run handler provided: {run_handler is not None}")

        try:
            await self.make_request( # create the message in the thread
                method="POST",
                url=f"{self.base_url}/threads/{thread_id}/messages",
                headers=self.headers,
                data={"role": "user", "content": message}
            )

            run_response = await self.make_request( # create and start a new run
                method="POST",
                url=f"{self.base_url}/threads/{thread_id}/runs",
                headers=self.headers,
                data={"assistant_id": assistant_id}
            )
            run_id = run_response["id"]
            logger.info(f"Started new run with ID: {run_id}")

            # Monitor the run status and handle any required actions
            while True:    
                status_response = await self.make_request(
                    method="GET",
                    url=f"{self.base_url}/threads/{thread_id}/runs/{run_id}",
                    headers=self.headers
                )

                # if the run requires action, it means the assistant is waiting for a tool call
                if status_response["status"] == "requires_action":
                    if run_handler:
                        tool_calls = status_response["required_action"]["submit_tool_outputs"]["tool_calls"]
                        logger.info(f"Received tool calls to process: {json.dumps(tool_calls, indent=2)}")
                        
                        tool_outputs = await run_handler(tool_calls) # tool_calls is data from OpenAI describing what functions to call and with what parameters
                        
                        # Submit the tool outputs back to OpenAI
                        await self.make_request(
                            method="POST",
                            url=f"{self.base_url}/threads/{thread_id}/runs/{run_id}/submit_tool_outputs",
                            headers=self.headers,
                            data={"tool_outputs": tool_outputs}
                        )

                    else:
                        logger.error("Function call required but no run_handler provided")
                        raise Exception("Function execution not supported")

                # if the run is completed, get the final response
                elif status_response["status"] == "completed":
                    messages_response = await self.make_request(
                        method="GET",
                        url=f"{self.base_url}/threads/{thread_id}/messages",
                        headers=self.headers,
                        params={"limit": 1, "order": "desc"}
                    )

                    # Validate the response structure
                    if not messages_response.get("data"):
                        logger.error("No messages returned in response")
                        raise Exception("Invalid message response")

                    message_content = messages_response["data"][0].get("content", [])
                    if not message_content or not message_content[0].get("text", {}).get("value"):
                        logger.error("Invalid message content structure")
                        raise Exception("Invalid message content")

                    return message_content[0]["text"]["value"]

                elif status_response["status"] in ["failed", "cancelled", "expired"]:
                    error_message = f"Run failed with status: {status_response['status']}"
                    logger.error(error_message)
                    raise Exception(error_message)

                await asyncio.sleep(1) # wait for 1 second before checking the status again 
                ###TODO: make 0.5? 

        except Exception as e:
            logger.error(f"Error processing message: {str(e)}", exc_info=True)
            raise

    
    async def __aenter__(self): # Simply returns the service instance itself
        """Support for async context manager protocol."""
        return self


    async def __aexit__(self, exc_type, exc_val, exc_tb): # clean up resources
        """Ensure proper cleanup of resources when used as a context manager."""
        await self.close()