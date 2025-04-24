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
        logger.info(f"Message content: {message[:100]}..." if len(message) > 100 else f"Message content: {message}")

        try:
            # Check if assistant_id is valid and log its configuration
            try:

                # Verify the assistant exists and log its details
                assistant_response = await self.make_request(
                    method="GET",
                    url=f"{self.base_url}/assistants/{assistant_id}",
                    headers=self.headers,
                )

                # First, ensure the vector store is properly attached to the assistant
                vector_store_id = "vs_6806b8d5767c8191b307104b59ce1949"
                await self.ensure_vector_store_attached(assistant_id, vector_store_id)
                
                # Log detailed assistant information
                logger.info(f"Assistant verified: {assistant_id}")
                logger.info(f"Assistant name: {assistant_response.get('name', 'Not set')}")
                logger.info(f"Assistant model: {assistant_response.get('model', 'Not set')}")
                
                # Log tools information
                tools = assistant_response.get('tools', [])
                logger.info(f"Assistant tools count: {len(tools)}")
                tool_types = [tool.get('type') for tool in tools]
                logger.info(f"Assistant tool types: {tool_types}")
                
                # Specifically check for file_search capability
                has_file_search = any(tool.get('type') == 'file_search' for tool in tools)
                logger.info(f"Assistant has file search enabled: {has_file_search}")
                
                # Log file information
                file_ids = assistant_response.get('file_ids', [])
                logger.info(f"Assistant file IDs: {file_ids}")
                if file_ids:
                    logger.info(f"Number of files attached to assistant: {len(file_ids)}")
                    # If needed, you could make additional API calls to get file details
                    
            except Exception as e:
                logger.error(f"Error verifying assistant {assistant_id}: {str(e)}")
                if hasattr(e, 'response') and hasattr(e.response, 'text'):
                    logger.error(f"Response error: {e.response.text}")
                raise Exception(f"Invalid assistant ID: {assistant_id}")

            # Create the message in the thread
            message_response = await self.make_request(
                method="POST",
                url=f"{self.base_url}/threads/{thread_id}/messages",
                headers=self.headers,
                data={"role": "user", "content": message}
            )
            logger.info(f"Created message in thread. Message ID: {message_response.get('id')}")

            # Create and start a new run with improved error handling
            try:
                run_response = await self.make_request(
                    method="POST",
                    url=f"{self.base_url}/threads/{thread_id}/runs",
                    headers=self.headers,
                    data={"assistant_id": assistant_id}
                )
                run_id = run_response["id"]
                logger.info(f"Started new run with ID: {run_id}")
                
            except Exception as e:
                logger.error(f"Failed to start run: {str(e)}")
                if hasattr(e, 'response') and hasattr(e.response, 'text'):
                    logger.error(f"Response error: {e.response.text}")
                raise Exception(f"Failed to start conversation with assistant: {str(e)}")

            # Monitor the run status with enhanced logging
            max_retries = 40  # Maximum number of status checks
            retries = 0
            
            while retries < max_retries:
                try:
                    status_response = await self.make_request(
                        method="GET",
                        url=f"{self.base_url}/threads/{thread_id}/runs/{run_id}",
                        headers=self.headers
                    )
                    
                    # Log current status on each check
                    logger.info(f"Run status check {retries+1}/{max_retries}: {status_response['status']}")
                    
                except Exception as e:
                    logger.error(f"Error checking run status: {str(e)}")
                    if hasattr(e, 'response') and hasattr(e.response, 'text'):
                        logger.error(f"Response error: {e.response.text}")
                    retries += 1
                    await asyncio.sleep(1)
                    continue

                # Handle function calls (remaining logic same as before)
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

                    
                # On completion, get the final response
                elif status_response["status"] == "completed":
                    logger.info(f"Run completed successfully after {retries+1} checks")
                    
                    try:
                        messages_response = await self.make_request(
                            method="GET",
                            url=f"{self.base_url}/threads/{thread_id}/messages",
                            headers=self.headers,
                            params={"limit": 1, "order": "desc"}
                        )
                        
                        # Log response details
                        if messages_response.get("data") and len(messages_response["data"]) > 0:
                            message_id = messages_response["data"][0].get("id", "unknown")
                            logger.info(f"Retrieved message ID: {message_id}")
                            
                            # Check if content exists
                            message_content = messages_response["data"][0].get("content", [])
                            if not message_content:
                                logger.error("Message content array is empty")
                                raise Exception("Empty message content returned")
                                
                            # Check if it contains text content
                            has_text = any(content.get("type") == "text" for content in message_content)
                            logger.info(f"Message has text content: {has_text}")
                            
                            if has_text:
                                # Extract and return the text value
                                text_content = next((content["text"]["value"] for content in message_content 
                                                if content.get("type") == "text" and content.get("text", {}).get("value")), None)
                                
                                if text_content:
                                    logger.info(f"Response text length: {len(text_content)}")
                                    logger.info(f"Response preview: {text_content[:100]}...")
                                    return text_content
                                else:
                                    logger.error("No text value found in message content")
                                    raise Exception("No valid text content in response")
                            else:
                                logger.error("No text type content in message")
                                logger.error(f"Available content types: {[content.get('type') for content in message_content]}")
                                raise Exception("No text content in response")
                        else:
                            logger.error("No messages returned in response")
                            logger.error(f"Full response: {json.dumps(messages_response, indent=2)}")
                            raise Exception("Invalid message response")
                            
                    except Exception as e:
                        logger.error(f"Error retrieving messages: {str(e)}")
                        if hasattr(e, 'response') and hasattr(e.response, 'text'):
                            logger.error(f"Response error: {e.response.text}")
                        raise Exception(f"Failed to retrieve assistant response: {str(e)}")

                # Handle failure states with detailed logging
                elif status_response["status"] in ["failed", "cancelled", "expired"]:
                    # Extract error information
                    error_message = status_response.get("last_error", {}).get("message", "Unknown error")
                    error_code = status_response.get("last_error", {}).get("code", "unknown")
                    
                    # Log full status response for debugging
                    logger.error(f"Run failed with full status response: {json.dumps(status_response, indent=2)}")
                    logger.error(f"Run failed with status: {status_response['status']}, code: {error_code}, message: {error_message}")
                    
                    # Try to get more details about the run steps
                    try:
                        run_steps_response = await self.make_request(
                            method="GET",
                            url=f"{self.base_url}/threads/{thread_id}/runs/{run_id}/steps",
                            headers=self.headers
                        )
                        
                        # Log the run steps for detailed debugging
                        if run_steps_response.get("data"):
                            steps = run_steps_response.get("data", [])
                            logger.error(f"Run had {len(steps)} steps before failure")
                            
                            # Log each step with its status
                            for i, step in enumerate(steps):
                                step_id = step.get("id", "unknown")
                                step_type = step.get("type", "unknown")
                                step_status = step.get("status", "unknown")
                                
                                logger.error(f"Step {i+1}: ID={step_id}, Type={step_type}, Status={step_status}")
                                
                                # If step has error, log it
                                if step.get("step_details") and step.get("step_details").get("message_creation") and step.get("step_details").get("message_creation").get("text"):
                                    logger.error(f"Step message: {step['step_details']['message_creation']['text']}")
                        else:
                            logger.error("No run steps found")
                            
                    except Exception as step_err:
                        logger.error(f"Error getting run steps: {str(step_err)}")
                    
                    # Return appropriate error message
                    if error_code == "rate_limit_exceeded":
                        raise Exception("The AI service is currently experiencing high demand. Please try again in a few minutes.")
                    elif error_code == "content_filter":
                        raise Exception("Your message couldn't be processed due to content filtering. Please rephrase your question.")
                    else:
                        raise Exception(f"Run failed: {error_message}")

                # Still in progress
                else:
                    retries += 1
                    await asyncio.sleep(1)
                    continue

            # If we've exceeded max retries
            logger.error(f"Run timed out after {max_retries} checks")
            raise Exception("The request timed out. Please try again later.")

        except Exception as e:
            logger.error(f"Error processing message: {str(e)}", exc_info=True)
            raise

    async def __aenter__(self): # Simply returns the service instance itself
        """Support for async context manager protocol."""
        return self


    async def __aexit__(self, exc_type, exc_val, exc_tb): # clean up resources
        """Ensure proper cleanup of resources when used as a context manager."""
        await self.close()

    async def ensure_vector_store_attached(self, assistant_id: str, vector_store_id: str = "vs_6806b8d5767c8191b307104b59ce1949") -> bool:
        """
        Ensures the specified vector store is properly attached to the assistant.
        Returns True if successful, False otherwise.
        
        This solves the issue where vector stores appear in the UI but aren't properly
        configured in the API.
        """
        try:
            # Check if assistant exists and has the vector store attached
            logger.info(f"Verifying vector store attachment for assistant {assistant_id}")
            
            # Get current assistant configuration
            assistant_response = await self.make_request(
                method="GET",
                url=f"{self.base_url}/assistants/{assistant_id}",
                headers=self.headers
            )
            
            # Check if vector store is already attached
            tool_resources = assistant_response.get('tool_resources', {})
            file_search = tool_resources.get('file_search', {})
            vector_store_ids = file_search.get('vector_store_ids', [])
            
            if vector_store_id in vector_store_ids:
                logger.info(f"Vector store {vector_store_id} is already attached to assistant {assistant_id}")
                return True
                
            # Vector store not attached, update the assistant
            logger.info(f"Attaching vector store {vector_store_id} to assistant {assistant_id}")
            
            updated_assistant = await self.make_request(
                method="POST",
                url=f"{self.base_url}/assistants/{assistant_id}",
                headers=self.headers,
                data={
                    "tool_resources": {
                        "file_search": {
                            "vector_store_ids": [vector_store_id]
                        }
                    }
                }
            )
            
            # Verify update
            updated_tool_resources = updated_assistant.get('tool_resources', {})
            updated_file_search = updated_tool_resources.get('file_search', {})
            updated_vector_store_ids = updated_file_search.get('vector_store_ids', [])
            
            if vector_store_id in updated_vector_store_ids:
                logger.info(f"Successfully attached vector store {vector_store_id} to assistant {assistant_id}")
                return True
            else:
                logger.warning(f"Failed to attach vector store {vector_store_id} to assistant {assistant_id}")
                return False
                
        except Exception as e:
            logger.error(f"Error ensuring vector store attachment: {str(e)}")
            return False