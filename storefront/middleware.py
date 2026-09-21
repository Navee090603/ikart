class ContentSecurityPolicyMiddleware:
    """Adds a pragmatic CSP header.

    Templates rely on inline <script>/<style> blocks and the Tailwind CDN, so
    this isn't a strict CSP — 'unsafe-inline' is required for script/style to
    avoid breaking the existing UI. It still restricts the categories that
    matter most for this app: no third-party script hosts beyond Tailwind's
    CDN, no framing (clickjacking), no arbitrary form targets.
    """

    CSP = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://checkout.razorpay.com; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "font-src 'self' data:; "
        "connect-src 'self' https://*.razorpay.com; "
        "frame-src 'self' https://*.razorpay.com; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self';"
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault("Content-Security-Policy", self.CSP)
        return response
