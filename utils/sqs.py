import json
import os

import boto3

_sqs = None


def _client():
    global _sqs
    if _sqs is None:
        _sqs = boto3.client("sqs", region_name=os.environ["AWS_REGION"])
    return _sqs


QUEUE_URLS = {
    "video":  os.environ.get("SQS_URL_VIDEO", ""),
    "tamper": os.environ.get("SQS_URL_LIPSYNC", ""),
    "audio":  os.environ.get("SQS_URL_AUDIO", ""),
}


def enqueue_scan(scan_id: str, scan_type: str, s3_key: str | None = None, url_source: str | None = None) -> str:
    queue_url = QUEUE_URLS.get(scan_type)
    if not queue_url:
        raise ValueError(f"No SQS queue configured for scan_type '{scan_type}'")

    body: dict = {"scan_id": scan_id, "scan_type": scan_type}
    if s3_key:
        body["s3_key"] = s3_key
    if url_source:
        body["url_source"] = url_source

    response = _client().send_message(QueueUrl=queue_url, MessageBody=json.dumps(body))
    return response["MessageId"]
