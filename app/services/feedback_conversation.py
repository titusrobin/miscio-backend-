# app/services/feedback_conversation_service.py
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.models.feedback_conversation import (
    FeedbackConversationState, QuestionProgress, ResponseAnalysis,
    DeliveryStrategy, EngagementLevel, ConversationStatus
)
from app.services.openai_service import OpenAIService
from bson import ObjectId

logger = logging.getLogger(__name__)

class FeedbackConversationService:
    def __init__(self, database: AsyncIOMotorDatabase, openai_service: OpenAIService):
        self.db = database
        self.openai_service = openai_service
    
    async def initialize_conversation(
        self, 
        student_id: str, 
        campaign_id: str
    ) -> FeedbackConversationState:
        """Initialize conversation state for a student starting a feedback campaign"""
        try:
            # Get campaign questions
            campaign = await self.db.campaigns.find_one({"_id": ObjectId(campaign_id)})
            if not campaign or campaign.get("type") != "feedback":
                raise Exception(f"Invalid feedback campaign: {campaign_id}")
            
            # Check if conversation already exists
            existing = await self.db.feedback_conversations.find_one({
                "student_id": student_id,
                "campaign_id": campaign_id
            })
            
            if existing:
                logger.info(f"Resuming existing conversation for student {student_id}")
                return FeedbackConversationState(**existing)
            
            # Create question progress tracking
            questions = []
            for i, q in enumerate(campaign.get("questions", [])):
                progress = QuestionProgress(
                    question_id=q.get("id", str(i)),
                    question_text=q.get("text", ""),
                    order=q.get("order", i + 1)
                )
                questions.append(progress)
            
            # Initialize conversation state
            conversation_state = FeedbackConversationState(
                student_id=student_id,
                campaign_id=campaign_id,
                questions=questions,
                total_questions=len(questions),
                status=ConversationStatus.NOT_STARTED,
                started_at=datetime.utcnow()
            )
            
            # Save to database
            await self.db.feedback_conversations.insert_one(conversation_state.dict())
            
            logger.info(f"Initialized feedback conversation for student {student_id}, campaign {campaign_id}")
            return conversation_state
            
        except Exception as e:
            logger.error(f"Error initializing conversation: {str(e)}")
            raise
    
    async def get_conversation_state(
        self, 
        student_id: str, 
        campaign_id: str
    ) -> Optional[FeedbackConversationState]:
        """Get current conversation state for a student"""
        try:
            state_doc = await self.db.feedback_conversations.find_one({
                "student_id": student_id,
                "campaign_id": campaign_id
            })
            
            if state_doc:
                return FeedbackConversationState(**state_doc)
            return None
            
        except Exception as e:
            logger.error(f"Error getting conversation state: {str(e)}")
            return None
    
    async def analyze_student_response(
        self, 
        response: str, 
        conversation_state: FeedbackConversationState
    ) -> ResponseAnalysis:
        """Analyze student response to determine which questions were addressed"""
        try:
            # Get unanswered questions for context
            unanswered_questions = [
                q for q in conversation_state.questions 
                if q.status in ["not_asked", "asked", "partially_answered"]
            ]
            
            if not unanswered_questions:
                return ResponseAnalysis(
                    questions_addressed=[],
                    engagement_indicators={"response_length": len(response)},
                    partial_answers={},
                    suggested_follow_ups=[],
                    next_strategy=DeliveryStrategy.WRAP_UP
                )
            
            # Create analysis prompt for AI
            questions_text = "\n".join([
                f"{q.order}. {q.question_text}" for q in unanswered_questions
            ])
            
            analysis_prompt = f"""Analyze this student response to determine which feedback questions were addressed.

STUDENT RESPONSE: "{response}"

PENDING QUESTIONS:
{questions_text}

Return JSON with:
{{
  "questions_addressed": [list of question numbers that were answered],
  "partial_answers": {{"question_number": "what part was answered"}},
  "engagement_level": "high/medium/low",
  "response_depth": "brief/moderate/detailed", 
  "follow_up_needed": [list of question numbers needing follow-up],
  "suggested_next_strategy": "batch/weave/follow_up/wrap_up"
}}

Guidelines:
- A question is "addressed" if student gave a meaningful response to it
- Mark as partial if they touched on it but didn't fully answer
- Consider engagement based on response length and enthusiasm
- Suggest batch for simple questions, weave for complex ones"""

            # Use OpenAI to analyze response
            headers = {
                "Authorization": f"Bearer {self.openai_service.headers['Authorization'].split(' ')[1]}",
                "Content-Type": "application/json"
            }
            
            data = {
                "model": "gpt-4-turbo-preview",
                "messages": [{"role": "user", "content": analysis_prompt}],
                "max_tokens": 500,
                "temperature": 0.3
            }
            
            ai_response = await self.openai_service.make_request(
                method="POST",
                url="https://api.openai.com/v1/chat/completions",
                headers=headers,
                data=data
            )
            
            if ai_response and "choices" in ai_response:
                analysis_text = ai_response["choices"][0]["message"]["content"].strip()
                
                try:
                    import json
                    analysis_data = json.loads(analysis_text)
                    
                    return ResponseAnalysis(
                        questions_addressed=[str(q) for q in analysis_data.get("questions_addressed", [])],
                        engagement_indicators={
                            "response_length": len(response),
                            "engagement_level": analysis_data.get("engagement_level", "medium"),
                            "response_depth": analysis_data.get("response_depth", "moderate")
                        },
                        partial_answers=analysis_data.get("partial_answers", {}),
                        suggested_follow_ups=[str(q) for q in analysis_data.get("follow_up_needed", [])],
                        next_strategy=DeliveryStrategy(analysis_data.get("suggested_next_strategy", "weave"))
                    )
                    
                except json.JSONDecodeError:
                    logger.error(f"Failed to parse AI analysis: {analysis_text}")
                    return self._fallback_analysis(response, unanswered_questions)
            
            return self._fallback_analysis(response, unanswered_questions)
            
        except Exception as e:
            logger.error(f"Error analyzing response: {str(e)}")
            return self._fallback_analysis(response, conversation_state.questions)
    
    def _fallback_analysis(self, response: str, questions: List[QuestionProgress]) -> ResponseAnalysis:
        """Fallback analysis when AI analysis fails"""
        response_length = len(response)
        
        # Simple heuristics
        engagement = EngagementLevel.HIGH if response_length > 100 else EngagementLevel.MEDIUM if response_length > 20 else EngagementLevel.LOW
        strategy = DeliveryStrategy.WEAVE if len(questions) > 2 else DeliveryStrategy.BATCH
        
        return ResponseAnalysis(
            questions_addressed=[],
            engagement_indicators={"response_length": response_length},
            partial_answers={},
            suggested_follow_ups=[],
            next_strategy=strategy
        )
    
    async def update_conversation_state(
        self,
        conversation_state: FeedbackConversationState,
        response_analysis: ResponseAnalysis,
        student_response: str
    ) -> FeedbackConversationState:
        """Update conversation state based on response analysis"""
        try:
            # Update question progress
            for question_id in response_analysis.questions_addressed:
                for q in conversation_state.questions:
                    if str(q.order) == question_id or q.question_id == question_id:
                        q.status = "fully_answered"
                        q.student_response = student_response
                        q.answered_at = datetime.utcnow()
                        break
            
            # Handle partial answers
            for question_id, partial_text in response_analysis.partial_answers.items():
                for q in conversation_state.questions:
                    if str(q.order) == question_id or q.question_id == question_id:
                        q.status = "partially_answered"
                        q.student_response = partial_text
                        q.follow_up_needed = True
                        break
            
            # Update overall state
            conversation_state.questions_completed = len([
                q for q in conversation_state.questions if q.status == "fully_answered"
            ])
            
            conversation_state.engagement_level = EngagementLevel(
                response_analysis.engagement_indicators.get("engagement_level", "medium")
            )
            
            conversation_state.current_strategy = response_analysis.next_strategy
            conversation_state.last_response_analysis = response_analysis
            conversation_state.last_interaction = datetime.utcnow()
            
            # Update priority questions (follow-ups first, then unanswered)
            follow_up_questions = [q.question_id for q in conversation_state.questions if q.follow_up_needed]
            unanswered_questions = [q.question_id for q in conversation_state.questions if q.status == "not_asked"]
            conversation_state.priority_questions = follow_up_questions + unanswered_questions[:3]
            
            # Check if conversation is complete
            if conversation_state.questions_completed >= conversation_state.total_questions:
                conversation_state.status = ConversationStatus.COMPLETED
                conversation_state.completed_at = datetime.utcnow()
            elif conversation_state.status == ConversationStatus.NOT_STARTED:
                conversation_state.status = ConversationStatus.IN_PROGRESS
            
            # Save updated state
            await self.db.feedback_conversations.replace_one(
                {"student_id": conversation_state.student_id, "campaign_id": conversation_state.campaign_id},
                conversation_state.dict()
            )
            
            logger.info(f"Updated conversation state: {conversation_state.questions_completed}/{conversation_state.total_questions} questions completed")
            return conversation_state
            
        except Exception as e:
            logger.error(f"Error updating conversation state: {str(e)}")
            raise
    
    async def generate_assistant_prompt(
        self, 
        conversation_state: FeedbackConversationState,
        student_message: str,
        student_name: str = "Student"
    ) -> str:
        """Generate context-aware prompt for the assistant based on conversation state"""
        try:
            # Get campaign context
            campaign = await self.db.campaigns.find_one({"_id": ObjectId(conversation_state.campaign_id)})
            research_topic = campaign.get("feedback_metadata", {}).get("research_topic", "feedback")
            conversation_style = campaign.get("feedback_metadata", {}).get("conversation_style", "casual and friendly")
            
            # Analyze current situation
            unanswered_questions = [q for q in conversation_state.questions if q.status in ["not_asked", "asked"]]
            follow_up_questions = [q for q in conversation_state.questions if q.follow_up_needed]
            completed_count = conversation_state.questions_completed
            total_count = conversation_state.total_questions
            
            # Build context-aware prompt
            if conversation_state.status == ConversationStatus.NOT_STARTED:
                prompt_context = f"This is the start of a feedback conversation about {research_topic}."
            elif conversation_state.status == ConversationStatus.COMPLETED:
                prompt_context = f"All questions have been covered. Wrap up the conversation naturally."
            else:
                prompt_context = f"Ongoing feedback conversation about {research_topic}. Progress: {completed_count}/{total_count} questions covered."
            
            # Strategy-specific instructions
            strategy_instructions = ""
            if conversation_state.current_strategy == DeliveryStrategy.BATCH:
                strategy_instructions = "Ask 2-3 related questions together in a natural way."
            elif conversation_state.current_strategy == DeliveryStrategy.WEAVE:
                strategy_instructions = "Weave the next question naturally into the conversation flow."
            elif conversation_state.current_strategy == DeliveryStrategy.FOLLOW_UP:
                strategy_instructions = "Follow up on previous responses that need more detail."
            elif conversation_state.current_strategy == DeliveryStrategy.WRAP_UP:
                strategy_instructions = "Begin wrapping up the conversation - thank them and offer final thoughts."
            
            # Build question context
            question_context = ""
            if follow_up_questions:
                follow_up_text = "\n".join([f"- {q.question_text} (needs follow-up)" for q in follow_up_questions[:2]])
                question_context += f"FOLLOW-UP NEEDED:\n{follow_up_text}\n\n"
            
            if unanswered_questions:
                next_questions = unanswered_questions[:3]  # Next 3 questions
                questions_text = "\n".join([f"- {q.question_text}" for q in next_questions])
                question_context += f"REMAINING QUESTIONS:\n{questions_text}\n\n"
            
            # Main prompt
            prompt = f"""You are having a {conversation_style} feedback conversation with {student_name} about {research_topic}.

{prompt_context}

STUDENT JUST SAID: "{student_message}"

{question_context}STRATEGY: {strategy_instructions}

CONVERSATION GUIDELINES:
- Keep the tone {conversation_style}
- Make transitions between questions feel natural
- Acknowledge their responses before moving to new topics
- Don't ask all questions at once unless they're very related
- If they seem engaged, you can ask more; if brief responses, keep it lighter
- Remember this is research, so getting thoughtful responses matters

Respond naturally and continue the conversation according to your strategy."""

            return prompt
            
        except Exception as e:
            logger.error(f"Error generating assistant prompt: {str(e)}")
            # Fallback simple prompt
            return f"Continue your casual feedback conversation with {student_name}. Student just said: '{student_message}'"
