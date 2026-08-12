from pydantic import BaseModel


class CrashReportRequest(BaseModel):
    message: str
    stackTrace: str | None = None
    isFatal: bool = True
    platform: str | None = None
    appVersion: str | None = None
    osVersion: str | None = None
    deviceModel: str | None = None
    context: dict | None = None
