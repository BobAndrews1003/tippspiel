from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
import logging

from allauth.account.models import EmailAddress
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .models import (
    GroupMembership,
    Match,
    Prediction,
    TipReminderDelivery,
    UserProfile,
)
from .tournament_stages import matchday_label_for_match


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TipReminderRunResult:
    enabled: bool
    dry_run: bool
    candidate_matches: int
    due_deliveries: int
    recipients: int
    deliveries_created: int
    users_without_verified_email: int
    failures: int


def _absolute_url(path: str) -> str:
    return (
        f"{settings.PUBLIC_BASE_URL}"
        f"{path}"
    )


def _verified_email_by_user(
    user_ids: set[int],
) -> dict[int, str]:
    addresses = (
        EmailAddress.objects
        .filter(
            user_id__in=user_ids,
            verified=True,
        )
        .order_by(
            "user_id",
            "-primary",
            "id",
        )
        .values_list(
            "user_id",
            "email",
        )
    )

    result: dict[int, str] = {}

    for user_id, email in addresses:
        normalized_email = email.strip()

        if (
            user_id not in result
            and normalized_email
        ):
            result[user_id] = normalized_email

    return result


def _build_sections(
    pending_items,
) -> list[dict]:
    grouped = defaultdict(list)

    for membership, match in pending_items:
        grouped[
            (
                membership.group_id,
                match.matchday,
            )
        ].append(
            (
                membership,
                match,
            )
        )

    sections = []

    for items in grouped.values():
        membership = items[0][0]
        matches = sorted(
            (
                item[1]
                for item in items
            ),
            key=lambda match: (
                match.kickoff,
                match.id,
            ),
        )
        matchday = matches[0].matchday
        path = reverse(
            "group_tip_redirect",
            args=[
                membership.group_id,
            ],
        )

        if matchday is not None:
            path = f"{path}?md={matchday}"

        sections.append(
            {
                "group": membership.group,
                "matchday": matchday,
                "matchday_label": (
                    matchday_label_for_match(
                        matches[0]
                    )
                ),
                "matches": matches,
                "tip_url": _absolute_url(path),
            }
        )

    return sorted(
        sections,
        key=lambda section: (
            section["matches"][0].kickoff,
            section["group"].name.lower(),
            section["group"].id,
        ),
    )


def _send_user_reminder(
    *,
    email: str,
    user,
    pending_items,
) -> bool:
    context = {
        "user": user,
        "sections": _build_sections(
            pending_items
        ),
        "settings_url": _absolute_url(
            reverse(
                "notification_settings"
            )
        ),
    }

    subject = render_to_string(
        "tipping/email/tip_reminder_subject.txt",
        context,
    )
    subject = " ".join(
        subject.splitlines()
    ).strip()

    text_body = render_to_string(
        "tipping/email/tip_reminder.txt",
        context,
    )
    html_body = render_to_string(
        "tipping/email/tip_reminder.html",
        context,
    )

    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[
            email,
        ],
        headers={
            "List-Unsubscribe": (
                f'<{context["settings_url"]}>'
            ),
        },
    )
    message.attach_alternative(
        html_body,
        "text/html",
    )

    return message.send(
        fail_silently=False
    ) == 1


