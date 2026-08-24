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

Razorpay card/UPI checkout is implemented for test or live keys. The server creates the Razorpay order, verifies the checkout signature, checks/captures the payment server-side, and accepts signed webhooks as the final asynchronous reconciliation path. Cash on delivery remains available when Razorpay is not configured.

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
- `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, and `RAZORPAY_WEBHOOK_SECRET` to enable card/UPI payments.
- SMTP sender values: `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, and `DEFAULT_FROM_EMAIL`.

Render provides HTTPS. Use a real random `SECRET_KEY` in production. The application uses local SQLite/media during development, then automatically moves to Neon and Cloudinary once their environment variables are provided.

## Razorpay test-mode setup

1. In the Razorpay Dashboard, create or copy **Test Mode** API keys and set `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET` in `.env` (never commit them).
2. Start the site and select **Card / UPI (Razorpay)** at checkout. Use Razorpay’s test payment methods; no real money is taken in test mode.
3. Once the site has a public HTTPS URL, create a Razorpay webhook for `https://YOUR-DOMAIN/payments/razorpay/webhook/`, subscribe to `payment.captured`, `payment.failed`, `order.paid`, `refund.processed`, and `refund.failed`, then copy the webhook secret into `RAZORPAY_WEBHOOK_SECRET`.
4. Configure Razorpay payment capture for the account. IKart also attempts to capture an authorised payment, while the signed webhook handles delayed confirmations and payment failures.

The payment amount is created and checked on the server from the current cart quote; the browser only opens Razorpay Checkout and returns its signed result. A payment failure/cancellation restores inventory and leaves the customer’s cart available to retry.

Run `.venv/bin/python manage.py release_stale_payment_reservations` every 15 minutes in production (or use the **Payment transactions** admin action) to release abandoned checkout reservations. Set `PAYMENT_RESERVATION_MINUTES` if the default 30-minute hold does not suit the store.

## Background tasks (Celery + Redis)

The Celery application lives in `ikart/celery.py` and reads every `CELERY_*` setting from `ikart/settings.py`. Nothing runs on a worker yet: `CELERY_TASK_ALWAYS_EAGER` defaults to `True`, so any task executes inline in the calling process exactly as the current synchronous code does. Order emails and the reservation sweep move onto the queue in a later change.

To run the queue locally with Docker:

```bash
docker compose up            # redis, web, worker, and beat
```

Or keep Django on the host and start only Redis plus the Celery processes:

```bash
docker run -d --name ikart-redis -p 6379:6379 redis:7.4-alpine
.venv/bin/celery -A ikart worker -l info -Q ikart
.venv/bin/celery -A ikart beat -l info --schedule /tmp/celerybeat-schedule
```

Set `CELERY_TASK_ALWAYS_EAGER=False` and `CELERY_BROKER_URL` in `.env` to route work to that worker. A worker sharing the development SQLite file will hit `database is locked` errors under concurrency, so point `DATABASE_URL` at PostgreSQL before enabling it. `PAYMENT_SWEEP_CRON_MINUTES` controls how often beat schedules the reservation sweep, which is separate from the `PAYMENT_RESERVATION_MINUTES` age threshold.

## Delivery roadmap

## Phase 2 — Growth

Phase 2 is implemented as an additive layer on the Phase 1 shopping loop:

- Wishlists and save-for-later for signed-in customers.
- Saved-address management and choosing a saved address at checkout.
- Admin-managed coupon codes, including percentage/fixed discounts, dates, order thresholds, and usage limits.
- Cancellation and return requests with customer reason codes, Admin approval/refund workflow, and order-status emails.
- Product Q&A, support FAQs, customer support tickets, and Admin replies.
- Behavioural recommendations based on product views and previous baskets.
- Search autocomplete, close-match typo suggestions, and brand/rating/sale filters.
- Shipment tracking records and event timeline, plus email notification logs.
- Store analytics, low-stock visibility, and CSV product imports in Django Admin.

Use **Admin → Products → Import CSV** for a product file with required columns `name`, `category`, `price`, `stock`, and `description`. Optional columns are `brand`, `short_description`, `compare_at_price`, `low_stock_threshold`, `is_featured`, and `is_active`.

Order, shipping, return, and promotion emails use the SMTP setup described above. SMS preferences and notification logging are ready, but actual SMS delivery and carrier live-status synchronization each require a third-party provider/API and its credentials. Phase 3 can add the planned AI features after choosing an AI provider and configuring its API credentials.
