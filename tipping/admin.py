# Register your models here.
from django.contrib import admin
from .models import Tournament, Group, Match, GroupMembership, Prediction


@admin.register(Tournament)
class TournamentAdmin(admin.ModelAdmin):
    list_display = ("id", "name")


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "tournament", "join_code")
    search_fields = ("name", "join_code")
    list_filter = ("tournament",)


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = ("id", "tournament", "home_team", "away_team", "kickoff", "home_score", "away_score")
    list_filter = ("tournament",)
    search_fields = ("home_team", "away_team")


@admin.register(GroupMembership)
class GroupMembershipAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "group")
    list_filter = ("group",)


@admin.register(Prediction)
class PredictionAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "group", "match", "pred_home", "pred_away", "updated_at")
    list_filter = ("group",)
