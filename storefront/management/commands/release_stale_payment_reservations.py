from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from storefront.services import release_stale_payment_reservations


class Command(BaseCommand):
    help = "Release expired, unpaid Razorpay stock reservations."

    def add_arguments(self, parser):
        parser.add_argument(
            "--minutes",
            type=int,
            default=settings.PAYMENT_RESERVATION_MINUTES,
            help="Age in minutes after which an uncompleted payment reservation is released.",
        )

    def handle(self, *args, **options):
        minutes = options["minutes"]
        if minutes < 1:
            self.stderr.write("--minutes must be at least 1.")
            return
        released = release_stale_payment_reservations(timezone.now() - timedelta(minutes=minutes))
        self.stdout.write(self.style.SUCCESS(f"Released {released} stale payment reservation(s)."))
