from django.urls import path
from . import views

app_name = "storefront"
urlpatterns = [
    path("", views.home, name="home"),
    path("shop/", views.product_list, name="product_list"),
    path("category/<slug:category_slug>/", views.product_list, name="category"),
    path("product/<slug:slug>/", views.product_detail, name="product_detail"),
    path("product/<int:product_id>/cart/", views.add_to_cart, name="add_to_cart"),
    path("cart/", views.cart_detail, name="cart"),
    path("cart/update/", views.update_cart, name="update_cart"),
    path("cart/remove/<path:key>/", views.remove_from_cart, name="remove_from_cart"),
    path("checkout/", views.checkout, name="checkout"),
    path("order/<str:number>/", views.order_confirmation, name="order_confirmation"),
    path("orders/", views.order_history, name="order_history"),
    path("signup/", views.signup, name="signup"),
    path("verify-email/", views.verify_email, name="verify_email"),
    path("verify-email/resend/", views.resend_verification_code, name="resend_verification_code"),
    path("product/<slug:slug>/review/", views.add_review, name="add_review"),
    path("<slug:page>/", views.trust_page, name="trust_page"),
]
