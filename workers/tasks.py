from celery import Celery
from config import settings

app = Celery("tasks", broker=settings.celery_broker_url, backend=settings.celery_result_backend)


@app.task
def send_order_notification(order_id: int):
    # Stub for sending notifications to kitchen/customer
    print(f"[Celery] Sending notification for order #{order_id}")
    return True


@app.task
def refresh_analytics():
    # Stub for analytics refresh
    print("[Celery] Refreshing analytics cache...")
    return True
