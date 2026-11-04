from django.contrib import (
    admin,
    messages,
)
from django.utils import timezone

from .models import (
    AccountRetentionNotice,
    BonusPrediction,
    Group,
    GroupBranding,
    GroupMembership,
    GroupScoringSettings,
    GroupTournamentSelection,
    Match,
    Prediction,
    Season,
    StandingRebuildJob,
    TipReminderDelivery,
    Tournament,
    TournamentStage,
)


@admin.register(Season)
class SeasonAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "year",
        "is_open_for_groups",
    )
    list_filter = ("is_open_for_groups",)
    search_fields = ("name",)
    ordering = ("-year", "name")


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


class TournamentStageInline(admin.TabularInline):
    model = TournamentStage
    extra = 0
    fields = (
        "code",
        "name",
        "sort_order",
        "round_count",
    )


@admin.register(Tournament)
class TournamentAdmin(admin.ModelAdmin):
    inlines = (
        TournamentStageInline,
    )

    list_display = (
        "id",
        "name",
        "season",
        "code",
        "is_selectable",
    )
    list_filter = (
        "season",
        "is_selectable",
    )
    search_fields = ("name", "code")
    list_select_related = ("season",)


@admin.register(TournamentStage)
class TournamentStageAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "tournament",
        "name",
        "code",
        "sort_order",
        "round_count",
    )

    list_filter = (
        "tournament",
        "code",
    )

    search_fields = (
        "name",
        "tournament__name",
    )

    list_select_related = (
        "tournament",
    )

    ordering = (
        "tournament",
        "sort_order",
    )


class GroupBrandingInline(admin.StackedInline):
    model = GroupBranding
    extra = 0
    max_num = 1


class GroupScoringSettingsInline(admin.StackedInline):
    model = GroupScoringSettings
    extra = 0
    max_num = 1
    can_delete = False
    fields = (
        "exact_points",
        "goal_difference_points",
        "tendency_points",
        "incorrect_points",
        "locked_at",
        "updated_at",
    )
    readonly_fields = (
        "locked_at",
        "updated_at",
    )

    def get_readonly_fields(
        self,
        request,
        obj=None,
    ):
        readonly = list(
            super().get_readonly_fields(
                request,
                obj,
            )
        )

        if (
            obj is not None
            and hasattr(obj, "scoring_settings")
            and obj.scoring_settings.is_locked
        ):
            readonly.extend(
                [
                    "exact_points",
                    "goal_difference_points",
                    "tendency_points",
                    "incorrect_points",
                ]
            )

        return tuple(readonly)


class GroupTournamentSelectionInline(admin.TabularInline):
    model = GroupTournamentSelection
    extra = 0
    can_delete = False
    fields = (
        "tournament",
        "sort_order",
        "selected_at",
        "locked_at",
    )
    readonly_fields = ("selected_at", "locked_at")


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    inlines = (
        GroupTournamentSelectionInline,
        GroupScoringSettingsInline,
        GroupBrandingInline,
    )

    list_display = (
        "id",
        "name",
        "tournament",
        "selected_competitions",
        "effective_plan_name",
        "plan_expires_at",
        "join_enabled",
        "join_code",
    )

    search_fields = (
        "name",
        "join_code",
    )

    list_filter = (
        "tournament",
        "plan",
        "join_enabled",
    )

    @admin.display(description="Wettbewerbe")
    def selected_competitions(self, obj):
        return obj.competition_names

    fieldsets = (
        (
            "Gruppe",
            {
                "fields": (
                    "name",
                    "tournament",
                    "owner",
                    "join_enabled",
                    "join_code",
                ),
            },
        ),
        (
            "Gruppenplan (manuelle Testfreigabe)",
            {
                "fields": (
                    "plan",
                    "plan_expires_at",
                ),
                "description": (
                    "Es existiert noch kein Checkout. Plus und Club "
                    "dürfen derzeit nur für Tests vergeben werden."
                ),
            },
        ),
    )

    @admin.display(
        description="Wirksamer Plan",
        ordering="plan",
    )
    def effective_plan_name(self, obj):
        return obj.effective_plan_label


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "tournament",
        "matchday",
        "stage",
        "stage_round",
        "home_team",
        "away_team",
        "kickoff",
        "source_status",
        "live_home_score",
        "live_away_score",
        "home_score",
        "away_score",
        "source_synced_at",
    )

    list_filter = (
        "tournament",
        "stage",
        "source_status",
    )

    search_fields = (
        "home_team",
        "away_team",
        "external_id",
    )

    readonly_fields = (
        "external_source",
        "external_id",
        "source_status",
        "live_home_score",
        "live_away_score",
        "source_synced_at",
    )

    list_select_related = (
        "tournament",
        "stage",
    )

    ordering = (
        "tournament",
        "matchday",
        "stage__sort_order",
        "kickoff",
    )


@admin.register(GroupMembership)
class GroupMembershipAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "group",
        "is_creator",
        "is_co_admin",
        "is_active",
        "removed_at",
    )

    list_filter = (
        "group",
        "is_creator",
        "is_co_admin",
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
        "score_category",
        "points",
        "updated_at",
    )

    list_filter = (
        "group",
        "score_category",
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
