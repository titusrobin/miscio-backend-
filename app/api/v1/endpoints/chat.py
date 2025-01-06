# app/api/v1/endpoints/chat.py
from fastapi import APIRouter, Depends, HTTPException, status
from app.models.admin import Admin
from app.core.security import get_current_admin_user
from app.services.openai_service import OpenAIService
from app.services.campaign_service import CampaignService
from app.db.mongodb import db
from app.services.twilio_service import TwilioService
from typing import Dict, List
import logging
import json

router = APIRouter()
logger = logging.getLogger(__name__)


def get_openai_service():
    return OpenAIService()


def get_campaign_service():
    openai_service = OpenAIService()
    twilio_service = TwilioService()
    return CampaignService(openai_service, twilio_service, db.db)


async def handle_tool_calls(
    tool_calls: List[Dict], current_admin: Admin, campaign_service: CampaignService
) -> List[Dict]:
    """Handle function calls from the OpenAI assistant"""
    tool_outputs = []

    for tool_call in tool_calls:
        try:
            function_name = tool_call["function"]["name"]
            arguments = json.loads(tool_call["function"]["arguments"])
            logger.info(
                f"Handling function call: {function_name} with arguments: {arguments}"
            )

            if function_name == "run_campaign":
                # Execute campaign
                result = await campaign_service.create_campaign(
                    campaign=arguments["campaign_description"],
                    admin_id=current_admin.id,
                )

                tool_outputs.append(
                    {
                        "tool_call_id": tool_call["id"],
                        "output": json.dumps(
                            {
                                "status": "success",
                                "message": f"Campaign started successfully with description: {arguments['campaign_description']}",
                            }
                        ),
                    }
                )

            elif function_name == "query_student_chats":
                # Query student chats
                chat_results = await campaign_service.query_student_chats(
                    query=arguments["query"]
                )

                tool_outputs.append(
                    {
                        "tool_call_id": tool_call["id"],
                        "output": json.dumps({"results": chat_results}),
                    }
                )

            logger.info(f"Function call handled successfully: {function_name}")

        except Exception as e:
            logger.error(f"Error handling tool call: {str(e)}")
            tool_outputs.append(
                {
                    "tool_call_id": tool_call["id"],
                    "output": json.dumps({"error": str(e)}),
                }
            )

    return tool_outputs


@router.post("/message")
async def process_message(
    message: Dict[str, str],
    current_admin: Admin = Depends(get_current_admin_user),
    openai_service: OpenAIService = Depends(get_openai_service),
    campaign_service: CampaignService = Depends(get_campaign_service),
):
    """
    Process a message from an admin to their assistant
    """
    logger.info("Received request to process message")
    try:
        content = message.get("content")
        if not content:
            logger.error("Message content is missing")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Message content is required",
            )

        logger.info(f"Processing message: {content}")
        logger.info(
            f"Admin ID: {current_admin.id}, Thread ID: {current_admin.thread_id}, Assistant ID: {current_admin.assistant_id}"
        )

        # Process the message with function calling support
        response = await openai_service.process_message(
            thread_id=current_admin.thread_id,
            message=content,
            assistant_id=current_admin.assistant_id,
            run_handler=lambda tool_calls: handle_tool_calls(
                tool_calls, current_admin, campaign_service
            ),
        )

        logger.info(f"Received response: {response}")
        return {"response": response}

    except Exception as e:
        logger.error(f"Error processing message: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )
