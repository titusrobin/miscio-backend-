# app/services/openai_service.py
from app.core.config import settings
from typing import Dict, Any, Optional, List
from app.services.base_service import BaseAPIService
import json
import asyncio
import logging
import os
import random 

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
                        "name": "create_messaging_draft",
                        "description": "Create a draft messaging campaign that requires admin approval before sending to students",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "campaign_purpose": {
                                    "type": "string",
                                    "description": "The primary goal and intent of this messaging campaign (e.g., 'remind about library hours', 'announce new resources', 'inform about deadline')"
                                },
                                "campaign_details": {
                                    "type": "string",
                                    "description": "Comprehensive description of what needs to be communicated to students with all important context"
                                },
                                "target_audience": {
                                    "type": "string",
                                    "description": "Which students this targets",
                                    "default": "all students"
                                },
                                "tone_and_style": {
                                    "type": "string",
                                    "description": "How the message should sound (e.g., 'friendly and helpful', 'formal', 'encouraging', 'urgent')",
                                    "default": "friendly and helpful"
                                },
                                "key_points": {
                                    "type": "string",
                                    "description": "Essential information that must be included in the message to students"
                                },
                                "call_to_action": {
                                    "type": "string",
                                    "description": "What students should do after reading (e.g., 'respond with questions', 'check the portal', 'complete registration')",
                                    "default": "respond with any questions"
                                }
                            },
                            "required": ["campaign_purpose", "campaign_details", "key_points"]
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "execute_campaign",
                        "description": "Execute an approved campaign draft to send messages to all students",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "campaign_id": {
                                    "type": "string",
                                    "description": "The ID of the campaign draft to execute"
                                },
                                "confirmation": {
                                    "type": "string",
                                    "description": "Admin confirmation that the campaign should be sent (e.g., 'approved', 'send now')"
                                }
                            },
                            "required": ["campaign_id", "confirmation"]
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "create_feedback_draft",
                        "description": "Create a draft feedback campaign with research questions that requires admin approval",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "campaign_purpose": {
                                    "type": "string",
                                    "description": "The primary goal of this feedback campaign (e.g., 'assess student satisfaction with dining services', 'gather opinions on new academic policy')"
                                },
                                "research_topic": {
                                    "type": "string", 
                                    "description": "Detailed description of what you want to research or get feedback about"
                                },
                                "target_audience": {
                                    "type": "string",
                                    "description": "Which students this targets",
                                    "default": "all students"
                                },
                                "conversation_style": {
                                    "type": "string",
                                    "description": "How the feedback conversations should feel (e.g., 'casual and friendly', 'professional survey', 'supportive check-in')",
                                    "default": "casual and friendly"
                                },
                                "admin_provided_questions": {
                                    "type": "array",
                                    "description": "Questions provided by the admin (if any). Leave empty if admin wants AI to generate questions.",
                                    "items": {"type": "string"},
                                    "default": []
                                }
                            },
                            "required": ["campaign_purpose", "research_topic"]
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "update_messaging_draft",
                        "description": "Update an existing messaging draft with specific modifications",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "campaign_id": {"type": "string", "description": "ID of the draft to update"},
                                "modification_request": {"type": "string", "description": "Specific change requested (e.g., 'make it a one-liner', 'more formal tone')"},
                                "revised_message": {"type": "string", "description": "The updated message content"},
                                "revised_subject": {"type": "string", "description": "Updated subject line if needed"}
                            },
                            "required": ["campaign_id", "modification_request", "revised_message"]
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
            "instructions": """You are an advanced AI school administrative/student services assistant with role-adaptive capabilities.

            CRITICAL ROLE DETECTION:
            - Check for role context in each conversation
            - Admin conversations: Full administrative capabilities
            - Student conversations: Limited to support role with strict confidentiality

            WHEN IN ADMIN MODE (default):
            """ + """You currently specialize in student communications and campaign management. Your role is to assist school admins create and execute both MESSAGING(broadcast-type) and FEEDBACK(survey-type) communication campaigns.

                CAMPAIGN TYPE DETECTION:
                Automatically detect campaign type from admin requests:
                
                MESSAGING CAMPAIGNS - Keywords/intent: "remind", "announce", "let know", "inform", "tell students", "notify"
                FEEDBACK CAMPAIGNS - Keywords/intent: "feedback", "survey", "get opinions", "find out what students think", "assess", "gather input", "research"
                
                When intent is UNCLEAR, ask for clarification: "I can approach this as either MESSAGING (inform students about X) or FEEDBACK (gather opinions about X). Which would you advice is more helpful?"

                MESSAGING CAMPAIGN WORKFLOW:
                When an admin wants to send a message to students:
                1. Automatically detect this is a MESSAGING campaign
                2. If you have questions, ask them to better create the draft, but MAKE SURE YOU DO NOT MAKE UP ANY INFORMATION -- DON'T ASSUME what is not provided please.
                3. Use create_messaging_draft function to generate a complete draft message
                3. Present the draft with format(example):

                "Here's a draft:

                [THE GENERATED MESSAGE CONTENT]

                Do you have any changes in mind, or should I go ahead with this?"

                4. When admin approves (says things like "good to go", "send it", "approved", "this is fine"):
                - Use execute_campaign function with the campaign_id from the draft
                - Confirm the message has been sent to all students

                5. When admin requests changes:
                - Use update_messaging_draft instead of creating a new draft. Always reference the most recent campaign_id from the conversation.

                FEEDBACK CAMPAIGN WORKFLOW:
                When an admin wants to gather feedback or conduct research:
                1. Automatically detect this is a FEEDBACK campaign
                2. Use create_feedback_draft function
                3. If admin provided specific questions, confirm them with admin(example):
                
                "I'll cover these questions conversationally:
                1. [Question 1]
                2. [Question 2]
                ...
                
                Should I add any additional questions, or start the feedback campaign?"
                
                4. If no questions provided, generate 2-3 relevant research questions:
                
                "Research questions:
                1. [Generated question 1]
                2. [Generated question 2]
                ...
                
                Do you have any additional data points in mind, or should I go ahead with this?"
                
                5. When admin approves questions:
                - Use execute_campaign function to start the feedback campaign
                - Confirm that feedback conversations will begin with students

                CAMPAIGN EXECUTION:
                - MESSAGING: Immediate delivery to all students after approval
                - FEEDBACK: Gradual conversation initiation to naturally cover approved questions
                - Always provide confirmation that campaign has started
                - Include execution summary when available

                MESSAGE GENERATION GUIDELINES:
                - Keep messages concise and student-friendly (1-2 paragraphs max)
                - Use the specified tone (default: friendly and helpful)
                - Include all key points naturally in the message
                - Make it personal and engaging for students
                - Don't use asterisks or markdown formatting

                QUESTION GENERATION GUIDELINES:
                - Create 2-3 qualitative research questions that cover the topic comprehensively(insightful/good questions, not just plain and direct)
                - Mix question types: open-ended, specific examples
                - Frame questions conversationally (not robotic survey style)
                - Include follow-up prompts ("opinion + why", "examples", etc.)
                - Cover both current state and improvement suggestions
                - Ensure questions will gather actionable insights

                CORE PRINCIPLES:
                - Always create drafts first for admin review
                - Present content in the specified formats
                - Execute campaigns immediately after admin approval
                - Provide execution confirmation with details
                - Ask for clarification when campaign type is ambiguous
                - Maintain professional, helpful tone throughout all interactions""" + """

            WHEN IN STUDENT MODE (when additional_instructions indicate student context):
            You transform into a friendly student support team member.

            CRITICAL STUDENT INTERACTION RULES:
            1. CONFIDENTIALITY IS PARAMOUNT
            - NEVER mention other students' names, responses, or information
            - NEVER reveal admin conversations or internal processes
            - NEVER discuss campaign mechanics or how messages were sent
            - Treat each student conversation as completely isolated

            2. ROLE BEHAVIOR
            - You are a member of the student support team
            - You work at their school and care about their experience
            - You're reaching out to check in or share information
            - You have no knowledge of other students or admin operations
            - WHEN THE FEEDBACK QUESTION LIST IS COVERED, NATURALLY END CONVO WITH STUDENT, DON'T KEEP ASKING AND BOGGING THEM DOWN

            3. CONVERSATION STYLE
            - Warm, approachable, and genuine
            - Use natural, conversational language
            - Show genuine interest in their feedback
            - Be helpful with their questions
            - DO NOT OVERDO THE CARE, THEY WILL SEEM INGENUINE, STARTING OFF WITH EMPATHY IS GREAT, THEN BE DIRECT AND GENUINE 

            4. FORBIDDEN TOPICS IN STUDENT MODE
            - Campaign creation or management
            - Other students' information or responses  
            - Admin tools or functions
            - Internal processes or operations
            - Any data aggregation or analytics

            5. IF ASKED ABOUT CAPABILITIES
            - "I'm here to help answer questions and gather feedback"
            - "I work with the student support team"
            - Never mention AI, assistant, or technical capabilities

            Remember: When talking to students, you know ONLY about that specific student and the current topic. WHEN THE FEEDBACK QUESTION LIST IS COVERED, NATURALLY END CONVO WITH STUDENT, DON'T KEEP ASKING AND BOGGING THEM DOWN
            Each conversation exists in complete isolation for privacy and confidentiality.


            REFERENCE_EXAMPLE: 
            **REFERENCE EXAMPLE** - Innovation Program Dropout Prevention (adapt this excellence standard to any domain/request by admin):

            **Example Scenario**: User runs an 8-week innovation program, loses 50% of students, needs pulse check at Week 3

            **Excellent Greeting Response**:
            "Liam, it's an honor to partner with you in developing the next generation of Kingdom innovators! 🙌 Based on your role, here's how I can specifically help you with real-time student care, north star metrics analysis, and feedback intelligence..."

            **Excellent Pulse Check Questions** (note: NOT asking directly about struggles):
            1. "What's one thing about this program that surprised you so far? How does it compare to what you expected when you first signed up?"
            2. "Imagine it's 6 months from now and you're telling a colleague about your experience. What's the first story you'd share?"

            **Excellent Response Analysis** (reading between the lines):
            - "Classic imposter syndrome - expectation mismatch between 'creative thinking' and 'tech implementation.' Struggling with belonging. Can't visualize positive outcomes."
            - "Value misalignment between expectations (ministry focus) and perceived reality (business focus). Questioning program relevance - moderate dropout risk."
            - "Unable to engage with future-thinking due to present crisis. Clear indicators of overwhelm and inability to process program content. Needs immediate support."

            **Excellent Summary Report**:
            "Week 3 retention risk analysis: HIGH DROPOUT RISK - James (imposter syndrome + tech intimidation), David (personal crisis overwhelming engagement). MODERATE RISK - Sarah (value misalignment). STRONG RETENTION - Maria (empowered), Rachel (identity transformation). Recommended Actions: 1. Create tech-optional track for James 2. Share ministry-specific examples with Sarah 3. Offer David flexible timeline. This could move completion rate from 50% to 78%."

            **KEY EXCELLENCE STANDARDS** (apply to ANY conversation):
            - Use warm, collegial tone that acknowledges their expertise and mission
            - Ask indirect questions that reveal psychological states rather than direct problem questions  
            - Analyze responses for deeper patterns (imposter syndrome, value misalignment, crisis overwhelm, etc.)
            - Provide specific, actionable insights with predicted outcomes
            - Adapt language to their domain while maintaining this standard of sophistication""",
                            "model": settings.OPENAI_ASSISTANT_MODEL,
                            "tools": tools
                        }

            # Create the assistant using the OpenAI API
            #logger.info(f"Creating assistant for admin {admin_id} via endpoint: {self.base_url}/assistants")
            #logger.info(f"Assistant configuration: {json.dumps(assistant_data, indent=2)}")
            response = await self.make_request(
                method="POST",
                url=f"{self.base_url}/assistants",
                headers=self.headers,
                data=assistant_data
            )
            
            # Create an initial thread for the assistant
            #logger.info(f"Creating initial thread via endpoint: {self.base_url}/threads")            
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
        #logger.info(f"Creating new thread via endpoint: {self.base_url}/threads")
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
        thread_tool_resources: Optional[dict] = None, # files/rag
        additional_instructions: Optional[str] = None  # NEW PARAMETER
    ) -> str:
        """
        Process a message with support for function calling.

        1. Thread is simply a container for storing messages
        2. Run actual execution of assistant's instructions
        """
        logger.warning(f"OpenAI process/message() - Thread: {thread_id}, Assistant: {assistant_id}, Message: {message[:100]}...") 
        #logger.info(f"Starting to process message in thread {thread_id}")
        #logger.info(f"Assistant ID: {assistant_id}")
        #logger.info(f"Run handler provided: {run_handler is not None}")
        #logger.info(f"Message content: {message[:100]}..." if len(message) > 100 else f"Message content: {message}")

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
                #logger.info(f"Assistant has file search enabled: {has_file_search}")
                
                # Log file information
                tool_resources = assistant_response.get('tool_resources', {})
                file_search = tool_resources.get('file_search', {})
                vector_store_ids = file_search.get('vector_store_ids', [])
                #if vector_store_ids:
                 #   logger.info(f"Assistant has vector stores: {vector_store_ids}")
                
                # Add file_search tool if not present but vector_store_ids are attached
                if not has_file_search and vector_store_ids:
                    #logger.info(f"Adding file_search tool to assistant {assistant_id}")
                    tools.append({"type": "file_search"})
                    await self.make_request(
                        method="POST",
                        url=f"{self.base_url}/assistants/{assistant_id}",
                        headers=self.headers,
                        data={"tools": tools}
                    )
                    # logger.info(f"Added file_search tool to assistant {assistant_id}")
                    
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
            #logger.warning(f"process/message() - Created message in thread.")

            # Prepare run data with thread_tool_resources if provided
            run_data = {"assistant_id": assistant_id}
            if thread_tool_resources:
                run_data["tool_resources"] = thread_tool_resources
                #logger.info(f"Including tool resources in run: {json.dumps(thread_tool_resources, indent=2)}")

            # NEW: Add additional_instructions if provided
            if additional_instructions:
                run_data["additional_instructions"] = additional_instructions
                # logger.info(f"CMP: OpenAI context mode - {additional_instructions[:100]}...")  # ADD THIS
                #logger.info(f"Including additional instructions for role: {'student' if 'STUDENT' in additional_instructions else 'admin'}")
            
            # Create and start a new run with improved error handling
            try:
                run_response = await self.make_request(
                    method="POST",
                    url=f"{self.base_url}/threads/{thread_id}/runs",
                    headers=self.headers,
                    data=run_data
                )
                run_id = run_response["id"]
                logger.warning(f"process/message() - Started new run with ID")
                
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
                    logger.warning(f"process/message() - Run status check {retries+1}/{max_retries}: {status_response['status']}")
                    
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
                        logger.warning(f"process/message RUN: Received tool calls to process at {retries} and tool calls: {tool_calls}")
                        
                        tool_outputs = await run_handler(tool_calls) # tool_calls is data from OpenAI describing what functions to call and with what parameters
                        logger.warning(f"process/message RUN: Tool outputs: {tool_outputs}") #TODO: There's a lot of redundancy in this dict returned / token consumption 
                        
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
                    logger.warning(f"process/message() - Run completed successfully at {retries+1} steps")
                    
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
                                            #logger.info(f"File search used in run with {len(results)} results")
                        
                        messages_response = await self.make_request(
                            method="GET",
                            url=f"{self.base_url}/threads/{thread_id}/messages",
                            headers=self.headers,
                            params={"limit": 1, "order": "desc"}
                        )
                        
                        # Log response details
                        if messages_response.get("data") and len(messages_response["data"]) > 0:
                            message_id = messages_response["data"][0].get("id", "unknown")
                            #logger.info(f"Retrieved message ID: {message_id}")
                            
                            # Check if content exists
                            message_content = messages_response["data"][0].get("content", [])
                            if not message_content:
                                #logger.error("Message content array is empty")
                                raise Exception("Empty message content returned")
                                
                            # Check if it contains text content
                            has_text = any(content.get("type") == "text" for content in message_content)
                            #logger.info(f"Message has text content: {has_text}")
                            
                            if has_text:
                                # Extract and return the text value
                                text_content = next((content["text"]["value"] for content in message_content 
                                                if content.get("type") == "text" and content.get("text", {}).get("value")), None)
                                
                                #RETURN
                                if text_content:
                                    #logger.info(f"Response text length: {len(text_content)}")
                                    #logger.info(f"process/message() - Response preview: {text_content[:100]}...")
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
            # logger.info(f"Uploading file: {filename} from path: {file_path}")
            
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
                
                # logger.info(f"File uploaded successfully: {result.get('id')}")
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
                
            # logger.info(f"Creating vector store with data: {json.dumps(data)}")
                
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
            # logger.info(f"Vector store created: {vector_store_id}")
            
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
                    # logger.info(f"Vector store {vector_store_id} processing complete")
                    return response
                    
                # Wait before retrying
                retry_count += 1
                # logger.info(f"Vector store processing in progress: {in_progress} files. Retry {retry_count}/{MAX_RETRIES}")
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
            
            # logger.info(f"File {file_id} added to vector store {vector_store_id}")
            
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
                    # logger.info(f"File {file_id} processing complete")
                    return response
                elif status == "failed":
                    error_message = response.get("error", {}).get("message", "Unknown error")
                    logger.error(f"File {file_id} processing failed: {error_message}")
                    raise Exception(f"File processing failed: {error_message}")
                    
                # Wait before retrying
                retry_count += 1
                # logger.info(f"File processing in progress: {status}. Retry {retry_count}/{MAX_RETRIES}")
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
            
            # logger.info(f"File {file_id} removed from vector store {vector_store_id}")
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
            
            # logger.info(f"File {file_id} deleted from OpenAI")
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
            
            # logger.info(f"Vector store {vector_store_id} attached to assistant {assistant_id}")
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
            #logger.info(f"Verifying vector store attachment for assistant {assistant_id}")
            
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
                #logger.info(f"Vector store {vector_store_id} is already attached to assistant {assistant_id}")
                return True
                    
            # Vector store not attached, update the assistant
            #logger.info(f"Attaching vector store {vector_store_id} to assistant {assistant_id}")
            
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
               #logger.info(f"Successfully attached vector store {vector_store_id} to assistant {assistant_id}")
                return True
            else:
               # logger.warning(f"Failed to attach vector store {vector_store_id} to assistant {assistant_id}")
                return False
                    
        except Exception as e:
            #logger.error(f"Error ensuring vector store attachment: {str(e)}")
            return False

    #########################################################################  
    ##################### Loading Assistant Stuff ##########################
    #########################################################################
    async def generate_loading_messages(self, user_prompt: str) -> List[str]:
        """
        Generate contextual loading messages for a user prompt using the dedicated loading assistant.
        
        Args:
            user_prompt: The original prompt from the admin user
            
        Returns:
            List of contextual loading messages to display during processing
        """
        try:
           # logger.info(f"Generating loading messages for prompt: {user_prompt[:100]}...")
            
            # Create a temporary thread for the loading assistant
            thread_data = await self.create_thread()
            thread_id = thread_data["id"]
            
            # Prepare the prompt for the loading assistant
            loading_prompt = f"""Generate ONLY a JSON array of 15-20 fun loading messages for this admin request: {user_prompt}

    CRITICAL: Return ONLY the JSON array, no explanations, no markdown, no extra text.

    Format: ["message1", "message2", ...]

    Make messages contextual to the request but keep them engaging and fun with emojis."""
            
            # Send message to loading assistant
            message_response = await self.make_request(
                method="POST",
                url=f"{self.base_url}/threads/{thread_id}/messages",
                headers=self.headers,
                data={"role": "user", "content": loading_prompt}
            )
          #  logger.info(f"Loading assistant message created: {message_response.get('id')}")
            
            # Create and start a run with the loading assistant
            run_response = await self.make_request(
                method="POST",
                url=f"{self.base_url}/threads/{thread_id}/runs",
                headers=self.headers,
                data={"assistant_id": settings.LOADING_ASSISTANT_ID}
            )
            run_id = run_response["id"]
          #  logger.info(f"Loading assistant run started: {run_id}")
            
            # Poll for completion (simplified version for loading assistant)
            max_retries = 20  # Loading assistant should be fast
            retries = 0
            
            while retries < max_retries:
                try:
                    status_response = await self.make_request(
                        method="GET",
                        url=f"{self.base_url}/threads/{thread_id}/runs/{run_id}",
                        headers=self.headers
                    )
                    
                    # logger.info(f"Loading assistant run status: {status_response['status']}")
                    
                    if status_response["status"] == "completed":
                        # Get the response
                        messages_response = await self.make_request(
                            method="GET",
                            url=f"{self.base_url}/threads/{thread_id}/messages",
                            headers=self.headers,
                            params={"limit": 1, "order": "desc"}
                        )
                        
                        if messages_response.get("data") and len(messages_response["data"]) > 0:
                            message_content = messages_response["data"][0].get("content", [])
                            if message_content and message_content[0].get("type") == "text":
                                response_text = message_content[0]["text"]["value"]
                                # logger.info(f"Loading assistant raw response: {response_text}")
                                
                                # Extract JSON from response that might have extra text
                                loading_messages = self._extract_json_from_response(response_text)
                                
                                if loading_messages and isinstance(loading_messages, list):
                                    # logger.info(f"Successfully generated {len(loading_messages)} loading messages")
                                    return loading_messages
                                else:
                                    logger.warning("Loading assistant didn't return a valid JSON array")
                                    return self._get_fallback_messages()
                        
                        logger.error("No valid content in loading assistant response")
                        return self._get_fallback_messages()
                    
                    elif status_response["status"] in ["failed", "cancelled", "expired"]:
                        error_message = status_response.get("last_error", {}).get("message", "Unknown error")
                        logger.error(f"Loading assistant run failed: {error_message}")
                        return self._get_fallback_messages()
                    
                    # Still in progress, wait and retry
                    retries += 1
                    await asyncio.sleep(1)
                    
                except Exception as e:
                    logger.error(f"Error checking loading assistant status: {str(e)}")
                    retries += 1
                    await asyncio.sleep(1)
            
            # Timeout reached
            logger.warning("Loading assistant timed out")
            return self._get_fallback_messages()
            
        except Exception as e:
            logger.error(f"Error generating loading messages: {str(e)}")
            return self._get_fallback_messages()
    
    def _extract_json_from_response(self, response_text: str) -> Optional[List[str]]:
        """
        Extract JSON array from a response that might contain extra text.
        """
        try:
            import json
            
            # Method 1: Try to parse the entire response as JSON
            try:
                result = json.loads(response_text.strip())
                if isinstance(result, list):
                    return result
            except json.JSONDecodeError:
                pass
            
            # Method 2: Look for JSON array markers
            start_index = response_text.find('[')
            end_index = response_text.rfind(']') + 1
            
            if start_index != -1 and end_index > start_index:
                json_text = response_text[start_index:end_index]
                try:
                    result = json.loads(json_text)
                    if isinstance(result, list):
                        return result
                except json.JSONDecodeError:
                    pass
            
            # Method 3: Look for markdown code blocks
            import re
            json_match = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', response_text, re.DOTALL)
            if json_match:
                try:
                    result = json.loads(json_match.group(1))
                    if isinstance(result, list):
                        return result
                except json.JSONDecodeError:
                    pass
            
            # Method 4: Look for lines that start with quotes (individual array items)
            lines = response_text.split('\n')
            extracted_messages = []
            for line in lines:
                line = line.strip()
                # Look for lines that look like JSON array items
                if line.startswith('"') and line.endswith('",') or line.endswith('"'):
                    try:
                        # Clean up the line to be valid JSON
                        clean_line = line.rstrip(',')
                        message = json.loads(clean_line)
                        if isinstance(message, str):
                            extracted_messages.append(message)
                    except:
                        continue
            
            if extracted_messages:
                return extracted_messages
                
            logger.warning(f"Could not extract JSON from response: {response_text[:200]}...")
            return None
            
        except Exception as e:
            logger.error(f"Error extracting JSON: {str(e)}")
            return None

    def _get_fallback_messages(self) -> List[str]:
        """
        Fallback loading messages in case the loading assistant fails.
        """
        all_messages = [
            "🚀 Thinking as we speak...",
            "Okay, hunting down the answer here...",
            "🎯 Zeroing in on your question real quick...",
            "Bullseye! Almost got it...",
            "✅ Quality checking what we have here...",
            "Alrighty, juggling a couple thoughts for a second..."
        ]
        
        # Randomly shuffle the messages for variety
        random.shuffle(all_messages)
        
        # Return a random subset (8-12 messages) to keep it fresh
        subset_size = random.randint(8, 12)
        return all_messages[:subset_size]