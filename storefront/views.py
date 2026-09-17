from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from difflib import get_close_matches
import hashlib
import json
import logging
from uuid import uuid4

import razorpay
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import User
from django.conf import settings
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Avg, Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .cart import Cart
from .forms import AddressForm, CheckoutForm, MarketingPreferenceForm, OrderRequestForm, OTPVerificationForm, ProductQuestionForm, ReviewForm, SignUpForm, SupportTicketForm
from .models import Address, Category, Coupon, CouponRedemption, FAQ, MarketingPreference, Order, OrderItem, OrderRequest, PaymentTransaction, PaymentWebhookEvent, Product, ProductQuestion, ProductVariant, ProductView, Review, SavedForLaterItem, Shipment, SupportTicket, WishlistItem
from .payments.razorpay_links import PaymentLinkError, cancel_payment_link, create_payment_link, verify_payment_link_signature
from .ratelimit import rate_limit
from .services import calculate_cart_quote, customers_also_viewed, deduct_order_inventory, fail_or_cancel_payment, frequently_bought_together, mark_payment_captured, notify_order_email, restore_order_inventory
from django.contrib.auth import views as auth_views

logger = logging.getLogger(__name__)


@require_GET
def health_check(request):
    from django.db import connection
    try:
        connection.ensure_connection()
    except Exception:
        logger.exception("Health check failed: database connection unavailable.")
        return HttpResponse("unavailable", status=503)
    return HttpResponse("ok", status=200)


class IKartPasswordResetView(auth_views.PasswordResetView):
    def form_valid(self, form):
        logger = logging.getLogger(__name__)
        if not settings.SITE_URL or not isinstance(settings.SITE_URL, str):
            logger.error(f"SITE_URL is not properly configured: {settings.SITE_URL}")
            messages.error(self.request, "Password reset is temporarily unavailable. Please try again later.")
            return self.form_invalid(form)

        site_url = settings.SITE_URL.rstrip("/")
        if not site_url.startswith(("http://", "https://")):
            logger.error(f"SITE_URL must start with http:// or https://: {site_url}")
            messages.error(self.request, "Password reset is temporarily unavailable. Please try again later.")
            return self.form_invalid(form)

        try:
            form.save(
                domain_override=site_url.replace("https://", "").replace("http://", ""),
                use_https=site_url.startswith("https://"),
                token_generator=self.token_generator,
                from_email=self.from_email,
                email_template_name=self.email_template_name,
                subject_template_name=self.subject_template_name,
                request=self.request,
                html_email_template_name=self.html_email_template_name,
                extra_email_context=None,
            )
        except Exception as e:
            logger.exception(f"Failed to send password reset email: {e}")
            messages.error(self.request, "Failed to send password reset email. Please try again later.")
            return self.form_invalid(form)

        return redirect(self.get_success_url())


def home(request):
    return render(request, "storefront/home.html", {
        "featured": Product.objects.filter(is_active=True, is_featured=True)[:8],
        "categories": Category.objects.filter(parent__isnull=True)[:8],
    })


def product_list(request, category_slug=None):
    products = Product.objects.filter(is_active=True).select_related("category").prefetch_related("images").annotate(
        rating_value=Avg("reviews__rating", filter=Q(reviews__is_approved=True)), review_count=Count("reviews", filter=Q(reviews__is_approved=True)),
    )
    category = None
    if category_slug:
        category = get_object_or_404(Category, slug=category_slug)
        products = products.filter(Q(category=category) | Q(category__parent=category))
    query = request.GET.get("q", "").strip()
    typo_suggestions = []
    if query:
        searched_products = products.filter(Q(name__icontains=query) | Q(description__icontains=query) | Q(brand__icontains=query))
        if not searched_products.exists():
            names = list(Product.objects.filter(is_active=True).values_list("name", flat=True))
            typo_suggestions = get_close_matches(query, names, n=3, cutoff=0.55)
            if typo_suggestions:
                searched_products = products.filter(name__in=typo_suggestions)
        products = searched_products
    for parameter, lookup in (("min_price", "price__gte"), ("max_price", "price__lte")):
        raw_value = request.GET.get(parameter, "").strip()
        if raw_value:
            try:
                value = Decimal(raw_value)
                if value >= 0:
                    products = products.filter(**{lookup: value})
            except (InvalidOperation, ValueError):
                pass
    brand = request.GET.get("brand", "").strip()
    if brand:
        products = products.filter(brand__iexact=brand)
    try:
        rating_min = Decimal(request.GET.get("rating", ""))
        if Decimal("0") <= rating_min <= Decimal("5"):
            products = products.filter(rating_value__gte=rating_min)
    except (InvalidOperation, ValueError):
        pass
    if request.GET.get("discount"):
        products = products.filter(compare_at_price__gt=F("price"))
    ordering = request.GET.get("sort", "newest")
    products = products.order_by({"price_low": "price", "price_high": "-price", "newest": "-created_at", "popular": "-review_count", "rating": "-rating_value"}.get(ordering, "-created_at"))
    brands = Product.objects.filter(is_active=True).exclude(brand="").values_list("brand", flat=True).distinct().order_by("brand")
    paginator = Paginator(products, 24)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "storefront/product_list.html", {"products": page_obj, "page_obj": page_obj, "categories": Category.objects.filter(parent__isnull=True), "current_category": category, "brands": brands, "typo_suggestions": typo_suggestions})


def search_autocomplete(request):
    query = request.GET.get("q", "").strip()
    if len(query) < 2:
        return JsonResponse({"results": []})
    matches = Product.objects.filter(is_active=True).filter(Q(name__icontains=query) | Q(brand__icontains=query)).values("name", "slug", "price")[:8]
    return JsonResponse({"results": list(matches)})


def product_detail(request, slug):
    product = get_object_or_404(Product.objects.prefetch_related("images", "variants", "reviews__user"), slug=slug, is_active=True)
    if not request.session.session_key:
        request.session.create()
    ProductView.objects.create(product=product, user=request.user if request.user.is_authenticated else None, session_key=request.session.session_key)
    is_wishlisted = request.user.is_authenticated and WishlistItem.objects.filter(user=request.user, product=product).exists()
    return render(request, "storefront/product_detail.html", {
        "product": product, "review_form": ReviewForm(), "question_form": ProductQuestionForm(),
        "is_wishlisted": is_wishlisted, "frequently_bought": frequently_bought_together(product),
        "also_viewed": customers_also_viewed(product),
    })


