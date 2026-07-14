import json
import os

import boto3

_sqs = None


def _client():
    global _sqs
    if _sqs is None:
        _sqs = boto3.client("sqs", region_name=os.environ["AWS_REGION"])
    return _sqs


QUEUE_URL = os.environ.get("SQS_URL", "")


def enqueue_scan(request_id: str, detection_type: str, s3_key: str | None = None, url_source: str | None = None) -> str:
    if not QUEUE_URL:
        raise ValueError("SQS_URL is not configured")

    body: dict = {"request_id": request_id, "detection_type": detection_type}
    if s3_key:
        body["s3_key"] = s3_key
    if url_source:
        body["url_source"] = url_source

    response = _client().send_message(QueueUrl=QUEUE_URL, MessageBody=json.dumps(body))
    return response["MessageId"]
