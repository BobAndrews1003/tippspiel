import re

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models import Min


YEAR_PATTERN = re.compile(r"\b(20\d{2})\b")


def migrate_existing_competitions(apps, schema_editor):
    Season = apps.get_model("tipping", "Season")
    Tournament = apps.get_model("tipping", "Tournament")
    Group = apps.get_model("tipping", "Group")
    GroupTournamentSelection = apps.get_model(
        "tipping",
        "GroupTournamentSelection",
    )
    Match = apps.get_model("tipping", "Match")
    MatchdayScore = apps.get_model("tipping", "MatchdayScore")

    fallback_season = None

    for tournament in Tournament.objects.all().order_by("id"):
        match = YEAR_PATTERN.search(tournament.name)

        if match:
            year = int(match.group(1))
            season, _created = Season.objects.get_or_create(
                year=year,
                defaults={"name": f"Temporada {year}"},
            )
        else:
            if fallback_season is None:
                fallback_season, _created = Season.objects.get_or_create(
                    name="Temporada existente",
                    year=None,
                )
            season = fallback_season

        Tournament.objects.filter(pk=tournament.pk).update(
            season_id=season.pk,
        )

    GroupTournamentSelection.objects.bulk_create(
        [
            GroupTournamentSelection(
                group_id=group.id,
                tournament_id=group.tournament_id,
                sort_order=1,
            )
            for group in Group.objects.all().iterator()
        ],
        ignore_conflicts=True,
        batch_size=1000,
    )

    round_starts = {
        (row["tournament_id"], row["matchday"]): row["round_start"]
        for row in (
            Match.objects
            .exclude(matchday__isnull=True)
            .values("tournament_id", "matchday")
            .annotate(round_start=Min("kickoff"))
        )
    }

    group_tournaments = dict(
        Group.objects.values_list("id", "tournament_id")
    )

    for score in MatchdayScore.objects.all().iterator(chunk_size=1000):
        tournament_id = group_tournaments.get(score.group_id)
        score.tournament_id = tournament_id
        score.round_started_at = round_starts.get(
            (tournament_id, score.matchday)
        )
        score.save(
            update_fields=[
                "tournament",
                "round_started_at",
            ]
        )


class Migration(migrations.Migration):

    dependencies = [
        ("tipping", "0028_match_live_data"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Season",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=80)),
                (
                    "year",
                    models.PositiveSmallIntegerField(
                        blank=True,
                        null=True,
                        unique=True,
                    ),
                ),
                (
                    "is_open_for_groups",
                    models.BooleanField(
                        default=True,
                        help_text=(
                            "Steuert, ob die Saison bei der Erstellung "
                            "einer Gruppe angeboten wird."
                        ),
                    ),
                ),
            ],
            options={
                "ordering": ("-year", "name"),
            },
        ),
        migrations.AddField(
            model_name="tournament",
            name="season",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="tournaments",
                to="tipping.season",
            ),
        ),
        migrations.AddField(
            model_name="tournament",
            name="code",
            field=models.SlugField(
                blank=True,
                help_text=(
                    "Stabiler interner Schlüssel, z. B. ligapro, "
                    "copa-ecuador oder copa-de-la-liga."
                ),
                max_length=50,
            ),
        ),
        migrations.AddField(
            model_name="tournament",
            name="is_selectable",
            field=models.BooleanField(
                default=True,
                help_text=(
                    "Noch nicht bestätigte oder abgeschlossene Wettbewerbe "
                    "können für neue Gruppen ausgeblendet werden."
                ),
            ),
        ),
        migrations.AlterField(
            model_name="tournamentstage",
            name="code",
            field=models.CharField(
                max_length=32,
                validators=[
                    django.core.validators.RegexValidator(
                        message=(
                            "Der Phasenschlüssel darf nur Kleinbuchstaben, "
                            "Zahlen und Unterstriche enthalten."
                        ),
                        regex="^[a-z0-9_]+$",
                    )
                ],
            ),
        ),
        migrations.CreateModel(
            name="GroupTournamentSelection",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "sort_order",
                    models.PositiveSmallIntegerField(
                        default=1,
                        validators=[
                            django.core.validators.MinValueValidator(1)
                        ],
                    ),
                ),
                ("selected_at", models.DateTimeField(auto_now_add=True)),
                (
                    "locked_at",
                    models.DateTimeField(
                        blank=True,
                        help_text=(
                            "Nach dem ersten Tipp in diesem Wettbewerb darf "
                            "die Auswahl nicht mehr entfernt werden."
                        ),
                        null=True,
                    ),
                ),
                (
                    "group",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="tournament_selections",
                        to="tipping.group",
                    ),
                ),
                (
                    "tournament",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="group_selections",
                        to="tipping.tournament",
                    ),
                ),
            ],
            options={
                "ordering": ("group_id", "sort_order", "id"),
                "constraints": [
                    models.UniqueConstraint(
                        fields=("group", "tournament"),
                        name="uniq_group_tournament_selection",
                    )
                ],
            },
        ),
        migrations.AddField(
            model_name="group",
            name="tournaments",
            field=models.ManyToManyField(
                related_name="selected_by_groups",
                through="tipping.GroupTournamentSelection",
                to="tipping.tournament",
            ),
        ),
        migrations.AlterField(
            model_name="group",
            name="tournament",
            field=models.ForeignKey(
                help_text=(
                    "Primärer Wettbewerb für Bonustipps und die "
                    "Rückwärtskompatibilität bestehender Gruppen."
                ),
                on_delete=django.db.models.deletion.CASCADE,
                related_name="groups",
                to="tipping.tournament",
            ),
        ),
        migrations.AddField(
            model_name="matchdayscore",
            name="tournament",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "Wettbewerb, zu dem dieser Spieltag gehört. Null bleibt "
                    "nur für historische Kompatibilität zulässig."
                ),
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="matchday_scores",
                to="tipping.tournament",
            ),
        ),
        migrations.AddField(
            model_name="matchdayscore",
            name="round_started_at",
            field=models.DateTimeField(
                blank=True,
                help_text=(
                    "Erster Anstoß dieses Wettbewerbsspieltags; dient der "
                    "chronologischen kombinierten Rangentwicklung."
                ),
                null=True,
            ),
        ),
        migrations.RunPython(
            migrate_existing_competitions,
            migrations.RunPython.noop,
        ),
        migrations.RemoveConstraint(
            model_name="matchdayscore",
            name="uniq_group_user_matchday",
        ),
        migrations.RemoveIndex(
            model_name="matchdayscore",
            name="score_group_md_rank_idx",
        ),
        migrations.RemoveIndex(
            model_name="matchdayscore",
            name="score_group_user_md_idx",
        ),
        migrations.AddConstraint(
            model_name="matchdayscore",
            constraint=models.UniqueConstraint(
                condition=models.Q(tournament__isnull=False),
                fields=("group", "user", "tournament", "matchday"),
                name="uniq_group_user_tournament_matchday",
            ),
        ),
        migrations.AddConstraint(
            model_name="matchdayscore",
            constraint=models.UniqueConstraint(
                condition=models.Q(tournament__isnull=True),
                fields=("group", "user", "matchday"),
                name="uniq_legacy_group_user_matchday",
            ),
        ),
        migrations.AddIndex(
            model_name="matchdayscore",
            index=models.Index(
                fields=["group", "tournament", "matchday", "rank"],
                name="score_group_tourn_md_rank_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="matchdayscore",
            index=models.Index(
                fields=["group", "user", "tournament", "matchday"],
                name="score_group_user_tourn_md_idx",
            ),
        ),
    ]
