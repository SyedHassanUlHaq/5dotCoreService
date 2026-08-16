from pydantic import BaseModel


class UpdateProfileRequest(BaseModel):
    name: str | None = None
    avatarColor: str | None = None
    pushToken: str | None = None
    firstName: str | None = None
    lastName: str | None = None
    phoneNumber: str | None = None


class DeactivateAccountRequest(BaseModel):
    password: str | None = None


class DeleteAccountRequest(BaseModel):
    password: str | None = None