def send_due_tip_reminders(
    *,
    now=None,
    dry_run: bool = False,
) -> TipReminderRunResult:
    """
    Versendet eine gebündelte Erinnerung je Nutzer.

    Ein Versand wird erst nach erfolgreicher Übergabe an das
    E-Mail-Backend pro Nutzer, Gruppe und Spiel protokolliert.
    """

    feature_enabled = bool(
        settings.TIP_REMINDERS_ENABLED
    )

    if not feature_enabled and not dry_run:
        return TipReminderRunResult(
            enabled=False,
            dry_run=False,
            candidate_matches=0,
            due_deliveries=0,
            recipients=0,
            deliveries_created=0,
            users_without_verified_email=0,
            failures=0,
        )

    current_time = now or timezone.now()
    reminder_deadline = (
        current_time
        + timedelta(
            hours=(
                settings
                .TIP_REMINDER_LEAD_HOURS
            ),
        )
    )

    candidate_matches = list(
        Match.objects
        .filter(
            kickoff__gt=current_time,
            kickoff__lte=reminder_deadline,
            home_score__isnull=True,
            away_score__isnull=True,
        )
        .select_related(
            "tournament",
            "stage",
        )
        .order_by("kickoff", "id")
    )

    if not candidate_matches:
        return TipReminderRunResult(
            enabled=feature_enabled,
            dry_run=dry_run,
            candidate_matches=0,
            due_deliveries=0,
            recipients=0,
            deliveries_created=0,
            users_without_verified_email=0,
            failures=0,
        )

    profiles = list(
        UserProfile.objects
        .filter(
            tip_reminders_enabled=True,
            user__is_active=True,
        )
        .select_related("user")
    )
    users_by_id = {
        profile.user_id: profile.user
        for profile in profiles
    }
    user_ids = set(users_by_id)

    if not user_ids:
        return TipReminderRunResult(
            enabled=feature_enabled,
            dry_run=dry_run,
            candidate_matches=len(
                candidate_matches
            ),
            due_deliveries=0,
            recipients=0,
            deliveries_created=0,
            users_without_verified_email=0,
            failures=0,
        )

    matches_by_tournament = defaultdict(list)

    for match in candidate_matches:
        matches_by_tournament[
            match.tournament_id
        ].append(match)

    memberships = list(
        GroupMembership.objects
        .filter(
            user_id__in=user_ids,
            group__tournament_id__in=(
                matches_by_tournament.keys()
            ),
        )
        .select_related(
            "group",
            "group__tournament",
        )
        .order_by("user_id", "group_id")
    )
    group_ids = {
        membership.group_id
        for membership in memberships
    }
    match_ids = {
        match.id
        for match in candidate_matches
    }

    complete_predictions = set(
        Prediction.objects
        .filter(
            user_id__in=user_ids,
            group_id__in=group_ids,
            match_id__in=match_ids,
            pred_home__isnull=False,
            pred_away__isnull=False,
        )
        .values_list(
            "user_id",
            "group_id",
            "match_id",
        )
    )

    delivered = set(
        TipReminderDelivery.objects
        .filter(
            user_id__in=user_ids,
            group_id__in=group_ids,
            match_id__in=match_ids,
        )
        .values_list(
            "user_id",
            "group_id",
            "match_id",
        )
    )

    pending_by_user = defaultdict(list)

    for membership in memberships:
        for match in matches_by_tournament[
            membership.group.tournament_id
        ]:
            key = (
                membership.user_id,
                membership.group_id,
                match.id,
            )

            if (
                key in complete_predictions
                or key in delivered
            ):
                continue

            pending_by_user[
                membership.user_id
            ].append(
                (
                    membership,
                    match,
                )
            )

    due_deliveries = sum(
        len(items)
        for items in pending_by_user.values()
    )
    verified_emails = _verified_email_by_user(
        set(pending_by_user)
    )
    recipients = 0
    deliveries_created = 0
    users_without_verified_email = 0
    failures = 0

    for user_id, pending_items in (
        pending_by_user.items()
    ):
        email = verified_emails.get(user_id)

        if not email:
            users_without_verified_email += 1
            continue

        if dry_run:
            recipients += 1
            continue

        try:
            sent = _send_user_reminder(
                email=email,
                user=users_by_id[user_id],
                pending_items=pending_items,
            )

            if not sent:
                failures += 1
                logger.error(
                    "Tipperinnerung wurde vom "
                    "E-Mail-Backend nicht versendet "
                    "(user_id=%s).",
                    user_id,
                )
                continue

            deliveries = [
                TipReminderDelivery(
                    user_id=user_id,
                    group_id=(
                        membership.group_id
                    ),
                    match_id=match.id,
                )
                for membership, match
                in pending_items
            ]
            TipReminderDelivery.objects.bulk_create(
                deliveries,
                ignore_conflicts=True,
            )
            recipients += 1
            deliveries_created += len(
                deliveries
            )

        except Exception:
            failures += 1
            logger.exception(
                "Tipperinnerung fehlgeschlagen "
                "(user_id=%s).",
                user_id,
            )

    return TipReminderRunResult(
        enabled=feature_enabled,
        dry_run=dry_run,
        candidate_matches=len(
            candidate_matches
        ),
        due_deliveries=due_deliveries,
        recipients=recipients,
        deliveries_created=(
            deliveries_created
        ),
        users_without_verified_email=(
            users_without_verified_email
        ),
        failures=failures,
    )
