from pydantic import BaseModel, Field

class GradeResult(BaseModel):
    """
    Structured result from grading a spoken (transcribed) answer against a
    ReviewCard's reference answer. Contract between GradingService and SchedulerService.
    """
    score: int = Field(ge=0, le=100, description="Numerical score from 0 to 100")
    missed_key_point: bool = Field(description="True if an essential concept or mechanism was omitted or incorrect")
    feedback: str = Field(description="One or two sentences of constructive, conversational feedback")

