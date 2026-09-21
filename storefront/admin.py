import csv
import logging
from decimal import Decimal, InvalidOperation
from io import TextIOWrapper

import requests
from django import forms
from django.core.files.base import ContentFile

from django.contrib import admin, messages
from django.db import transaction, IntegrityError
from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils.text import slugify

from .forms import ProductCSVUploadForm
from .forms import CategoryCSVUploadForm
from django.core.mail import send_mail

from .models import Address, Category, Coupon, CouponRedemption, FAQ, MarketingPreference, NotificationLog, Order, OrderItem, OrderRequest, PaymentTransaction, PaymentWebhookEvent, Product, ProductImage, ProductQuestion, ProductVariant, Review, SavedForLaterItem, Shipment, ShipmentEvent, SupportTicket, SupportTicketReply, WishlistItem
from .services import fail_or_cancel_payment, notify_order_email, refund_captured_payment, restore_order_inventory

logger = logging.getLogger(__name__)


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 1


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "brand",
        "category",
        "price",
        "stock",
        "low_stock",
        "is_active",
        "is_featured",
    )

    list_filter = (
        "is_active",
        "is_featured",
        "category",
        "brand",
    )

    search_fields = (
        "name",
        "brand",
        "description",
    )

    prepopulated_fields = {
        "slug": ("name",)
    }

    change_list_template = "admin/storefront/product/change_list.html"

    inlines = [
        ProductImageInline,
        ProductVariantInline
    ]


    @admin.display(
        boolean=True,
        description="Low stock"
    )
    def low_stock(self, product):
        return product.is_low_stock



    def get_urls(self):

        urls = super().get_urls()

        custom_urls = [
            path(
                "upload-csv/",
                self.admin_site.admin_view(self.upload_csv),
                name="storefront_product_upload_csv",
            )
        ]

        return custom_urls + urls



    def upload_csv(self, request):

        if request.method == "POST":

            form = ProductCSVUploadForm(
                request.POST,
                request.FILES
            )


            if form.is_valid():

                csv_file = form.cleaned_data["csv_file"]


                reader = csv.DictReader(
                    TextIOWrapper(
                        csv_file.file,
                        encoding="utf-8-sig"
                    )
                )


                required_columns = {
                    "name",
                    "category",
                    "price",
                    "stock",
                    "description"
                }


                if (
                    not reader.fieldnames
                    or not required_columns.issubset(
                        set(reader.fieldnames)
                    )
                ):

                    form.add_error(
                        "csv_file",
                        "Required columns: name, category, price, stock, description"
                    )


                else:

                    rows = []
                    errors = []


                    for line_number, row in enumerate(reader, start=2):

                        name = (
                            row.get("name") or ""
                        ).strip()


                        category_name = (
                            row.get("category") or ""
                        ).strip()


                        description = (
                            row.get("description") or ""
                        ).strip()



                        try:

                            price = Decimal(
                                row.get("price")
                            )

                            stock = int(
                                row.get("stock")
                            )


                            low_stock_threshold = int(
                                row.get(
                                    "low_stock_threshold",
                                    5
                                )
                            )


                            compare_at_price = (

                                Decimal(
                                    row["compare_at_price"]
                                )

                                if row.get("compare_at_price")

                                else None

                            )


                        except (
                            InvalidOperation,
                            ValueError,
                            TypeError
                        ):

                            errors.append(
                                f"Row {line_number}: Invalid price or stock"
                            )

                            continue



                        if not name or not category_name or not description:

                            errors.append(
                                f"Row {line_number}: Required fields missing"
                            )


                        elif price < 0 or stock < 0:

                            errors.append(
                                f"Row {line_number}: Negative values not allowed"
                            )


                        elif (
                            compare_at_price
                            and compare_at_price < price
                        ):

                            errors.append(
                                f"Row {line_number}: compare price cannot be lower"
                            )


                        else:


                            rows.append({

                                "line_number": line_number,

                                "name": name,

                                "slug": slugify(name),

                                "category_name": category_name,


                                "brand": (
                                    row.get("brand")
                                    or ""
                                ).strip(),


                                "short_description": (
                                    row.get("short_description")
                                    or description[:250]
                                ),


                                "description": description,


                                "price": price,


                                "compare_at_price": compare_at_price,


                                "stock": stock,


                                "low_stock_threshold": low_stock_threshold,


                                "is_featured":
                                    (
                                        row.get("is_featured","")
                                        .lower()
                                        in [
                                            "true",
                                            "1",
                                            "yes"
                                        ]
                                    ),


                                "is_active":
                                    (
                                        row.get(
                                            "is_active",
                                            "true"
                                        )
                                        .lower()
                                        not in [
                                            "false",
                                            "0",
                                            "no"
                                        ]
                                    ),



                                "images":
                                    (
                                        row.get("images")
                                        or ""
                                    ).strip(),



                                "variants":
                                    (
                                        row.get("variants")
                                        or ""
                                    ).strip(),

                            })




                    if errors:

                        form.add_error(
                            "csv_file",
                            " | ".join(errors[:5])
                        )


                    elif not rows:

                        form.add_error(
                            "csv_file",
                            "No products found"
                        )



                    else:

                        imported_count = 0

                        for row in rows:
                            line_number = row["line_number"]
                            try:
                                with transaction.atomic():
                                    self._import_product_row(row, line_number, errors)
                                imported_count += 1
                            except Exception as e:
                                errors.append(
                                    f"Row {line_number}: Import failed, row skipped: {str(e)[:150]}"
                                )
                                continue

                        if errors:
                            form.add_error(
                                "csv_file",
                                " | ".join(errors[:5])
                            )

                        if imported_count:

                            self.message_user(
                                request,
                                f"Successfully imported {imported_count} of {len(rows)} product(s)."
                                + (f" {len(errors)} issue(s) reported below." if errors else ""),
                                messages.SUCCESS if not errors else messages.WARNING
                            )

                            return redirect(
                                reverse(
                                    "admin:storefront_product_changelist"
                                )
                            )



        else:

            form = ProductCSVUploadForm()



        return render(

            request,

            "admin/storefront/product/csv_upload.html",

            {

                **self.admin_site.each_context(request),

                "form": form,

                "title":
                    "Import products from CSV"

            }

        )

    def _import_product_row(self, row, line_number, errors):
        """Import a single CSV row. Runs inside a per-row transaction so one bad
        row can't roll back products already imported earlier in the same file."""

        # -------------------------
        # CATEGORY CREATE
        # -------------------------

        category, _ = Category.objects.get_or_create(
            name=row["category_name"],
            defaults={"slug": slugify(row["category_name"])},
        )

        # -------------------------
        # PRODUCT CREATE / UPDATE
        # -------------------------

        slug = row["slug"]
        existing_product = Product.objects.filter(slug=slug).first()
        if existing_product and existing_product.name != row["name"]:
            counter = 2
            original_slug = slug
            while Product.objects.filter(slug=slug).exclude(name=row["name"]).exists():
                slug = f"{original_slug}-{counter}"
                counter += 1

        product, created = Product.objects.update_or_create(
            slug=slug,
            defaults={
                "category": category,
                "name": row["name"],
                "brand": row["brand"],
                "short_description": row["short_description"],
                "description": row["description"],
                "price": row["price"],
                "compare_at_price": row["compare_at_price"],
                "stock": row["stock"],
                "low_stock_threshold": row["low_stock_threshold"],
                "is_featured": row["is_featured"],
                "is_active": row["is_active"],
            },
        )

        # -------------------------
        # PRODUCT IMAGES
        # -------------------------

        if row["images"]:

            ProductImage.objects.filter(product=product).delete()

            image_list = row["images"].split("|")

            for index, image_url in enumerate(image_list):

                image_url = image_url.strip()
                if not image_url:
                    continue

                if not image_url.startswith(("http://", "https://")):
                    errors.append(
                        f"Row {line_number}, image {index + 1}: "
                        f"Image URL must start with http:// or https://. "
                        f"Got: {image_url}"
                    )
                    continue

                try:
                    filename, content = self._fetch_image(image_url)
                except (requests.RequestException, ValueError) as e:
                    errors.append(
                        f"Row {line_number}, image {index + 1}: "
                        f"Could not download image from {image_url}: {str(e)[:100]}"
                    )
                    continue

                image = ProductImage(
                    product=product,
                    alt_text=product.name,
                    sort_order=index,
                )
                image.image.save(filename, content, save=True)

        # -------------------------
        # PRODUCT VARIANTS
        # -------------------------

        if row["variants"]:

            ProductVariant.objects.filter(product=product).delete()

            variant_list = row["variants"].split("|")

            for variant_idx, variant in enumerate(variant_list, start=1):

                parts = variant.split("-")
                if len(parts) < 5:
                    errors.append(
                        f"Row {line_number}, variant {variant_idx}: "
                        f"Expected format 'size-color-sku-adjustment-stock' "
                        f"(SKU can contain hyphens). Got: {variant}"
                    )
                    continue

                size = parts[0]
                color = parts[1]
                adjustment = parts[-2]
                variant_stock = parts[-1]
                sku = "-".join(parts[2:-2])

                try:
                    price_adj = Decimal(adjustment)
                    stock_qty = int(variant_stock)
                except (InvalidOperation, ValueError):
                    errors.append(
                        f"Row {line_number}, variant {variant_idx}: "
                        f"Adjustment must be a decimal, stock must be an integer. "
                        f"Got adjustment='{adjustment}', stock='{variant_stock}'"
                    )
                    continue

                try:
                    ProductVariant.objects.create(
                        product=product,
                        size=size,
                        color=color,
                        sku=sku,
                        price_adjustment=price_adj,
                        stock=stock_qty,
                    )
                except (IntegrityError, ValueError) as e:
                    errors.append(
                        f"Row {line_number}, variant {variant_idx}: "
                        f"Failed to create variant: {str(e)[:100]}"
                    )
                    continue

    @staticmethod
    def _fetch_image(image_url, timeout=10, max_bytes=10 * 1024 * 1024):
        """Download a remote image and return (filename, ContentFile) ready for an ImageField."""
        response = requests.get(image_url, timeout=timeout, stream=True)
        response.raise_for_status()

        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > max_bytes:
            raise ValueError("Image exceeds maximum allowed size")

        data = response.raw.read(max_bytes + 1, decode_content=True)
        if len(data) > max_bytes:
            raise ValueError("Image exceeds maximum allowed size")

        filename = image_url.rstrip("/").split("/")[-1].split("?")[0] or "image"
        if "." not in filename:
            content_type = response.headers.get("Content-Type", "")
            ext = content_type.split("/")[-1].split(";")[0] if "/" in content_type else "jpg"
            filename = f"{filename}.{ext}"

        return filename, ContentFile(data)

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
                    logger.exception("Failed to send promotion email for coupon %s to %s", coupon.code, recipient)
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
                logger.exception("Razorpay refund failed to start for order %s", obj.order.number)
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
    list_display = ("order", "provider", "provider_order_id", "provider_payment_link_id", "provider_payment_id", "status", "amount", "updated_at")
    list_filter = ("provider", "status")
    search_fields = ("order__number", "provider_order_id", "provider_payment_link_id", "provider_payment_id", "provider_refund_id")
    readonly_fields = ("order", "provider", "provider_order_id", "provider_payment_link_id", "provider_payment_id", "provider_refund_id", "amount", "currency", "status", "inventory_released", "verified_at", "provider_payload", "created_at", "updated_at")
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


