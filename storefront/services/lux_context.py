"""Live store data that Lux can quote: matching products and the customer's own orders."""

import re
from decimal import Decimal

from ..models import Order, Product

MAX_PRODUCTS = 12
MAX_ORDERS = 5

ORDER_NUMBER = re.compile(r"\bIK[0-9A-F]{10}\b", re.IGNORECASE)
PRICE_CEILING = re.compile(r"\b(?:under|below|less than|within|upto|up to|max(?:imum)?|budget(?: of)?)\s*(?:rs\.?|inr|₹)?\s*(\d[\d,]*)", re.IGNORECASE)
PRICE_FLOOR = re.compile(r"\b(?:above|over|more than|min(?:imum)?|at least)\s*(?:rs\.?|inr|₹)?\s*(\d[\d,]*)", re.IGNORECASE)
WORD = re.compile(r"[a-z]+")

SHOPPING_WORDS = {
    "suggest", "recommend", "show", "looking", "look", "want", "need", "buy", "gift", "wear", "outfit",
    "product", "products", "item", "items", "price", "cheap", "cheapest", "affordable", "costly", "expensive",
    "size", "sizes", "colour", "color", "stock", "available", "new", "latest", "sale", "discount", "offer",
    "party", "wedding", "office", "casual", "summer", "festive", "collection", "catalogue", "catalog",
}
ORDER_WORDS = {
    "order", "orders", "track", "tracking", "deliver", "delivered", "delivery", "shipped", "shipping",
    "parcel", "package", "courier", "arrive", "arriving", "return", "refund", "cancel", "cancellation", "status",
}
STOP_WORDS = {
    "a", "an", "the", "i", "me", "my", "you", "your", "for", "to", "of", "in", "on", "and", "or", "is", "are",
    "it", "do", "does", "have", "has", "any", "some", "with", "please", "can", "could", "would", "what", "which",
    "show", "want", "need", "looking", "suggest", "recommend", "rs", "inr", "under", "below", "above", "over",
}


def _words(text):
    return set(WORD.findall(text.lower()))


def _search_terms(text):
    """Meaningful words from a question, plus simple singular forms ("dresses" -> "dress")."""
    terms = set()
    for word in _words(text) - STOP_WORDS:
        if len(word) < 3:
            continue
        terms.add(word)
        if word.endswith("es") and len(word) > 4:
            terms.add(word[:-2])
        if word.endswith("s") and len(word) > 3:
            terms.add(word[:-1])
    return terms


def _non_english(text):
    """Written mostly in another script (Tamil, Hindi...), which keyword matching can't read."""
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum(not c.isascii() for c in letters) > len(letters) / 2


def _amount(match):
    return Decimal(match.group(1).replace(",", "")) if match else None


def _in_stock_sizes(product):
    return [v.size or v.label for v in product.variants.all() if v.stock > 0]


def _product_line(product):
    sizes = _in_stock_sizes(product)
    has_options = bool(product.variants.all())
    if has_options:
        availability = f"sizes in stock: {', '.join(sizes)}" if sizes else "out of stock"
    else:
        availability = "in stock" if product.stock > 0 else "out of stock"
    price = f"₹{product.price:.0f}"
    if product.discount_percentage:
        price += f" (was ₹{product.compare_at_price:.0f}, {product.discount_percentage}% off)"
    brand = f" | {product.brand}" if product.brand else ""
    return f"- {product.name} | {price} | {product.category.name}{brand} | {availability} | {product.short_description} | {product.get_absolute_url()}"


def relevant_products(message):
    """Up to MAX_PRODUCTS catalogue lines for a shopping question, or None if it isn't one."""
    words = _words(message)
    ceiling = _amount(PRICE_CEILING.search(message))
    floor = _amount(PRICE_FLOOR.search(message))
    products = list(
        Product.objects.filter(is_active=True)
        .select_related("category", "category__parent")
        .prefetch_related("variants")
    )

    def haystack(product):
        return _search_terms(" ".join([
            product.name, product.short_description, product.brand, product.category.name,
            product.category.parent.name if product.category.parent else "",
            " ".join(v.label for v in product.variants.all()),
        ]))

    terms = _search_terms(message)
    scored = [(len(terms & haystack(p)), p) for p in products]
    if not (ceiling or floor or words & SHOPPING_WORDS or any(score for score, _ in scored) or _non_english(message)):
        return None
    if any(score for score, _ in scored):
        scored = [(score, p) for score, p in scored if score]

    if ceiling is not None:
        scored = [(s, p) for s, p in scored if p.price <= ceiling]
    if floor is not None:
        scored = [(s, p) for s, p in scored if p.price >= floor]
    if not scored:
        limit = " and ".join(filter(None, [f"at least ₹{floor}" if floor else "", f"at most ₹{ceiling}" if ceiling else ""]))
        return f"No matching products are priced {limit}."
    # Keyword matches first, then featured, then cheapest; the model picks what actually fits.
    scored.sort(key=lambda sp: (-sp[0], not sp[1].is_featured, sp[1].price))
    return "\n".join(_product_line(p) for _, p in scored[:MAX_PRODUCTS])


def _order_line(order):
    items = ", ".join(
        f"{i.quantity}× {i.product_name}{f' ({i.variant_label})' if i.variant_label else ''}" for i in order.items.all()
    )
    parts = [
        f"- {order.number} | placed {order.created_at:%d %b %Y} | status: {order.get_status_display()}",
        f"payment: {order.get_payment_method_display()}, {order.payment_status.replace('_', ' ')}",
        f"total ₹{order.total:.0f}",
        f"items: {items}",
    ]
    shipment = getattr(order, "shipment", None)
    if shipment and (shipment.carrier or shipment.tracking_number or shipment.estimated_delivery):
        tracking = " ".join(filter(None, [shipment.carrier, shipment.tracking_number]))
        if shipment.estimated_delivery:
            tracking += f" (estimated delivery {shipment.estimated_delivery:%d %b %Y})"
        parts.append(f"tracking: {tracking.strip()}")
    if order.delivered_at:
        parts.append(f"delivered {order.delivered_at:%d %b %Y}")
    if order.can_request_return:
        parts.append(f"returns open until {order.return_deadline:%d %b %Y}")
    open_requests = [r for r in order.requests.all() if r.status in {"requested", "approved", "refund_pending"}]
    for request in open_requests:
        parts.append(f"{request.get_request_type_display().lower()} request: {request.get_status_display().lower()}")
    parts.append(f"page: /order/{order.number}/")
    return " | ".join(parts)


def customer_orders(user, message):
    """The signed-in customer's recent orders for an order question, or None if it isn't one."""
    mentioned = {n.upper() for n in ORDER_NUMBER.findall(message)}
    if not mentioned and not (_words(message) & ORDER_WORDS) and not _non_english(message):
        return None
    if not user or not user.is_authenticated:
        return "The customer is not signed in, so you cannot see any orders. Ask them to sign in and check Order History (/orders/)."
    orders = (
        Order.objects.filter(user=user)
        .exclude(status__in=[Order.Status.PAYMENT_PENDING, Order.Status.PAYMENT_FAILED])
        .select_related("shipment")
        .prefetch_related("items", "requests")
    )
    recent = list(orders.order_by("-created_at")[:MAX_ORDERS])
    extra = [o for o in orders.filter(number__in=mentioned) if o not in recent]
    listed = recent + extra
    if not listed:
        return "This customer has no orders yet."
    lines = [_order_line(order) for order in listed]
    missing = mentioned - {o.number for o in listed}
    if missing:
        lines.append(f"Not found in this customer's account: {', '.join(sorted(missing))}.")
    return "\n".join(lines)
