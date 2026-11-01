from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from .models import (
    Group,
    GroupScoringSettings,
)
from .scoring_config import (
    ScoringValues,
    STANDARD_SCORING_VALUES,
)


def ensure_group_scoring_settings(
    group: Group,
) -> GroupScoringSettings:
    settings, _created = (
        GroupScoringSettings.objects.get_or_create(
            group=group,
        )
    )

    return settings


def scoring_values_for_group(
    group: Group | None,
) -> ScoringValues:
    if group is None or group.pk is None:
        return STANDARD_SCORING_VALUES

    try:
        scoring_settings = group.scoring_settings
    except GroupScoringSettings.DoesNotExist:
        return STANDARD_SCORING_VALUES

    return ScoringValues(
        exact_points=scoring_settings.exact_points,
        goal_difference_points=(
            scoring_settings.goal_difference_points
        ),
        tendency_points=scoring_settings.tendency_points,
        incorrect_points=scoring_settings.incorrect_points,
    )


@transaction.atomic
def lock_group_scoring_settings(
    group_id: int,
) -> GroupScoringSettings:
    scoring_settings, _created = (
        GroupScoringSettings.objects
        .select_for_update()
        .get_or_create(
            group_id=group_id,
        )
    )

    if scoring_settings.locked_at is None:
        scoring_settings.locked_at = timezone.now()
        scoring_settings.save(
            update_fields=[
                "locked_at",
                "updated_at",
            ],
        )

    return scoring_settings
