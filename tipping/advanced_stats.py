from __future__ import annotations

from collections import defaultdict

from django.db.models import Count, F, Q, Sum
from django.utils import timezone

from .bonus_scoring import get_bonus_lock_time
from .models import (
    Group,
    GroupMembership,
    GroupStanding,
    Match,
    MatchdayScore,
    Prediction,
    Tournament,
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
    tournament_ids = group.selected_tournament_ids()
    tournaments_by_id = {
        tournament.id: tournament
        for tournament in (
            Tournament.objects
            .filter(id__in=tournament_ids)
        )
    }

    score_rows = list(
        MatchdayScore.objects
        .filter(group=group, user_id__in=member_ids)
        .only(
            "user_id",
            "tournament_id",
            "matchday",
            "round_started_at",
            "points",
            "cumulative_points",
            "cumulative_matchday_wins",
            "rank",
        )
        .order_by(
            "round_started_at",
            "tournament_id",
            "matchday",
            "user_id",
        )
    )
    scores_by_user_id = defaultdict(list)
    scores_by_user_event = {}
    scores_by_event = defaultdict(list)

    for score in score_rows:
        event_key = (
            score.tournament_id,
            score.matchday,
        )
        scores_by_user_id[score.user_id].append(score)
        scores_by_user_event[(score.user_id, event_key)] = score
        scores_by_event[event_key].append(score)

    evaluated_events = list(scores_by_event)
    metadata_by_event = {}

    for tournament_id in tournament_ids:
        tournament_matchdays = [
            matchday
            for event_tournament_id, matchday in evaluated_events
            if event_tournament_id == tournament_id
        ]
        tournament = tournaments_by_id.get(tournament_id)

        if tournament is None:
            continue

        tournament_metadata = build_matchday_metadata(
            tournament,
            tournament_matchdays,
        )

        for matchday, metadata in tournament_metadata.items():
            label = metadata.label
            if len(tournament_ids) > 1:
                label = f"{tournament.name} · {label}"
            metadata_by_event[(tournament_id, matchday)] = label

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
                correct=Count(
                    "id",
                    filter=(
                        Q(
                            score_category__in=(
                                Prediction.ScoreCategory.EXACT,
                                Prediction.ScoreCategory.GOAL_DIFFERENCE,
                                Prediction.ScoreCategory.TENDENCY,
                            ),
                        )
                        | (
                            Q(score_category__isnull=True)
                            & Q(points__gt=0)
                        )
                    ),
                ),
                exact=Count(
                    "id",
                    filter=(
                        Q(
                            score_category=(
                                Prediction.ScoreCategory.EXACT
                            ),
                        )
                        | (
                            Q(score_category__isnull=True)
                            & Q(
                                pred_home=F("match__home_score"),
                                pred_away=F("match__away_score"),
                            )
                        )
                    ),
                ),
                earned_points=Sum("points", default=0),
            )
        )
    }

    # Nur bereits gestartete Spiele fließen in die Teilnahmequote ein.
    # Tippinhalte werden weder geladen noch an das Template übergeben.
    started_matches = list(
        Match.objects
        .filter(
            tournament_id__in=tournament_ids,
            kickoff__lte=now,
        )
        .exclude(matchday__isnull=True)
        .values("id", "tournament_id", "matchday", "kickoff")
        .order_by("kickoff", "tournament_id", "matchday", "id")
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
    participation_by_event = defaultdict(
        lambda: {"matches": 0, "submitted": 0, "expected": 0}
    )

    for match in started_matches:
        event_key = (
            match["tournament_id"],
            match["matchday"],
        )
        matchday_report = participation_by_event[event_key]
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
            "matchday": event_key[1],
            "matchday_label": metadata_by_event.get(
                event_key,
                f"Fecha {event_key[1]}",
            ),
            "matches": report["matches"],
            "submitted": report["submitted"],
            "expected": report["expected"],
            "rate": _percentage(
                report["submitted"],
                report["expected"],
            ),
        }
        for event_key, report in (
            participation_by_event.items()
        )
    ]
    total_submitted = sum(
        report["submitted"]
        for report in participation_by_event.values()
    )
    total_expected = sum(
        report["expected"]
        for report in participation_by_event.values()
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
                    score.round_started_at or now,
                    score.tournament_id or 0,
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
                        / len(evaluated_events),
                        1,
                    )
                    if evaluated_events
                    else None
                ),
                "last_five_points": sum(
                    (
                        score.points
                        if (
                            score := scores_by_user_event.get(
                                (user_id, event_key)
                            )
                        ) is not None
                        else 0
                    )
                    for event_key in evaluated_events[-5:]
                ),
                "best_matchday": (
                    best_score.matchday
                    if best_score is not None
                    else None
                ),
                "best_matchday_label": (
                    metadata_by_event.get(
                        (
                            best_score.tournament_id,
                            best_score.matchday,
                        ),
                        f"Fecha {best_score.matchday}",
                    )
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

        for event_key in evaluated_events:
            score = scores_by_user_event.get((player_id, event_key))

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

    for event_key in evaluated_events:
        current_leaders = frozenset(
            score.user_id
            for score in scores_by_event[event_key]
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
            metadata_by_event.get(
                event_key,
                f"Fecha {event_key[1]}",
            )
            for event_key in evaluated_events
        ],
        "comparison_series": comparison_series,
        "participation_rows": participation_rows,
        "member_count": len(memberships),
        "evaluated_matchday_count": len(evaluated_events),
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
