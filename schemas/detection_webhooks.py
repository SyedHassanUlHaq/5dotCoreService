from pydantic import BaseModel


class DetectionWebhookPayload(BaseModel):
    job_id: str
    service_name: str | None = None
    status: str
    result: dict = {}
