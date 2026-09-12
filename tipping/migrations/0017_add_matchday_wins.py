from collections import defaultdict

from django.db import migrations, models


def _rebuild_historical_ranks(
    apps,
    schema_editor,
    *,
    use_matchday_wins,
):
    MatchdayScore = apps.get_model(
        "tipping",
        "MatchdayScore",
    )
    GroupStanding = apps.get_model(
        "tipping",
        "GroupStanding",
    )
    database_alias = schema_editor.connection.alias

    group_ids = (
        MatchdayScore.objects
        .using(database_alias)
        .order_by()
        .values_list(
            "group_id",
            flat=True,
        )
        .distinct()
    )

    for group_id in group_ids.iterator():
        score_rows = list(
            MatchdayScore.objects
            .using(database_alias)
            .filter(group_id=group_id)
            .order_by(
                "matchday",
                "user_id",
            )
        )

        if not score_rows:
            continue

        rows_by_matchday = defaultdict(list)
        user_ids = set()

        for row in score_rows:
            rows_by_matchday[
                row.matchday
            ].append(row)
            user_ids.add(row.user_id)

        cumulative_points = {
            user_id: 0
            for user_id in user_ids
        }
        cumulative_wins = {
            user_id: 0
            for user_id in user_ids
        }
        previous_ranks = {
            user_id: None
            for user_id in user_ids
        }

        for matchday in sorted(rows_by_matchday):
            day_rows = rows_by_matchday[
                matchday
            ]

            for row in day_rows:
                cumulative_points[
                    row.user_id
                ] += row.points or 0

            if use_matchday_wins:
                winning_points = max(
                    row.points or 0
                    for row in day_rows
                )

                for row in day_rows:
                    if (
                        row.points or 0
                    ) == winning_points:
                        cumulative_wins[
                            row.user_id
                        ] += 1

            sorted_user_ids = sorted(
                user_ids,
                key=lambda user_id: (
                    -cumulative_points[user_id],
                    -cumulative_wins[user_id],
                    user_id,
                ),
            )
            current_ranks = {}
            previous_key = None
            current_rank = 0

            for index, user_id in enumerate(
                sorted_user_ids,
                start=1,
            ):
                ranking_key = (
                    cumulative_points[user_id],
                    cumulative_wins[user_id],
                )

                if ranking_key != previous_key:
                    current_rank = index
                    previous_key = ranking_key

                current_ranks[user_id] = (
                    current_rank
                )

            for row in day_rows:
                old_rank = previous_ranks[
                    row.user_id
                ]
                new_rank = current_ranks[
                    row.user_id
                ]
                row.cumulative_points = (
                    cumulative_points[
                        row.user_id
                    ]
                )
                row.cumulative_matchday_wins = (
                    cumulative_wins[
                        row.user_id
                    ]
                )
                row.rank = new_rank
                row.rank_change = (
                    None
                    if old_rank is None
                    else old_rank - new_rank
                )

            previous_ranks = current_ranks

        MatchdayScore.objects.using(
            database_alias
        ).bulk_update(
            score_rows,
            [
                "cumulative_points",
                "cumulative_matchday_wins",
                "rank",
                "rank_change",
            ],
            batch_size=1000,
        )

        standing_rows = list(
            GroupStanding.objects
            .using(database_alias)
            .filter(group_id=group_id)
        )

        for standing in standing_rows:
            standing.matchday_wins = (
                cumulative_wins.get(
                    standing.user_id,
                    0,
                )
            )

        GroupStanding.objects.using(
            database_alias
        ).bulk_update(
            standing_rows,
            [
                "matchday_wins",
            ],
            batch_size=1000,
        )


def backfill_matchday_wins(
    apps,
    schema_editor,
):
    _rebuild_historical_ranks(
        apps,
        schema_editor,
        use_matchday_wins=True,
    )


def restore_points_only_ranks(
    apps,
    schema_editor,
):
    _rebuild_historical_ranks(
        apps,
        schema_editor,
        use_matchday_wins=False,
    )


class Migration(migrations.Migration):

    dependencies = [
        (
            "tipping",
            "0016_add_tip_reminders",
        ),
    ]

    operations = [
        migrations.AddField(
            model_name="matchdayscore",
            name="cumulative_matchday_wins",
            field=models.PositiveIntegerField(
                default=0,
            ),
        ),
        migrations.AddField(
            model_name="groupstanding",
            name="matchday_wins",
            field=models.PositiveIntegerField(
                default=0,
            ),
        ),
        migrations.RemoveIndex(
            model_name="groupstanding",
            name="standing_group_total_idx",
        ),
        migrations.RemoveIndex(
            model_name="groupstanding",
            name="standing_group_match_idx",
        ),
        migrations.AddIndex(
            model_name="groupstanding",
            index=models.Index(
                fields=[
                    "group",
                    "-total_points",
                    "-matchday_wins",
                    "user",
                ],
                name=(
                    "standing_group_total_win_idx"
                ),
            ),
        ),
        migrations.AddIndex(
            model_name="groupstanding",
            index=models.Index(
                fields=[
                    "group",
                    "-match_points",
                    "-matchday_wins",
                    "user",
                ],
                name=(
                    "standing_group_match_win_idx"
                ),
            ),
        ),
        migrations.RunPython(
            backfill_matchday_wins,
            reverse_code=(
                restore_points_only_ranks
            ),
        ),
    ]
