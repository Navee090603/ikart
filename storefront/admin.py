import csv
from decimal import Decimal, InvalidOperation
from io import TextIOWrapper

from django.contrib import admin, messages
from django.db import transaction
from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils.text import slugify

from .forms import ProductCSVUploadForm
from django.core.mail import send_mail

from .models import Address, Category, Coupon, CouponRedemption, FAQ, MarketingPreference, NotificationLog, Order, OrderItem, OrderRequest, PaymentTransaction, PaymentWebhookEvent, Product, ProductImage, ProductQuestion, ProductVariant, Review, SavedForLaterItem, Shipment, ShipmentEvent, SupportTicket, SupportTicketReply, WishlistItem
from .services import fail_or_cancel_payment, notify_order_email, refund_captured_payment, restore_order_inventory


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 1


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "brand", "category", "price", "stock", "low_stock", "is_active", "is_featured")
    list_filter = ("is_active", "is_featured", "category", "brand")
    search_fields = ("name", "brand", "description")
    prepopulated_fields = {"slug": ("name",)}
    change_list_template = "admin/storefront/product/change_list.html"
    inlines = [ProductImageInline, ProductVariantInline]

    @admin.display(boolean=True, description="Low stock")
    def low_stock(self, product):
        return product.is_low_stock

    def get_urls(self):
        urls = super().get_urls()
        return [path("upload-csv/", self.admin_site.admin_view(self.upload_csv), name="storefront_product_upload_csv")] + urls

    def upload_csv(self, request):
        if request.method == "POST":
            form = ProductCSVUploadForm(request.POST, request.FILES)
            if form.is_valid():
                reader = csv.DictReader(TextIOWrapper(form.cleaned_data["csv_file"].file, encoding="utf-8-sig"))
                required = {"name", "category", "price", "stock", "description"}
                if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
                    form.add_error("csv_file", "Required columns: name, category, price, stock, description.")
                else:
                    rows, errors = [], []
                    for line_number, row in enumerate(reader, start=2):
                        name = (row.get("name") or "").strip()
                        category_name = (row.get("category") or "").strip()
                        description = (row.get("description") or "").strip()
                        try:
                            price = Decimal((row.get("price") or "").strip())
                            stock = int((row.get("stock") or "").strip())
                            low_stock_threshold = int((row.get("low_stock_threshold") or "5").strip())
                            compare_at_price = Decimal(row["compare_at_price"].strip()) if (row.get("compare_at_price") or "").strip() else None
                        except (InvalidOperation, ValueError):
                            errors.append(f"Row {line_number}: price, stock, low_stock_threshold, or compare_at_price is invalid.")
                            continue
                        if not name or not slugify(name) or not category_name or not description:
                            errors.append(f"Row {line_number}: name, category, and description are required.")
                        elif price < 0 or stock < 0 or low_stock_threshold < 0:
                            errors.append(f"Row {line_number}: price and stock values cannot be negative.")
                        elif compare_at_price is not None and compare_at_price < price:
                            errors.append(f"Row {line_number}: compare_at_price cannot be lower than price.")
                        else:
                            rows.append({
                                "name": name, "slug": slugify(name), "category_name": category_name,
                                "brand": (row.get("brand") or "").strip(),
                                "short_description": (row.get("short_description") or "").strip() or description[:250],
                                "description": description, "price": price, "stock": stock,
                                "low_stock_threshold": low_stock_threshold, "compare_at_price": compare_at_price,
                                "is_featured": (row.get("is_featured") or "").strip().lower() in {"true", "1", "yes"},
                                "is_active": (row.get("is_active") or "true").strip().lower() not in {"false", "0", "no"},
                            })
                    if errors:
                        form.add_error("csv_file", " ".join(errors[:5]))
                    elif not rows:
                        form.add_error("csv_file", "The CSV does not contain any product rows.")
                    else:
                        with transaction.atomic():
                            for row in rows:
                                category, _ = Category.objects.get_or_create(name=row.pop("category_name"))
                                Product.objects.update_or_create(slug=row.pop("slug"), defaults={"category": category, **row})
                        self.message_user(request, f"Imported or updated {len(rows)} products.", messages.SUCCESS)
                        return redirect(reverse("admin:storefront_product_changelist"))
        else:
            form = ProductCSVUploadForm()
        return render(request, "admin/storefront/product/csv_upload.html", {**self.admin_site.each_context(request), "form": form, "title": "Import products from CSV"})


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    readonly_fields = ("product", "product_name", "variant_label", "quantity", "unit_price")
    can_delete = False
    extra = 0


