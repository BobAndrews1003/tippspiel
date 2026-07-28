from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from tipping.models import (
    StandingRebuildJob,
    Tournament,
)


class CleanupStandingJobsTests(TestCase):
    def setUp(self):
        self.tournament = (
            Tournament.objects.create(
                name="Cleanup-Turnier",
            )
        )

    def create_job(
        self,
        *,
        status,
        days_old,
    ):
        job = StandingRebuildJob.objects.create(
            tournament=self.tournament,
            affected_matchdays=[
                1,
            ],
            match_ids=[],
            group_ids=[],
            status=status,
        )

        timestamp = (
            timezone.now()
            - timedelta(
                days=days_old,
            )
        )

        StandingRebuildJob.objects.filter(
            pk=job.id,
        ).update(
            created_at=timestamp,
            finished_at=(
                timestamp
                if status
                in {
                    StandingRebuildJob
                    .Status
                    .COMPLETED,
                    StandingRebuildJob
                    .Status
                    .FAILED,
                }
                else None
            ),
        )

        job.refresh_from_db()

        return job

    def test_cleanup_deletes_only_old_completed_jobs_by_default(
        self,
    ):
        old_completed = self.create_job(
            status=(
                StandingRebuildJob
                .Status
                .COMPLETED
            ),
            days_old=40,
        )

        recent_completed = self.create_job(
            status=(
                StandingRebuildJob
                .Status
                .COMPLETED
            ),
            days_old=10,
        )

        old_failed = self.create_job(
            status=(
                StandingRebuildJob
                .Status
                .FAILED
            ),
            days_old=40,
        )

        pending = self.create_job(
            status=(
                StandingRebuildJob
                .Status
                .PENDING
            ),
            days_old=40,
        )

        call_command(
            "cleanup_standing_jobs",
            older_than_days=30,
            stdout=StringIO(),
        )

        self.assertFalse(
            StandingRebuildJob.objects.filter(
                pk=old_completed.id,
            ).exists()
        )

        self.assertTrue(
            StandingRebuildJob.objects.filter(
                pk=recent_completed.id,
            ).exists()
        )

        self.assertTrue(
            StandingRebuildJob.objects.filter(
                pk=old_failed.id,
            ).exists()
        )

        self.assertTrue(
            StandingRebuildJob.objects.filter(
                pk=pending.id,
            ).exists()
        )

    def test_cleanup_can_include_failed_and_supports_dry_run(
        self,
    ):
        old_failed = self.create_job(
            status=(
                StandingRebuildJob
                .Status
                .FAILED
            ),
            days_old=40,
        )

        output = StringIO()

        call_command(
            "cleanup_standing_jobs",
            older_than_days=30,
            include_failed=True,
            dry_run=True,
            stdout=output,
        )

        self.assertTrue(
            StandingRebuildJob.objects.filter(
                pk=old_failed.id,
            ).exists()
        )

        self.assertIn(
            "1 alte Jobs",
            output.getvalue(),
        )

        call_command(
            "cleanup_standing_jobs",
            older_than_days=30,
            include_failed=True,
            stdout=StringIO(),
        )

        self.assertFalse(
            StandingRebuildJob.objects.filter(
                pk=old_failed.id,
            ).exists()
        )
