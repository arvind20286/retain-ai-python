from retain_ai.domain.review_card import ReviewCard
import asyncio
import json
import logging
from typing import Optional
from fastapi import WebSocket, WebSocketDisconnect
from google.genai import types

from retain_ai.database import async_session_factory
from retain_ai.repository.review_card_repository import ReviewCardRepository
from retain_ai.service.grading_service import GradingService
from retain_ai.service.review_orchestrator import ReviewOrchestrator
from retain_ai.service.scheduler_service import SchedulerService
from retain_ai.voice.gemini_live_client import GeminiLiveClient

logger = logging.getLogger(__name__)

class LiveVoiceSessionHandler:
    """
    Bridges the browser WebSocket connection (mic audio in, spoken response audio out)
    to the Gemini Live API session.
    """

    def __init__(
        self,
        gemini_live_client: GeminiLiveClient,
        review_orchestrator: ReviewOrchestrator,
        grading_service: GradingService,
        system_prompt: str,
    ):
        self.gemini_live_client = gemini_live_client
        self.review_orchestrator = review_orchestrator
        self.grading_service = grading_service
        self.system_prompt = system_prompt
        self.cards_q = asyncio.Queue()
        self.current_card: Optional[ReviewCard] = None

    async def handle(self, websocket: WebSocket) -> None:
        await websocket.accept()
        logger.info("Frontend WebSocket accepted: %s", websocket.client)

        # Check for due review cards
        due_cards = []
        try:
            due_cards = await self.review_orchestrator.next_cards_for_session()
        except Exception as e:
            logger.warning("Could not fetch due cards for session: %s", e)

        self.cards_q = asyncio.Queue()
        self.current_card = None
        for card in due_cards:
            self.cards_q.put_nowait(card)
        logger.info("Queued %d due card(s) for this review session", len(due_cards))

        tools = [
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(
                        name="ask_next_card",
                        description="Retrieves the next study card to ask the user. Returns question, reference_answer, and card_id.",
                    ),
                    types.FunctionDeclaration(
                        name="grade_and_notify",
                        description="Grades the user's answer against the review card, updates the review schedule, and sends feedback to the user UI. Call this when the user has provided their answer to the current card.",
                        parameters=types.Schema(
                            type="OBJECT",
                            properties={
                                "user_answer": types.Schema(
                                    type="STRING",
                                    description="The user's spoken or typed answer to be graded."
                                ),
                                "card_id": types.Schema(
                                    type="INTEGER",
                                    description="Optional ID of the card being answered. If omitted, the currently active card is graded."
                                ),
                            },
                            required=["user_answer"],
                        ),
                    ),
                ]
            )
        ]
        try:
            async with self.gemini_live_client.connect(system_prompt=self.system_prompt, tools=tools) as live_session:
                # Concurrent tasks: browser -> gemini, and gemini -> browser
                gemini_to_browser_task = asyncio.create_task(
                    self._gemini_to_browser_loop(live_session, websocket)
                )
                browser_to_gemini_task = asyncio.create_task(
                    self._browser_to_gemini_loop(websocket, live_session)
                )

                done, pending = await asyncio.wait(
                    [gemini_to_browser_task, browser_to_gemini_task],
                    return_when=asyncio.FIRST_COMPLETED
                )

                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

        except WebSocketDisconnect:
            logger.info("Frontend WebSocket disconnected: %s", websocket.client)
        except Exception as e:
            logger.error("Live voice session error: %s", e, exc_info=True)
            try:
                await websocket.send_text(json.dumps({"error": f"Session error: {str(e)}"}))
                await websocket.close()
            except Exception:
                pass

    async def _gemini_to_browser_loop(self, live_session, websocket: WebSocket) -> None:
        """
        Receives server content from Gemini Live and relays to browser:
        - Tool calls (e.g. ask_next_card) handled and answered back to Gemini
        - Audio chunks (PCM 24kHz) sent as binary messages
        - Text chunks sent as JSON { "type": "gemini", "text": "..." }
        - Turn complete notifications
        """
        try:
            while True:
                async for response in live_session.receive():
                    # Setup complete signal
                    if getattr(response, "setup_complete", None):
                        await websocket.send_text(json.dumps({
                            "type": "interaction_status",
                            "status": "REQUIRES_ACTION"
                        }))
                        continue

                    # 1. Handle Tool Calls from Gemini
                    tool_call = getattr(response, "tool_call", None)
                    if tool_call and getattr(tool_call, "function_calls", None):
                        logger.info("Gemini requested tool call: %s", [fc.name for fc in tool_call.function_calls])
                        function_responses = []
                        for fc in tool_call.function_calls:
                            if fc.name == "ask_next_card":
                                if not self.cards_q.empty():
                                    current_card = self.cards_q.get_nowait()
                                    self.current_card = current_card
                                    logger.info("Dispatching card %s ('%s') to Gemini", current_card.id, current_card.question)
                                    # Notify UI
                                    await websocket.send_text(json.dumps({
                                        "type": "card",
                                        "question": current_card.question,
                                        "card_id": current_card.id
                                    }))
                                    resp_payload = {
                                        "card_id": current_card.id,
                                        "question": current_card.question,
                                        "reference_answer": current_card.reference_answer
                                    }
                                else:
                                    self.current_card = None
                                    logger.info("No more cards due in queue")
                                    resp_payload = {
                                        "status": "completed",
                                        "message": "There are no more review cards due at this moment."
                                    }

                                function_responses.append(
                                    types.FunctionResponse(
                                        id=fc.id,
                                        name=fc.name,
                                        response=resp_payload
                                    )
                                )
                            elif fc.name == "grade_and_notify":
                                args = fc.args or {}
                                user_answer = args.get("user_answer", "")
                                card_id_raw = args.get("card_id")
                                card_id = None
                                if card_id_raw is not None:
                                    try:
                                        card_id = int(card_id_raw)
                                    except (ValueError, TypeError):
                                        card_id = None

                                if not card_id and self.current_card:
                                    card_id = self.current_card.id

                                logger.info(
                                    "Gemini called grade_and_notify for card_id=%s with answer: '%s'",
                                    card_id, user_answer
                                )

                                if card_id:
                                    resp_payload = await self._grade_and_notify(
                                        websocket=websocket,
                                        card_id=card_id,
                                        answer=user_answer
                                    )
                                    if self.current_card and self.current_card.id == card_id:
                                        self.current_card = None
                                else:
                                    logger.warning("grade_and_notify called without active card or card_id")
                                    resp_payload = {
                                        "status": "error",
                                        "message": "No active review card to grade. Please call ask_next_card first."
                                    }

                                function_responses.append(
                                    types.FunctionResponse(
                                        id=fc.id,
                                        name=fc.name,
                                        response=resp_payload
                                    )
                                )

                        if function_responses:
                            logger.info("Sending tool response to Gemini Live session...")
                            await live_session.send_tool_response(function_responses=function_responses)
                        continue

                    # 2. Handle Server Content (Audio / Text)
                    server_content = getattr(response, "server_content", None)
                    if not server_content:
                        continue

                    model_turn = getattr(server_content, "model_turn", None)
                    if model_turn:
                        for part in getattr(model_turn, "parts", []):
                            # Text part
                            text = getattr(part, "text", None)
                            if text:
                                await websocket.send_text(json.dumps({
                                    "type": "gemini",
                                    "text": text
                                }))

                            # Audio data part (PCM 24kHz)
                            inline_data = getattr(part, "inline_data", None)
                            if inline_data and getattr(inline_data, "data", None):
                                audio_bytes = inline_data.data
                                await websocket.send_bytes(audio_bytes)

                    # Turn complete
                    if getattr(server_content, "turn_complete", False):
                        await websocket.send_text(json.dumps({
                            "type": "turn_complete"
                        }))

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Error in gemini_to_browser_loop: %s", e, exc_info=True)

    async def _browser_to_gemini_loop(self, websocket: WebSocket, live_session) -> None:
        """
        Receives audio or text from browser and forwards to Gemini Live.
        """
        last_user_text = ""
        try:
            while True:
                message = await websocket.receive()
                msg_type = message.get("type")

                if msg_type == "websocket.disconnect":
                    break

                # Binary audio frame (16-bit 16kHz PCM)
                if "bytes" in message and message["bytes"]:
                    pcm_bytes = message["bytes"]
                    await live_session.send_realtime_input(
                        audio=types.Blob(
                            data=pcm_bytes,
                            mime_type="audio/pcm;rate=16000"
                        )
                    )
                    continue

                # Text frame
                if "text" in message and message["text"]:
                    raw_text = message["text"].strip()
                    try:
                        data = json.loads(raw_text)
                    except json.JSONDecodeError:
                        data = {"text": raw_text}

                    if data.get("audioStreamEnd"):
                        await live_session.send_realtime_input(audio_stream_end=True)
                        continue

                    user_text = data.get("text", "")
                    if user_text:
                        last_user_text = user_text
                        await live_session.send_client_content(
                            turns=types.Content(
                                role="user",
                                parts=[types.Part.from_text(text=user_text)]
                            ),
                            turn_complete=True
                        )

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Error in browser_to_gemini_loop: %s", e, exc_info=True)

    async def _grade_and_notify(self, websocket: WebSocket, card_id: int, answer: str) -> dict:
        """Grade in a fresh DB session to avoid detached-instance errors."""
        try:
            async with async_session_factory() as session:
                card_repo = ReviewCardRepository(session)
                scheduler_svc = SchedulerService(card_repo)

                # Re-load the card in this session so it's persistent
                fresh_card = await card_repo.find_by_id(card_id)
                if not fresh_card:
                    logger.error("Card %s not found in DB for grading", card_id)
                    return {"status": "error", "message": f"Card {card_id} not found."}

                grade = await self.grading_service.grade(fresh_card, answer)
                await scheduler_svc.apply_grade(fresh_card, grade)

                await websocket.send_text(json.dumps({
                    "type": "grade",
                    "score": grade.score,
                    "missed_key_point": grade.missed_key_point,
                    "feedback": grade.feedback
                }))

                return {
                    "status": "graded",
                    "score": grade.score,
                    "feedback": grade.feedback,
                    "missed_key_point": grade.missed_key_point
                }
        except Exception as e:
            logger.error("Failed to grade answer: %s", e, exc_info=True)
            return {"status": "error", "message": str(e)}