class ShipmentInline(admin.StackedInline):
    model = Shipment
    extra = 0


class OrderRequestInline(admin.TabularInline):
    model = OrderRequest
    extra = 0
    readonly_fields = ("user", "request_type", "reason", "note", "created_at", "updated_at")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("number", "full_name", "total", "discount_amount", "payment_method", "payment_status", "status", "created_at")
    list_filter = ("status", "payment_method", "created_at")
    search_fields = ("number", "full_name", "email")
    readonly_fields = ("number", "subtotal", "delivery_fee", "total")
    inlines = [OrderItemInline, ShipmentInline, OrderRequestInline]

    def save_model(self, request, obj, form, change):
        previous_status = Order.objects.get(pk=obj.pk).status if change else None
        super().save_model(request, obj, form, change)
        if change and obj.status in {Order.Status.CANCELLED, Order.Status.REFUNDED} and previous_status != obj.status:
            restore_order_inventory(obj)
        if change and previous_status != obj.status:
            notify_order_email(obj, "order_status", f"Order {obj.number} is {obj.get_status_display()}", f"Your order status is now: {obj.get_status_display()}.")


class ShipmentEventInline(admin.TabularInline):
    model = ShipmentEvent
    extra = 1


@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    list_display = ("order", "carrier", "tracking_number", "estimated_delivery", "updated_at")
    search_fields = ("order__number", "tracking_number", "carrier")
    inlines = [ShipmentEventInline]

    def save_model(self, request, obj, form, change):
        previous = Shipment.objects.filter(pk=obj.pk).values("tracking_number").first() if change else None
        super().save_model(request, obj, form, change)
        if obj.tracking_number and (not previous or previous["tracking_number"] != obj.tracking_number):
            notify_order_email(
                obj.order,
                "shipment_update",
                f"Order {obj.order.number} is on its way",
                f"Your order has a shipment update. Carrier: {obj.carrier or 'Pending'}. Tracking number: {obj.tracking_number}.",
            )


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = ("code", "discount_type", "value", "minimum_order_amount", "ends_at", "is_active", "redemptions_count")
    list_filter = ("discount_type", "is_active")
    search_fields = ("code", "description")
    actions = ("send_promotion_email",)

    @admin.display(description="Redemptions")
    def redemptions_count(self, coupon):
        return coupon.redemptions.count()

    @admin.action(description="Send selected coupon by email to opted-in customers")
    def send_promotion_email(self, request, queryset):
        preferences = MarketingPreference.objects.filter(email_promotions=True).select_related("user")
        recipients = [item.user.email for item in preferences if item.user.email]
        sent = 0
        for coupon in queryset:
            subject = f"IKart offer: use {coupon.code}"
            body = coupon.description or f"Use code {coupon.code} on your next IKart order."
            for recipient in recipients:
                try:
                    send_mail(subject, body, None, [recipient], fail_silently=False)
                    NotificationLog.objects.create(recipient=recipient, channel=NotificationLog.Channel.EMAIL, event="promotion", subject=subject, message=body, delivery_status="sent")
                    sent += 1
                except Exception:
                    NotificationLog.objects.create(recipient=recipient, channel=NotificationLog.Channel.EMAIL, event="promotion", subject=subject, message=body, delivery_status="failed")
        self.message_user(request, f"Queued {sent} promotional email(s).", messages.SUCCESS)


