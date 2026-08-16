from pydantic import BaseModel, Field


class BugReportRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=5000)
    stepsToReproduce: str | None = Field(default=None, max_length=5000)
    severity: str | None = None
    platform: str | None = Field(default=None, max_length=50)
    appVersion: str | None = Field(default=None, max_length=50)
    osVersion: str | None = Field(default=None, max_length=50)
    deviceModel: str | None = Field(default=None, max_length=100)
    context: dict | None = None
