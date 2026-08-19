from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import (
    call_command,
)
from django.test import TransactionTestCase
from django.utils import timezone

from tipping.models import (
    StandingRebuildJob,
    Tournament,
)
from tipping.standing_jobs import (
    recover_stale_standing_rebuild_jobs,
)


class StandingWorkerResilienceTests(
    TransactionTestCase
):
    def setUp(self):
        self.tournament = (
            Tournament.objects.create(
                name="Worker-Resilience-Turnier",
            )
        )

    def test_only_stale_running_jobs_are_requeued(
        self,
    ):
        now = timezone.now()

        stale_job = (
            StandingRebuildJob.objects.create(
                tournament=self.tournament,
                affected_matchdays=[
                    1,
                ],
                match_ids=[],
                status=(
                    StandingRebuildJob
                    .Status
                    .RUNNING
                ),
                attempts=1,
                started_at=(
                    now
                    - timedelta(hours=2)
                ),
            )
        )

        recent_job = (
            StandingRebuildJob.objects.create(
                tournament=self.tournament,
                affected_matchdays=[
                    2,
                ],
                match_ids=[],
                status=(
                    StandingRebuildJob
                    .Status
                    .RUNNING
                ),
                attempts=1,
                started_at=(
                    now
                    - timedelta(minutes=10)
                ),
            )
        )

        recovered = (
            recover_stale_standing_rebuild_jobs(
                stale_minutes=60,
            )
        )

        self.assertEqual(
            recovered,
            1,
        )

        stale_job.refresh_from_db()
        recent_job.refresh_from_db()

        self.assertEqual(
            stale_job.status,
            StandingRebuildJob.Status.PENDING,
        )

        self.assertIsNone(
            stale_job.started_at
        )

        self.assertEqual(
            stale_job.attempts,
            1,
        )

        self.assertEqual(
            recent_job.status,
            StandingRebuildJob.Status.RUNNING,
        )

    def test_watch_mode_stops_cleanly(
        self,
    ):
        output = StringIO()
        errors = StringIO()

        with patch(
            (
                "tipping.management.commands."
                "process_standing_jobs.sleep"
            ),
            side_effect=KeyboardInterrupt,
        ):
            call_command(
                "process_standing_jobs",
                watch=True,
                limit=1,
                poll_seconds=0.1,
                stale_minutes=60,
                stdout=output,
                stderr=errors,
            )

        self.assertIn(
            "Standing-Worker läuft",
            output.getvalue(),
        )

        self.assertIn(
            "Standing-Worker beendet",
            output.getvalue(),
        )
