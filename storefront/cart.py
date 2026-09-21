from decimal import Decimal

from .models import Product, ProductVariant


class Cart:
    """Session-backed cart that works for guests and signed-in customers."""

    session_key = "cart"
    coupon_session_key = "cart_coupon_code"

    def __init__(self, request):
        self.session = request.session
        self.data = self.session.get(self.session_key, {})

    def add(self, product, quantity=1, variant=None):
        key = f"{product.id}:{variant.id if variant else 0}"
        item = self.data.get(key, {"product_id": product.id, "variant_id": variant.id if variant else None, "quantity": 0})
        item["quantity"] += int(quantity)
        self.data[key] = item
        self._save()

    def update(self, key, quantity):
        if key in self.data:
            if int(quantity) > 0:
                self.data[key]["quantity"] = int(quantity)
            else:
                self.data.pop(key)
            self._save()

    def remove(self, key):
        self.data.pop(key, None)
        self._save()

    def clear(self):
        self.session.pop(self.session_key, None)
        self.session.pop(self.coupon_session_key, None)
        self.session.modified = True

    @property
    def coupon_code(self):
        return self.session.get(self.coupon_session_key, "")

    def set_coupon(self, code):
        if code:
            self.session[self.coupon_session_key] = code.upper()
        else:
            self.session.pop(self.coupon_session_key, None)
        self.session.modified = True

    def __iter__(self):
        products = Product.objects.filter(is_active=True).in_bulk(item["product_id"] for item in self.data.values())
        variants = ProductVariant.objects.in_bulk([item["variant_id"] for item in self.data.values() if item["variant_id"]])
        for key, item in self.data.items():
            product = products.get(item["product_id"])
            if not product:
                continue
            variant = variants.get(item["variant_id"])
            if item["variant_id"] and (not variant or variant.product_id != product.id):
                continue
            price = product.price + (variant.price_adjustment if variant else Decimal("0"))
            yield {"key": key, "product": product, "variant": variant, "quantity": item["quantity"], "price": price, "total": price * item["quantity"]}

    def prune_stale(self):
        """Remove items whose product/variant vanished or was deactivated since being added.

        Returns the number of items removed, so callers can tell the user
        their cart changed instead of it silently shrinking.
        """
        live_keys = {item["key"] for item in self}
        stale_keys = [key for key in self.data if key not in live_keys]
        for key in stale_keys:
            self.data.pop(key, None)
        if stale_keys:
            self._save()
        return len(stale_keys)

    @property
    def subtotal(self):
        return sum((item["total"] for item in self), Decimal("0"))

    @property
    def count(self):
        return sum(item["quantity"] for item in self)

    def _save(self):
        self.session[self.session_key] = self.data
        self.session.modified = True
