from django.db import migrations


def add_username_column_if_missing(apps, schema_editor):
    """Repare les bases locales creees sans la colonne username."""

    table_name = "accounts_user"
    connection = schema_editor.connection

    with connection.cursor() as cursor:
        columns = [
            column.name
            for column in connection.introspection.get_table_description(
                cursor,
                table_name,
            )
        ]

        if "username" in columns:
            return

        cursor.execute(
            f'ALTER TABLE "{table_name}" ADD COLUMN "username" varchar(150)'
        )

        cursor.execute(f'SELECT "id", "email" FROM "{table_name}"')
        users = cursor.fetchall()

        for user_id, email in users:
            base_username = (email.split("@", 1)[0] if email else "user")[:140]
            username = f"{base_username}_{user_id}"
            cursor.execute(
                f'UPDATE "{table_name}" SET "username" = %s WHERE "id" = %s',
                [username, user_id],
            )

        cursor.execute(
            f'CREATE UNIQUE INDEX "accounts_user_username_repair_uniq" '
            f'ON "{table_name}" ("username")'
        )


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_alter_user_username"),
    ]

    operations = [
        migrations.RunPython(
            add_username_column_if_missing,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