@admin.register(OrderRequest)
class OrderRequestAdmin(admin.ModelAdmin):
    list_display = ("order", "request_type", "reason", "user", "status", "created_at")
    list_filter = ("request_type", "reason", "status")
    search_fields = ("order__number", "user__username")

    def save_model(self, request, obj, form, change):
        previous_status = OrderRequest.objects.get(pk=obj.pk).status if change else None
        requires_refund = (
            (obj.status == OrderRequest.Status.APPROVED and obj.request_type == OrderRequest.RequestType.CANCELLATION)
            or obj.status == OrderRequest.Status.REFUNDED
        ) and previous_status != obj.status
        if requires_refund and obj.order.payment_method == Order.PaymentMethod.RAZORPAY:
            try:
                payment = refund_captured_payment(obj.order)
            except ValueError as error:
                self.message_user(request, str(error), messages.ERROR)
                return
            except Exception:
                self.message_user(request, "Razorpay refund could not be started. The request was not updated.", messages.ERROR)
                return
            if payment and payment.status == payment.Status.REFUND_PENDING:
                obj.status = OrderRequest.Status.REFUND_PENDING
                self.message_user(request, "Razorpay accepted the refund. It will be marked refunded after the signed refund webhook arrives.", messages.INFO)
        super().save_model(request, obj, form, change)
        order = obj.order
        if obj.status == OrderRequest.Status.APPROVED and obj.request_type == OrderRequest.RequestType.CANCELLATION:
            order.status = Order.Status.CANCELLED
            order.payment_status = "refunded" if obj.order.payment_method == Order.PaymentMethod.RAZORPAY else "cancelled"
        elif obj.status == OrderRequest.Status.REFUNDED:
            order.status = Order.Status.REFUNDED
            order.payment_status = "refunded"
        elif obj.status == OrderRequest.Status.REFUND_PENDING:
            if obj.request_type == OrderRequest.RequestType.CANCELLATION:
                order.status = Order.Status.CANCELLED
                restore_order_inventory(order)
            order.payment_status = "refund_pending"
            order.save(update_fields=["status", "payment_status", "updated_at"])
            notify_order_email(order, "refund_pending", f"Order {order.number}: refund initiated", "Your refund has been initiated and is awaiting confirmation from the payment provider.")
            return
        else:
            return
        restore_order_inventory(order)
        order.save(update_fields=["status", "payment_status", "updated_at"])
        notify_order_email(order, "request_updated", f"Order {order.number}: {obj.get_status_display()}", f"Your {obj.get_request_type_display().lower()} request is now {obj.get_status_display().lower()}.")


class SupportTicketReplyInline(admin.TabularInline):
    model = SupportTicketReply
    extra = 1


@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = ("id", "subject", "user", "category", "status", "updated_at")
    list_filter = ("status", "category")
    search_fields = ("subject", "message", "user__username")
    inlines = [SupportTicketReplyInline]

    def save_model(self, request, obj, form, change):
        previous_status = SupportTicket.objects.get(pk=obj.pk).status if change else None
        super().save_model(request, obj, form, change)
        if change and previous_status != obj.status and obj.user.email:
            send_mail(
                f"IKart support ticket #{obj.id} update",
                f"Your support ticket is now {obj.get_status_display().lower()}.",
                None,
                [obj.user.email],
                fail_silently=True,
            )


@admin.register(ProductQuestion)
class ProductQuestionAdmin(admin.ModelAdmin):
    list_display = ("product", "user", "question", "is_published", "created_at", "answered_at")
    list_filter = ("is_published",)
    search_fields = ("product__name", "question", "answer")


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = ("event", "channel", "recipient", "order", "delivery_status", "created_at")
    list_filter = ("channel", "event", "delivery_status")
    readonly_fields = ("order", "user", "recipient", "channel", "event", "subject", "message", "delivery_status", "created_at")


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = ("order", "provider", "provider_order_id", "provider_payment_id", "status", "amount", "updated_at")
    list_filter = ("provider", "status")
    search_fields = ("order__number", "provider_order_id", "provider_payment_id", "provider_refund_id")
    readonly_fields = ("order", "provider", "provider_order_id", "provider_payment_id", "provider_refund_id", "amount", "currency", "status", "inventory_released", "verified_at", "provider_payload", "created_at", "updated_at")
    actions = ("release_unpaid_reservations",)

    @admin.action(description="Release selected unpaid payment reservations")
    def release_unpaid_reservations(self, request, queryset):
        released = 0
        for payment in queryset.filter(status__in=[PaymentTransaction.Status.CREATED, PaymentTransaction.Status.AUTHORIZED]):
            order = fail_or_cancel_payment(payment, PaymentTransaction.Status.CANCELLED, {"reason": "staff_released_reservation"})
            if order.payment_status == "cancelled":
                released += 1
        self.message_user(request, f"Released {released} unpaid reservation(s).", messages.SUCCESS)


@admin.register(PaymentWebhookEvent)
class PaymentWebhookEventAdmin(admin.ModelAdmin):
    list_display = ("provider", "event_type", "event_id", "processed_at")
    list_filter = ("provider", "event_type")
    search_fields = ("event_id",)
    readonly_fields = ("provider", "event_id", "event_type", "payload", "processed_at")


admin.site.register([Address, Category, CouponRedemption, FAQ, MarketingPreference, Review, SavedForLaterItem, WishlistItem])
