from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging

from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.db.models.functions import Coalesce
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .models import (
    AccountRetentionNotice,
    Group,
)


logger = logging.getLogger(__name__)

FIRST_WARNING = "first"
FINAL_WARNING = "final"


@dataclass(frozen=True)
class AccountRetentionNoticeRunResult:
    enabled: bool
    dry_run: bool
    first_due: int
    final_due: int
    sent: int
    users_without_verified_email: int
    failures: int


@dataclass(frozen=True)
class _NoticeCandidate:
    user_id: int
    inactivity_since: object
    stage: str


@dataclass(frozen=True)
class _ClaimedNotice:
    state_id: int
    claimed_at: object
    stage: str
    email: str
    user: object
    inactivity_since: object
    deletion_not_before: object
    owns_groups: bool


def _absolute_url(path: str) -> str:
    return f"{settings.PUBLIC_BASE_URL}{path}"


def _claim_cutoff(now):
    return now - timedelta(
        minutes=(
            settings
            .ACCOUNT_RETENTION_NOTICE_CLAIM_STALE_MINUTES
        ),
    )


def _stage_due(
    *,
    state,
    inactivity_since,
    now,
) -> str | None:
    first_due_at = (
        inactivity_since
        + timedelta(
            days=(
                settings.DATA_RETENTION_INACTIVE_ACCOUNT_DAYS
                - settings.ACCOUNT_RETENTION_FIRST_NOTICE_DAYS
            ),
        )
    )

    if now < first_due_at:
        return None

    same_cycle = (
        state is not None
        and state.inactivity_since == inactivity_since
    )

    if not same_cycle or state.first_warning_sent_at is None:
        first_claim = (
            state.first_warning_claimed_at
            if same_cycle
            else None
        )

        if (
            first_claim is not None
            and first_claim > _claim_cutoff(now)
        ):
            return None

        return FIRST_WARNING

    if state.final_warning_sent_at is not None:
        return None

    final_due_at = max(
        inactivity_since
        + timedelta(
            days=(
                settings.DATA_RETENTION_INACTIVE_ACCOUNT_DAYS
                - settings.ACCOUNT_RETENTION_FINAL_NOTICE_DAYS
            ),
        ),
        state.first_warning_sent_at
        + timedelta(
            days=(
                settings.ACCOUNT_RETENTION_FIRST_NOTICE_DAYS
                - settings.ACCOUNT_RETENTION_FINAL_NOTICE_DAYS
            ),
        ),
    )

    if now < final_due_at:
        return None

    if (
        state.final_warning_claimed_at is not None
        and state.final_warning_claimed_at
        > _claim_cutoff(now)
    ):
        return None

    return FINAL_WARNING


def _candidate_users(*, now):
    verified_addresses = EmailAddress.objects.filter(
        user_id=OuterRef("pk"),
        verified=True,
    )

    return (
        get_user_model().objects
        .annotate(
            retention_last_activity=Coalesce(
                "last_login",
                "date_joined",
            ),
            retention_has_verified_email=Exists(
                verified_addresses,
            ),
        )
        .filter(
            is_active=True,
            is_staff=False,
            is_superuser=False,
            retention_has_verified_email=True,
            retention_last_activity__lte=(
                now
                - timedelta(
                    days=(
                        settings
                        .DATA_RETENTION_INACTIVE_ACCOUNT_DAYS
                        - settings
                        .ACCOUNT_RETENTION_FIRST_NOTICE_DAYS
                    ),
                )
            ),
        )
        .order_by(
            "retention_last_activity",
            "pk",
        )
    )


def _due_candidates(
    *,
    now,
    limit: int,
) -> list[_NoticeCandidate]:
    users = list(
        _candidate_users(now=now)
    )
    states = {
        state.user_id: state
        for state in (
            AccountRetentionNotice.objects
            .filter(
                user_id__in=[
                    user.pk
                    for user in users
                ],
            )
        )
    }
    candidates = []

    for user in users:
        stage = _stage_due(
            state=states.get(user.pk),
            inactivity_since=(
                user.retention_last_activity
            ),
            now=now,
        )

        if stage is None:
            continue

        candidates.append(
            _NoticeCandidate(
                user_id=user.pk,
                inactivity_since=(
                    user.retention_last_activity
                ),
                stage=stage,
            )
        )

    candidates.sort(
        key=lambda candidate: (
            0
            if candidate.stage == FINAL_WARNING
            else 1,
            candidate.inactivity_since,
            candidate.user_id,
        )
    )

    return candidates[:limit]


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
    result = {}

    for user_id, email in addresses:
        normalized_email = email.strip()

        if user_id not in result and normalized_email:
            result[user_id] = normalized_email

    return result


