from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from django.contrib.auth import views as auth_views

from storefront.ratelimit import rate_limit
from storefront.views import health_check

urlpatterns = [
    path("healthz/", health_check, name="health_check"),
    path("admin/", admin.site.urls),
    path(
        "accounts/login/",
        rate_limit("login", limit=15, period_seconds=300)(auth_views.LoginView.as_view()),
        name="login",
    ),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("storefront.urls", namespace="storefront")),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
