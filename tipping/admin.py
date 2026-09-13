from django.contrib import (
    admin,
    messages,
)
from django.utils import timezone

from .models import (
    AccountRetentionNotice,
    BonusPrediction,
    Group,
    GroupMembership,
    Match,
    Prediction,
    StandingRebuildJob,
    TipReminderDelivery,
    Tournament,
)


@admin.register(AccountRetentionNotice)
class AccountRetentionNoticeAdmin(
    admin.ModelAdmin
):
    list_display = (
        "id",
        "user",
        "inactivity_since",
        "first_warning_sent_at",
        "final_warning_sent_at",
        "updated_at",
    )

    search_fields = (
        "user__username",
        "user__email",
    )

    list_select_related = (
        "user",
    )

    readonly_fields = (
        "id",
        "user",
        "inactivity_since",
        "first_warning_claimed_at",
        "first_warning_sent_at",
        "final_warning_claimed_at",
        "final_warning_sent_at",
        "updated_at",
    )

    ordering = (
        "inactivity_since",
        "id",
    )

    def has_add_permission(
        self,
        request,
    ):
        return False

    def has_change_permission(
        self,
        request,
        obj=None,
    ):
        return False

    def has_delete_permission(
        self,
        request,
        obj=None,
    ):
        return False


@admin.register(TipReminderDelivery)
class TipReminderDeliveryAdmin(
    admin.ModelAdmin
):
    list_display = (
        "id",
        "user",
        "group",
        "match",
        "sent_at",
    )

    list_filter = (
        "group",
        "sent_at",
    )

    search_fields = (
        "user__username",
        "group__name",
        "match__home_team",
        "match__away_team",
    )

    list_select_related = (
        "user",
        "group",
        "match",
    )

    readonly_fields = (
        "id",
        "user",
        "group",
        "match",
        "sent_at",
    )

    def has_add_permission(
        self,
        request,
    ):
        return False

    def has_change_permission(
        self,
        request,
        obj=None,
    ):
        return False

    def has_delete_permission(
        self,
        request,
        obj=None,
    ):
        return False


@admin.register(Tournament)
class TournamentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
    )


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "tournament",
        "join_enabled",
        "join_code",
    )

    search_fields = (
        "name",
        "join_code",
    )

    list_filter = (
        "tournament",
        "join_enabled",
    )


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "tournament",
        "home_team",
        "away_team",
        "kickoff",
        "home_score",
        "away_score",
    )

    list_filter = (
        "tournament",
    )

    search_fields = (
        "home_team",
        "away_team",
    )


@admin.register(GroupMembership)
class GroupMembershipAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "group",
        "is_active",
        "removed_at",
    )

    list_filter = (
        "group",
        "is_active",
    )

    def get_queryset(self, request):
        return (
            GroupMembership.all_objects
            .select_related(
                "user",
                "group",
            )
        )


@admin.register(Prediction)
class PredictionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "group",
        "match",
        "pred_home",
        "pred_away",
        "updated_at",
    )

    list_filter = (
        "group",
    )


@admin.register(BonusPrediction)
class BonusPredictionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "group",
        "tournament",
        "bonus_type",
        "value",
        "updated_at",
    )

    list_filter = (
        "group",
        "tournament",
        "bonus_type",
    )

    search_fields = (
        "user__username",
        "value",
    )


@admin.action(
    description=(
        "Ausgewählte fehlgeschlagene "
        "Jobs erneut einreihen"
    )
)
def retry_failed_standing_jobs(
    modeladmin,
    request,
    queryset,
):
    now = timezone.now()

    updated = (
        queryset
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

    modeladmin.message_user(
        request,
        (
            f"{updated} fehlgeschlagene "
            "Jobs wurden erneut eingereiht."
        ),
        level=messages.SUCCESS,
    )


@admin.register(StandingRebuildJob)
class StandingRebuildJobAdmin(
    admin.ModelAdmin
):
    list_display = (
        "id",
        "tournament",
        "status",
        "start_matchday",
        "match_count",
        "rebuild_bonus",
        "attempts",
        "processed_groups",
        "created_at",
        "started_at",
        "finished_at",
    )

    list_filter = (
        "status",
        "rebuild_bonus",
        "tournament",
    )

    search_fields = (
        "tournament__name",
        "last_error",
    )

    list_select_related = (
        "tournament",
    )

    ordering = (
        "-created_at",
        "-id",
    )

    list_per_page = 50

    actions = [
        retry_failed_standing_jobs,
    ]

    readonly_fields = (
        "id",
        "tournament",
        "affected_matchdays",
        "match_ids",
        "group_ids",
        "rebuild_bonus",
        "status",
        "attempts",
        "processed_groups",
        "last_error",
        "created_at",
        "updated_at",
        "started_at",
        "finished_at",
    )

    fieldsets = (
        (
            "Auftrag",
            {
                "fields": (
                    "id",
                    "tournament",
                    "status",
                    "affected_matchdays",
                    "match_ids",
                    "rebuild_bonus",
                ),
            },
        ),
        (
            "Verarbeitung",
            {
                "fields": (
                    "attempts",
                    "processed_groups",
                    "last_error",
                    "created_at",
                    "updated_at",
                    "started_at",
                    "finished_at",
                ),
            },
        ),
    )

    def has_add_permission(
        self,
        request,
    ):
        return False

    @admin.display(
        description="Ab Spieltag",
    )
    def start_matchday(
        self,
        obj,
    ):
        values = (
            obj.affected_matchdays
            or []
        )

        if not values:
            return "–"

        try:
            return min(
                int(value)
                for value in values
            )

        except (
            TypeError,
            ValueError,
        ):
            return "Ungültig"

    @admin.display(
        description="Spiele",
    )
    def match_count(
        self,
        obj,
    ):
        return len(
            obj.match_ids
            or []
        )
