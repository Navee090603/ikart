import re
import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core import mail
from django.core.management import call_command
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Address, Category, Coupon, CouponRedemption, Order, OrderItem, OrderRequest, PaymentTransaction, Product, ProductQuestion, Review, SavedForLaterItem, SupportTicket, WishlistItem


class ShoppingFlowTests(TestCase):
    def setUp(self):
        category = Category.objects.create(name="Home")
        self.product = Product.objects.create(
            category=category, name="Coffee mug", short_description="Ceramic mug",
            description="A sturdy everyday mug.", price="299.00", stock=5, is_featured=True,
        )

    def test_guest_can_add_to_cart_and_place_cod_order(self):
        self.client.post(reverse("storefront:add_to_cart", args=[self.product.id]), {"quantity": 2})
        response = self.client.post(reverse("storefront:checkout"), self.checkout_data())
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
        self.assertEqual(len(mail.outbox), 1)
        session = self.client.session
        session["pending_registration"]["last_sent_at"] = (timezone.now() - timedelta(seconds=61)).isoformat()
        session.save()
        response = self.client.post(reverse("storefront:resend_verification_code"))
        self.assertRedirects(response, reverse("storefront:verify_email"))
        self.assertEqual(len(mail.outbox), 2)

    def login_customer(self):
        user = User.objects.create_user("customer", "customer@example.com", "Secur3Password!")
        self.client.login(username="customer", password="Secur3Password!")
        return user

    def checkout_token(self):
        self.client.get(reverse("storefront:checkout"))
        return self.client.session["checkout_token"]

    def checkout_data(self, **overrides):
        data = {
            "email": "buyer@example.com", "full_name": "Test Buyer", "phone": "9999999999",
            "address_line1": "10 Main Street", "address_line2": "", "city": "Pune",
            "state": "Maharashtra", "postal_code": "411001", "delivery_option": "standard",
            "payment_method": "cod", "coupon_code": "", "checkout_token": self.checkout_token(),
        }
        data.update(overrides)
        return data

    def test_wishlist_and_save_for_later_are_persistent_for_customer(self):
        user = self.login_customer()
        self.client.post(reverse("storefront:toggle_wishlist", args=[self.product.id]))
        self.assertTrue(WishlistItem.objects.filter(user=user, product=self.product).exists())
        self.client.post(reverse("storefront:add_to_cart", args=[self.product.id]), {"quantity": 1})
        cart_key = next(iter(self.client.session["cart"]))
        self.client.post(reverse("storefront:save_cart_item_for_later", args=[cart_key]))
        self.assertTrue(SavedForLaterItem.objects.filter(user=user, product=self.product).exists())

    def test_coupon_and_saved_address_are_applied_at_checkout(self):
        user = self.login_customer()
        address = Address.objects.create(user=user, full_name="Customer", phone="9999999999", line1="1 Main St", city="Pune", state="Maharashtra", postal_code="411001", is_default=True)
        coupon = Coupon.objects.create(code="SAVE10", discount_type="percent", value="10", minimum_order_amount="100")
        self.client.post(reverse("storefront:add_to_cart", args=[self.product.id]), {"quantity": 2})
        response = self.client.post(reverse("storefront:checkout"), self.checkout_data(
            email=user.email, saved_address=address.id, coupon_code="save10",
        ))
        self.assertEqual(response.status_code, 302)
        order = Order.objects.get(user=user)
        self.assertEqual(order.discount_amount, Decimal("59.80"))
        self.assertEqual(order.total, Decimal("538.20"))
        self.assertTrue(CouponRedemption.objects.filter(coupon=coupon, order=order).exists())

    def test_customer_can_submit_questions_support_and_cancellation(self):
        user = self.login_customer()
        self.client.post(reverse("storefront:add_product_question", args=[self.product.slug]), {"question": "Is it dishwasher safe?"})
        self.assertTrue(ProductQuestion.objects.filter(product=self.product, user=user).exists())
        order = Order.objects.create(user=user, email=user.email, full_name="Customer", phone="9999999999", address_line1="1 Main", city="Pune", state="Maharashtra", postal_code="411001", payment_method="cod", subtotal="299", total="299")
        response = self.client.post(reverse("storefront:request_order_change", args=[order.number, "cancellation"]), {"reason": "changed_mind", "note": "No longer needed"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(OrderRequest.objects.filter(order=order, request_type="cancellation").exists())
        self.assertTrue(SupportTicket.objects.create(user=user, subject="Need help", message="Please help").pk)

    def test_autocomplete_returns_catalogue_matches(self):
        response = self.client.get(reverse("storefront:search_autocomplete"), {"q": "coffee"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["name"], "Coffee mug")

    def test_phase_two_customer_pages_render(self):
        user = self.login_customer()
        Address.objects.create(user=user, full_name="Customer", phone="9999999999", line1="1 Main St", city="Pune", state="Maharashtra", postal_code="411001")
        self.assertEqual(self.client.get(self.product.get_absolute_url()).status_code, 200)
        self.assertEqual(self.client.get(reverse("storefront:wishlist")).status_code, 200)
        self.assertEqual(self.client.get(reverse("storefront:saved_for_later")).status_code, 200)
        self.assertEqual(self.client.get(reverse("storefront:addresses")).status_code, 200)
        self.assertEqual(self.client.get(reverse("storefront:support")).status_code, 200)
        self.assertEqual(self.client.get(reverse("storefront:notification_preferences")).status_code, 200)

    def test_staff_can_open_analytics_dashboard(self):
        staff = User.objects.create_superuser("admin", "admin@example.com", "Secur3Password!")
        self.client.login(username=staff.username, password="Secur3Password!")
        self.assertEqual(self.client.get(reverse("storefront:analytics_dashboard")).status_code, 200)

    def test_coupon_quote_refreshes_and_checkout_recalculates_on_the_server(self):
        coupon = Coupon.objects.create(code="SAVE10", discount_type="percent", value="10", minimum_order_amount="100")
        self.client.post(reverse("storefront:add_to_cart", args=[self.product.id]), {"quantity": 2})
        response = self.client.post(reverse("storefront:update_coupon_quote"), {"coupon_code": coupon.code, "delivery_option": "standard"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["discount_amount"], "59.80")
        self.assertEqual(response.json()["total"], "538.20")
        cart_key = next(iter(self.client.session["cart"]))
        response = self.client.post(reverse("storefront:update_cart_quote"), {"key": cart_key, "quantity": 1})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["discount_amount"], "29.90")
        self.assertEqual(response.json()["total"], "318.10")
        response = self.client.post(reverse("storefront:checkout"), self.checkout_data(coupon_code=coupon.code))
        order = Order.objects.get()
        self.assertRedirects(response, reverse("storefront:order_confirmation", args=[order.number]))
        self.assertEqual(order.total, Decimal("318.10"))

    @override_settings(RAZORPAY_KEY_ID="rzp_test_key", RAZORPAY_KEY_SECRET="secret", RAZORPAY_CURRENCY="INR")
    @patch("storefront.views.razorpay.Client")
    def test_verified_online_payment_is_captured_once_and_clears_cart(self, client_class):
        fake_client = client_class.return_value
        fake_client.order.create.return_value = {"id": "order_test_123"}
        fake_client.payment.fetch.return_value = {"id": "pay_test_123", "order_id": "order_test_123", "amount": 34800, "currency": "INR", "status": "captured"}
        self.client.post(reverse("storefront:add_to_cart", args=[self.product.id]), {"quantity": 1})
        response = self.client.post(reverse("storefront:checkout"), self.checkout_data(payment_method="razorpay"))
        order = Order.objects.get()
        self.assertRedirects(response, reverse("storefront:payment_checkout", args=[order.number]))
        self.assertTrue(self.client.session.get("cart"))
        self.assertEqual(order.status, Order.Status.PAYMENT_PENDING)
        response = self.client.post(reverse("storefront:verify_razorpay_payment", args=[order.number]), {
            "razorpay_order_id": "order_test_123", "razorpay_payment_id": "pay_test_123", "razorpay_signature": "valid",
        })
        self.assertRedirects(response, reverse("storefront:order_confirmation", args=[order.number]))
        order.refresh_from_db()
        self.assertEqual(order.payment_status, "paid")
        self.assertEqual(order.status, Order.Status.PLACED)
        self.assertEqual(PaymentTransaction.objects.get(order=order).status, PaymentTransaction.Status.CAPTURED)
        self.assertFalse(self.client.session.get("cart"))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 4)
        self.client.post(reverse("storefront:verify_razorpay_payment", args=[order.number]), {
            "razorpay_order_id": "order_test_123", "razorpay_payment_id": "pay_test_123", "razorpay_signature": "valid",
        })
        self.assertEqual(Order.objects.count(), 1)

    @override_settings(RAZORPAY_KEY_ID="rzp_test_key", RAZORPAY_KEY_SECRET="secret", RAZORPAY_CURRENCY="INR")
    @patch("storefront.views.razorpay.Client")
    def test_cancelled_online_payment_restores_stock_keeps_cart_and_releases_coupon(self, client_class):
        client_class.return_value.order.create.return_value = {"id": "order_test_cancel"}
        coupon = Coupon.objects.create(code="SAVE10", discount_type="percent", value="10")
        self.client.post(reverse("storefront:add_to_cart", args=[self.product.id]), {"quantity": 1})
        response = self.client.post(reverse("storefront:checkout"), self.checkout_data(payment_method="razorpay", coupon_code=coupon.code))
        order = Order.objects.get()
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 4)
        self.assertTrue(CouponRedemption.objects.filter(order=order).exists())
        response = self.client.post(reverse("storefront:cancel_razorpay_payment", args=[order.number]))
        self.assertRedirects(response, reverse("storefront:cart"))
        order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PAYMENT_FAILED)
        self.assertEqual(self.product.stock, 5)
        self.assertTrue(self.client.session.get("cart"))
        self.assertFalse(CouponRedemption.objects.filter(order=order).exists())

    def test_question_is_moderated_and_duplicate_submission_is_blocked(self):
        user = self.login_customer()
        question = "Is it dishwasher safe?"
        self.client.post(reverse("storefront:add_product_question", args=[self.product.slug]), {"question": question})
        self.client.post(reverse("storefront:add_product_question", args=[self.product.slug]), {"question": question})
        self.assertEqual(ProductQuestion.objects.filter(product=self.product, user=user).count(), 1)
        self.assertFalse(ProductQuestion.objects.get(product=self.product, user=user).is_published)

    def test_review_rating_is_limited_to_five_stars(self):
        self.login_customer()
        self.client.post(reverse("storefront:add_review", args=[self.product.slug]), {"rating": 6, "title": "Invalid", "body": "This should not be accepted."})
        self.assertFalse(Review.objects.filter(product=self.product).exists())

    @override_settings(RAZORPAY_KEY_ID="rzp_test_key", RAZORPAY_KEY_SECRET="secret", RAZORPAY_WEBHOOK_SECRET="webhook-secret")
    @patch("storefront.views.razorpay.Client")
    def test_refund_webhook_finalises_refund_and_restores_inventory_once(self, client_class):
        order = Order.objects.create(
            email="buyer@example.com", full_name="Buyer", phone="9999999999", address_line1="1 Main",
            city="Pune", state="Maharashtra", postal_code="411001", payment_method="razorpay",
            subtotal="299", delivery_fee="49", total="348", status=Order.Status.PLACED,
            payment_status="refund_pending", inventory_deducted=True,
        )
        OrderItem.objects.create(order=order, product=self.product, product_name=self.product.name, quantity=1, unit_price="299")
        self.product.stock = 4
        self.product.save(update_fields=["stock"])
        payment = PaymentTransaction.objects.create(
            order=order, provider_order_id="order_refund_123", provider_payment_id="pay_refund_123",
            provider_refund_id="rfnd_123", amount="348", status=PaymentTransaction.Status.REFUND_PENDING,
        )
        change_request = OrderRequest.objects.create(
            order=order, user=User.objects.create_user("refundbuyer", "refund@example.com", "Secur3Password!"),
            request_type="return", reason="damaged", status=OrderRequest.Status.REFUND_PENDING,
        )
        payload = {
            "event": "refund.processed",
            "payload": {"refund": {"entity": {"id": "rfnd_123", "payment_id": "pay_refund_123", "amount": 34800, "currency": "INR", "status": "processed"}}},
        }
        response = self.client.post(
            reverse("storefront:razorpay_webhook"), data=json.dumps(payload), content_type="application/json",
            headers={"X-Razorpay-Signature": "valid", "X-Razorpay-Event-Id": "event-refund-1"},
        )
        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        payment.refresh_from_db()
        change_request.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(order.status, Order.Status.REFUNDED)
        self.assertEqual(payment.status, PaymentTransaction.Status.REFUNDED)
        self.assertEqual(change_request.status, OrderRequest.Status.REFUNDED)
        self.assertEqual(self.product.stock, 5)
        self.client.post(
            reverse("storefront:razorpay_webhook"), data=json.dumps(payload), content_type="application/json",
            headers={"X-Razorpay-Signature": "valid", "X-Razorpay-Event-Id": "event-refund-1"},
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 5)

    def test_stale_payment_reservation_command_releases_stock(self):
        order = Order.objects.create(
            email="buyer@example.com", full_name="Buyer", phone="9999999999", address_line1="1 Main",
            city="Pune", state="Maharashtra", postal_code="411001", payment_method="razorpay",
            subtotal="299", delivery_fee="49", total="348", status=Order.Status.PAYMENT_PENDING,
            payment_status="initiated", inventory_deducted=True,
        )
        OrderItem.objects.create(order=order, product=self.product, product_name=self.product.name, quantity=1, unit_price="299")
        self.product.stock = 4
        self.product.save(update_fields=["stock"])
        payment = PaymentTransaction.objects.create(order=order, provider_order_id="order_stale_123", amount="348")
        PaymentTransaction.objects.filter(pk=payment.pk).update(created_at=timezone.now() - timedelta(minutes=31))
        call_command("release_stale_payment_reservations", minutes=30)
        order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PAYMENT_FAILED)
        self.assertEqual(self.product.stock, 5)
