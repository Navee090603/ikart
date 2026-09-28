from django.apps import AppConfig


class StorefrontConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "storefront"

    def ready(self):
        from django.contrib.auth.signals import user_logged_in

        from .services import claim_guest_orders

        user_logged_in.connect(
            lambda sender, request, user, **kwargs: claim_guest_orders(user),
            weak=False,
            dispatch_uid="storefront.claim_guest_orders",
        )
