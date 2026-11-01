import asyncio
import json
from unittest.mock import AsyncMock, MagicMock
from retain_ai.domain.article import Article
from retain_ai.domain.review_card import ReviewCard
from retain_ai.service.grading_service import GradingService
from retain_ai.service.question_generator_service import QuestionGeneratorService

async def test_question_generator_mock():
    service = QuestionGeneratorService(api_key="mock_key", model_name="gemini-2.0-flash", openrouter_api_key="")
    mock_resp = MagicMock()
    mock_resp.text = json.dumps({
        "cards": [
            {
                "question": "What is the primary trade-off in the CAP theorem?",
                "reference_answer": "In the event of a network partition, a distributed system must choose between consistency and availability."
            }
        ]
    })
    service.client = MagicMock()
    service.client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    article = Article(
        id=1,
        title="CAP Theorem",
        content="CAP theorem discusses consistency, availability, and partition tolerance.",
        user_notes="Key trade-off under partitions.",
        tags=["distributed-systems"]
    )
    cards = await service.generate_cards_for(article)
    assert len(cards) == 1
    assert cards[0].question == "What is the primary trade-off in the CAP theorem?"
    assert cards[0].article_id == 1
    assert cards[0].stability == 0.4
    assert cards[0].difficulty == 5.0
    print("QuestionGeneratorService test passed!")

async def test_question_generator_openrouter_mock():
    service = QuestionGeneratorService(
        openrouter_api_key="sk-or-v1-mock-key",
        openrouter_model="deepseek/deepseek-v4.1-flash-1017",
    )
    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps({
        "cards": [
            {
                "question": "How does Raft leader election handle split votes?",
                "reference_answer": "Raft uses randomized election timeouts so split votes are quickly resolved in the next election term."
            }
        ]
    })
    mock_choice.message.reasoning_details = "Raft uses randomized election timeouts to ensure only one candidate times out."
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    service.openrouter_client = MagicMock()
    service.openrouter_client.chat.completions.create = AsyncMock(return_value=mock_response)

    article = Article(
        id=2,
        title="Raft Consensus",
        content="Raft splits consensus into leader election, log replication, and safety.",
        user_notes="Random election timeouts prevent split vote livelocks.",
        tags=["consensus", "raft"]
    )
    cards = await service.generate_cards_for(article)
    assert len(cards) == 1
    assert cards[0].question == "How does Raft leader election handle split votes?"
    assert cards[0].article_id == 2
    assert cards[0].stability == 0.4
    assert cards[0].difficulty == 5.0
    print("OpenRouter QuestionGeneratorService test passed!")

async def test_question_generator_retry_and_success():
    service = QuestionGeneratorService(
        openrouter_api_key="sk-or-v1-mock-key",
        max_retries=3,
    )
    # Attempt 1: bad schema (missing 'cards')
    bad_choice = MagicMock()
    bad_choice.message.content = json.dumps({"invalid_field": "no cards here"})
    bad_resp = MagicMock(choices=[bad_choice])

    # Attempt 2: valid schema
    good_choice = MagicMock()
    good_choice.message.content = json.dumps({
        "cards": [{"question": "Valid Q?", "reference_answer": "Valid A."}]
    })
    good_resp = MagicMock(choices=[good_choice])

    service.openrouter_client = MagicMock()
    service.openrouter_client.chat.completions.create = AsyncMock(side_effect=[bad_resp, good_resp])

    article = Article(id=10, title="Retry Article", content="Article content")
    cards = await service.generate_cards_for(article)

    assert len(cards) == 1
    assert cards[0].question == "Valid Q?"
    assert service.openrouter_client.chat.completions.create.call_count == 2
    print("Retry and succeed test passed!")

async def test_question_generator_skip_after_max_retries():
    service = QuestionGeneratorService(
        openrouter_api_key="sk-or-v1-mock-key",
        max_retries=2,
    )
    # All attempts return invalid JSON/schema
    bad_choice = MagicMock()
    bad_choice.message.content = "Invalid non-JSON response"
    bad_resp = MagicMock(choices=[bad_choice])

    service.openrouter_client = MagicMock()
    service.openrouter_client.chat.completions.create = AsyncMock(return_value=bad_resp)

    article = Article(id=11, title="Failing Article", content="Article content")
    cards = await service.generate_cards_for(article)

    # Should skip and return empty list
    assert cards == []
    assert service.openrouter_client.chat.completions.create.call_count == 2
    print("Skip article after max retries test passed!")

async def test_grading_service_mock():
    service = GradingService(api_key="mock_key", model_name="gemini-2.0-flash", openrouter_api_key="")
    mock_resp = MagicMock()
    mock_resp.text = json.dumps({
        "score": 90,
        "missed_key_point": False,
        "feedback": "Spot on explanation of partition trade-offs."
    })
    service.client = MagicMock()
    service.client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    card = ReviewCard(
        id=42,
        question="What happens during a network partition according to CAP?",
        reference_answer="The system can guarantee either consistency or availability, but not both."
    )
    grade = await service.grade(card, "During a partition, you have to sacrifice either consistency or availability.")
    assert grade.score == 90
    assert grade.missed_key_point is False
    assert "Spot on" in grade.feedback
    print("GradingService Gemini test passed!")

async def test_grading_service_openrouter_mock():
    from retain_ai.adapter.openrouter_client import OpenRouterClient

    client = OpenRouterClient(api_key="mock_key", model_name="deepseek/deepseek-v4.1-flash-1017")
    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps({
        "score": 95,
        "missed_key_point": False,
        "feedback": "Excellent understanding of Raft leader election."
    })
    mock_choice.message.reasoning_details = "The candidate transitions and increments the term correctly."
    mock_resp = MagicMock(choices=[mock_choice])

    client.client = MagicMock()
    client.client.chat.completions.create = AsyncMock(return_value=mock_resp)

    service = GradingService(openrouter_client=client)

    card = ReviewCard(
        id=43,
        question="How does Raft leader election work?",
        reference_answer="Followers timeout, increment term, vote for self, and request votes."
    )
    grade = await service.grade(card, "Followers timeout, become candidate, increment term, and request votes.")
    assert grade.score == 95
    assert grade.missed_key_point is False
    assert "Excellent" in grade.feedback
    print("GradingService OpenRouter test passed!")

if __name__ == "__main__":
    asyncio.run(test_question_generator_mock())
    asyncio.run(test_grading_service_mock())
    print("ALL GEMINI SERVICE TESTS PASSED!")