@require_POST
def add_to_cart(request, product_id):
    product = get_object_or_404(Product, id=product_id, is_active=True)
    variant_id = request.POST.get("variant")
    variant = product.variants.filter(id=variant_id).first() if variant_id else None
    available = variant.stock if variant else product.stock
    try:
        quantity = int(request.POST.get("quantity", 1))
    except (TypeError, ValueError):
        quantity = 0
    if quantity < 1:
        messages.error(request, "Choose a valid quantity.")
        return redirect(product.get_absolute_url())
    cart = Cart(request)
    key = f"{product.id}:{variant.id if variant else 0}"
    current_quantity = cart.data.get(key, {}).get("quantity", 0)
    if available < current_quantity + quantity:
        messages.error(request, "That quantity is not currently in stock.")
        return redirect(product.get_absolute_url())
    cart.add(product, quantity, variant)
    messages.success(request, f"{product.name} was added to your cart.")
    return redirect(request.POST.get("next") or "storefront:cart")


def cart_detail(request):
    cart = Cart(request)
    quote = calculate_cart_quote(cart, request.user, coupon_code=cart.coupon_code)
    return render(request, "storefront/cart.html", {"cart": cart, "quote": quote})


def _update_cart_item(cart, key, raw_quantity):
    try:
        quantity = int(raw_quantity)
    except (TypeError, ValueError):
        return "Enter a whole number for quantity."
    if key not in cart.data:
        return "This cart item no longer exists."
    if quantity < 0:
        return "Quantity cannot be negative."
    if quantity == 0:
        cart.remove(key)
        return ""
    item = cart.data[key]
    product = Product.objects.filter(id=item["product_id"], is_active=True).first()
    variant = ProductVariant.objects.filter(id=item["variant_id"], product=product).first() if item["variant_id"] and product else None
    if item["variant_id"] and not variant:
        return "This product option is no longer available."
    available = variant.stock if variant else (product.stock if product else 0)
    if not product or quantity > available:
        return "Requested quantity is no longer in stock."
    cart.update(key, quantity)
    return ""


@require_POST
def update_cart(request):
    cart = Cart(request)
    errors = []
    for key, quantity in request.POST.items():
        if key.startswith("qty_"):
            error = _update_cart_item(cart, key[4:], quantity)
            if error:
                errors.append(error)
    if errors:
        messages.error(request, errors[0])
    else:
        messages.success(request, "Your cart has been updated.")
    return redirect("storefront:cart")


@require_POST
def update_cart_quote(request):
    cart = Cart(request)
    error = _update_cart_item(cart, request.POST.get("key", ""), request.POST.get("quantity", ""))
    if error:
        return JsonResponse({"ok": False, "error": error}, status=400)
    quote = calculate_cart_quote(cart, request.user, request.POST.get("delivery_option", Order.DeliveryOption.STANDARD), cart.coupon_code)
    if quote.coupon_error and cart.coupon_code:
        cart.set_coupon("")
    return JsonResponse({"ok": True, **quote.as_dict(), "cart_count": cart.count})


@require_POST
def update_coupon_quote(request):
    cart = Cart(request)
    code = request.POST.get("coupon_code", "").strip().upper()
    quote = calculate_cart_quote(cart, request.user, request.POST.get("delivery_option", Order.DeliveryOption.STANDARD), code)
    if quote.coupon_error:
        cart.set_coupon("")
        return JsonResponse({"ok": False, **quote.as_dict()}, status=400)
    cart.set_coupon(quote.coupon.code if quote.coupon else "")
    return JsonResponse({"ok": True, **quote.as_dict()})


@require_POST
def remove_from_cart(request, key):
    Cart(request).remove(key)
    return redirect("storefront:cart")


@login_required
def wishlist(request):
    items = request.user.wishlist_items.select_related("product").prefetch_related("product__images")
    return render(request, "storefront/wishlist.html", {"items": items})


@login_required
@require_POST
def toggle_wishlist(request, product_id):
    product = get_object_or_404(Product, id=product_id, is_active=True)
    item = WishlistItem.objects.filter(user=request.user, product=product).first()
    if item:
        item.delete()
        messages.info(request, f"{product.name} was removed from your wishlist.")
    else:
        WishlistItem.objects.create(user=request.user, product=product)
        messages.success(request, f"{product.name} was saved to your wishlist.")
    return redirect(request.POST.get("next") or product.get_absolute_url())


@login_required
@require_POST
def save_cart_item_for_later(request, key):
    cart = Cart(request)
    item = cart.data.get(key)
    if not item:
        raise Http404
    product = get_object_or_404(Product, id=item["product_id"])
    variant = ProductVariant.objects.filter(id=item["variant_id"]).first() if item["variant_id"] else None
    saved = SavedForLaterItem.objects.filter(user=request.user, product=product, variant=variant).first()
    if saved:
        saved.quantity += item["quantity"]
        saved.save(update_fields=["quantity"])
    else:
        SavedForLaterItem.objects.create(user=request.user, product=product, variant=variant, quantity=item["quantity"])
    cart.remove(key)
    messages.success(request, "Item saved for later.")
    return redirect("storefront:cart")


@login_required
def saved_for_later(request):
    items = request.user.saved_for_later_items.select_related("product", "variant").prefetch_related("product__images")
    return render(request, "storefront/saved_for_later.html", {"items": items})


@login_required
@require_POST
def move_saved_item_to_cart(request, item_id):
    item = get_object_or_404(SavedForLaterItem, id=item_id, user=request.user)
    available = item.variant.stock if item.variant else item.product.stock
    if not available:
        messages.error(request, "This item is currently out of stock.")
    else:
        Cart(request).add(item.product, min(item.quantity, available), item.variant)
        item.delete()
        messages.success(request, "Item moved to your cart.")
    return redirect("storefront:saved_for_later")


