import re

from django.core import mail
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Category, Order, Product


class ShoppingFlowTests(TestCase):
    def setUp(self):
        category = Category.objects.create(name="Home")
        self.product = Product.objects.create(
            category=category, name="Coffee mug", short_description="Ceramic mug",
            description="A sturdy everyday mug.", price="299.00", stock=5, is_featured=True,
        )

    def test_guest_can_add_to_cart_and_place_cod_order(self):
        self.client.post(reverse("storefront:add_to_cart", args=[self.product.id]), {"quantity": 2})
        response = self.client.post(reverse("storefront:checkout"), {
            "email": "buyer@example.com", "full_name": "Test Buyer", "phone": "9999999999",
            "address_line1": "10 Main Street", "address_line2": "", "city": "Pune",
            "state": "Maharashtra", "postal_code": "411001", "delivery_option": "standard", "payment_method": "cod",
        })
        self.assertEqual(response.status_code, 302)
        order = Order.objects.get()
        self.assertEqual(order.total, 598)
        self.assertEqual(order.items.count(), 1)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 3)
        self.assertContains(self.client.get(response.url), order.number)

    def test_search_finds_product(self):
        response = self.client.get(reverse("storefront:product_list"), {"q": "coffee"})
        self.assertContains(response, "Coffee mug")

    def test_new_account_requires_email_otp_before_activation(self):
        response = self.client.post(reverse("storefront:signup"), {
            "username": "newbuyer", "email": "newbuyer@example.com",
            "password1": "Secur3Password!", "password2": "Secur3Password!",
        })
        self.assertRedirects(response, reverse("storefront:verify_email"))
        self.assertFalse(User.objects.filter(username="newbuyer").exists())
        self.assertEqual(len(mail.outbox), 1)
        code = re.search(r"\b(\d{6})\b", mail.outbox[0].body).group(1)
        response = self.client.post(reverse("storefront:verify_email"), {"code": code})
        self.assertRedirects(response, reverse("storefront:home"))
        user = User.objects.get(username="newbuyer")
        self.assertTrue(user.is_active)

    def test_pending_signup_can_resend_code_from_verification_page(self):
        self.client.post(reverse("storefront:signup"), {
            "username": "waiting", "email": "waiting@example.com",
            "password1": "Secur3Password!", "password2": "Secur3Password!",
        })
        response = self.client.post(reverse("storefront:resend_verification_code"))
        self.assertRedirects(response, reverse("storefront:verify_email"))
        self.assertEqual(len(mail.outbox), 2)
