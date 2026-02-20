from datetime import time
from django.core.management.base import BaseCommand
from django.utils import timezone

from tipping.models import Match


class Command(BaseCommand):
    help = "Set kickoff time to 23:59 for matches that still have the default 12:00 time."

    def add_arguments(self, parser):
        parser.add_argument("--only-tournament", type=str, default=None, help="Optional tournament name filter")

    def handle(self, *args, **options):
        only_tournament = options["only_tournament"]
        tz = timezone.get_current_timezone()

        qs = Match.objects.all()
        if only_tournament:
            qs = qs.filter(tournament__name=only_tournament)

        changed = 0
        for m in qs:
            # Nur ändern, wenn Uhrzeit genau 12:00 ist (dein bisheriger Default)
            if m.kickoff and m.kickoff.astimezone(tz).time() == time(12, 0):
                local_dt = m.kickoff.astimezone(tz)
                new_local = local_dt.replace(hour=23, minute=59, second=0, microsecond=0)
                m.kickoff = new_local.astimezone(timezone.UTC) if timezone.is_aware(m.kickoff) else new_local
                m.save(update_fields=["kickoff"])
                changed += 1

        self.stdout.write(self.style.SUCCESS(f"Kickoffs updated: {changed}"))
