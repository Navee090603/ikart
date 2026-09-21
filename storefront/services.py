from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Case, Count, IntegerField, When
from django.utils import timezone
import razorpay

from .models import Coupon, CouponRedemption, NotificationLog, Order, OrderItem, PaymentTransaction, Product, ProductVariant, ProductView


@dataclass
class CartQuote:
    subtotal: Decimal
    delivery_fee: Decimal
    discount_amount: Decimal
    tax_amount: Decimal
    total: Decimal
    coupon: Coupon | None
    coupon_error: str = ""

    def as_dict(self):
        return {
            "subtotal": str(self.subtotal), "delivery_fee": str(self.delivery_fee),
            "discount_amount": str(self.discount_amount), "tax_amount": str(self.tax_amount),
            "total": str(self.total), "coupon_code": self.coupon.code if self.coupon else "",
            "coupon_error": self.coupon_error,
        }


def calculate_cart_quote(cart, user=None, delivery_option=Order.DeliveryOption.STANDARD, coupon_code=""):
    """The only source of truth for cart, checkout, and payment amounts."""
    subtotal = cart.subtotal
    delivery_fee = Decimal("99") if delivery_option == Order.DeliveryOption.EXPRESS else (Decimal("0") if subtotal >= 499 else Decimal("49"))
    coupon = None
    discount_amount = Decimal("0")
    coupon_error = ""
    code = (coupon_code or "").strip().upper()
    if code:
        coupon = Coupon.objects.filter(code__iexact=code).first()
        if not coupon:
            coupon_error = "That coupon code does not exist."
        else:
            valid, coupon_error = coupon.is_valid_for(subtotal, user if getattr(user, "is_authenticated", False) else None)
            if valid:
                discount_amount = coupon.discount_for(subtotal).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            else:
                coupon = None
    taxable_amount = max(subtotal - discount_amount, Decimal("0"))
    tax_rate = Decimal(str(getattr(settings, "TAX_RATE", Decimal("0"))))
    tax_amount = (taxable_amount * tax_rate / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total = (taxable_amount + delivery_fee + tax_amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return CartQuote(subtotal, delivery_fee, discount_amount, tax_amount, total, coupon, coupon_error)


def deduct_order_inventory(order):
    """Reserve/deduct exactly once, with row locks to prevent overselling."""
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if order.inventory_deducted and not order.inventory_restored:
            return order
        items = list(order.items.select_related("product", "variant"))
        product_ids = [item.product_id for item in items if item.product_id and not item.variant_id]
        variant_ids = [item.variant_id for item in items if item.variant_id]
        products = {product.id: product for product in Product.objects.select_for_update().filter(id__in=product_ids)}
        variants = {variant.id: variant for variant in ProductVariant.objects.select_for_update().filter(id__in=variant_ids)}
        for item in items:
            stock_item = variants.get(item.variant_id) if item.variant_id else products.get(item.product_id)
            if not stock_item or item.quantity > stock_item.stock:
                raise ValueError(f"{item.product_name} is no longer available in the requested quantity.")
        for item in items:
            stock_item = variants[item.variant_id] if item.variant_id else products[item.product_id]
            stock_item.stock -= item.quantity
            stock_item.save(update_fields=["stock"])
        order.inventory_deducted = True
        order.inventory_restored = False
        order.save(update_fields=["inventory_deducted", "inventory_restored", "updated_at"])
        return order


def restore_order_inventory(order):
    """Return stock once only for payment failures, cancellations, or refunded returns."""
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if not order.inventory_deducted or order.inventory_restored:
            return False
        items = list(order.items.select_related("product", "variant"))
        product_ids = [item.product_id for item in items if item.product_id and not item.variant_id]
        variant_ids = [item.variant_id for item in items if item.variant_id]
        products = {product.id: product for product in Product.objects.select_for_update().filter(id__in=product_ids)}
        variants = {variant.id: variant for variant in ProductVariant.objects.select_for_update().filter(id__in=variant_ids)}
        for item in items:
            stock_item = variants.get(item.variant_id) if item.variant_id else products.get(item.product_id)
            if stock_item:
                stock_item.stock += item.quantity
                stock_item.save(update_fields=["stock"])
        order.inventory_restored = True
        order.save(update_fields=["inventory_restored", "updated_at"])
        return True


def _release_coupon_redemption(order):
    """Do not consume a coupon for an online payment that did not complete."""
    CouponRedemption.objects.filter(order=order).delete()


def _ensure_coupon_redemption(order):
    """Restore a coupon reservation if a late verified payment arrives. Lock prevents concurrent redemption."""
    if order.coupon_id:
        with transaction.atomic():
            existing = CouponRedemption.objects.select_for_update().filter(order=order).first()
            if not existing:
                CouponRedemption.objects.create(
                    order=order,
                    coupon_id=order.coupon_id,
                    user=order.user,
                    discount_amount=order.discount_amount,
                )


def mark_payment_captured(payment, payment_id, payload=None):
    """Idempotently finalise a verified Razorpay payment. Handles cases where inventory
    may have already been deducted or restored (e.g., after a refund was processed).
    If inventory can't be deducted (already gone), payment is marked as captured but
    order status is set to PAYMENT_PENDING to indicate manual review is needed."""
    with transaction.atomic():
        payment = PaymentTransaction.objects.select_for_update().select_related("order").get(pk=payment.pk)
        if payment.status == PaymentTransaction.Status.CAPTURED:
            return payment.order
        order = payment.order
        inventory_deduction_failed = False
        try:
            if not order.inventory_deducted or order.inventory_restored:
                order = deduct_order_inventory(order)
        except ValueError as e:
            inventory_deduction_failed = True
            import logging
            logging.getLogger(__name__).warning(
                f"Payment {payment.pk} captured but inventory deduction failed for order {order.number}: {e}"
            )
        if payment_id:
            payment.provider_payment_id = payment_id
        if payload and isinstance(payload, dict) and payload.get("order_id") and not payment.provider_order_id:
            payment.provider_order_id = payload["order_id"]
        payment.status = PaymentTransaction.Status.CAPTURED
        payment.verified_at = timezone.now()
        if payload:
            payment.provider_payload = {**payment.provider_payload, "payment": payload}
        payment.save(update_fields=["provider_order_id", "provider_payment_id", "status", "verified_at", "provider_payload", "updated_at"])
        if inventory_deduction_failed:
            order.payment_status = "paid_manual_review"
            order.status = Order.Status.PAYMENT_PENDING
        else:
            order.payment_status = "paid"
            order.status = Order.Status.PLACED
        order.save(update_fields=["payment_status", "status", "updated_at"])
        _ensure_coupon_redemption(order)
        return order


def fail_or_cancel_payment(payment, status, payload=None):
    """Idempotently close an unpaid attempt and release its stock reservation."""
    with transaction.atomic():
        payment = PaymentTransaction.objects.select_for_update().select_related("order").get(pk=payment.pk)
        if payment.status == PaymentTransaction.Status.CAPTURED:
            return payment.order
        if payment.status in {PaymentTransaction.Status.FAILED, PaymentTransaction.Status.CANCELLED}:
            return payment.order
        payment.status = status
        if payload:
            payment.provider_payload = {**payment.provider_payload, "failure": payload}
        payment.inventory_released = True
        payment.save(update_fields=["status", "provider_payload", "inventory_released", "updated_at"])
        order = payment.order
        restore_order_inventory(order)
        _release_coupon_redemption(order)
        order.payment_status = "failed" if status == PaymentTransaction.Status.FAILED else "cancelled"
        order.status = Order.Status.PAYMENT_FAILED
        order.save(update_fields=["payment_status", "status", "updated_at"])
        return order


def release_stale_payment_reservations(cutoff):
    """Release old uncompleted Razorpay reservations; safe to run repeatedly."""
    payment_ids = list(
        PaymentTransaction.objects.filter(
            status__in=[PaymentTransaction.Status.CREATED, PaymentTransaction.Status.AUTHORIZED],
            created_at__lt=cutoff,
        ).values_list("id", flat=True)
    )
    released = 0
    for payment_id in payment_ids:
        payment = PaymentTransaction.objects.filter(pk=payment_id).first()
        if not payment:
            continue
        order = fail_or_cancel_payment(payment, PaymentTransaction.Status.CANCELLED, {"reason": "payment_reservation_expired"})
        if order.payment_status == "cancelled":
            released += 1
    return released


def refund_captured_payment(order):
    """Issue one Razorpay refund for a captured online payment.

    COD has no gateway transaction and is deliberately left to the store team to
    complete before they mark the request refunded in the admin.
    """
    payment = PaymentTransaction.objects.select_related("order").filter(order=order).first()
    if not payment:
        return None
    if payment.status == PaymentTransaction.Status.REFUNDED:
        return payment
    if payment.status != PaymentTransaction.Status.CAPTURED or not payment.provider_payment_id:
        raise ValueError("This online payment has not been captured and cannot be refunded.")
    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        raise ValueError("Razorpay refund keys are not configured.")
    client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
    refund = client.payment.refund(
        payment.provider_payment_id,
        {"amount": int(payment.amount * 100), "notes": {"ikart_order": order.number}},
    )
    with transaction.atomic():
        payment = PaymentTransaction.objects.select_for_update().get(pk=payment.pk)
        refund_status = refund.get("status", "pending")
        payment.provider_refund_id = refund.get("id") or payment.provider_refund_id
        payment.status = PaymentTransaction.Status.REFUNDED if refund_status == "processed" else PaymentTransaction.Status.REFUND_PENDING
        payment.provider_payload = {**payment.provider_payload, "refund": refund}
        payment.save(update_fields=["provider_refund_id", "status", "provider_payload", "updated_at"])
    return payment


def frequently_bought_together(product, limit=4):
    """Use real completed basket pairs; no external recommendation service is required."""
    pairs = (
        OrderItem.objects.filter(order__items__product=product)
        .exclude(product=product)
        .values("product_id")
        .annotate(score=Count("id"))
        .order_by("-score")[:limit]
    )
    ids = [pair["product_id"] for pair in pairs]
    if not ids:
        return Product.objects.none()
    ordering = Case(*[When(id=product_id, then=position) for position, product_id in enumerate(ids)], output_field=IntegerField())
    return Product.objects.filter(id__in=ids, is_active=True).order_by(ordering)


def customers_also_viewed(product, limit=4):
    sessions = ProductView.objects.filter(product=product).exclude(session_key="").values("session_key")
    viewed = (
        ProductView.objects.filter(session_key__in=sessions)
        .exclude(product=product)
        .values("product_id")
        .annotate(score=Count("id"))
        .order_by("-score")[:limit]
    )
    ids = [item["product_id"] for item in viewed]
    if not ids:
        return Product.objects.none()
    ordering = Case(*[When(id=product_id, then=position) for position, product_id in enumerate(ids)], output_field=IntegerField())
    return Product.objects.filter(id__in=ids, is_active=True).order_by(ordering)


def notify_order_email(order, event, subject, message):
    """Email now; SMS delivery can later plug into the same notification log."""
    log = NotificationLog.objects.create(
        order=order, user=order.user, recipient=order.email, channel=NotificationLog.Channel.EMAIL,
        event=event, subject=subject, message=message,
    )
    try:
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [order.email], fail_silently=False)
    except Exception:
        logging.getLogger(__name__).exception(
            "Failed to send '%s' email for order %s", event, order.number,
        )
        log.delivery_status = "failed"
        log.save(update_fields=["delivery_status"])
        return False
    log.delivery_status = "sent"
    log.save(update_fields=["delivery_status"])
    return True
