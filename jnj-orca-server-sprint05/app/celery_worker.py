import os
import sys

from celery import Celery
from app.config.settings import settings

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))


celery_app = Celery(
    "worker",
    broker=settings.celery_broker,
    backend=settings.celery_backend,
    include=["app.utils.add_watermark",
             "app.api.v1.endpoints.download",
             "app.utils.get_user_output_mapping"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Kolkata",
    enable_utc=True,
)
