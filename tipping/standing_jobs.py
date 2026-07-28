from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import StandingRebuildJob
from .result_processing import (
    process_queued_tournament_rebuild,
)


def _normalize_positive_integers(
    values,
    *,
    field_name: str,
) -> list[int]:
    normalized = set()

    for raw_value in values:
        try:
            value = int(raw_value)

        except (
            TypeError,
            ValueError,
        ) as exc:
            raise ValueError(
                f"{field_name} darf nur "
                "ganze Zahlen enthalten."
            ) from exc

        if value < 1:
            raise ValueError(
                f"{field_name} darf nur Werte "
                "größer oder gleich 1 enthalten."
            )

        normalized.add(value)

    return sorted(normalized)


@transaction.atomic
def enqueue_standing_rebuild(
    *,
    tournament_id: int,
    affected_matchdays,
    match_ids=None,
    group_ids=None,
    rebuild_bonus: bool = False,
) -> StandingRebuildJob:
    """
    Erstellt oder erweitert einen ausstehenden Job.

    group_ids=[] bedeutet alle Gruppen des Turniers.
    Sobald einer der zusammengeführten Jobs alle Gruppen
    betrifft, bleibt der Gesamtauftrag turnierweit.
    """

    normalized_matchdays = (
        _normalize_positive_integers(
            affected_matchdays,
            field_name="affected_matchdays",
        )
    )

    if not normalized_matchdays:
        raise ValueError(
            "Mindestens ein betroffener Spieltag "
            "ist erforderlich."
        )

    normalized_match_ids = (
        _normalize_positive_integers(
            match_ids or [],
            field_name="match_ids",
        )
    )

    normalized_group_ids = (
        _normalize_positive_integers(
            group_ids or [],
            field_name="group_ids",
        )
    )

    pending_jobs = list(
        StandingRebuildJob.objects
        .select_for_update()
        .filter(
            tournament_id=tournament_id,
            status=(
                StandingRebuildJob.Status.PENDING
            ),
        )
        .order_by(
            "created_at",
            "id",
        )
    )

    if not pending_jobs:
        return StandingRebuildJob.objects.create(
            tournament_id=tournament_id,
            affected_matchdays=(
                normalized_matchdays
            ),
            match_ids=normalized_match_ids,
            group_ids=normalized_group_ids,
            rebuild_bonus=rebuild_bonus,
        )

    target_job = pending_jobs[0]

    merged_matchdays = set(
        normalized_matchdays
    )

    merged_match_ids = set(
        normalized_match_ids
    )

    merged_group_ids = set(
        normalized_group_ids
    )

    all_groups = not normalized_group_ids
    merged_rebuild_bonus = rebuild_bonus

    for pending_job in pending_jobs:
        merged_matchdays.update(
            pending_job.affected_matchdays or []
        )

        merged_match_ids.update(
            pending_job.match_ids or []
        )

        pending_group_ids = (
            pending_job.group_ids or []
        )

        if not pending_group_ids:
            all_groups = True

        else:
            merged_group_ids.update(
                pending_group_ids
            )

        merged_rebuild_bonus = (
            merged_rebuild_bonus
            or pending_job.rebuild_bonus
        )

    target_job.affected_matchdays = sorted(
        int(value)
        for value in merged_matchdays
    )

    target_job.match_ids = sorted(
        int(value)
        for value in merged_match_ids
    )

    target_job.group_ids = (
        []
        if all_groups
        else sorted(
            int(value)
            for value in merged_group_ids
        )
    )

    target_job.rebuild_bonus = (
        merged_rebuild_bonus
    )

    target_job.save(
        update_fields=[
            "affected_matchdays",
            "match_ids",
            "group_ids",
            "rebuild_bonus",
            "updated_at",
        ]
    )

    duplicate_ids = [
        pending_job.id
        for pending_job in pending_jobs[1:]
    ]

    if duplicate_ids:
        StandingRebuildJob.objects.filter(
            pk__in=duplicate_ids,
        ).delete()

    return target_job


@transaction.atomic
def recover_stale_standing_rebuild_jobs(
    *,
    stale_minutes: int,
) -> int:
    if stale_minutes < 1:
        raise ValueError(
            "stale_minutes muss mindestens 1 sein."
        )

    now = timezone.now()

    stale_before = (
        now
        - timedelta(
            minutes=stale_minutes,
        )
    )

    return (
        StandingRebuildJob.objects
        .filter(
            status=(
                StandingRebuildJob.Status.RUNNING
            ),
            started_at__isnull=False,
            started_at__lt=stale_before,
        )
        .update(
            status=(
                StandingRebuildJob.Status.PENDING
            ),
            started_at=None,
            finished_at=None,
            processed_groups=0,
            last_error=(
                "Nach möglichem Worker-Abbruch "
                "automatisch erneut freigegeben."
            ),
            updated_at=now,
        )
    )


@transaction.atomic
def claim_next_standing_rebuild_job() -> int | None:
    job = (
        StandingRebuildJob.objects
        .select_for_update()
        .filter(
            status=(
                StandingRebuildJob.Status.PENDING
            ),
        )
        .order_by(
            "created_at",
            "id",
        )
        .first()
    )

    if job is None:
        return None

    job.status = (
        StandingRebuildJob.Status.RUNNING
    )

    job.attempts += 1
    job.started_at = timezone.now()
    job.finished_at = None
    job.last_error = ""

    job.save(
        update_fields=[
            "status",
            "attempts",
            "started_at",
            "finished_at",
            "last_error",
            "updated_at",
        ]
    )

    return job.id


def execute_standing_rebuild_job(
    *,
    job_id: int,
) -> int:
    job = StandingRebuildJob.objects.get(
        pk=job_id,
    )

    if (
        job.status
        != StandingRebuildJob.Status.RUNNING
    ):
        raise ValueError(
            f"Job {job_id} befindet sich nicht "
            "im Status running."
        )

    try:
        processed_groups = (
            process_queued_tournament_rebuild(
                tournament_id=job.tournament_id,
                affected_matchdays=(
                    job.affected_matchdays
                ),
                match_ids=job.match_ids,
                group_ids=job.group_ids,
                rebuild_bonus=(
                    job.rebuild_bonus
                ),
            )
        )

    except Exception as exc:
        StandingRebuildJob.objects.filter(
            pk=job_id,
        ).update(
            status=(
                StandingRebuildJob.Status.FAILED
            ),
            finished_at=timezone.now(),
            last_error=str(exc)[:4000],
        )

        raise

    StandingRebuildJob.objects.filter(
        pk=job_id,
    ).update(
        status=(
            StandingRebuildJob.Status.COMPLETED
        ),
        processed_groups=processed_groups,
        finished_at=timezone.now(),
        last_error="",
    )

    return processed_groups
