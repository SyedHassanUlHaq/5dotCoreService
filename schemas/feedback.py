from pydantic import BaseModel


class FeedbackRequest(BaseModel):
    scanId: str
    correctVerdict: str        # authentic | ai | unsure
    reasons: list[str] = []
    detail: str | None = None
    allowAnonymizedCopy: bool = False
