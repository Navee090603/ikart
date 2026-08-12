"""Razorpay hosted Payment Link integration.

This flow deliberately avoids browser popups and checkout.js.
Razorpay hosts the payment page and redirects the customer back
to this site after payment.
"""

import hashlib
import hmac
import logging
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.utils import timezone


logger = logging.getLogger(__name__)


class PaymentLinkError(ValueError):
    """Raised when Razorpay does not return a usable hosted payment link."""


def _amount_to_paise(amount):
    return int(Decimal(amount) * 100)


def create_payment_link(client, order, callback_url):
    """Create and validate an expiring, full-amount Razorpay hosted Payment Link.

    Razorpay Payment Link creation returns a `plink_...` Payment Link ID and a
    hosted URL. It must not be treated as a Razorpay Order checkout response;
    an `order_id` may be absent at this stage.
    """
    if not client:
        raise PaymentLinkError("Razorpay client is not configured.")

    phone_digits = "".join(
        char for char in order.phone
        if char.isdigit()
    )

    # Keep only the last 10 digits for an Indian phone number.
    phone_number = phone_digits[-10:]

    payload = {
        "amount": _amount_to_paise(order.total),
        "currency": settings.RAZORPAY_CURRENCY,
        "accept_partial": False,
        "expire_by": int(
            (
                timezone.now()
                + timedelta(
                    minutes=settings.PAYMENT_RESERVATION_MINUTES
                )
            ).timestamp()
        ),
        "reference_id": order.number,
        "description": f"IKart order {order.number}",
        "customer": {
            "name": order.full_name,
            "email": order.email,
            "contact": f"+91{phone_number}",
        },
        "notify": {
            "sms": False,
            "email": False,
        },
        "reminder_enable": False,
        "notes": {
            "ikart_order": order.number,
        },
        "callback_url": callback_url,
        "callback_method": "get",
    }

    logger.info(
        "Creating Razorpay Payment Link for order %s",
        order.number,
    )

    try:
        payment_link = client.payment_link.create(payload)

    except Exception as exc:
        logger.exception(
            "Razorpay Payment Link API failed for order %s",
            order.number,
        )

        raise PaymentLinkError("Razorpay Payment Link creation failed.") from exc

    # A hosted Payment Link needs these fields for our flow. Do NOT require
    # `order_id`: Payment Links are identified by `id` and resumed via
    # `short_url`; a Razorpay Order ID is separate and may not exist yet.
    payment_link_id = payment_link.get("id")
    payment_link_url = payment_link.get("short_url")
    reference_id = payment_link.get("reference_id")
    amount = payment_link.get("amount")
    currency = payment_link.get("currency")

    if not payment_link_id or not payment_link_url:
        logger.warning("Razorpay returned incomplete Payment Link fields for order %s", order.number)
        raise PaymentLinkError("Razorpay returned an incomplete Payment Link response.")
    if reference_id and reference_id != order.number:
        logger.warning("Razorpay Payment Link reference mismatch for order %s", order.number)
        raise PaymentLinkError("Razorpay returned a Payment Link for a different order.")
    if amount is not None and int(amount) != _amount_to_paise(order.total):
        logger.warning("Razorpay Payment Link amount mismatch for order %s", order.number)
        raise PaymentLinkError("Razorpay returned a Payment Link with an unexpected amount.")
    if currency and currency != settings.RAZORPAY_CURRENCY:
        logger.warning("Razorpay Payment Link currency mismatch for order %s", order.number)
        raise PaymentLinkError("Razorpay returned a Payment Link with an unexpected currency.")

    logger.info(
        "Razorpay Payment Link created for order %s: link_id=%s status=%s",
        order.number,
        payment_link_id,
        payment_link.get("status", "created"),
    )

    return payment_link


def verify_payment_link_signature(
    payment_link_id,
    reference_id,
    status,
    payment_id,
    signature,
):
    """Verify the exact Payment Link callback payload using the server secret."""

    payload = "|".join(
        (
            payment_link_id,
            reference_id,
            status,
            payment_id,
        )
    )

    expected = hmac.new(
        settings.RAZORPAY_KEY_SECRET.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(
        expected,
        signature,
    )


def cancel_payment_link(client, payment_link_id):
    """Cancel the hosted page before releasing an unpaid local reservation."""

    return client.payment_link.cancel(payment_link_id)