@login_required
@require_POST
def remove_saved_item(request, item_id):
    get_object_or_404(SavedForLaterItem, id=item_id, user=request.user).delete()
    return redirect("storefront:saved_for_later")


@login_required
def addresses(request):
    form = AddressForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        address = form.save(commit=False)
        address.user = request.user
        if address.is_default:
            request.user.addresses.update(is_default=False)
        address.save()
        messages.success(request, "Address saved.")
        return redirect("storefront:addresses")
    return render(request, "storefront/addresses.html", {"addresses": request.user.addresses.order_by("-is_default", "-id"), "form": form})


@login_required
def edit_address(request, address_id):
    address = get_object_or_404(Address, id=address_id, user=request.user)
    form = AddressForm(request.POST or None, instance=address)
    if request.method == "POST" and form.is_valid():
        address = form.save(commit=False)
        if address.is_default:
            request.user.addresses.exclude(id=address.id).update(is_default=False)
        address.save()
        messages.success(request, "Address updated.")
        return redirect("storefront:addresses")
    return render(request, "storefront/address_form.html", {"form": form, "address": address})


@login_required
@require_POST
def delete_address(request, address_id):
    get_object_or_404(Address, id=address_id, user=request.user).delete()
    messages.info(request, "Address deleted.")
    return redirect("storefront:addresses")


def _new_checkout_token(request):
    token = uuid4()
    request.session["checkout_token"] = str(token)
    return token


def _remember_order(request, number):
    """Store order number in session with timestamp for access control and expiry."""
    orders = request.session.get("recent_order_numbers", {})
    if not isinstance(orders, dict):
        orders = {}
    now = timezone.now()
    orders[number] = now.isoformat()
    filtered = {k: v for k, v in orders.items() if k != number}
    filtered[number] = now.isoformat()
    request.session["recent_order_numbers"] = dict(list(filtered.items())[-10:])


def _can_access_order(request, order):
    """Check if guest/authenticated user can view this order via session or user auth."""
    if order.user and request.user.is_authenticated and order.user == request.user:
        return True
    orders = request.session.get("recent_order_numbers", {})
    if not isinstance(orders, dict):
        return False
    if order.number not in orders:
        return False
    order_time = datetime.fromisoformat(orders[order.number])
    is_expired = timezone.now() - order_time > timedelta(hours=24)
    return not is_expired


def _razorpay_client():
    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        return None
    return razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))


def _create_order_from_cart(form, cart, quote, checkout_token, payment_pending=False):
    """Create one local order from a server-side quote and reserve stock atomically."""
    with transaction.atomic():
        coupon = None
        if quote.coupon:
            coupon = Coupon.objects.select_for_update().get(pk=quote.coupon.pk)
            valid, error = coupon.is_valid_for(quote.subtotal, form.user if getattr(form.user, "is_authenticated", False) else None)
            if not valid:
                raise ValueError(error)
            quote = calculate_cart_quote(cart, form.user, form.cleaned_data["delivery_option"], coupon.code)
            if quote.coupon_error:
                raise ValueError(quote.coupon_error)
        order = form.save(commit=False)
        order.user = form.user if getattr(form.user, "is_authenticated", False) else None
        order.checkout_token = checkout_token
        order.subtotal = quote.subtotal
        order.delivery_fee = quote.delivery_fee
        order.tax_amount = quote.tax_amount
        order.coupon = coupon
        order.coupon_code = coupon.code if coupon else ""
        order.discount_amount = quote.discount_amount
        order.total = quote.total
        order.status = Order.Status.PAYMENT_PENDING if payment_pending else Order.Status.PLACED
        order.payment_status = "initiated" if payment_pending else "pending"
        order.save()
        for item in cart:
            OrderItem.objects.create(
                order=order, product=item["product"], variant=item["variant"], product_name=item["product"].name,
                variant_label=item["variant"].label if item["variant"] else "", quantity=item["quantity"], unit_price=item["price"],
            )
        order = deduct_order_inventory(order)
        if coupon:
            CouponRedemption.objects.create(coupon=coupon, order=order, user=order.user, discount_amount=quote.discount_amount)
        return order


