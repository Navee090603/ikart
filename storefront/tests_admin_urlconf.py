"""URLconf with the admin moved off /admin/, for testing links that must follow ADMIN_URL."""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("staff-test/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("storefront.urls", namespace="storefront")),
]
