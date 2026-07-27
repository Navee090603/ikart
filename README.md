# IKart

IKart is a mobile-responsive, Django shopping website built as the Phase 1 foundation for an Amazon-inspired store. It supports a complete customer shopping loop and an admin workflow for fulfilling orders.

## What works in Phase 1

- Home page with promotion area, category navigation, and featured products.
- Category browsing, keyword search, price filters, and product sorting.
- Product detail pages with image gallery, descriptions, specifications, variants, stock availability, and customer reviews.
- Guest or signed-in, session-backed cart with quantity updates, removal, and live totals.
- Checkout with delivery details, standard/express options, cash on delivery, confirmation email, and order confirmation.
- Email OTP verification on signup, account sign-in, and order history; guests can still check out.
- Admin-managed products, multiple images, size/color variants, inventory, orders, and order-status updates.
- Privacy, terms, return, and secure-checkout trust pages.

Razorpay is represented as the online card/UPI option but intentionally cannot be selected until secure payment creation, signature verification, and webhooks are configured. Cash on delivery is the usable MVP payment path.

## Run locally

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py runserver
```

Visit `http://127.0.0.1:8000/` for the storefront and `http://127.0.0.1:8000/admin/` to add categories, products, images, and variants.

During local development, verification emails (including the one-time code) print in the terminal running `runserver`. To deliver OTPs to real inboxes, set `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend` plus the `EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, and sender values in `.env`; use the exact SMTP credentials supplied by your email provider, then restart the server.

## Zero-cost deployment setup

`render.yaml` and `build.sh` are ready for Render. Before deploying, set these values in Render:

- `DATABASE_URL`: Neon connection string with `sslmode=require`.
- `CLOUDINARY_URL`: Cloudinary environment URL for hosted catalog images.
- `ALLOWED_HOSTS`: the Render hostname (and any custom domain).
- `DEBUG=False`.

Render provides HTTPS. Use a real random `SECRET_KEY` in production. The application uses local SQLite/media during development, then automatically moves to Neon and Cloudinary once their environment variables are provided.

## Delivery roadmap

Phase 1 is the implemented MVP. The next priority set is Phase 2: wishlists, coupons, richer search, returns/refunds, support, lifecycle notifications, CSV product import, and analytics. Phase 3 can then add personalization, deals, memberships, marketplace sellers, logistics, mobile apps, and multi-region support.
