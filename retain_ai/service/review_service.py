import logging
from retain_ai.adapter.content_source import ContentSource
from retain_ai.repository.article_repository import ArticleRepository
from retain_ai.repository.review_card_repository import ReviewCardRepository
from retain_ai.service.question_generator_service import QuestionGeneratorService

logger = logging.getLogger(__name__)

class ReviewService:
    def __init__(
        self,
        article_repository: ArticleRepository,
        review_card_repository: ReviewCardRepository,
        content_source: ContentSource,
        question_generator_service: QuestionGeneratorService
    ):
        self.article_repository = article_repository
        self.review_card_repository = review_card_repository
        self.content_source = content_source
        self.question_generator_service = question_generator_service

    async def sync_articles(self) -> dict[str, int]:
        """
        Pulls ready articles from ContentSource (Notion), upserts them in DB,
        and generates review questions via Gemini for any new articles.
        """
        articles = await self.content_source.fetch_ready_articles(self.article_repository)
        synced_count = 0
        cards_generated_total = 0

        for article in articles:
            saved_article = await self.article_repository.save(article)
            synced_count += 1

            # Check if this article already has cards
            existing_cards = await self.review_card_repository.find_by_article_id(saved_article.id)
            if not existing_cards:
                new_cards = await self.question_generator_service.generate_cards_for(saved_article)
                if new_cards:
                    await self.review_card_repository.save_all(new_cards)
                    cards_generated_total += len(new_cards)

        logger.info("Sync completed: %d articles synced, %d cards generated.", synced_count, cards_generated_total)
        return {
            "articles_synced": synced_count,
            "cards_generated": cards_generated_total
        }

