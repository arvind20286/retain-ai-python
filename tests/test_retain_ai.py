import asyncio
import datetime
from httpx import ASGITransport, AsyncClient

from retain_ai.config import settings
from retain_ai.database import Base, async_session_factory, engine, init_db
from retain_ai.domain.article import Article
from retain_ai.domain.grade_result import GradeResult
from retain_ai.domain.review_card import ReviewCard
from retain_ai.main import app
from retain_ai.repository.article_repository import ArticleRepository
from retain_ai.repository.review_card_repository import ReviewCardRepository
from retain_ai.service.scheduler_service import SchedulerService

async def test_database_and_repositories():
    await init_db()
    async with async_session_factory() as session:
        article_repo = ArticleRepository(session)
        card_repo = ReviewCardRepository(session)

        # 1. Test Article Save & Retrieve
        article = Article(
            page_id="test-page-123",
            source_name="notion",
            title="Distributed Systems Consensus",
            source_url="https://example.com/raft",
            content="Raft is a consensus algorithm designed as an alternative to Paxos.",
            user_notes="Key mechanism is leader election and log replication.",
            tags=["distributed-systems", "raft"]
        )
        saved_article = await article_repo.save(article)
        assert saved_article.id is not None
        assert saved_article.title == "Distributed Systems Consensus"

        # 2. Test ReviewCard Save & find_due
        card = ReviewCard(
            article_id=saved_article.id,
            question="How does Raft handle leader election?",
            reference_answer="Nodes start as followers; if no heartbeat arrives within election timeout, a node becomes candidate and requests votes.",
            stability=0.4,
            difficulty=5.0,
            next_review_at=datetime.datetime.now(datetime.timezone.utc),
            times_reviewed=0
        )
        saved_card = await card_repo.save(card)
        assert saved_card.id is not None
        assert saved_card.is_due is True

        due_cards = await card_repo.find_due()
        assert len(due_cards) >= 1
        assert any(c.id == saved_card.id for c in due_cards)

        # 3. Test FSRS Scheduler update
        scheduler_svc = SchedulerService(card_repo)
        grade = GradeResult(score=85, missed_key_point=False, feedback="Accurate explanation of leader election timeout.")
        updated_card = await scheduler_svc.apply_grade(saved_card, grade)

        assert updated_card.times_reviewed == 1
        assert updated_card.stability > 0
        assert updated_card.difficulty > 0
        assert updated_card.next_review_at is not None
        print(f"FSRS scheduled next review: {updated_card.next_review_at}, stability={updated_card.stability:.2f}")

async def test_fastapi_endpoints():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Test index endpoint
        resp = await client.get("/")
        assert resp.status_code == 200

        # Test due cards endpoint
        resp = await client.get("/api/cards/due")
        assert resp.status_code == 200
        cards = resp.json()
        assert isinstance(cards, list)
        print(f"API /api/cards/due returned {len(cards)} card(s)")

if __name__ == "__main__":
    asyncio.run(test_database_and_repositories())
    asyncio.run(test_fastapi_endpoints())
    print("ALL TESTS PASSED SUCCESSFULLY!")
