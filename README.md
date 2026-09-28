# IKart — AI-Powered Fashion E-Commerce

IKart is a mobile-responsive, Django-based e-commerce platform for Indian fashion retail. It combines a complete customer shopping loop with AI-powered shopping assistance (Lux), flexible product variants, and comprehensive order management.

## Current Features

### Phase 1 — Core Shopping
- Home page with promotion area, category navigation, and featured products.
- Category browsing, keyword search, price filters, and product sorting.
- Product detail pages with image gallery, descriptions, specifications, variants, stock availability, and customer reviews.
- Guest or signed-in, session-backed cart with quantity updates, removal, and live totals.
- Checkout with delivery details, standard/express options, cash on delivery, confirmation email, and order confirmation.
- Email OTP verification on signup, account sign-in, and order history; guests can still check out.
- Admin-managed products, multiple images, size/color variants, inventory, orders, and order-status updates.
- Privacy, terms, return, and secure-checkout trust pages.

### Phase 2 — Growth & Intelligence
- **Lux AI Assistant** — Groq-powered chatbot for product recommendations, order tracking, delivery info, return policies, and 24/7 customer support.
- **Mobile Number at Signup** — Indian-format validation (10-digit, starting with 6-9). Stored as `+91XXXXXXXXXX`, pre-fills checkout, editable on My Account.
- **Flexible Variant Selection** — Button grids for product sizes/colors/attributes (not dropdowns). Admin sets `primary_variant_attribute` per product.
- **Wishlists and save-for-later** for signed-in customers.
- **Saved-address management** and choosing a saved address at checkout.
- **Admin-managed coupon codes** — percentage/fixed discounts, dates, order thresholds, usage limits.
- **Cancellation and return requests** — customer reason codes, admin approval/refund workflow, order-status emails.
- **Refund tracking** — shows refund amount, timeline (5–7 working days), reference, and ARN (bank reference number).
- **Product Q&A, support FAQs, customer support tickets**, and admin replies.
- **Behavioral recommendations** based on product views and previous baskets.
- **Search autocomplete, close-match typo suggestions**, brand/rating/sale filters.
- **Shipment tracking records** and event timeline, plus email notification logs.
- **Store analytics, low-stock visibility**, and CSV product imports in Django Admin.

### Payment & Delivery
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

## Production Deployment

**Live deployment:** `ikart-sg` on Render (Singapore region) with Neon Postgres (ap-southeast-1) for low-latency access across India.

`render.yaml` and `build.sh` are ready for Render. Before deploying, set these values in Render:

- `DATABASE_URL`: Neon connection string with `sslmode=require` (for India region, use ap-southeast-1).
- `CLOUDINARY_URL`: Cloudinary environment URL for hosted catalog images with strict transformations enabled.
- `ALLOWED_HOSTS`: the Render hostname (and any custom domain).
- `DEBUG=False`.
- `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET` (test mode for development, live keys for production).
- `RAZORPAY_WEBHOOK_SECRET` for payment webhook verification.
- `GROQ_API_KEY` for Lux AI assistant (free tier available).
- SMTP sender values: `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, and `DEFAULT_FROM_EMAIL` (Brevo recommended for India).
- `ADMIN_URL` for custom admin dashboard path (security through obscurity).

Render provides HTTPS and auto-deploys from the `main` branch. Use a real random `SECRET_KEY` in production. The application uses local SQLite/media during development, then automatically moves to Neon and Cloudinary once their environment variables are provided.

## Lux AI Assistant Setup

Lux is a Groq-powered chatbot integrated into the storefront. It provides:
- Real-time product recommendations based on customer queries
- Order status tracking for signed-in customers
- Delivery timeline and return policy information
- 24/7 availability with knowledge of store policies and FAQ

**To enable Lux:**
1. Get a free Groq API key from https://console.groq.com/
2. Set `GROQ_API_KEY=your-key` in `.env` (development) or Render environment (production).
3. The chatbot widget appears on all pages in the bottom-right corner.

Lux uses `openai/gpt-oss-20b` model by default and can be swapped to other providers (Claude, OpenAI) by changing `AI_PROVIDER` setting without code changes.

## Razorpay test-mode setup

1. In the Razorpay Dashboard, create or copy **Test Mode** API keys and set `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET` in `.env` (never commit them).
2. Start the site and select **Card / UPI (Razorpay)** at checkout. Use Razorpay’s test payment methods; no real money is taken in test mode.
3. Once the site has a public HTTPS URL, create a Razorpay webhook for `https://YOUR-DOMAIN/payments/razorpay/webhook/`, subscribe to `payment.captured`, `payment.failed`, `order.paid`, `refund.processed`, and `refund.failed`, then copy the webhook secret into `RAZORPAY_WEBHOOK_SECRET`.
4. Configure Razorpay payment capture for the account. IKart also attempts to capture an authorised payment, while the signed webhook handles delayed confirmations and payment failures.

The payment amount is created and checked on the server from the current cart quote; the browser only opens Razorpay Checkout and returns its signed result. A payment failure/cancellation restores inventory and leaves the customer’s cart available to retry.

Run `.venv/bin/python manage.py release_stale_payment_reservations` every 15 minutes in production (or use the **Payment transactions** admin action) to release abandoned checkout reservations. Set `PAYMENT_RESERVATION_MINUTES` if the default 30-minute hold does not suit the store.

## Delivery Roadmap

### ✅ Phase 2 — Growth & Intelligence (Complete)

- ✅ Lux AI Assistant (Groq-powered product recommendations, order tracking, support)
- ✅ Mobile number collection at signup (Indian format validation, stored on profile)
- ✅ Flexible variant button grid UI (size, color, any custom attribute)
- ✅ Refund tracking with ARN (bank reference number)
- ✅ Wishlists and save-for-later for signed-in customers
- ✅ Saved-address management and choosing a saved address at checkout
- ✅ Admin-managed coupon codes (percentage/fixed discounts, dates, order thresholds, usage limits)
- ✅ Cancellation and return requests (customer reason codes, admin approval/refund workflow, order-status emails)
- ✅ Product Q&A, support FAQs, customer support tickets, and admin replies
- ✅ Behavioral recommendations based on product views and previous baskets
- ✅ Search autocomplete, close-match typo suggestions, brand/rating/sale filters
- ✅ Shipment tracking records and event timeline, plus email notification logs
- ✅ Store analytics, low-stock visibility, and CSV product imports in Django Admin
- ✅ Singapore hosting on Render with Neon Postgres (ap-southeast-1)

### 🔧 Phase 3 — Scaling & Localization (Planned)

- SMS OTP verification for mobile numbers
- WhatsApp/SMS customer notifications
- Multi-language support (Hindi, Tamil, Telugu, Kannada)
- Regional payment methods (UPI enhancements, bank transfers)
- Lux mobile app (iOS/Android)
- Admin analytics dashboard
- Inventory forecasting and low-stock automation
- Dynamic pricing based on inventory/demand

### Admin Features

Use **Admin → Products → Import CSV** for a product file with required columns `name`, `category`, `price`, `stock`, and `description`. Optional columns are `brand`, `short_description`, `compare_at_price`, `low_stock_threshold`, `is_featured`, and `is_active`.

Order, shipping, return, and promotion emails use the SMTP setup described above. SMS preferences and notification logging are ready, but actual SMS delivery and carrier live-status synchronization each require a third-party provider/API and its credentials.
