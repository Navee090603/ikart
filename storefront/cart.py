from decimal import Decimal

from .models import Product, ProductVariant


class Cart:
    """Session-backed cart that works for guests and signed-in customers."""

    session_key = "cart"

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
        self.session.modified = True

    def __iter__(self):
        products = Product.objects.in_bulk(item["product_id"] for item in self.data.values())
        variants = ProductVariant.objects.in_bulk([item["variant_id"] for item in self.data.values() if item["variant_id"]])
        for key, item in self.data.items():
            product = products.get(item["product_id"])
            if not product:
                continue
            variant = variants.get(item["variant_id"])
            price = product.price + (variant.price_adjustment if variant else Decimal("0"))
            yield {"key": key, "product": product, "variant": variant, "quantity": item["quantity"], "price": price, "total": price * item["quantity"]}

    @property
    def subtotal(self):
        return sum((item["total"] for item in self), Decimal("0"))

    @property
    def count(self):
        return sum(item["quantity"] for item in self.data.values())

    def _save(self):
        self.session[self.session_key] = self.data
        self.session.modified = True
