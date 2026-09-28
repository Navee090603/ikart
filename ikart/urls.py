from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from django.contrib.auth import views as auth_views

from storefront.forms import ChangePasswordForm, LoginForm
from storefront.ratelimit import rate_limit
from django.contrib.sitemaps.views import sitemap

from storefront.sitemaps import SITEMAPS
from storefront.views import health_check, robots_txt

# The admin has its own login form (not django.contrib.auth's), so it needs
# its own rate limit rather than reusing the one on /accounts/login/.
# admin.site.login is already a bound method (self baked in), so it can be
# wrapped directly like any other (request, ...) view callable.
admin.site.login = rate_limit("admin_login", limit=15, period_seconds=300)(admin.site.login)

urlpatterns = [
    path("healthz/", health_check, name="health_check"),
    path("robots.txt", robots_txt, name="robots_txt"),
    path("sitemap.xml", sitemap, {"sitemaps": SITEMAPS}, name="django.contrib.sitemaps.views.sitemap"),
    path(settings.ADMIN_URL, admin.site.urls),
    path(
        "accounts/login/",
        rate_limit("login", limit=15, period_seconds=300)(auth_views.LoginView.as_view(authentication_form=LoginForm)),
        name="login",
    ),
    path(
        "accounts/password_change/",
        auth_views.PasswordChangeView.as_view(form_class=ChangePasswordForm),
        name="password_change",
    ),
    # Django's stock reset view has no rate limit; send it to IKart's limited one.
    path("accounts/password_reset/", RedirectView.as_view(pattern_name="storefront:password_reset")),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("storefront.urls", namespace="storefront")),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
