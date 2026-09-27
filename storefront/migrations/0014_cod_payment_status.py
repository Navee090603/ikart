from django.db import migrations


def settle_cod_payment_status(apps, schema_editor):
    Order = apps.get_model("storefront", "Order")
    cod_pending = Order.objects.filter(payment_method="cod", payment_status="pending")
    cod_pending.filter(status="delivered").update(payment_status="paid")
    cod_pending.filter(status="cancelled").update(payment_status="cancelled")


class Migration(migrations.Migration):

    dependencies = [
        ("storefront", "0013_order_delivered_at"),
    ]

    operations = [
        migrations.RunPython(settle_cod_payment_status, migrations.RunPython.noop),
    ]
