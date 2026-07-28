from time import sleep

from django.core.management.base import (
    BaseCommand,
    CommandError,
)
from django.db import (
    close_old_connections,
    connection,
)
from django.utils import timezone

from tipping.models import (
    StandingRebuildJob,
)
from tipping.standing_jobs import (
    claim_next_standing_rebuild_job,
    execute_standing_rebuild_job,
    recover_stale_standing_rebuild_jobs,
)


class Command(BaseCommand):
    help = (
        "Verarbeitet ausstehende "
        "StandingRebuildJob-Aufträge."
    )

    requires_migrations_checks = True

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=10,
            help=(
                "Maximale Anzahl Jobs pro Durchlauf. "
                "Standard: 10."
            ),
        )

        parser.add_argument(
            "--retry-failed",
            action="store_true",
            help=(
                "Setzt fehlgeschlagene Jobs beim Start "
                "erneut auf pending."
            ),
        )

        parser.add_argument(
            "--watch",
            action="store_true",
            help=(
                "Lässt den Worker kontinuierlich laufen."
            ),
        )

        parser.add_argument(
            "--poll-seconds",
            type=float,
            default=2.0,
            help=(
                "Wartezeit zwischen leeren Prüfungen "
                "im Watch-Modus. Standard: 2 Sekunden."
            ),
        )

        parser.add_argument(
            "--stale-minutes",
            type=int,
            default=60,
            help=(
                "Running-Jobs werden nach dieser Zeit "
                "erneut freigegeben. Standard: 60 Minuten."
            ),
        )

    def _retry_failed_jobs(self) -> int:
        now = timezone.now()

        return (
            StandingRebuildJob.objects
            .filter(
                status=(
                    StandingRebuildJob.Status.FAILED
                ),
            )
            .update(
                status=(
                    StandingRebuildJob.Status.PENDING
                ),
                started_at=None,
                finished_at=None,
                processed_groups=0,
                last_error="",
                updated_at=now,
            )
        )

    def _recover_stale_jobs(
        self,
        *,
        stale_minutes: int,
    ) -> int:
        recovered = (
            recover_stale_standing_rebuild_jobs(
                stale_minutes=stale_minutes,
            )
        )

        if recovered:
            self.stdout.write(
                self.style.WARNING(
                    f"{recovered} festhängende "
                    "Jobs erneut freigegeben."
                )
            )

        return recovered

    def _process_cycle(
        self,
        *,
        limit: int,
    ) -> tuple[int, int]:
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

        return (
            completed,
            failed,
        )

    def _run_once(
        self,
        *,
        limit: int,
        stale_minutes: int,
    ) -> None:
        self._recover_stale_jobs(
            stale_minutes=stale_minutes,
        )

        completed, failed = (
            self._process_cycle(
                limit=limit,
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

    def _run_watch(
        self,
        *,
        limit: int,
        poll_seconds: float,
        stale_minutes: int,
    ) -> None:
        if connection.vendor == "sqlite":
            self.stderr.write(
                self.style.WARNING(
                    "SQLite erkannt: Es darf nur ein "
                    "Standing-Worker gleichzeitig laufen."
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                "Standing-Worker läuft. "
                "Beenden mit Ctrl+C."
            )
        )

        try:
            while True:
                close_old_connections()

                recovered = (
                    self._recover_stale_jobs(
                        stale_minutes=(
                            stale_minutes
                        ),
                    )
                )

                completed, failed = (
                    self._process_cycle(
                        limit=limit,
                    )
                )

                processed = (
                    completed
                    + failed
                )

                if (
                    recovered
                    or processed
                ):
                    self.stdout.write(
                        (
                            "Durchlauf beendet: "
                            f"{completed} abgeschlossen, "
                            f"{failed} fehlgeschlagen."
                        )
                    )

                close_old_connections()

                # Bei einer vollständig gefüllten Charge
                # könnten weitere Jobs warten. Dann wird
                # ohne künstliche Pause weitergemacht.
                if processed < limit:
                    sleep(
                        poll_seconds
                    )

        except KeyboardInterrupt:
            self.stdout.write("")

            self.stdout.write(
                self.style.WARNING(
                    "Standing-Worker beendet."
                )
            )

        finally:
            close_old_connections()

    def handle(self, *args, **options):
        limit = options["limit"]
        poll_seconds = options[
            "poll_seconds"
        ]
        stale_minutes = options[
            "stale_minutes"
        ]

        if limit < 1:
            raise CommandError(
                "--limit muss mindestens 1 sein."
            )

        if poll_seconds < 0.1:
            raise CommandError(
                "--poll-seconds muss mindestens "
                "0.1 sein."
            )

        if stale_minutes < 1:
            raise CommandError(
                "--stale-minutes muss mindestens "
                "1 sein."
            )

        if options["retry_failed"]:
            retried = (
                self._retry_failed_jobs()
            )

            self.stdout.write(
                f"{retried} fehlgeschlagene "
                "Jobs erneut freigegeben."
            )

        if options["watch"]:
            self._run_watch(
                limit=limit,
                poll_seconds=poll_seconds,
                stale_minutes=stale_minutes,
            )

            return

        self._run_once(
            limit=limit,
            stale_minutes=stale_minutes,
        )
