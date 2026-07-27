from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .cart import Cart
from .forms import CheckoutForm, OTPVerificationForm, ReviewForm, SignUpForm
from .models import Category, Order, OrderItem, Product, Review


def home(request):
    return render(request, "storefront/home.html", {
        "featured": Product.objects.filter(is_active=True, is_featured=True)[:8],
        "categories": Category.objects.filter(parent__isnull=True)[:8],
    })


def product_list(request, category_slug=None):
    products = Product.objects.filter(is_active=True).select_related("category").prefetch_related("images")
    category = None
    if category_slug:
        category = get_object_or_404(Category, slug=category_slug)
        products = products.filter(Q(category=category) | Q(category__parent=category))
    query = request.GET.get("q", "").strip()
    if query:
        products = products.filter(Q(name__icontains=query) | Q(description__icontains=query))
    if request.GET.get("min_price"):
        products = products.filter(price__gte=request.GET["min_price"])
    if request.GET.get("max_price"):
        products = products.filter(price__lte=request.GET["max_price"])
    ordering = request.GET.get("sort", "newest")
    products = products.order_by({"price_low": "price", "price_high": "-price", "newest": "-created_at", "popular": "-is_featured"}.get(ordering, "-created_at"))
    return render(request, "storefront/product_list.html", {"products": products, "categories": Category.objects.filter(parent__isnull=True), "current_category": category})


def product_detail(request, slug):
    product = get_object_or_404(Product.objects.prefetch_related("images", "variants", "reviews__user"), slug=slug, is_active=True)
    return render(request, "storefront/product_detail.html", {"product": product, "review_form": ReviewForm()})


@require_POST
def add_to_cart(request, product_id):
    product = get_object_or_404(Product, id=product_id, is_active=True)
    variant_id = request.POST.get("variant")
    variant = product.variants.filter(id=variant_id).first() if variant_id else None
    available = variant.stock if variant else product.stock
    quantity = max(1, int(request.POST.get("quantity", 1)))
    if available < quantity:
        messages.error(request, "That quantity is not currently in stock.")
        return redirect(product.get_absolute_url())
    Cart(request).add(product, quantity, variant)
    messages.success(request, f"{product.name} was added to your cart.")
    return redirect(request.POST.get("next") or "storefront:cart")


def cart_detail(request):
    return render(request, "storefront/cart.html", {"cart": Cart(request)})


@require_POST
def update_cart(request):
    cart = Cart(request)
    for key, quantity in request.POST.items():
        if key.startswith("qty_"):
            cart.update(key[4:], quantity)
    messages.success(request, "Your cart has been updated.")
    return redirect("storefront:cart")


@require_POST
def remove_from_cart(request, key):
    Cart(request).remove(key)
    return redirect("storefront:cart")


def checkout(request):
    cart = Cart(request)
    if not cart.count:
        messages.info(request, "Your cart is empty.")
        return redirect("storefront:product_list")
    delivery_fee = Decimal("0") if cart.subtotal >= 499 else Decimal("49")
    if request.method == "POST":
        form = CheckoutForm(request.POST)
        if form.is_valid():
            if form.cleaned_data["delivery_option"] == Order.DeliveryOption.EXPRESS:
                delivery_fee = Decimal("99")
            # Razorpay is deliberately gated until server-side payment verification is configured.
            if form.cleaned_data["payment_method"] == Order.PaymentMethod.RAZORPAY:
                messages.error(request, "Online payment is not configured yet. Please choose cash on delivery.")
            else:
                with transaction.atomic():
                    order = form.save(commit=False)
                    order.user = request.user if request.user.is_authenticated else None
                    order.subtotal = cart.subtotal
                    order.delivery_fee = delivery_fee
                    order.total = cart.subtotal + delivery_fee
                    order.save()
                    for item in cart:
                        available = item["variant"].stock if item["variant"] else item["product"].stock
                        if item["quantity"] > available:
                            raise Http404("An item in your cart is no longer available in that quantity.")
                        OrderItem.objects.create(order=order, product=item["product"], product_name=item["product"].name,
                            variant_label=item["variant"].label if item["variant"] else "", quantity=item["quantity"], unit_price=item["price"])
                        if item["variant"]:
                            item["variant"].stock -= item["quantity"]
                            item["variant"].save(update_fields=["stock"])
                        else:
                            item["product"].stock -= item["quantity"]
                            item["product"].save(update_fields=["stock"])
                    cart.clear()
                send_mail(f"Order {order.number} confirmed", f"Thanks for your order. Total: ₹{order.total}", None, [order.email], fail_silently=True)
                request.session["recent_order_numbers"] = [order.number]
                return redirect("storefront:order_confirmation", number=order.number)
    else:
        form = CheckoutForm(initial={"email": request.user.email} if request.user.is_authenticated else None)
    return render(request, "storefront/checkout.html", {"cart": cart, "form": form, "delivery_fee": delivery_fee, "total": cart.subtotal + delivery_fee})


def order_confirmation(request, number):
    order = get_object_or_404(Order, number=number)
    can_view = (order.user and order.user == request.user) or number in request.session.get("recent_order_numbers", [])
    if not can_view:
        raise Http404
    return render(request, "storefront/order_confirmation.html", {"order": order})


@login_required
def order_history(request):
    return render(request, "storefront/order_history.html", {"orders": request.user.orders.prefetch_related("items")})


def signup(request):
    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            code_hash, expires_at = _send_verification_code(form.cleaned_data["email"])
            request.session["pending_registration"] = {
                "username": form.cleaned_data["username"],
                "email": form.cleaned_data["email"],
                "password_hash": make_password(form.cleaned_data["password1"]),
                "code_hash": code_hash,
                "expires_at": expires_at.isoformat(),
                "attempts": 0,
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
def resend_verification_code(request):
    pending = request.session.get("pending_registration")
    if not pending:
        messages.info(request, "Start by creating your account.")
        return redirect("storefront:signup")
    code_hash, expires_at = _send_verification_code(pending["email"])
    pending.update({"code_hash": code_hash, "expires_at": expires_at.isoformat(), "attempts": 0})
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
    return redirect(product.get_absolute_url())


def trust_page(request, page):
    pages = {"privacy", "terms", "returns"}
    if page not in pages:
        raise Http404
    return render(request, "storefront/trust_page.html", {"page": page})
