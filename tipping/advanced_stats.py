from __future__ import annotations

from collections import defaultdict

from django.db.models import Count, Q, Sum
from django.utils import timezone

from .bonus_scoring import get_bonus_lock_time
from .models import (
    Group,
    GroupMembership,
    GroupStanding,
    Match,
    MatchdayScore,
    Prediction,
)
from .tournament_stages import build_matchday_metadata


CHART_COLORS = ("#4ea1ff", "#f3b64c")


def _display_name(membership: GroupMembership) -> str:
    user = membership.user
    return user.get_username().strip() or f"Jugador {user.id}"


def _percentage(value: int, total: int) -> int:
    return round(value / total * 100) if total > 0 else 0


def build_advanced_group_stats(
    *,
    group: Group,
    viewer_user_id: int,
    requested_player_a_id: int | None = None,
    requested_player_b_id: int | None = None,
    now=None,
) -> dict:
    """Bereitet gruppeninterne Verlaufs- und Vergleichsdaten auf."""

    now = now or timezone.now()
    memberships = list(
        GroupMembership.objects
        .filter(group=group)
        .select_related("user")
        .order_by("user__username", "user_id")
    )
    member_ids = [membership.user_id for membership in memberships]

    score_rows = list(
        MatchdayScore.objects
        .filter(group=group, user_id__in=member_ids)
        .only(
            "user_id",
            "matchday",
            "points",
            "cumulative_points",
            "cumulative_matchday_wins",
            "rank",
        )
        .order_by("matchday", "user_id")
    )
    scores_by_user_id = defaultdict(list)
    scores_by_user_matchday = {}
    scores_by_matchday = defaultdict(list)

    for score in score_rows:
        scores_by_user_id[score.user_id].append(score)
        scores_by_user_matchday[(score.user_id, score.matchday)] = score
        scores_by_matchday[score.matchday].append(score)

    evaluated_matchdays = sorted(scores_by_matchday)
    matchday_metadata = build_matchday_metadata(
        group.tournament,
        evaluated_matchdays,
    )
    bonus_lock_time = get_bonus_lock_time(group.tournament)
    bonus_reveal = bool(
        bonus_lock_time
        and now >= bonus_lock_time
    )
    standings_by_user_id = {
        standing.user_id: standing
        for standing in (
            GroupStanding.objects
            .filter(
                group=group,
                user_id__in=member_ids,
            )
            .only(
                "user_id",
                "match_points",
                "bonus_points",
                "total_points",
                "matchday_wins",
            )
        )
    }
    prediction_aggregates = {
        row["user_id"]: row
        for row in (
            Prediction.objects
            .filter(
                group=group,
                user_id__in=member_ids,
                points__isnull=False,
            )
            .values("user_id")
            .annotate(
                evaluated=Count("id"),
                correct=Count("id", filter=Q(points__gt=0)),
                exact=Count("id", filter=Q(points=4)),
                earned_points=Sum("points", default=0),
            )
        )
    }

    # Nur bereits gestartete Spiele fließen in die Teilnahmequote ein.
    # Tippinhalte werden weder geladen noch an das Template übergeben.
    started_matches = list(
        Match.objects
        .filter(
            tournament=group.tournament,
            kickoff__lte=now,
        )
        .exclude(matchday__isnull=True)
        .values("id", "matchday", "kickoff")
        .order_by("matchday", "kickoff", "id")
    )
    started_match_ids = [match["id"] for match in started_matches]
    submitted_prediction_keys = set(
        Prediction.objects
        .filter(
            group=group,
            user_id__in=member_ids,
            match_id__in=started_match_ids,
            pred_home__isnull=False,
            pred_away__isnull=False,
        )
        .values_list("user_id", "match_id")
    )

    participation_by_user_id = {
        user_id: {"submitted": 0, "expected": 0}
        for user_id in member_ids
    }
    participation_by_matchday = defaultdict(
        lambda: {"matches": 0, "submitted": 0, "expected": 0}
    )

    for match in started_matches:
        matchday_report = participation_by_matchday[match["matchday"]]
        matchday_report["matches"] += 1

        for membership in memberships:
            prediction_key = (membership.user_id, match["id"])
            submitted = prediction_key in submitted_prediction_keys
            eligible = submitted or match["kickoff"] >= membership.joined_at

            if not eligible:
                continue

            matchday_report["expected"] += 1
            user_report = participation_by_user_id[membership.user_id]
            user_report["expected"] += 1

            if submitted:
                matchday_report["submitted"] += 1
                user_report["submitted"] += 1

    participation_rows = [
        {
            "matchday": matchday,
            "matchday_label": (
                matchday_metadata[matchday].label
            ),
            "matches": report["matches"],
            "submitted": report["submitted"],
            "expected": report["expected"],
            "rate": _percentage(
                report["submitted"],
                report["expected"],
            ),
        }
        for matchday, report in sorted(
            participation_by_matchday.items()
        )
    ]
    total_submitted = sum(
        report["submitted"]
        for report in participation_by_matchday.values()
    )
    total_expected = sum(
        report["expected"]
        for report in participation_by_matchday.values()
    )

    member_rows = []

    for membership in memberships:
        user_id = membership.user_id
        user_scores = scores_by_user_id[user_id]
        aggregate = prediction_aggregates.get(user_id, {})
        participation = participation_by_user_id[user_id]
        standing = standings_by_user_id.get(user_id)
        evaluated = aggregate.get("evaluated", 0)
        correct = aggregate.get("correct", 0)
        earned_points = aggregate.get("earned_points", 0) or 0
        best_score = (
            max(
                user_scores,
                key=lambda score: (
                    score.points,
                    score.matchday,
                ),
            )
            if user_scores
            else None
        )

        member_rows.append(
            {
                "user_id": user_id,
                "display_name": _display_name(membership),
                "is_viewer": user_id == viewer_user_id,
                "rank": None,
                "match_points": (
                    (
                        standing.total_points
                        if bonus_reveal
                        else standing.match_points
                    )
                    if standing is not None
                    else (
                        user_scores[-1].cumulative_points
                        if user_scores
                        else 0
                    )
                ),
                "matchday_wins": (
                    standing.matchday_wins
                    if standing is not None
                    else (
                        user_scores[-1].cumulative_matchday_wins
                        if user_scores
                        else 0
                    )
                ),
                "average_points": (
                    round(
                        sum(score.points for score in user_scores)
                        / len(evaluated_matchdays),
                        1,
                    )
                    if evaluated_matchdays
                    else None
                ),
                "last_five_points": sum(
                    (
                        score.points
                        if (
                            score := scores_by_user_matchday.get(
                                (user_id, matchday)
                            )
                        ) is not None
                        else 0
                    )
                    for matchday in evaluated_matchdays[-5:]
                ),
                "best_matchday": (
                    best_score.matchday
                    if best_score is not None
                    else None
                ),
                "best_matchday_label": (
                    matchday_metadata[
                        best_score.matchday
                    ].label
                    if best_score is not None
                    else None
                ),
                "best_matchday_points": (
                    best_score.points
                    if best_score is not None
                    else None
                ),
                "evaluated_predictions": evaluated,
                "correct_predictions": correct,
                "exact_predictions": aggregate.get("exact", 0),
                "hit_rate": _percentage(correct, evaluated),
                "points_per_prediction": (
                    round(earned_points / evaluated, 2)
                    if evaluated
                    else None
                ),
                "submitted_predictions": participation["submitted"],
                "expected_predictions": participation["expected"],
                "participation_rate": _percentage(
                    participation["submitted"],
                    participation["expected"],
                ),
            }
        )

    member_rows.sort(
        key=lambda row: (
            -row["match_points"],
            -row["matchday_wins"],
            row["display_name"].lower(),
            row["user_id"],
        )
    )
    current_rank = 0
    previous_ranking_key = None

    for index, row in enumerate(member_rows, start=1):
        ranking_key = (
            row["match_points"],
            row["matchday_wins"],
        )

        if ranking_key != previous_ranking_key:
            current_rank = index
            previous_ranking_key = ranking_key

        row["rank"] = current_rank

    valid_member_ids = set(member_ids)
    player_a_id = (
        requested_player_a_id
        if requested_player_a_id in valid_member_ids
        else viewer_user_id
    )

    if player_a_id not in valid_member_ids:
        player_a_id = member_rows[0]["user_id"] if member_rows else None

    player_b_id = (
        requested_player_b_id
        if (
            requested_player_b_id in valid_member_ids
            and requested_player_b_id != player_a_id
        )
        else None
    )

    if player_b_id is None:
        player_b_id = next(
            (
                row["user_id"]
                for row in member_rows
                if row["user_id"] != player_a_id
            ),
            None,
        )

    member_row_by_user_id = {
        row["user_id"]: row
        for row in member_rows
    }
    selected_player_ids = [
        player_id
        for player_id in (player_a_id, player_b_id)
        if player_id is not None
    ]
    comparison_rows = [
        member_row_by_user_id[player_id]
        for player_id in selected_player_ids
    ]
    comparison_series = []

    for index, player_id in enumerate(selected_player_ids):
        cumulative_points = []
        ranks = []
        previous_points = 0

        for matchday in evaluated_matchdays:
            score = scores_by_user_matchday.get((player_id, matchday))

            if score is not None:
                previous_points = score.cumulative_points

            cumulative_points.append(previous_points)
            ranks.append(score.rank if score is not None else None)

        comparison_series.append(
            {
                "label": member_row_by_user_id[player_id]["display_name"],
                "color": CHART_COLORS[index],
                "points": cumulative_points,
                "ranks": ranks,
            }
        )

    leader_changes = 0
    previous_leaders = None

    for matchday in evaluated_matchdays:
        current_leaders = frozenset(
            score.user_id
            for score in scores_by_matchday[matchday]
            if score.rank == 1
        )

        if (
            previous_leaders is not None
            and current_leaders != previous_leaders
        ):
            leader_changes += 1

        previous_leaders = current_leaders

    return {
        "member_options": sorted(
            (
                {
                    "user_id": membership.user_id,
                    "display_name": _display_name(membership),
                }
                for membership in memberships
            ),
            key=lambda row: (
                row["display_name"].lower(),
                row["user_id"],
            ),
        ),
        "member_rows": member_rows,
        "comparison_rows": comparison_rows,
        "selected_player_a_id": player_a_id,
        "selected_player_b_id": player_b_id,
        "timeline_labels": [
            matchday_metadata[matchday].label
            for matchday in evaluated_matchdays
        ],
        "comparison_series": comparison_series,
        "participation_rows": participation_rows,
        "member_count": len(memberships),
        "evaluated_matchday_count": len(evaluated_matchdays),
        "evaluated_prediction_count": sum(
            row.get("evaluated", 0)
            for row in prediction_aggregates.values()
        ),
        "participation_rate": _percentage(
            total_submitted,
            total_expected,
        ),
        "leader_changes": leader_changes,
        "bonus_reveal": bonus_reveal,
    }
