import json
import os

import boto3

_sqs = None


def _client():
    global _sqs
    if _sqs is None:
        _sqs = boto3.client("sqs", region_name=os.environ["AWS_REGION"])
    return _sqs


_QUEUE_URLS = {
    "ai_video": os.environ.get("SQS_URL_VIDEO", ""),
    "ai_audio": os.environ.get("SQS_URL_AUDIO", ""),
    "changes":  os.environ.get("SQS_URL_SCENE", ""),
    "lipsync":  os.environ.get("SQS_URL_LIPSYNC", ""),
}


def enqueue_scan(request_id: str, detection_type: str, s3_key: str | None = None, url_source: str | None = None) -> str:
    queue_url = _QUEUE_URLS.get(detection_type)
    if not queue_url:
        raise ValueError(f"No SQS queue configured for detection_type '{detection_type}'")

    body: dict = {"job_id": request_id, "detection_type": detection_type}
    if s3_key:
        body["s3_key"] = s3_key
    if url_source:
        body["url_source"] = url_source

    response = _client().send_message(QueueUrl=queue_url, MessageBody=json.dumps(body))
    return response["MessageId"]
