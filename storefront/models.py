from decimal import Decimal
from uuid import uuid4

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify


class Category(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True, blank=True)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="children")
    image = models.ImageField(upload_to="categories/", blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Product(models.Model):
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    name = models.CharField(max_length=180)
    slug = models.SlugField(unique=True, blank=True)
    short_description = models.CharField(max_length=250)
    description = models.TextField()
    specifications = models.TextField(blank=True, help_text="One specification per line, e.g. Material: Cotton")
    brand = models.CharField(max_length=100, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    compare_at_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Original price, used to show a discount.")
    stock = models.PositiveIntegerField(default=0)
    low_stock_threshold = models.PositiveIntegerField(default=5)
    is_featured = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    @property
    def image(self):
        first = self.images.first()
        return first.image if first else None

    @property
    def average_rating(self):
        value = self.reviews.filter(is_approved=True).aggregate(models.Avg("rating"))["rating__avg"]
        return round(value or 0, 1)

    @property
    def discount_percentage(self):
        if self.compare_at_price and self.compare_at_price > self.price:
            return round((self.compare_at_price - self.price) / self.compare_at_price * 100)
        return 0

    @property
    def is_low_stock(self):
        return self.stock <= self.low_stock_threshold

    def get_absolute_url(self):
        return reverse("storefront:product_detail", args=[self.slug])

    def __str__(self):
        return self.name


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="products/")
    alt_text = models.CharField(max_length=150, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]


class ProductVariant(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    size = models.CharField(max_length=40, blank=True)
    color = models.CharField(max_length=40, blank=True)
    sku = models.CharField(max_length=64, unique=True)
    price_adjustment = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    stock = models.PositiveIntegerField(default=0)

    @property
    def label(self):
        return " / ".join(filter(None, [self.size, self.color])) or self.sku

    def __str__(self):
        return f"{self.product.name} — {self.label}"


class Address(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="addresses")
    full_name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20)
    line1 = models.CharField(max_length=160)
    line2 = models.CharField(max_length=160, blank=True)
    city = models.CharField(max_length=80)
    state = models.CharField(max_length=80)
    postal_code = models.CharField(max_length=20)
    is_default = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.full_name}, {self.city}"


class Order(models.Model):
    class Status(models.TextChoices):
        PAYMENT_PENDING = "payment_pending", "Payment pending"
        PAYMENT_FAILED = "payment_failed", "Payment failed"
        PLACED = "placed", "Placed"
        SHIPPED = "shipped", "Shipped"
        DELIVERED = "delivered", "Delivered"
        CANCELLED = "cancelled", "Cancelled"
        CANCELLATION_REQUESTED = "cancellation_requested", "Cancellation requested"
        RETURN_REQUESTED = "return_requested", "Return requested"
        REFUNDED = "refunded", "Refunded"

    class PaymentMethod(models.TextChoices):
        COD = "cod", "Cash on delivery"
        RAZORPAY = "razorpay", "Card / UPI (Razorpay)"

    class DeliveryOption(models.TextChoices):
        STANDARD = "standard", "Standard delivery (3–5 days) — Free"
        EXPRESS = "express", "Express delivery (1–2 days) — ₹99"

    number = models.CharField(max_length=20, unique=True, editable=False)
    checkout_token = models.UUIDField(null=True, blank=True, unique=True, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="orders")
    email = models.EmailField()
    full_name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20)
    address_line1 = models.CharField(max_length=160)
    address_line2 = models.CharField(max_length=160, blank=True)
    city = models.CharField(max_length=80)
    state = models.CharField(max_length=80)
    postal_code = models.CharField(max_length=20)
    delivery_option = models.CharField(max_length=30, choices=DeliveryOption.choices, default=DeliveryOption.STANDARD)
    payment_method = models.CharField(max_length=20, choices=PaymentMethod.choices)
    payment_status = models.CharField(max_length=30, default="pending")
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.PLACED)
    coupon = models.ForeignKey("Coupon", null=True, blank=True, on_delete=models.SET_NULL, related_name="orders")
    coupon_code = models.CharField(max_length=40, blank=True)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    inventory_deducted = models.BooleanField(default=False)
    inventory_restored = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = f"IK{uuid4().hex[:10].upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.number


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, null=True, on_delete=models.SET_NULL)
    variant = models.ForeignKey(ProductVariant, null=True, blank=True, on_delete=models.SET_NULL)
    product_name = models.CharField(max_length=180)
    variant_label = models.CharField(max_length=100, blank=True)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)

    @property
    def total(self):
        return self.quantity * self.unit_price


class Review(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="reviews")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    title = models.CharField(max_length=120)
    body = models.TextField()
    is_approved = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["product", "user"], name="one_review_per_product_user")]
        ordering = ["-created_at"]


class WishlistItem(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wishlist_items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="wishlisted_by")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "product"], name="one_wishlist_item_per_product_user")]
        ordering = ["-created_at"]


