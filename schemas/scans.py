from pydantic import BaseModel


class UrlScanRequest(BaseModel):
    url: str
    scanType: str
