import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from retain_ai.domain.grade_result import GradeResult
from retain_ai.domain.review_card import ReviewCard
from retain_ai.voice.live_voice_session_handler import LiveVoiceSessionHandler

@pytest.mark.asyncio
async def test_grade_and_notify_tool_execution():
    mock_live_client = MagicMock()
    mock_orchestrator = MagicMock()
    mock_grading_service = MagicMock()
    mock_grading_service.grade = AsyncMock(
        return_value=GradeResult(
            score=85,
            missed_key_point=False,
            feedback="Good answer with key mechanisms covered."
        )
    )

    handler = LiveVoiceSessionHandler(
        gemini_live_client=mock_live_client,
        review_orchestrator=mock_orchestrator,
        grading_service=mock_grading_service,
        system_prompt="test prompt"
    )

    mock_websocket = MagicMock()
    mock_websocket.send_text = AsyncMock()

    test_card = ReviewCard(
        id=99,
        article_id=10,
        question="What is two-phase commit?",
        reference_answer="Prepare phase followed by commit phase."
    )

    # Mock async_session_factory so it doesn't need real DB
    mock_session = AsyncMock()
    mock_repo = MagicMock()
    mock_repo.find_by_id = AsyncMock(return_value=test_card)
    mock_scheduler = MagicMock()
    mock_scheduler.apply_grade = AsyncMock()

    with patch("retain_ai.voice.live_voice_session_handler.async_session_factory") as mock_asf, \
         patch("retain_ai.voice.live_voice_session_handler.ReviewCardRepository", return_value=mock_repo), \
         patch("retain_ai.voice.live_voice_session_handler.SchedulerService", return_value=mock_scheduler):

        mock_asf.return_value.__aenter__.return_value = mock_session

        result = await handler._grade_and_notify(
            websocket=mock_websocket,
            card_id=99,
            answer="Phase 1 is prepare, phase 2 is commit."
        )

        assert result["status"] == "graded"
        assert result["score"] == 85
        assert result["feedback"] == "Good answer with key mechanisms covered."
        assert result["missed_key_point"] is False

        # Verify websocket message was sent to UI
        mock_websocket.send_text.assert_called_once()
        sent_payload = json.loads(mock_websocket.send_text.call_args[0][0])
        assert sent_payload["type"] == "grade"
        assert sent_payload["score"] == 85