@rate_limit("checkout", limit=30, period_seconds=300)
def checkout(request):
    cart = Cart(request)
    if not cart.count:
        messages.info(request, "Your cart is empty.")
        return redirect("storefront:product_list")
    session_token = request.session.get("checkout_token")
    checkout_token = session_token or _new_checkout_token(request)
    if request.method == "POST":
        form = CheckoutForm(request.POST, user=request.user)
        if form.is_valid():
            token = form.cleaned_data["checkout_token"]
            if str(token) != request.session.get("checkout_token"):
                form.add_error(None, "This checkout has expired. Please review your cart and try again.")
                return render(request, "storefront/checkout.html", {"cart": cart, "form": form, "quote": calculate_cart_quote(cart, request.user, form.cleaned_data["delivery_option"], form.cleaned_data["coupon_code"])})
            existing_order = Order.objects.filter(checkout_token=token).first()
            if existing_order:
                _remember_order(request, existing_order.number)
                payment = getattr(existing_order, "payment_transaction", None)
                if payment and payment.status == PaymentTransaction.Status.CREATED:
                    payment_link_url = payment.provider_payload.get("payment_link_url")
                    if payment_link_url:
                        return redirect(payment_link_url)
                    return redirect("storefront:payment_checkout", number=existing_order.number)
                return redirect("storefront:order_confirmation", number=existing_order.number)
            coupon_code = form.cleaned_data["coupon_code"].strip().upper() or cart.coupon_code
            quote = calculate_cart_quote(cart, request.user, form.cleaned_data["delivery_option"], coupon_code)
            if quote.coupon_error:
                form.add_error("coupon_code", quote.coupon_error)
            elif form.cleaned_data["payment_method"] == Order.PaymentMethod.RAZORPAY and not _razorpay_client():
                form.add_error("payment_method", "Online payments are temporarily unavailable. Please choose cash on delivery.")
            else:
                try:
                    is_online = form.cleaned_data["payment_method"] == Order.PaymentMethod.RAZORPAY
                    order = _create_order_from_cart(form, cart, quote, token, payment_pending=is_online)
                except ValueError as error:
                    form.add_error(None, str(error))
                else:
                    _remember_order(request, order.number)
                    if not is_online:
                        cart.clear()
                        request.session.pop("checkout_token", None)
                        notify_order_email(order, "order_placed", f"Order {order.number} confirmed", f"Thanks for your order. Total: ₹{order.total}")
                        return redirect("storefront:order_confirmation", number=order.number)
                    try:
                        callback_url = request.build_absolute_uri(reverse("storefront:razorpay_payment_link_callback", args=[order.number]))
                        payment_link = create_payment_link(_razorpay_client(), order, callback_url)
                        with transaction.atomic():
                            PaymentTransaction.objects.create(
                                order=order,
                                provider_order_id=payment_link.get("order_id") or None,
                                provider_payment_link_id=payment_link["id"],
                                amount=order.total,
                                currency=settings.RAZORPAY_CURRENCY,
                                provider_payload={
                                    "payment_link_id": payment_link["id"],
                                    "payment_link_url": payment_link["short_url"],
                                    "payment_link_status": payment_link.get("status", "created"),
                                    "payment_link_reference_id": payment_link.get("reference_id") or order.number,
                                },
                            )
                    except Exception:
                        logger.exception("Razorpay hosted payment link creation failed for order %s", order.number)
                        with transaction.atomic():
                            order = Order.objects.select_for_update().get(pk=order.pk)
                            restore_order_inventory(order)
                            CouponRedemption.objects.filter(order=order).delete()
                            order.status = Order.Status.PAYMENT_FAILED
                            order.payment_status = "failed"
                            order.checkout_token = None
                            order.save(update_fields=["status", "payment_status", "checkout_token", "updated_at"])
                        fresh_token = _new_checkout_token(request)
                        form.data = form.data.copy()
                        form.data["checkout_token"] = str(fresh_token)
                        form.add_error("payment_method", "Could not start the payment. No payment was taken; please try again.")
                    else:
                        return redirect(payment_link["short_url"])
    else:
        form = CheckoutForm(initial={"email": request.user.email, "coupon_code": cart.coupon_code, "checkout_token": checkout_token} if request.user.is_authenticated else {"coupon_code": cart.coupon_code, "checkout_token": checkout_token}, user=request.user)
    quote = calculate_cart_quote(cart, request.user, form.data.get("delivery_option", Order.DeliveryOption.STANDARD) if form.is_bound else Order.DeliveryOption.STANDARD, form.data.get("coupon_code", cart.coupon_code) if form.is_bound else cart.coupon_code)
    return render(request, "storefront/checkout.html", {"cart": cart, "form": form, "quote": quote})


def payment_checkout(request, number):
    order = get_object_or_404(Order, number=number)
    if not _can_access_order(request, order):
        raise Http404
    payment = get_object_or_404(PaymentTransaction, order=order)
    if payment.status == PaymentTransaction.Status.CAPTURED:
        return redirect("storefront:order_confirmation", number=order.number)
    if payment.status == PaymentTransaction.Status.AUTHORIZED:
        messages.info(request, "Your payment is being confirmed. Please wait for the order status update.")
        return redirect("storefront:order_confirmation", number=order.number)
    if payment.status != PaymentTransaction.Status.CREATED:
        messages.error(request, "This payment attempt is no longer active. Please place a new order.")
        return redirect("storefront:cart")
    payment_link_url = payment.provider_payload.get("payment_link_url")
    if not payment_link_url:
        messages.error(request, "This legacy payment attempt cannot be resumed. Please cancel it and start checkout again.")
        return redirect("storefront:cart")
    return render(request, "storefront/payment_link_checkout.html", {"order": order, "payment_link_url": payment_link_url})


@require_GET
def razorpay_payment_link_callback(request, number):
    """Verify the signed hosted-link return and finalise only a captured payment."""
    order = get_object_or_404(Order, number=number)
    payment = get_object_or_404(PaymentTransaction, order=order)
    payment_link_id = request.GET.get("razorpay_payment_link_id", "")
    reference_id = request.GET.get("razorpay_payment_link_reference_id", "")
    link_status = request.GET.get("razorpay_payment_link_status", "")
    payment_id = request.GET.get("razorpay_payment_id", "")
    signature = request.GET.get("razorpay_signature", "")
    expected_link_id = payment.provider_payment_link_id or payment.provider_payload.get("payment_link_id", "")
    if (
        payment_link_id != expected_link_id
        or reference_id != order.number
        or link_status != "paid"
        or not payment_id
        or not signature
        or not verify_payment_link_signature(payment_link_id, reference_id, link_status, payment_id, signature)
    ):
        logger.warning("Invalid Razorpay payment link callback for order %s", order.number)
        messages.error(request, "We could not verify this payment return. Please wait for the payment status update.")
        return redirect("storefront:order_confirmation", number=order.number)
    if payment.status == PaymentTransaction.Status.CAPTURED:
        _remember_order(request, order.number)
        return redirect("storefront:order_confirmation", number=order.number)
    client = _razorpay_client()
    try:
        provider_payment = client.payment.fetch(payment_id)
        fetched_order_id = provider_payment.get("order_id")
        if (
            (payment.provider_order_id and fetched_order_id != payment.provider_order_id)
            or int(provider_payment.get("amount", 0)) != int(payment.amount * 100)
            or provider_payment.get("currency") != payment.currency
        ):
            raise PaymentLinkError("Payment details did not match the order.")
        if not payment.provider_order_id and fetched_order_id:
            PaymentTransaction.objects.filter(pk=payment.pk, provider_order_id__isnull=True).update(provider_order_id=fetched_order_id)
            payment.provider_order_id = fetched_order_id
        if provider_payment.get("status") == "authorized":
            provider_payment = client.payment.capture(payment_id, int(payment.amount * 100), {"currency": payment.currency})
    except PaymentLinkError:
        logger.warning("Razorpay payment link callback did not match order %s", order.number)
        messages.error(request, "Payment details did not match this order. Please contact support.")
        return redirect("storefront:order_confirmation", number=order.number)
    except Exception:
        logger.exception("Razorpay payment link callback fetch failed for order %s", order.number)
        messages.info(request, "Your payment is being confirmed. We will update the order shortly.")
        _remember_order(request, order.number)
        return redirect("storefront:order_confirmation", number=order.number)
    if provider_payment.get("status") != "captured":
        messages.info(request, "Your payment is awaiting capture. We will update the order shortly.")
        _remember_order(request, order.number)
        return redirect("storefront:order_confirmation", number=order.number)
    order = mark_payment_captured(payment, payment_id, provider_payment)
    Cart(request).clear()
    request.session.pop("checkout_token", None)
    _remember_order(request, order.number)
    notify_order_email(order, "payment_captured", f"Order {order.number} confirmed", f"Your payment was successful. Total paid: ₹{order.total}")
    return redirect("storefront:order_confirmation", number=order.number)


