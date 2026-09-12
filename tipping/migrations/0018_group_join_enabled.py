from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        (
            "tipping",
            "0017_add_matchday_wins",
        ),
    ]

    operations = [
        migrations.AddField(
            model_name="group",
            name="join_enabled",
            field=models.BooleanField(
                default=True,
                help_text=(
                    "Controla si nuevos usuarios pueden "
                    "unirse mediante el código de acceso."
                ),
            ),
        ),
    ]
