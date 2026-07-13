from pydantic import BaseModel


class SendNotificationRequest(BaseModel):
    userId: str
    template: str
    data: dict = {}
