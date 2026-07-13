from pydantic import BaseModel


class UpdateProfileRequest(BaseModel):
    name: str | None = None
    avatarColor: str | None = None
    pushToken: str | None = None
