"""Seed 3-5 synthetic demo reviews per active product.

Usage:
    source venv/bin/activate
    python manage.py shell < scripts/seed_reviews.py

Creates a small pool of demo reviewer accounts (username prefix
"demo_reviewer_") if they don't already exist, then gives each active
product a handful of reviews with a positive-skewed rating distribution
and varied, product-agnostic review text. Safe to re-run: skips any
(product, user) pair that already has a review.
"""
import random

from django.contrib.auth.models import User

from storefront.models import Product, Review

random.seed(42)

REVIEWER_NAMES = [
    ("Aarav Mehta", "demo_reviewer_aarav"),
    ("Priya Nair", "demo_reviewer_priya"),
    ("Rohan Kapoor", "demo_reviewer_rohan"),
    ("Ishita Sharma", "demo_reviewer_ishita"),
    ("Kabir Singh", "demo_reviewer_kabir"),
    ("Ananya Iyer", "demo_reviewer_ananya"),
    ("Vikram Rao", "demo_reviewer_vikram"),
    ("Meera Pillai", "demo_reviewer_meera"),
    ("Arjun Desai", "demo_reviewer_arjun"),
    ("Sneha Reddy", "demo_reviewer_sneha"),
    ("Kunal Verma", "demo_reviewer_kunal"),
    ("Tanvi Joshi", "demo_reviewer_tanvi"),
]

REVIEW_TEMPLATES = {
    5: [
        ("Exceeded expectations", "The quality is even better than the photos. Fits true to size and the fabric feels premium. Highly recommend."),
        ("Absolutely love it", "Ordered this last week and it's already my favorite. Great stitching, comfortable, and true to the description."),
        ("Perfect purchase", "Fast delivery, well packaged, and the product itself is beautiful. Will definitely shop here again."),
        ("Worth every rupee", "Was a bit skeptical ordering online but this exceeded my expectations. Color and fit are exactly as shown."),
        ("Great quality", "Really impressed with the fabric quality and finishing. Looks even better in person."),
    ],
    4: [
        ("Really happy with this", "Good quality overall, fits well. Only minor thing is the color is slightly different from the photo but still nice."),
        ("Good value", "Solid purchase for the price. Comfortable to wear and the stitching feels durable."),
        ("Nice product", "Liked it a lot, sizing was accurate. Would buy again in another color."),
        ("Pretty satisfied", "Good quality fabric and comfortable fit. Delivery took a couple extra days but worth the wait."),
    ],
    3: [
        ("It's okay", "Decent product for the price, though the fabric feels a little thinner than expected."),
        ("Average", "Fits fine but the color was slightly different from what I expected. Not bad overall."),
    ],
    2: [
        ("Expected better", "Fabric quality was below what I was hoping for at this price point. Fit was okay though."),
        ("Mixed feelings", "Sizing ran a little off for me and the color was a bit different than pictured."),
    ],
}

RATING_WEIGHTS = {5: 45, 4: 35, 3: 15, 2: 5}


def get_or_create_reviewers():
    users = []
    for full_name, username in REVIEWER_NAMES:
        first, last = full_name.split(" ", 1)
        user, _ = User.objects.get_or_create(
            username=username,
            defaults={
                "first_name": first,
                "last_name": last,
                "email": f"{username}@example.com",
                "is_active": True,
            },
        )
        if not user.has_usable_password():
            user.set_unusable_password()
            user.save(update_fields=["password"])
        users.append(user)
    return users


def weighted_rating():
    ratings = list(RATING_WEIGHTS.keys())
    weights = list(RATING_WEIGHTS.values())
    return random.choices(ratings, weights=weights, k=1)[0]


def seed():
    reviewers = get_or_create_reviewers()
    products = list(Product.objects.filter(is_active=True))
    created_count = 0

    for product in products:
        num_reviews = random.randint(3, 5)
        chosen_reviewers = random.sample(reviewers, min(num_reviews, len(reviewers)))
        for user in chosen_reviewers:
            if Review.objects.filter(product=product, user=user).exists():
                continue
            rating = weighted_rating()
            title, body = random.choice(REVIEW_TEMPLATES[rating])
            Review.objects.create(
                product=product,
                user=user,
                rating=rating,
                title=title,
                body=body,
                is_approved=True,
            )
            created_count += 1

    print(f"Seeded {created_count} reviews across {len(products)} products using {len(reviewers)} demo reviewers.")


seed()
