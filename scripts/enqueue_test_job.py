"""
Send a test job onto one of the detection SQS queues, via the same
enqueue_scan() the API uses in production, so the message body matches
exactly what the consumers expect (a JSON body with a "job_id" key).

Usage:
    python scripts/enqueue_test_job.py <request_id> --type ai_video --s3-key clips/foo.mp4
    python scripts/enqueue_test_job.py <request_id> --type ai_audio --url https://youtube.com/watch?v=...
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.sqs import enqueue_scan


def main():
    parser = argparse.ArgumentParser(description="Enqueue a test detection job.")
    parser.add_argument("request_id")
    parser.add_argument("--type", required=True, choices=["ai_audio", "ai_video", "lipsync", "changes"])
    parser.add_argument("--s3-key", default=None)
    parser.add_argument("--url", default=None)
    args = parser.parse_args()

    message_id = enqueue_scan(args.request_id, args.type, s3_key=args.s3_key, url_source=args.url)
    print(f"Sent message {message_id} to the '{args.type}' queue for request {args.request_id}")


if __name__ == "__main__":
    main()