@require_POST
def verify_razorpay_payment(request, number):
    order = get_object_or_404(Order, number=number)
    if not _can_access_order(request, order):
        raise Http404
    payment = get_object_or_404(PaymentTransaction, order=order)
    if payment.status == PaymentTransaction.Status.CAPTURED:
        return redirect("storefront:order_confirmation", number=order.number)
    provider_order_id = request.POST.get("razorpay_order_id", "")
    provider_payment_id = request.POST.get("razorpay_payment_id", "")
    signature = request.POST.get("razorpay_signature", "")
    if provider_order_id != payment.provider_order_id or not provider_payment_id or not signature:
        fail_or_cancel_payment(payment, PaymentTransaction.Status.FAILED, {"reason": "invalid_callback"})
        messages.error(request, "Payment verification failed. No order has been placed.")
        return redirect("storefront:cart")
    client = _razorpay_client()
    if not client:
        messages.error(request, "Online payment verification is unavailable. Please contact support with your order number.")
        return redirect("storefront:order_confirmation", number=order.number)
    try:
        client.utility.verify_payment_signature({
            "razorpay_order_id": payment.provider_order_id,
            "razorpay_payment_id": provider_payment_id,
            "razorpay_signature": signature,
        })
    except razorpay.errors.SignatureVerificationError:
        fail_or_cancel_payment(payment, PaymentTransaction.Status.FAILED, {"reason": "invalid_signature"})
        request.session.pop("checkout_token", None)
        messages.error(request, "Payment verification failed. No payment was taken.")
        return redirect("storefront:cart")
    except Exception:
        messages.error(request, "We could not verify this payment yet. Please wait for the order status update.")
        return redirect("storefront:order_confirmation", number=order.number)
    try:
        provider_payment = client.payment.fetch(provider_payment_id)
        expected_amount = int(payment.amount * 100)
        if (
            provider_payment.get("order_id") != payment.provider_order_id
            or int(provider_payment.get("amount", 0)) != expected_amount
            or provider_payment.get("currency") != payment.currency
        ):
            raise ValueError("Payment details did not match the order.")
        if provider_payment.get("status") == "authorized":
            provider_payment = client.payment.capture(provider_payment_id, int(payment.amount * 100), {"currency": payment.currency})
    except ValueError as error:
        fail_or_cancel_payment(payment, PaymentTransaction.Status.FAILED, {"reason": "payment_mismatch"})
        request.session.pop("checkout_token", None)
        messages.error(request, str(error))
        return redirect("storefront:cart")
    except Exception:
        # A network/API failure after a valid signature is not proof of failure.
        # Keep stock reserved and let Razorpay's signed webhook reconcile it.
        with transaction.atomic():
            payment = PaymentTransaction.objects.select_for_update().get(pk=payment.pk)
            if payment.status != PaymentTransaction.Status.CAPTURED:
                payment.status = PaymentTransaction.Status.AUTHORIZED
                payment.provider_payment_id = provider_payment_id
                payment.save(update_fields=["status", "provider_payment_id", "updated_at"])
        messages.info(request, "Your payment is being confirmed. We will update the order shortly.")
        return redirect("storefront:order_confirmation", number=order.number)
    if provider_payment.get("status") == "failed":
        fail_or_cancel_payment(payment, PaymentTransaction.Status.FAILED, provider_payment)
        request.session.pop("checkout_token", None)
        messages.error(request, "Payment failed. Your cart is still available to try again.")
        return redirect("storefront:cart")
    if provider_payment.get("status") != "captured":
        with transaction.atomic():
            payment = PaymentTransaction.objects.select_for_update().get(pk=payment.pk)
            if payment.status != PaymentTransaction.Status.CAPTURED:
                payment.status = PaymentTransaction.Status.AUTHORIZED
                payment.provider_payment_id = provider_payment_id
                payment.provider_payload = provider_payment
                payment.save(update_fields=["status", "provider_payment_id", "provider_payload", "updated_at"])
        messages.info(request, "Your payment is authorised and awaiting capture. We will confirm it shortly.")
        return redirect("storefront:order_confirmation", number=order.number)
    order = mark_payment_captured(payment, provider_payment_id, provider_payment)
    cart = Cart(request)
    cart.clear()
    request.session.pop("checkout_token", None)
    _remember_order(request, order.number)
    if order.payment_status == "paid":
        notify_order_email(order, "payment_captured", f"Order {order.number} confirmed", f"Your payment was successful. Total paid: ₹{order.total}")
    else:
        notify_order_email(order, "payment_review", f"Payment received for order {order.number}", "Your payment was received and is being reviewed because the item is no longer available.")
    return redirect("storefront:order_confirmation", number=order.number)


