from django.db import migrations

# A migration that never made it into the codebase added these SMS-verification
# columns to some databases. No model uses them, so drop them where they exist
# (fresh databases never had them, so this is a no-op there).
ORPHAN_COLUMNS = ("is_phone_verified", "phone_otp", "phone_otp_expires_at", "phone_verified_at")
ORPHAN_MIGRATION = "0013_userprofile_is_phone_verified_userprofile_phone_otp_and_more"


def drop_orphan_sms_columns(apps, schema_editor):
    connection = schema_editor.connection
    table = "storefront_userprofile"
    with connection.cursor() as cursor:
        existing = {column.name for column in connection.introspection.get_table_description(cursor, table)}
        for column in ORPHAN_COLUMNS:
            if column in existing:
                cursor.execute(
                    f"ALTER TABLE {schema_editor.quote_name(table)} DROP COLUMN {schema_editor.quote_name(column)}"
                )
        cursor.execute("DELETE FROM django_migrations WHERE app = %s AND name = %s", ["storefront", ORPHAN_MIGRATION])


class Migration(migrations.Migration):
    dependencies = [("storefront", "0014_cod_payment_status")]

    operations = [migrations.RunPython(drop_orphan_sms_columns, migrations.RunPython.noop)]
