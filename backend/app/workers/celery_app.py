"""Celery application.

The worker executes pipeline stages (spec req 14); Celery Beat will drive
scheduled publishing (spec req 12). Task modules are registered lazily as the
orchestrator is built out.
"""

from __future__ import annotations

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "moneyprint",
    broker=settings.broker_url,
    backend=settings.result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_queue="default",
    timezone="UTC",
    beat_schedule={
        "dispatch-due-publications": {
            "task": "schedule.dispatch_due_publications",
            "schedule": 60.0,  # check once a minute
        }
    },
)

# Register task modules so the worker/beat discover them.
celery_app.autodiscover_tasks(
    ["app.orchestrator", "app.workers"], related_name="tasks"
)
celery_app.conf.imports = (
    "app.orchestrator.tasks",
    "app.workers.schedule_tasks",
)