@require_POST
def cancel_razorpay_payment(request, number):
    order = get_object_or_404(Order, number=number)
    if not _can_access_order(request, order):
        raise Http404
    payment = get_object_or_404(PaymentTransaction, order=order)
    if payment.status == PaymentTransaction.Status.CAPTURED:
        return redirect("storefront:order_confirmation", number=order.number)
    payment_link_id = payment.provider_payload.get("payment_link_id")
    if payment_link_id:
        try:
            cancel_payment_link(_razorpay_client(), payment_link_id)
        except Exception:
            logger.exception("Razorpay hosted payment link cancellation failed for order %s", order.number)
            messages.error(request, "We could not safely cancel the Razorpay payment page. Please try again shortly.")
            return redirect("storefront:payment_checkout", number=order.number)
    fail_or_cancel_payment(payment, PaymentTransaction.Status.CANCELLED, {"reason": "customer_cancelled"})
    request.session.pop("checkout_token", None)
    messages.info(request, "Payment was cancelled and reserved stock was released.")
    return redirect("storefront:cart")


@require_POST
def razorpay_checkout_event(request, number):
    """Persist a small, non-sensitive browser diagnostic without changing payment state."""
    order = get_object_or_404(Order, number=number)
    if not _can_access_order(request, order):
        raise Http404
    payment = get_object_or_404(PaymentTransaction, order=order)
    event = request.POST.get("event", "")[:40]
    if event not in {"opened", "dismissed", "failed", "client_error"}:
        return HttpResponse(status=400)
    diagnostic = {"event": event, "at": timezone.now().isoformat()}
    for field, maximum_length in (("code", 100), ("source", 100), ("step", 100), ("reason", 100), ("description", 300), ("payment_id", 100)):
        value = request.POST.get(field, "").strip()
        if value:
            diagnostic[field] = value[:maximum_length]
    with transaction.atomic():
        payment = PaymentTransaction.objects.select_for_update().get(pk=payment.pk)
        payload = dict(payment.provider_payload or {})
        diagnostics = list(payload.get("checkout_diagnostics", []))[-9:]
        diagnostics.append(diagnostic)
        payload["checkout_diagnostics"] = diagnostics
        payment.provider_payload = payload
        payment.save(update_fields=["provider_payload", "updated_at"])
    logger.info("Razorpay checkout event %s for order %s", event, order.number)
    return HttpResponse(status=204)


def _apply_refund_webhook(payment, refund, succeeded):
    """Apply a signed Razorpay refund state without claiming a pending refund is final."""
    with transaction.atomic():
        payment = PaymentTransaction.objects.select_for_update().select_related("order").get(pk=payment.pk)
        order = payment.order
        if not succeeded and payment.status == PaymentTransaction.Status.REFUNDED:
            return order
        if refund.get("id"):
            payment.provider_refund_id = refund["id"]
        payment.provider_payload = {**payment.provider_payload, "refund": refund}
        if succeeded:
            payment.status = PaymentTransaction.Status.REFUNDED
            payment.save(update_fields=["provider_refund_id", "status", "provider_payload", "updated_at"])
            order.status = Order.Status.REFUNDED
            order.payment_status = "refunded"
            order.save(update_fields=["status", "payment_status", "updated_at"])
            OrderRequest.objects.filter(
                order=order,
                status__in=[OrderRequest.Status.APPROVED, OrderRequest.Status.REFUND_PENDING],
            ).update(status=OrderRequest.Status.REFUNDED)
            restore_order_inventory(order)
        else:
            # A failed refund leaves the original payment captured so staff can
            # safely retry it after resolving the provider-side issue.
            payment.status = PaymentTransaction.Status.CAPTURED
            payment.save(update_fields=["provider_refund_id", "status", "provider_payload", "updated_at"])
            order.payment_status = "refund_failed"
            order.save(update_fields=["payment_status", "updated_at"])
        return order