admin.site.register([Address, CouponRedemption, FAQ, MarketingPreference, Review, SavedForLaterItem, WishlistItem])

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):

    list_display = (
        "name",
        "parent",
        "slug",
    )

    search_fields = (
        "name",
        "slug",
    )


    def get_urls(self):

        urls = super().get_urls()

        custom_urls = [
            path(
                "upload-category-csv/",
                self.admin_site.admin_view(self.upload_csv),
                name="category-upload-csv"
            )
        ]

        return custom_urls + urls



    def upload_csv(self, request):

        if request.method == "POST":

            form = CategoryCSVUploadForm(
                request.POST,
                request.FILES
            )


            if form.is_valid():

                import csv

                file = form.cleaned_data["csv_file"]


                reader = csv.DictReader(
                    file.read().decode("utf-8-sig").splitlines()
                )


                required_columns = {"name", "slug", "category_id", "parent_id"}

                if not reader.fieldnames or not required_columns.issubset(set(reader.fieldnames or [])):
                    form.add_error(
                        "csv_file",
                        f"Required columns: {', '.join(sorted(required_columns))}"
                    )
                else:

                    categories = {}


                    for row in reader:

                        if not row.get("name") or not row.get("slug"):
                            form.add_error(
                                "csv_file",
                                "All rows must have 'name' and 'slug' values"
                            )
                            break

                        categories[row["name"]] = row


                    if not form.errors:

                        for name, row in categories.items():

                            parent = None


                            if row.get("parent_id"):

                                parent_name = None

                                for item in categories.values():

                                    if item.get("category_id") == row["parent_id"]:
                                        parent_name = item["name"]


                                if parent_name:

                                    parent, _ = Category.objects.get_or_create(
                                        name=parent_name
                                    )



                            Category.objects.update_or_create(

                                slug=row["slug"],

                                defaults={

                                    "name": name,

                                    "parent": parent,

                                }

                            )


                        self.message_user(
                            request,
                            "Categories imported successfully"
                        )

                        return redirect(
                            "admin:storefront_category_changelist"
                        )


        else:

            form = CategoryCSVUploadForm()



        return render(
            request,
            "admin/category_upload.html",
            {
                "form":form
            }
        )