def _reset_for_new_cycle(
    *,
    state,
    inactivity_since,
) -> None:
    state.inactivity_since = inactivity_since
    state.first_warning_claimed_at = None
    state.first_warning_sent_at = None
    state.final_warning_claimed_at = None
    state.final_warning_sent_at = None
    state.save(
        update_fields=[
            "inactivity_since",
            "first_warning_claimed_at",
            "first_warning_sent_at",
            "final_warning_claimed_at",
            "final_warning_sent_at",
            "updated_at",
        ]
    )


def _deletion_not_before(
    *,
    inactivity_since,
    stage: str,
    now,
):
    warning_days = (
        settings.ACCOUNT_RETENTION_FINAL_NOTICE_DAYS
        if stage == FINAL_WARNING
        else settings.ACCOUNT_RETENTION_FIRST_NOTICE_DAYS
    )

    return max(
        inactivity_since
        + timedelta(
            days=settings.DATA_RETENTION_INACTIVE_ACCOUNT_DAYS,
        ),
        now + timedelta(days=warning_days),
    )


def _claim_notice(
    *,
    candidate: _NoticeCandidate,
    now,
) -> _ClaimedNotice | None:
    user_model = get_user_model()

    with transaction.atomic():
        user = (
            user_model.objects
            .select_for_update()
            .annotate(
                retention_last_activity=Coalesce(
                    "last_login",
                    "date_joined",
                ),
            )
            .filter(
                pk=candidate.user_id,
                is_active=True,
                is_staff=False,
                is_superuser=False,
            )
            .first()
        )

        if (
            user is None
            or user.retention_last_activity
            != candidate.inactivity_since
        ):
            return None

        email_address = (
            EmailAddress.objects
            .select_for_update()
            .filter(
                user_id=user.pk,
                verified=True,
            )
            .order_by(
                "-primary",
                "id",
            )
            .first()
        )

        if (
            email_address is None
            or not email_address.email.strip()
        ):
            return None

        state, _ = (
            AccountRetentionNotice.objects
            .select_for_update()
            .get_or_create(
                user_id=user.pk,
                defaults={
                    "inactivity_since": (
                        user.retention_last_activity
                    ),
                },
            )
        )

        if (
            state.inactivity_since
            != user.retention_last_activity
        ):
            _reset_for_new_cycle(
                state=state,
                inactivity_since=(
                    user.retention_last_activity
                ),
            )

        current_stage = _stage_due(
            state=state,
            inactivity_since=(
                user.retention_last_activity
            ),
            now=now,
        )

        if current_stage != candidate.stage:
            return None

        claim_field = (
            "final_warning_claimed_at"
            if current_stage == FINAL_WARNING
            else "first_warning_claimed_at"
        )
        setattr(state, claim_field, now)
        state.save(
            update_fields=[
                claim_field,
                "updated_at",
            ]
        )

        return _ClaimedNotice(
            state_id=state.pk,
            claimed_at=now,
            stage=current_stage,
            email=email_address.email.strip(),
            user=user,
            inactivity_since=(
                user.retention_last_activity
            ),
            deletion_not_before=(
                _deletion_not_before(
                    inactivity_since=(
                        user.retention_last_activity
                    ),
                    stage=current_stage,
                    now=now,
                )
            ),
            owns_groups=(
                Group.objects.filter(
                    owner_id=user.pk,
                ).exists()
            ),
        )


def _finish_claim(
    *,
    claim: _ClaimedNotice,
    sent: bool,
    now,
) -> None:
    claim_field = (
        "final_warning_claimed_at"
        if claim.stage == FINAL_WARNING
        else "first_warning_claimed_at"
    )
    sent_field = (
        "final_warning_sent_at"
        if claim.stage == FINAL_WARNING
        else "first_warning_sent_at"
    )
    updates = {
        claim_field: None,
        "updated_at": now,
    }

    if sent:
        updates[sent_field] = now

    AccountRetentionNotice.objects.filter(
        pk=claim.state_id,
        **{
            claim_field: claim.claimed_at,
        },
    ).update(**updates)


