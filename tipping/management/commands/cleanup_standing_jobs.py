from datetime import timedelta

from django.core.management.base import (
    BaseCommand,
    CommandError,
)
from django.db.models import Q
from django.utils import timezone

from tipping.models import (
    StandingRebuildJob,
)


class Command(BaseCommand):
    help = (
        "Löscht alte abgeschlossene "
        "StandingRebuildJob-Datensätze."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--older-than-days",
            type=int,
            default=30,
            help=(
                "Mindestalter der Jobs in Tagen. "
                "Standard: 30."
            ),
        )

        parser.add_argument(
            "--include-failed",
            action="store_true",
            help=(
                "Löscht zusätzlich alte "
                "fehlgeschlagene Jobs."
            ),
        )

        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Zeigt die Zahl der Jobs, ohne "
                "Datensätze zu löschen."
            ),
        )

    def handle(self, *args, **options):
        older_than_days = options[
            "older_than_days"
        ]

        if older_than_days < 1:
            raise CommandError(
                "--older-than-days muss "
                "mindestens 1 sein."
            )

        statuses = [
            StandingRebuildJob.Status.COMPLETED,
        ]

        if options["include_failed"]:
            statuses.append(
                StandingRebuildJob.Status.FAILED
            )

        cutoff = (
            timezone.now()
            - timedelta(
                days=older_than_days,
            )
        )

        jobs = (
            StandingRebuildJob.objects
            .filter(
                status__in=statuses,
            )
            .filter(
                Q(
                    finished_at__lt=cutoff,
                )
                |
                Q(
                    finished_at__isnull=True,
                    created_at__lt=cutoff,
                )
            )
        )

        job_count = jobs.count()

        if options["dry_run"]:
            self.stdout.write(
                (
                    f"{job_count} alte Jobs "
                    "würden gelöscht."
                )
            )

            return

        jobs.delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"{job_count} alte Jobs gelöscht."
            )
        )