@csrf_exempt
@require_POST
def razorpay_webhook(request):
    if not settings.RAZORPAY_WEBHOOK_SECRET:
        return HttpResponse(status=400)
    signature = request.headers.get("X-Razorpay-Signature", "")
    client = _razorpay_client()
    if not client:
        return HttpResponse(status=400)
    try:
        client.utility.verify_webhook_signature(request.body.decode("utf-8"), signature, settings.RAZORPAY_WEBHOOK_SECRET)
        payload = json.loads(request.body)
    except Exception:
        logger.warning("Razorpay webhook rejected: invalid signature or malformed payload.")
        return HttpResponse(status=400)
    event_id = request.headers.get("X-Razorpay-Event-Id") or hashlib.sha256(request.body).hexdigest()
    event = payload.get("event", "")
    try:
        with transaction.atomic():
            webhook_event = PaymentWebhookEvent.objects.create(event_id=event_id, event_type=event, payload=payload)
    except IntegrityError:
        return HttpResponse(status=200)
    payload_entities = payload.get("payload", {})
    entity = payload_entities.get("payment", {}).get("entity", {})
    refund_entity = payload_entities.get("refund", {}).get("entity", {})
    payment_link_entity = payload_entities.get("payment_link", {}).get("entity", {})
    provider_order_id = entity.get("order_id") or payload.get("payload", {}).get("order", {}).get("entity", {}).get("id")
    payment = None
    if provider_order_id:
        payment = PaymentTransaction.objects.filter(provider_order_id=provider_order_id).first()
    if not payment and payment_link_entity.get("id"):
        payment = PaymentTransaction.objects.filter(provider_payment_link_id=payment_link_entity["id"]).first()
    if not payment and payment_link_entity.get("id"):
        payment = PaymentTransaction.objects.filter(provider_payload__payment_link_id=payment_link_entity["id"]).first()
    if not payment and refund_entity.get("payment_id"):
        payment = PaymentTransaction.objects.filter(provider_payment_id=refund_entity["payment_id"]).first()
    if not payment:
        return HttpResponse(status=200)
    try:
        if event in {"payment.captured", "order.paid", "payment_link.paid"}:
            if event == "payment_link.paid" and (
                payment_link_entity.get("id") != payment.provider_payload.get("payment_link_id")
                or payment_link_entity.get("reference_id") != payment.order.number
                or int(payment_link_entity.get("amount", 0)) != int(payment.amount * 100)
                or payment_link_entity.get("currency") != payment.currency
            ):
                return HttpResponse(status=200)
            if payment.status in {
                PaymentTransaction.Status.CREATED,
                PaymentTransaction.Status.AUTHORIZED,
                PaymentTransaction.Status.FAILED,
                PaymentTransaction.Status.CANCELLED,
            }:
                order = mark_payment_captured(payment, entity.get("id", ""), entity)
                if order.payment_status == "paid":
                    notify_order_email(order, "payment_captured", f"Order {order.number} confirmed", f"Your payment was successful. Total paid: ₹{order.total}")
                else:
                    notify_order_email(order, "payment_review", f"Payment received for order {order.number}", "Your payment was received and is being reviewed before fulfilment.")
        elif event == "payment.failed" and payment.status in {PaymentTransaction.Status.CREATED, PaymentTransaction.Status.AUTHORIZED}:
            order = fail_or_cancel_payment(payment, PaymentTransaction.Status.FAILED, entity)
            notify_order_email(order, "payment_failed", f"Payment failed for order {order.number}", "Your payment failed and no order was placed. You can try checkout again.")
        elif event.startswith("refund.") and (
            refund_entity.get("payment_id") != payment.provider_payment_id
            or int(refund_entity.get("amount", 0)) != int(payment.amount * 100)
            or (refund_entity.get("currency") and refund_entity["currency"] != payment.currency)
        ):
            return HttpResponse(status=200)
        elif event == "refund.created" and payment.status == PaymentTransaction.Status.CAPTURED:
            with transaction.atomic():
                payment = PaymentTransaction.objects.select_for_update().select_related("order").get(pk=payment.pk)
                payment.status = PaymentTransaction.Status.REFUND_PENDING
                payment.provider_refund_id = refund_entity.get("id") or payment.provider_refund_id
                payment.provider_payload = {**payment.provider_payload, "refund": refund_entity}
                payment.save(update_fields=["status", "provider_refund_id", "provider_payload", "updated_at"])
                payment.order.payment_status = "refund_pending"
                payment.order.save(update_fields=["payment_status", "updated_at"])
        elif event == "refund.processed":
            order = _apply_refund_webhook(payment, refund_entity, succeeded=True)
            notify_order_email(order, "refund_processed", f"Order {order.number}: refund processed", "Your refund has been processed by the payment provider.")
        elif event == "refund.failed":
            order = _apply_refund_webhook(payment, refund_entity, succeeded=False)
            notify_order_email(order, "refund_failed", f"Order {order.number}: refund needs attention", "Your refund could not be processed yet. Our support team will contact you.")
    except Exception:
        logger.exception(
            "Razorpay webhook processing failed for event_id=%s event_type=%s payment_id=%s",
            event_id, event, payment.pk,
        )
        # Delete the idempotency marker so Razorpay can retry a transient failure.
        webhook_event.delete()
        return HttpResponse(status=500)
    return HttpResponse(status=200)


def order_confirmation(request, number):
    order = get_object_or_404(Order, number=number)
    if not _can_access_order(request, order):
        raise Http404
    return render(request, "storefront/order_confirmation.html", {"order": order, "shipment": getattr(order, "shipment", None), "requests": order.requests.all()})


@login_required
def order_history(request):
    return render(request, "storefront/order_history.html", {"orders": request.user.orders.prefetch_related("items", "requests")})


@login_required
def request_order_change(request, number, request_type):
    if request_type not in {OrderRequest.RequestType.CANCELLATION, OrderRequest.RequestType.RETURN}:
        raise Http404
    order = get_object_or_404(Order, number=number, user=request.user)
    if request_type == OrderRequest.RequestType.CANCELLATION and order.status not in {Order.Status.PLACED, Order.Status.CANCELLATION_REQUESTED}:
        messages.error(request, "This order can no longer be cancelled online.")
        return redirect("storefront:order_confirmation", number=order.number)
    if request_type == OrderRequest.RequestType.RETURN and order.status not in {Order.Status.DELIVERED, Order.Status.RETURN_REQUESTED}:
        messages.error(request, "A return can be requested after delivery.")
        return redirect("storefront:order_confirmation", number=order.number)
    existing = order.requests.filter(request_type=request_type, status=OrderRequest.Status.REQUESTED).first()
    if existing:
        messages.info(request, "You already have a request in progress for this order.")
        return redirect("storefront:order_confirmation", number=order.number)
    form = OrderRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        change_request = form.save(commit=False)
        change_request.order = order
        change_request.user = request.user
        change_request.request_type = request_type
        change_request.save()
        order.status = Order.Status.CANCELLATION_REQUESTED if request_type == OrderRequest.RequestType.CANCELLATION else Order.Status.RETURN_REQUESTED
        order.save(update_fields=["status", "updated_at"])
        notify_order_email(order, f"{request_type}_requested", f"Order {order.number}: request received", f"We received your {request_type} request and will update you shortly.")
        messages.success(request, "Your request has been submitted.")
        return redirect("storefront:order_confirmation", number=order.number)
    return render(request, "storefront/order_request.html", {"form": form, "order": order, "request_type": request_type})


@rate_limit("signup", limit=10, period_seconds=600)
def signup(request):
    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            try:
                code_hash, expires_at = _send_verification_code(form.cleaned_data["email"])
            except Exception:
                form.add_error(None, "We could not send a verification email. Check the email settings and try again.")
                return render(request, "registration/signup.html", {"form": form})
            request.session["pending_registration"] = {
                "username": form.cleaned_data["username"],
                "email": form.cleaned_data["email"],
                "password_hash": make_password(form.cleaned_data["password1"]),
                "code_hash": code_hash,
                "expires_at": expires_at.isoformat(),
                "attempts": 0,
                "last_sent_at": timezone.now().isoformat(),
            }
            return redirect("storefront:verify_email")
    else:
        form = SignUpForm()
    return render(request, "registration/signup.html", {"form": form})


def _send_verification_code(email):
    """Send a raw OTP and return only its hash and expiry for session storage."""
    import secrets

    code = f"{secrets.randbelow(1_000_000):06d}"
    send_mail(
        "Your IKart verification code",
        f"Your IKart verification code is {code}. It expires in 10 minutes. Do not share this code with anyone.",
        None, [email], fail_silently=False,
    )
    return make_password(code), timezone.now() + timedelta(minutes=10)


