import django.db.models.manager
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        (
            "tipping",
            "0018_group_join_enabled",
        ),
    ]

    operations = [
        migrations.AddField(
            model_name="groupmembership",
            name="is_active",
            field=models.BooleanField(
                default=True,
            ),
        ),
        migrations.AddField(
            model_name="groupmembership",
            name="removed_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
            ),
        ),
        migrations.AlterModelOptions(
            name="groupmembership",
            options={
                "base_manager_name": "all_objects",
                "default_manager_name": "objects",
            },
        ),
        migrations.AlterModelManagers(
            name="groupmembership",
            managers=[
                (
                    "objects",
                    django.db.models.manager.Manager(),
                ),
                (
                    "all_objects",
                    django.db.models.manager.Manager(),
                ),
            ],
        ),
    ]
