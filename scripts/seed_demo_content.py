"""Seed demo Product Q&A, FAQ entries, and coupon codes.

Usage:
    source venv/bin/activate
    python manage.py shell < scripts/seed_demo_content.py

Safe to re-run: skips anything that already exists (FAQ questions by
text, coupons by code, product questions by exact text per product).
"""
import random
from datetime import timedelta

from django.contrib.auth.models import User
from django.utils import timezone

from storefront.models import Coupon, FAQ, Product, ProductQuestion

random.seed(7)

# -------------------------
# PRODUCT Q&A
# -------------------------

REVIEWER_USERNAMES = [
    "demo_reviewer_aarav", "demo_reviewer_priya", "demo_reviewer_rohan",
    "demo_reviewer_ishita", "demo_reviewer_kabir", "demo_reviewer_ananya",
    "demo_reviewer_vikram", "demo_reviewer_meera", "demo_reviewer_arjun",
    "demo_reviewer_sneha", "demo_reviewer_kunal", "demo_reviewer_tanvi",
]

QA_TEMPLATES = [
    ("Is this true to size or should I size up?", "This fits true to size for most customers. If you prefer a relaxed fit, we'd suggest sizing up."),
    ("What's the fabric like, is it breathable?", "Yes, it's made from a lightweight, breathable fabric that's comfortable for everyday wear."),
    ("Does the color match the product photos accurately?", "We photograph products in natural light to keep colors as accurate as possible, though slight variation can occur depending on your screen."),
    ("Is this machine washable?", "We recommend a gentle machine wash in cold water and air drying to keep the fabric and print looking their best."),
    ("How long does delivery usually take?", "Standard delivery typically takes 4-6 business days; express delivery is available at checkout for faster shipping."),
    ("Can I return this if it doesn't fit?", "Yes, we accept returns within our standard return window as long as the item is unworn with tags attached."),
]


def seed_product_questions():
    admin_user = User.objects.filter(is_superuser=True).order_by("id").first()
    reviewers = list(User.objects.filter(username__in=REVIEWER_USERNAMES))
    if not reviewers:
        print("No demo reviewer accounts found -- run scripts/seed_reviews.py first.")
        return

    created = 0
    for product in Product.objects.filter(is_active=True):
        num_questions = random.randint(2, 4)
        picks = random.sample(QA_TEMPLATES, min(num_questions, len(QA_TEMPLATES)))
        asker_pool = random.sample(reviewers, min(len(picks), len(reviewers)))
        for (question_text, answer_text), asker in zip(picks, asker_pool):
            if ProductQuestion.objects.filter(product=product, question__iexact=question_text).exists():
                continue
            asked_at = timezone.now() - timedelta(days=random.randint(1, 60))
            ProductQuestion.objects.create(
                product=product,
                user=asker,
                question=question_text,
                answer=answer_text,
                answered_by=admin_user,
                is_published=True,
                created_at=asked_at,
                answered_at=asked_at + timedelta(hours=random.randint(2, 48)),
            )
            created += 1
    print(f"Seeded {created} product Q&A entries.")


# -------------------------
# FAQ
# -------------------------

FAQ_ENTRIES = [
    ("Shipping", "How long does delivery take?", "Standard delivery takes 4-6 business days. Express delivery (2-3 business days) is available at checkout for an additional fee.", 1),
    ("Shipping", "Do you offer free shipping?", "Yes, orders above ₹499 qualify for free standard delivery. Express delivery has a flat fee regardless of order value.", 2),
    ("Returns", "What is your return policy?", "We accept returns within 7 days of delivery as long as items are unworn, unwashed, and have their original tags attached.", 1),
    ("Returns", "How do I request a return or exchange?", "Go to Order History, select the order, and choose 'Request Return' or 'Request Exchange'. Our support team will guide you through the next steps.", 2),
    ("Payments", "What payment methods do you accept?", "We accept all major credit/debit cards and UPI via Razorpay, as well as Cash on Delivery for eligible orders.", 1),
    ("Payments", "Is it safe to pay online on this site?", "Yes, all online payments are processed securely through Razorpay, and we never store your card details on our servers.", 2),
    ("Sizing", "How do I know what size to order?", "Each product page includes fit notes in the description. If you're between sizes, we generally recommend sizing up for a more relaxed fit.", 1),
    ("Orders", "Can I cancel or modify my order after placing it?", "You can request a cancellation from Order History shortly after placing your order. Once an order has shipped, it can no longer be cancelled.", 1),
]


def seed_faq():
    created = 0
    for category, question, answer, sort_order in FAQ_ENTRIES:
        _, was_created = FAQ.objects.get_or_create(
            question=question,
            defaults={"category": category, "answer": answer, "sort_order": sort_order, "is_active": True},
        )
        if was_created:
            created += 1
    print(f"Seeded {created} FAQ entries.")


# -------------------------
# COUPONS
# -------------------------

COUPONS = [
    dict(code="WELCOME10", description="10% off your first order", discount_type=Coupon.DiscountType.PERCENT,
         value="10", minimum_order_amount="499", maximum_discount_amount="300", usage_limit_per_user=1),
    dict(code="FLAT200", description="₹200 off orders above ₹1500", discount_type=Coupon.DiscountType.FIXED,
         value="200", minimum_order_amount="1500"),
    dict(code="SAVE15", description="15% off orders above ₹2000", discount_type=Coupon.DiscountType.PERCENT,
         value="15", minimum_order_amount="2000", maximum_discount_amount="500"),
]


def seed_coupons():
    created = 0
    for data in COUPONS:
        _, was_created = Coupon.objects.get_or_create(code=data["code"], defaults={**data, "is_active": True})
        if was_created:
            created += 1
    print(f"Seeded {created} coupon codes.")


seed_product_questions()
seed_faq()
seed_coupons()