@rate_limit("verify_email", limit=20, period_seconds=600)
def verify_email(request):
    pending = request.session.get("pending_registration")
    if not pending:
        messages.info(request, "Start by creating your account.")
        return redirect("storefront:signup")
    if request.method == "POST":
        form = OTPVerificationForm(request.POST)
        if form.is_valid():
            expires_at = datetime.fromisoformat(pending["expires_at"])
            if timezone.now() >= expires_at:
                form.add_error("code", "This code has expired. Request a new one below.")
            elif pending["attempts"] >= 5:
                form.add_error("code", "Too many attempts. Request a new code below.")
            elif check_password(form.cleaned_data["code"], pending["code_hash"]):
                if User.objects.filter(username=pending["username"]).exists() or User.objects.filter(email__iexact=pending["email"]).exists():
                    request.session.pop("pending_registration", None)
                    messages.error(request, "That username or email is already registered. Please sign in.")
                    return redirect("storefront:login")
                user = User(username=pending["username"], email=pending["email"], password=pending["password_hash"])
                user.save()
                request.session.pop("pending_registration", None)
                login(request, user)
                messages.success(request, "Your email has been verified. Welcome to IKart!")
                return redirect("storefront:home")
            else:
                pending["attempts"] += 1
                request.session["pending_registration"] = pending
                form.add_error("code", "That code is not correct.")
    else:
        form = OTPVerificationForm()
    return render(request, "registration/verify_email.html", {"form": form, "email": pending["email"]})


@require_POST
@rate_limit("resend_otp", limit=5, period_seconds=600)
def resend_verification_code(request):
    pending = request.session.get("pending_registration")
    if not pending:
        messages.info(request, "Start by creating your account.")
        return redirect("storefront:signup")
    last_sent_at = pending.get("last_sent_at")
    if last_sent_at and timezone.now() - datetime.fromisoformat(last_sent_at) < timedelta(seconds=60):
        messages.info(request, "Please wait one minute before requesting another code.")
        return redirect("storefront:verify_email")
    try:
        code_hash, expires_at = _send_verification_code(pending["email"])
    except Exception:
        messages.error(request, "We could not send a new verification email. Please try again shortly.")
        return redirect("storefront:verify_email")
    pending.update({"code_hash": code_hash, "expires_at": expires_at.isoformat(), "attempts": 0, "last_sent_at": timezone.now().isoformat()})
    request.session["pending_registration"] = pending
    messages.success(request, "A new verification code has been sent.")
    return redirect("storefront:verify_email")


@login_required
@require_POST
def add_review(request, slug):
    product = get_object_or_404(Product, slug=slug)
    form = ReviewForm(request.POST)
    if form.is_valid():
        Review.objects.update_or_create(product=product, user=request.user, defaults=form.cleaned_data)
        messages.success(request, "Thanks for reviewing this product.")
    else:
        messages.error(request, "Please provide a rating from 1 to 5 and complete the review fields.")
    return redirect(product.get_absolute_url())


@login_required
@require_POST
def add_product_question(request, slug):
    product = get_object_or_404(Product, slug=slug, is_active=True)
    form = ProductQuestionForm(request.POST)
    if form.is_valid():
        question = " ".join(form.cleaned_data["question"].split())
        recent_questions = ProductQuestion.objects.filter(
            product=product, user=request.user, created_at__gte=timezone.now() - timedelta(hours=1),
        )
        if recent_questions.filter(question__iexact=question).exists():
            messages.error(request, "You have already submitted that question.")
        elif recent_questions.count() >= 3:
            messages.error(request, "You can submit up to three questions per product each hour.")
        else:
            ProductQuestion.objects.create(product=product, user=request.user, question=question)
            messages.success(request, "Your question was submitted for moderation. We will publish an answer as soon as possible.")
    return redirect(product.get_absolute_url())


@login_required
def support_center(request):
    form = SupportTicketForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        ticket = form.save(commit=False)
        ticket.user = request.user
        ticket.save()
        messages.success(request, f"Support ticket #{ticket.id} was created.")
        return redirect("storefront:support_ticket", ticket_id=ticket.id)
    return render(request, "storefront/support.html", {
        "faqs": FAQ.objects.filter(is_active=True), "tickets": request.user.support_tickets.all(), "form": form,
    })


@login_required
def support_ticket(request, ticket_id):
    ticket = get_object_or_404(SupportTicket.objects.prefetch_related("replies__author"), id=ticket_id, user=request.user)
    return render(request, "storefront/support_ticket.html", {"ticket": ticket})


@login_required
def notification_preferences(request):
    preference, _ = MarketingPreference.objects.get_or_create(user=request.user)
    form = MarketingPreferenceForm(request.POST or None, instance=preference)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Notification preferences updated.")
        return redirect("storefront:notification_preferences")
    return render(request, "storefront/notification_preferences.html", {"form": form})


@staff_member_required
def analytics_dashboard(request):
    completed_orders = Order.objects.filter(status__in=[Order.Status.PLACED, Order.Status.SHIPPED, Order.Status.DELIVERED])
    totals = completed_orders.aggregate(revenue=Sum("total"), orders=Count("id"))
    top_products = (
        OrderItem.objects.filter(order__in=completed_orders)
        .values("product_name")
        .annotate(
            units=Sum("quantity"),
            revenue=Sum(ExpressionWrapper(F("unit_price") * F("quantity"), output_field=DecimalField(max_digits=12, decimal_places=2))),
        )
        .order_by("-units")[:8]
    )
    return render(request, "storefront/admin_analytics.html", {
        "revenue": totals["revenue"] or Decimal("0"), "order_count": totals["orders"],
        "top_products": top_products, "low_stock": Product.objects.filter(stock__lte=F("low_stock_threshold")).order_by("stock", "name"),
        "open_requests": OrderRequest.objects.filter(status=OrderRequest.Status.REQUESTED).select_related("order", "user"),
    })


def trust_page(request, page):
    pages = {"privacy", "terms", "returns"}
    if page not in pages:
        raise Http404
    return render(request, "storefront/trust_page.html", {"page": page})