def _send_account_retention_notice(
    *,
    claim: _ClaimedNotice,
) -> bool:
    days_remaining = (
        settings.ACCOUNT_RETENTION_FINAL_NOTICE_DAYS
        if claim.stage == FINAL_WARNING
        else settings.ACCOUNT_RETENTION_FIRST_NOTICE_DAYS
    )
    context = {
        "user": claim.user,
        "is_final": claim.stage == FINAL_WARNING,
        "days_remaining": days_remaining,
        "inactivity_since": claim.inactivity_since,
        "deletion_not_before": claim.deletion_not_before,
        "owns_groups": claim.owns_groups,
        "login_url": _absolute_url(
            reverse("account_login")
        ),
    }
    subject = render_to_string(
        "tipping/email/account_retention_subject.txt",
        context,
    )
    subject = " ".join(
        subject.splitlines()
    ).strip()
    text_body = render_to_string(
        "tipping/email/account_retention.txt",
        context,
    )
    html_body = render_to_string(
        "tipping/email/account_retention.html",
        context,
    )
    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[claim.email],
    )
    message.attach_alternative(
        html_body,
        "text/html",
    )

    return message.send(
        fail_silently=False
    ) == 1


def send_due_account_retention_notices(
    *,
    now=None,
    dry_run: bool = True,
    limit: int | None = None,
) -> AccountRetentionNoticeRunResult:
    """
    Prüft und versendet die 30-/7-Tage-Kontowarnungen.

    Der sichere Standard ist ein Prüfmodus. Ein echter Versand
    benötigt sowohl dry_run=False als auch den globalen Schalter.
    """

    feature_enabled = bool(
        settings.ACCOUNT_RETENTION_NOTICES_ENABLED
    )

    if not feature_enabled and not dry_run:
        return AccountRetentionNoticeRunResult(
            enabled=False,
            dry_run=False,
            first_due=0,
            final_due=0,
            sent=0,
            users_without_verified_email=0,
            failures=0,
        )

    if limit is None:
        limit = settings.ACCOUNT_RETENTION_NOTICE_BATCH_SIZE

    if limit < 1:
        raise ValueError("limit muss mindestens 1 sein.")

    current_time = now or timezone.now()
    candidates = _due_candidates(
        now=current_time,
        limit=limit,
    )
    first_due = sum(
        candidate.stage == FIRST_WARNING
        for candidate in candidates
    )
    final_due = sum(
        candidate.stage == FINAL_WARNING
        for candidate in candidates
    )
    verified_emails = _verified_email_by_user(
        {
            candidate.user_id
            for candidate in candidates
        }
    )
    users_without_verified_email = 0
    sent = 0
    failures = 0

    for candidate in candidates:
        if candidate.user_id not in verified_emails:
            users_without_verified_email += 1
            continue

        if dry_run:
            continue

        claim = _claim_notice(
            candidate=candidate,
            now=current_time,
        )

        if claim is None:
            continue

        try:
            was_sent = _send_account_retention_notice(
                claim=claim,
            )

            _finish_claim(
                claim=claim,
                sent=was_sent,
                now=current_time,
            )

            if was_sent:
                sent += 1
                continue

            failures += 1
            logger.error(
                "Kontowarnung wurde vom E-Mail-Backend "
                "nicht versendet (user_id=%s, stage=%s).",
                candidate.user_id,
                candidate.stage,
            )

        except Exception:
            failures += 1
            _finish_claim(
                claim=claim,
                sent=False,
                now=current_time,
            )
            logger.exception(
                "Kontowarnung fehlgeschlagen "
                "(user_id=%s, stage=%s).",
                candidate.user_id,
                candidate.stage,
            )

    return AccountRetentionNoticeRunResult(
        enabled=feature_enabled,
        dry_run=dry_run,
        first_due=first_due,
        final_due=final_due,
        sent=sent,
        users_without_verified_email=(
            users_without_verified_email
        ),
        failures=failures,
    )
