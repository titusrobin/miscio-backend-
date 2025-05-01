# app/services/openai_service.py
from app.core.config import settings
from typing import Dict, Any, Optional, List
from app.services.base_service import BaseAPIService
import json
import asyncio
import logging
import os

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
                        "description": "Run a detailed campaign to send personalized messages to students on behalf of the school admin",
                        "parameters": {
                            "type": "object",
                            "properties": { # JSON Schema to define inputs function needs
                                "campaign_purpose": {
                                "type": "string",
                                "description": "The primary goal and intent of this campaign (e.g., 'introduce a new resource', 'remind about deadlines', 'gather feedback')"
                            },
                            "campaign_details": {
                                "type": "string",
                                "description": "Comprehensive description of the campaign with all important context and background information the admin wants us aware of"
                            },
                            "target_audience": {
                                "type": "string",
                                "description": "Which students this targets (e.g., 'all students', 'first-year students', 'students who haven't responded')",
                                "default": "all students"
                            },
                            "tone_and_style": {
                                "type": "string",
                                "description": "How messages should sound (e.g., 'friendly', 'formal', 'encouraging', 'urgent')",
                                "default": "friendly and helpful"
                            },
                            "key_points": {
                                "type": "string",
                                "description": "Essential information that must be included in the first message"
                            },
                            "call_to_action": {
                                "type": "string",
                                "description": "What students should do after reading (e.g., 'respond with questions', 'check a resource', 'complete a task')",
                                "default": ""
                            }
                            },
                            "required": ["campaign_purpose", "campaign_details", "key_points"]
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
                },
                {
                    "type": "file_search"
                }
            ]

            # Configure the assistant with instructions and tools
            assistant_data = {
                "name": f"Admin Assistant - {admin_id}",
                "instructions": """You are an advanced administrative assistant for Miscio, specializing in student communications and campaign management to help with admin care and support students. 
                Your role is to help admins effectively communicate with students and analyze communications.

                CAMPAIGN CREATION GUIDANCE:
                When an admin wants to create a campaign to reach out to students:
                1. Thoroughly analyze the full context of what they're trying to achieve
                2. Extract detailed information about:
                - The campaign's primary purpose and goals
                - Key information that needs to be communicated
                - Preferred tone and communication style
                - Any specific call to action for students
                3. Consider the entire conversation history for context
                4. Reference any uploaded documents when relevant
                5. Use the run_campaign function with comprehensive details

                FILE AND KNOWLEDGE MANAGEMENT:
                1. Use the file_search tool to reference uploaded documents
                2. Incorporate relevant document information into your responses
                3. Consider document content when creating campaigns
                4. Students asking questions should only have their questions answered using file_search, don't need to allow students for other tools. 

                STUDENT INTERACTION ANALYSIS:
                1. Use query_student_chats to analyze student conversations
                2. Identify patterns, common questions, and feedback themes
                3. Provide insights to help admins improve communications
                
                Always maintain a professional, helpful tone. Ensure all campaign messages will be personally relevant to students and reflect the admin's communication goals.""",
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
        run_handler: Optional[callable] = None, # optionalfunction to handle tool calls
        thread_tool_resources: Optional[dict] = None
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

                # Check if file_search is enabled for this assistant
                tools = assistant_response.get('tools', [])
                has_file_search = any(tool.get('type') == 'file_search' for tool in tools)
                logger.info(f"Assistant has file search enabled: {has_file_search}")
                
                # Log file information
                tool_resources = assistant_response.get('tool_resources', {})
                file_search = tool_resources.get('file_search', {})
                vector_store_ids = file_search.get('vector_store_ids', [])
                if vector_store_ids:
                    logger.info(f"Assistant has vector stores: {vector_store_ids}")
                
                # Add file_search tool if not present but vector_store_ids are attached
                if not has_file_search and vector_store_ids:
                    logger.info(f"Adding file_search tool to assistant {assistant_id}")
                    tools.append({"type": "file_search"})
                    await self.make_request(
                        method="POST",
                        url=f"{self.base_url}/assistants/{assistant_id}",
                        headers=self.headers,
                        data={"tools": tools}
                    )
                    logger.info(f"Added file_search tool to assistant {assistant_id}")
                    
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

            # Prepare run data with thread_tool_resources if provided
            run_data = {"assistant_id": assistant_id}
            if thread_tool_resources:
                run_data["tool_resources"] = thread_tool_resources
                logger.info(f"Including tool resources in run: {json.dumps(thread_tool_resources, indent=2)}")

            # Create and start a new run with improved error handling
            try:
                run_response = await self.make_request(
                    method="POST",
                    url=f"{self.base_url}/threads/{thread_id}/runs",
                    headers=self.headers,
                    data=run_data
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
                        # Get run steps to check if file search was used
                        run_steps_response = await self.make_request(
                            method="GET",
                            url=f"{self.base_url}/threads/{thread_id}/runs/{run_id}/steps",
                            headers=self.headers,
                            #params={"include[]": "step_details.tool_calls.file_search.results.content"}

                        )
                        
                        # Log if file search was used
                        if run_steps_response.get("data"):
                            for step in run_steps_response.get("data", []):
                                if step.get("step_details") and step.get("step_details").get("tool_calls"):
                                    for tool_call in step.get("step_details").get("tool_calls", []):
                                        if tool_call.get("type") == "file_search":
                                            results = tool_call.get("file_search", {}).get("results", [])
                                            logger.info(f"File search used in run with {len(results)} results")
                        
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


    # file is first sent to your backend server
    # backend server temporarily stores this file somewhere (usually in memory or in a temporary directory)
    async def upload_file(self, file_path: str, purpose: str = "assistants") -> dict:
        """
        Upload a file to OpenAI for use with assistants.
        
        Args:
            file_path: Path to the file to upload
        """
        try:
            filename = os.path.basename(file_path)
            logger.info(f"Uploading file: {filename} from path: {file_path}")
            
            client = await self.get_client()
            
            headers = self.headers.copy()
            headers.pop("Content-Type", None)
            
            # Open the file and create the form data
            with open(file_path, "rb") as file:
                files = {"file": (filename, file, "application/octet-stream")} #content is a binary file
                data = {"purpose": purpose}
                
                # Make the request directly with httpx
                response = await client.post(
                    f"{self.base_url}/files",
                    headers=headers,
                    files=files,
                    data=data
                )
                response.raise_for_status()
                result = response.json()
                
                logger.info(f"File uploaded successfully: {result.get('id')}")
                return result
                
        except Exception as e:
            logger.error(f"Error uploading file: {str(e)}")
            raise Exception(f"Failed to upload file: {str(e)}")
    
    async def create_vector_store(self, name: str, file_ids: list = None) -> dict:
        """
        Create a new vector store for file search.
        
        Args:
            name: Name of the vector store
        """
        try:
            data = {"name": name}
            if file_ids:
                # Ensure file_ids is a list
                if not isinstance(file_ids, list):
                    file_ids = [file_ids]
                data["file_ids"] = file_ids
                
            logger.info(f"Creating vector store with data: {json.dumps(data)}")
                
            # Request to create vector store
            response = await self.make_request(
                method="POST",
                url=f"{self.base_url}/vector_stores",
                headers=self.headers,
                data=data
            )

            # Validate response
            if not response:
                logger.error("Empty response from vector store creation API")
                raise Exception("Empty response from vector store creation API")
            
            vector_store_id = response.get("id")
            logger.info(f"Vector store created: {vector_store_id}")
            
            # If file_ids were provided, poll until processing is complete
            if file_ids:
                await self.poll_vector_store_status(vector_store_id) # checking the status of the vector store creation process 
                
            return response
        
        except Exception as e:
            logger.error(f"Error creating vector store: {str(e)}")
            raise Exception(f"Failed to create vector store: {str(e)}")
        
    async def poll_vector_store_status(self, vector_store_id: str) -> dict:
        """
        Poll a vector store until all files are processed.
        
        Args:
            vector_store_id: ID of the vector store
            
        Returns:
            Final vector store object
        """
        MAX_RETRIES = 30
        retry_count = 0
        
        while retry_count < MAX_RETRIES:
            try:
                response = await self.make_request(
                    method="GET",
                    url=f"{self.base_url}/vector_stores/{vector_store_id}",
                    headers=self.headers
                )
                
                # Check file counts
                file_counts = response.get("file_counts", {})
                in_progress = file_counts.get("in_progress", 0)
                
                # If no files are still in progress, we're done
                if in_progress == 0:
                    logger.info(f"Vector store {vector_store_id} processing complete")
                    return response
                    
                # Wait before retrying
                retry_count += 1
                logger.info(f"Vector store processing in progress: {in_progress} files. Retry {retry_count}/{MAX_RETRIES}")
                await asyncio.sleep(3)
                
            except Exception as e:
                logger.error(f"Error polling vector store: {str(e)}")
                retry_count += 1
                await asyncio.sleep(5)
        
        logger.warning(f"Vector store polling timed out after {MAX_RETRIES} retries")
        return response

    async def add_file_to_vector_store(self, vector_store_id: str, file_id: str) -> dict:
        """
        Add a file to an existing vector store.
        
        Args:
            vector_store_id: ID of the vector store
            file_id: ID of the file to add
            
        Returns:
            File batch object
        """
        try:
            # Add file to vector store
            response = await self.make_request(
                method="POST",
                url=f"{self.base_url}/vector_stores/{vector_store_id}/files",
                headers=self.headers,
                data={"file_id": file_id}
            )
            
            logger.info(f"File {file_id} added to vector store {vector_store_id}")
            
            # Poll until processing is complete
            await self.poll_vector_store_file_status(vector_store_id, file_id)
            
            return response
        except Exception as e:
            logger.error(f"Error adding file to vector store: {str(e)}")
            raise Exception(f"Failed to add file to vector store: {str(e)}")
    
    ###TODO reduce redundancy of this function
    async def poll_vector_store_file_status(self, vector_store_id: str, file_id: str) -> dict:
        """
        Poll a vector store file until it is processed.
        
        Args:
            vector_store_id: ID of the vector store
            file_id: ID of the file to check
            
        Returns:
            File object
        """
        MAX_RETRIES = 30
        retry_count = 0
        
        while retry_count < MAX_RETRIES:
            try:
                response = await self.make_request(
                    method="GET",
                    url=f"{self.base_url}/vector_stores/{vector_store_id}/files/{file_id}",
                    headers=self.headers
                )
                
                # Check file status
                status = response.get("status")
                
                if status == "completed":
                    logger.info(f"File {file_id} processing complete")
                    return response
                elif status == "failed":
                    error_message = response.get("error", {}).get("message", "Unknown error")
                    logger.error(f"File {file_id} processing failed: {error_message}")
                    raise Exception(f"File processing failed: {error_message}")
                    
                # Wait before retrying
                retry_count += 1
                logger.info(f"File processing in progress: {status}. Retry {retry_count}/{MAX_RETRIES}")
                await asyncio.sleep(3)
                
            except Exception as e:
                logger.error(f"Error polling file status: {str(e)}")
                retry_count += 1
                await asyncio.sleep(5)
        
        logger.warning(f"File polling timed out after {MAX_RETRIES} retries")
        return response

    async def remove_file_from_vector_store(self, vector_store_id: str, file_id: str) -> None:
        """
        Remove a file from a vector store.
        
        Args:
            vector_store_id: ID of the vector store
            file_id: ID of the file to remove
        """
        try:
            await self.make_request(
                method="DELETE",
                url=f"{self.base_url}/vector_stores/{vector_store_id}/files/{file_id}",
                headers=self.headers
            )
            
            logger.info(f"File {file_id} removed from vector store {vector_store_id}")
        except Exception as e:
            logger.error(f"Error removing file from vector store: {str(e)}")
            raise Exception(f"Failed to remove file from vector store: {str(e)}")

    async def delete_file(self, file_id: str) -> None:
        """
        Delete a file from OpenAI.
        
        Args:
            file_id: ID of the file to delete
        """
        try:
            await self.make_request(
                method="DELETE",
                url=f"{self.base_url}/files/{file_id}",
                headers=self.headers
            )
            
            logger.info(f"File {file_id} deleted from OpenAI")
        except Exception as e:
            logger.error(f"Error deleting file: {str(e)}")
            raise Exception(f"Failed to delete file: {str(e)}")

    async def attach_vector_store_to_assistant(self, assistant_id: str, vector_store_id: str) -> dict:
        """
        Attach a vector store to an assistant.
        
        Args:
            assistant_id: ID of the assistant
            vector_store_id: ID of the vector store
            
        Returns:
            Updated assistant object
        """
        try:
            # Check if file_search is already in tools
            assistant_response = await self.make_request(
                method="GET",
                url=f"{self.base_url}/assistants/{assistant_id}",
                headers=self.headers
            )
            
            # Get current tools
            tools = assistant_response.get("tools", [])
            
            # Check if file_search is already in tools
            has_file_search = any(tool.get("type") == "file_search" for tool in tools)
            
            if not has_file_search:
                # Add file_search to tools
                tools.append({"type": "file_search"})
            
            # Update assistant with vector store
            response = await self.make_request(
                method="POST",
                url=f"{self.base_url}/assistants/{assistant_id}",
                headers=self.headers,
                data={
                    "tools": tools,
                    "tool_resources": {
                        "file_search": {
                            "vector_store_ids": [vector_store_id]
                        }
                    }
                }
            )
            
            logger.info(f"Vector store {vector_store_id} attached to assistant {assistant_id}")
            return response
        except Exception as e:
            logger.error(f"Error attaching vector store to assistant: {str(e)}")
            raise Exception(f"Failed to attach vector store to assistant: {str(e)}")
    
    async def ensure_vector_store_attached(self, assistant_id: str, vector_store_id: str) -> bool:
        """
        Ensures the specified vector store is properly attached to the assistant.
        Returns True if successful, False otherwise.
        """
        try:
            # Get current assistant configuration
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
            
            # Check if file_search is in tools
            tools = assistant_response.get('tools', [])
            has_file_search = any(tool.get('type') == 'file_search' for tool in tools)
            
            if not has_file_search:
                # Add file_search to tools
                tools.append({"type": "file_search"})
            
            updated_assistant = await self.make_request(
                method="POST",
                url=f"{self.base_url}/assistants/{assistant_id}",
                headers=self.headers,
                data={
                    "tools": tools,
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