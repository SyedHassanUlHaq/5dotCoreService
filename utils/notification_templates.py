"""Registry of push notification templates.

Each template's title/body are Python format strings rendered against the
`data` dict passed to /v1/notifications/send. Keep placeholder names here in
sync with whatever the calling endpoint passes.
"""

NOTIFICATION_TEMPLATES: dict[str, dict[str, str]] = {
    "welcome": {
        "title": "Welcome to 5dot!",
        "body": "Your account is ready. Upload a file to get a verdict in under 3 minutes.",
    },
    "scan_complete_ai": {
        "title": "AI content detected — {score}% confidence",
        "body": "{filename} was flagged as AI-generated.",
    },
    "scan_complete_authentic": {
        "title": "Scan complete — Authentic",
        "body": "{filename} came back clean. {score}% confidence it's real.",
    },
    "scan_complete_tampered": {
        "title": "Tamper detected — {editCount} edits found",
        "body": "{filename} has been cut and re-encoded.",
    },
    "feedback_received": {
        "title": "Feedback received",
        "body": "Thanks for reporting {filename}. We'll review it within 48 hours.",
    },
    "usage_warning": {
        "title": "You're at {percent}% of your monthly scans",
        "body": "{used} of {limit} scans used. Resets in {daysLeft} days.",
    },
    "model_updated": {
        "title": "Model updated to {modelVersion}",
        "body": "Improved detection accuracy — now benchmarking at {accuracy}%.",
    },
    "plan_upgraded": {
        "title": "Welcome to {planName}",
        "body": "Your plan is now active. Enjoy {scansPerMonth} scans/month.",
    },
}
