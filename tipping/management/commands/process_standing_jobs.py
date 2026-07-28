from django.core.management.base import (
    BaseCommand,
    CommandError,
)

from tipping.models import (
    StandingRebuildJob,
)
from tipping.standing_jobs import (
    claim_next_standing_rebuild_job,
    execute_standing_rebuild_job,
)


class Command(BaseCommand):
    help = (
        "Verarbeitet ausstehende "
        "StandingRebuildJob-Aufträge."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=10,
            help=(
                "Maximale Anzahl zu verarbeitender "
                "Aufträge. Standard: 10."
            ),
        )

        parser.add_argument(
            "--retry-failed",
            action="store_true",
            help=(
                "Setzt fehlgeschlagene Aufträge vor "
                "der Verarbeitung erneut auf pending."
            ),
        )

    def handle(self, *args, **options):
        limit = options["limit"]

        if limit < 1:
            raise CommandError(
                "--limit muss mindestens 1 sein."
            )

        if options["retry_failed"]:
            retried = (
                StandingRebuildJob.objects
                .filter(
                    status=(
                        StandingRebuildJob
                        .Status
                        .FAILED
                    ),
                )
                .update(
                    status=(
                        StandingRebuildJob
                        .Status
                        .PENDING
                    ),
                    started_at=None,
                    finished_at=None,
                    last_error="",
                )
            )

            self.stdout.write(
                f"{retried} fehlgeschlagene "
                "Aufträge erneut freigegeben."
            )

        completed = 0
        failed = 0

        for _ in range(limit):
            job_id = (
                claim_next_standing_rebuild_job()
            )

            if job_id is None:
                break

            self.stdout.write(
                f"Verarbeite Job {job_id} ..."
            )

            try:
                processed_groups = (
                    execute_standing_rebuild_job(
                        job_id=job_id,
                    )
                )

            except Exception as exc:
                failed += 1

                self.stderr.write(
                    self.style.ERROR(
                        f"Job {job_id} "
                        f"fehlgeschlagen: {exc}"
                    )
                )

                continue

            completed += 1

            self.stdout.write(
                self.style.SUCCESS(
                    f"Job {job_id} abgeschlossen: "
                    f"{processed_groups} Gruppen."
                )
            )

        self.stdout.write("")

        self.stdout.write(
            (
                "Job-Verarbeitung beendet: "
                f"{completed} abgeschlossen, "
                f"{failed} fehlgeschlagen."
            )
        )
