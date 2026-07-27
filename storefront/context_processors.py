from .cart import Cart


def cart_summary(request):
    return {"cart_count": Cart(request).count}
