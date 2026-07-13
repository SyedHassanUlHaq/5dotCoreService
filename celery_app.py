from celery import Celery
from config.project_config import REDIS_URL

# core_service only ever *dispatches* scan-processing jobs (via send_task,
# by name) to the workers defined in video_ai_service and ai_models_service —
# it never imports or executes AI inference itself. It still needs its own
# Celery app to run the forensic-PDF task, which is pure report generation.
celery_app = Celery(
    "faik-core",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["tasks.pdf_task"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
)