class SavedForLaterItem(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_for_later_items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    variant = models.ForeignKey(ProductVariant, null=True, blank=True, on_delete=models.SET_NULL)
    quantity = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class Coupon(models.Model):
    class DiscountType(models.TextChoices):
        PERCENT = "percent", "Percentage"
        FIXED = "fixed", "Fixed amount"

    code = models.CharField(max_length=40, unique=True)
    description = models.CharField(max_length=180, blank=True)
    discount_type = models.CharField(max_length=10, choices=DiscountType.choices, default=DiscountType.PERCENT)
    value = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    minimum_order_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    maximum_discount_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    usage_limit = models.PositiveIntegerField(null=True, blank=True)
    usage_limit_per_user = models.PositiveIntegerField(null=True, blank=True)
    starts_at = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return self.code

    def is_valid_for(self, subtotal, user=None):
        now = timezone.now()
        if not self.is_active or self.starts_at > now or (self.ends_at and self.ends_at < now):
            return False, "This coupon is not active."
        if subtotal < self.minimum_order_amount:
            return False, f"This coupon requires an order of at least ₹{self.minimum_order_amount}."
        redemptions = self.redemptions.count()
        if self.usage_limit is not None and redemptions >= self.usage_limit:
            return False, "This coupon has reached its usage limit."
        if user and self.usage_limit_per_user is not None and self.redemptions.filter(user=user).count() >= self.usage_limit_per_user:
            return False, "You have already used this coupon."
        return True, ""

    def discount_for(self, subtotal):
        if self.discount_type == self.DiscountType.PERCENT:
            discount = subtotal * self.value / Decimal("100")
            if self.maximum_discount_amount:
                discount = min(discount, self.maximum_discount_amount)
        else:
            discount = self.value
        return min(discount, subtotal)


class CouponRedemption(models.Model):
    coupon = models.ForeignKey(Coupon, on_delete=models.PROTECT, related_name="redemptions")
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="coupon_redemption")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)


class ProductQuestion(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="questions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    question = models.TextField()
    answer = models.TextField(blank=True)
    answered_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="answered_questions")
    is_published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    answered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class PaymentTransaction(models.Model):
    class Provider(models.TextChoices):
        RAZORPAY = "razorpay", "Razorpay"

    class Status(models.TextChoices):
        CREATED = "created", "Created"
        AUTHORIZED = "authorized", "Authorized"
        CAPTURED = "captured", "Captured"
        REFUND_PENDING = "refund_pending", "Refund pending"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"
        REFUNDED = "refunded", "Refunded"

    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="payment_transaction")
    provider = models.CharField(max_length=20, choices=Provider.choices, default=Provider.RAZORPAY)
    provider_order_id = models.CharField(max_length=100, unique=True)
    provider_payment_id = models.CharField(max_length=100, null=True, blank=True, unique=True)
    provider_refund_id = models.CharField(max_length=100, null=True, blank=True, unique=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="INR")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.CREATED)
    inventory_released = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    provider_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]


class PaymentWebhookEvent(models.Model):
    provider = models.CharField(max_length=20, default="razorpay")
    event_id = models.CharField(max_length=100, null=True, blank=True, unique=True)
    event_type = models.CharField(max_length=100)
    payload = models.JSONField(default=dict)
    processed_at = models.DateTimeField(auto_now_add=True)


class ProductView(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="product_views")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    session_key = models.CharField(max_length=40, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["product", "created_at"]), models.Index(fields=["session_key", "created_at"])]


class OrderRequest(models.Model):
    class RequestType(models.TextChoices):
        CANCELLATION = "cancellation", "Cancellation"
        RETURN = "return", "Return"

    class Reason(models.TextChoices):
        CHANGED_MIND = "changed_mind", "Changed my mind"
        DAMAGED = "damaged", "Item arrived damaged"
        WRONG_ITEM = "wrong_item", "Wrong item received"
        NOT_AS_DESCRIBED = "not_as_described", "Not as described"
        DELAYED = "delayed", "Delivery delayed"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        REQUESTED = "requested", "Requested"
        APPROVED = "approved", "Approved"
        REFUND_PENDING = "refund_pending", "Refund pending"
        REJECTED = "rejected", "Rejected"
        REFUNDED = "refunded", "Refunded"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="requests")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="order_requests")
    request_type = models.CharField(max_length=20, choices=RequestType.choices)
    reason = models.CharField(max_length=30, choices=Reason.choices)
    note = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.REQUESTED)
    admin_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]


class Shipment(models.Model):
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="shipment")
    carrier = models.CharField(max_length=80, blank=True)
    tracking_number = models.CharField(max_length=100, blank=True)
    tracking_url = models.URLField(blank=True)
    estimated_delivery = models.DateField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Shipment for {self.order.number}"


class ShipmentEvent(models.Model):
    shipment = models.ForeignKey(Shipment, on_delete=models.CASCADE, related_name="events")
    status = models.CharField(max_length=100)
    location = models.CharField(max_length=100, blank=True)
    detail = models.CharField(max_length=250, blank=True)
    occurred_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-occurred_at"]


class NotificationLog(models.Model):
    class Channel(models.TextChoices):
        EMAIL = "email", "Email"
        SMS = "sms", "SMS"

    order = models.ForeignKey(Order, null=True, blank=True, on_delete=models.CASCADE, related_name="notification_logs")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    recipient = models.CharField(max_length=254)
    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.EMAIL)
    event = models.CharField(max_length=50)
    subject = models.CharField(max_length=200, blank=True)
    message = models.TextField()
    delivery_status = models.CharField(max_length=30, default="queued")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class MarketingPreference(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="marketing_preference")
    email_promotions = models.BooleanField(default=False)
    sms_promotions = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)


class FAQ(models.Model):
    category = models.CharField(max_length=80, default="General")
    question = models.CharField(max_length=250)
    answer = models.TextField()
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["category", "sort_order", "question"]
        verbose_name = "FAQ"
        verbose_name_plural = "FAQs"


class SupportTicket(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_PROGRESS = "in_progress", "In progress"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"

    class Category(models.TextChoices):
        ORDER = "order", "Order"
        PAYMENT = "payment", "Payment"
        RETURN = "return", "Return"
        PRODUCT = "product", "Product"
        OTHER = "other", "Other"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="support_tickets")
    order = models.ForeignKey(Order, null=True, blank=True, on_delete=models.SET_NULL, related_name="support_tickets")
    subject = models.CharField(max_length=180)
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.OTHER)
    message = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"#{self.pk} — {self.subject}"


class SupportTicketReply(models.Model):
    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name="replies")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
