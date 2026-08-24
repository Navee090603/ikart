import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ikart.settings")

app = Celery("ikart")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@app.on_after_finalize.connect
def setup_periodic_tasks(sender, **kwargs):
    from django.conf import settings

    sender.add_periodic_task(
        crontab(minute=f"*/{settings.PAYMENT_SWEEP_CRON_MINUTES}"),
        sender.signature("storefront.tasks.release_stale_payment_reservations_task"),
        name="release-stale-payment-reservations",
    )
