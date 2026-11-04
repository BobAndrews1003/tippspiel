from django.core.management.base import BaseCommand
from django.db import transaction

from tipping.models import Season, Tournament
from tipping.tournament_stages import ensure_default_stages


COMPETITIONS = (
    ("ligapro", "LigaPro 2027"),
    ("copa-ecuador", "Copa Ecuador 2027"),
    ("copa-de-la-liga", "Copa de la Liga 2027"),
)


class Command(BaseCommand):
    help = (
        "Legt die Saison 2027 und die drei vorgesehenen "
        "ecuadorianischen Wettbewerbe idempotent an."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--open-for-groups",
            action="store_true",
            help=(
                "Bietet die Wettbewerbe sofort bei der "
                "Gruppenerstellung an. Ohne diese Option bleiben sie "
                "bis zur Freigabe im Admin verborgen."
            ),
        )

    @transaction.atomic
    def handle(self, *args, **options):
        open_for_groups = options["open_for_groups"]
        season, _created = Season.objects.update_or_create(
            year=2027,
            defaults={
                "name": "Temporada 2027",
                "is_open_for_groups": open_for_groups,
            },
        )

        for code, name in COMPETITIONS:
            tournament, created = Tournament.objects.update_or_create(
                season=season,
                code=code,
                defaults={
                    "name": name,
                    "is_selectable": open_for_groups,
                },
            )
            ensure_default_stages(tournament)
            state = "angelegt" if created else "aktualisiert"
            self.stdout.write(f"{name}: {state}")

        visibility = (
            "für neue Gruppen geöffnet"
            if open_for_groups
            else "bis zur Admin-Freigabe verborgen"
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Temporada 2027 ist {visibility}."
            )
        )
