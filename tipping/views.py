from __future__ import annotations

from collections import Counter, defaultdict

from typing import Optional

from .bonus_scoring import (
    get_bonus_lock_time,
)

from django.core.paginator import Paginator
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import logout
from django.db.models import CharField, Q, Value
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Count
from django.db.models.functions import Cast, Coalesce, Concat, Lower, NullIf
from django.http import HttpRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from .forms import (
    BonusPredictionForm,
    DeleteAccountForm,
    GroupCreateForm,
)
from .models import (
    BonusPrediction,
    Group,
    GroupMembership,
    GroupStanding,
    Match,
    MatchdayScore,
    Prediction,
    Tournament,
)

from .scoring import points_for_prediction

User = get_user_model()

GROUP_PAGE_SIZE = 50


# ---------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------

def _outcome(h: int, a: int) -> int:
    """1=Heimsieg, 0=Remis, -1=Auswärtssieg"""
    return (h > a) - (h < a)


def _prediction_points(
    match,
    prediction,
):
    if prediction is None:
        return None

    if (
        match.home_score is None
        or match.away_score is None
    ):
        return None

    return prediction.points




# ---------------------------------------------------------------------
# Membership / Matchday helpers
# ---------------------------------------------------------------------



def _require_active_membership(request) -> Optional[GroupMembership]:
    """
    Liefert die aktive GroupMembership (aus request.session["active_group_id"]).
    - Wenn active_group_id fehlt: nimmt die erste Membership des Users und setzt die Session.
    - Wenn active_group_id gesetzt aber ungültig/nicht Mitglied: repariert auf erste Membership.
    - Wenn User in keiner Gruppe ist: None zurück (View soll dann redirect join_group).
    """
    if not request.user.is_authenticated:
        return None

    active_group_id = request.session.get("active_group_id")

    # 1) Wenn aktive Gruppe gesetzt ist: Membership dafür holen
    if active_group_id:
        membership = (
            GroupMembership.objects
            .filter(user=request.user, group_id=active_group_id)
            .select_related("group__tournament")
            .first()
        )
        if membership:
            return membership

    # 2) Fallback: erste Membership nehmen
    membership = (
        GroupMembership.objects
        .filter(user=request.user)
        .select_related("group__tournament")
        .order_by("id")
        .first()
    )
    if membership:
        request.session["active_group_id"] = membership.group_id
        return membership

    # 3) Keine Gruppe vorhanden
    return None




def _get_selected_matchday(request, tournament, now):
    """
    Default:
      - wenn es zukünftige Spiele gibt: matchday des nächsten zukünftigen Spiels
      - sonst: letzter matchday im Turnier
    Optional:
      - ?md=3 erzwingt Spieltag 3 (wenn existiert)
    """

    # 1) Falls md explizit gesetzt ist: nutzen (wenn es diesen Spieltag gibt)
    md_param = request.GET.get("md")
    if md_param:
        try:
            selected_md = int(md_param.strip())
        except ValueError:
            selected_md = None

        if selected_md is not None:
            exists = Match.objects.filter(tournament=tournament, matchday=selected_md).exists()
            if exists:
                return selected_md

    # 2) Default: nächstes zukünftiges Spiel
    next_match = (
        Match.objects
        .filter(tournament=tournament, kickoff__gte=now)
        .exclude(matchday__isnull=True)
        .order_by("kickoff")
        .first()
    )
    if next_match:
        return next_match.matchday

    # 3) Fallback: letzter Spieltag im Turnier (wenn keine zukünftigen Spiele mehr existieren)
    last_md = (
        Match.objects
        .filter(tournament=tournament)
        .exclude(matchday__isnull=True)
        .order_by("-matchday")
        .values_list("matchday", flat=True)
        .first()
    )
    return last_md  # kann None sein, wenn es gar keine Matches gibt



def _prev_next_md(tournament, matchday):
    prev_md = (
        Match.objects.filter(tournament=tournament, matchday__lt=matchday)
        .order_by("-matchday")
        .values_list("matchday", flat=True)
        .first()
    )
    next_md = (
        Match.objects.filter(tournament=tournament, matchday__gt=matchday)
        .order_by("matchday")
        .values_list("matchday", flat=True)
        .first()
    )
    return prev_md, next_md



# ---------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------
@login_required
def dashboard(request):
    membership = _require_active_membership(
        request
    )

    if not membership:
        return redirect("join_group")

    group = membership.group
    tournament = group.tournament
    now = timezone.now()

    # --------------------------------------------------------------
    # Teilnehmerzahl der aktiven Gruppe
    #
    # Es werden nicht mehr alle Mitgliedschaften und Nutzer
    # für das Dashboard geladen.
    # --------------------------------------------------------------

    participant_count = (
        GroupMembership.objects
        .filter(
            group=group,
        )
        .count()
    )

    # --------------------------------------------------------------
    # Aktuellen beziehungsweise nächsten Spieltag bestimmen
    # --------------------------------------------------------------

    current_matchday = _get_selected_matchday(
        request,
        tournament,
        now,
    )

    current_matches = []

    if current_matchday is not None:
        current_matches = list(
            Match.objects
            .filter(
                tournament=tournament,
                matchday=current_matchday,
            )
            .order_by(
                "kickoff",
                "home_team",
            )
        )

    # --------------------------------------------------------------
    # Bereits vollständig abgegebene eigene Tipps
    #
    # Wir laden keine vollständigen Prediction-Objekte mehr,
    # sondern nur die IDs der Spiele mit einem vollständigen Tipp.
    # --------------------------------------------------------------

    completed_prediction_match_ids = set(
        Prediction.objects
        .filter(
            group=group,
            user=request.user,
            match__in=current_matches,
            pred_home__isnull=False,
            pred_away__isnull=False,
        )
        .values_list(
            "match_id",
            flat=True,
        )
    )

    # Ein Spiel ist offen, wenn:
    # - noch kein vollständiges Ergebnis existiert und
    # - der Anstoß noch nicht erreicht wurde.
    open_matches = [
        match
        for match in current_matches
        if (
            not match.has_result
            and now < match.kickoff
        )
    ]

    locked_matches = [
        match
        for match in current_matches
        if (
            match.has_result
            or now >= match.kickoff
        )
    ]

    has_open_matches = bool(
        open_matches
    )

    missing_predictions = sum(
        1
        for match in open_matches
        if (
            match.id
            not in completed_prediction_match_ids
        )
    )

    completed_open_predictions = (
        len(open_matches)
        - missing_predictions
    )

    next_deadline = min(
        (
            match.kickoff
            for match in open_matches
        ),
        default=None,
    )

    if not current_matches:
        current_matchday_state = "empty"

    elif open_matches and locked_matches:
        current_matchday_state = (
            "in_progress"
        )

    elif open_matches:
        current_matchday_state = (
            "upcoming"
        )

    else:
        current_matchday_state = (
            "closed"
        )

    # --------------------------------------------------------------
    # Spieltage mit vollständigen Ergebnissen
    # --------------------------------------------------------------

    result_matchdays = list(
        Match.objects
        .filter(
            tournament=tournament,
            home_score__isnull=False,
            away_score__isnull=False,
        )
        .exclude(
            matchday__isnull=True,
        )
        .values_list(
            "matchday",
            flat=True,
        )
        .distinct()
        .order_by(
            "matchday",
        )
    )

    standings_started = bool(
        result_matchdays
    )

    # --------------------------------------------------------------
    # Vorbereitete Gesamt- und Spieltagspunkte
    #
    # Die Ranglistenwerte werden nicht mehr bei jedem
    # Seitenaufruf aus allen Tipps neu berechnet.
    # --------------------------------------------------------------

    bonus_lock_time = get_bonus_lock_time(
        tournament
    )

    bonus_reveal = bool(
        bonus_lock_time
        and now >= bonus_lock_time
    )

    # Vor der Bonusfreigabe zählt ausschließlich
    # match_points, danach total_points.
    ranking_points_field = (
        "total_points"
        if bonus_reveal
        else "match_points"
    )

    # Für die persönlichen Dashboardwerte wird nur noch
    # die Standing-Zeile des angemeldeten Nutzers geladen.
    current_user_standing = (
        GroupStanding.objects
        .filter(
            group=group,
            user=request.user,
        )
        .select_related(
            "user",
            "user__tip_profile",
        )
        .first()
    )

    user_total_points = (
        getattr(
            current_user_standing,
            ranking_points_field,
        )
        or 0
        if current_user_standing
        else 0
    )

    # --------------------------------------------------------------
    # Eigene Punkte nach Spieltag
    # --------------------------------------------------------------

    user_matchday_points = defaultdict(
        int
    )

    if result_matchdays:
        own_matchday_rows = (
            MatchdayScore.objects
            .filter(
                group=group,
                user=request.user,
                matchday__in=result_matchdays,
            )
            .values_list(
                "matchday",
                "points",
            )
            .order_by(
                "matchday",
            )
        )

        for matchday, points in own_matchday_rows:
            user_matchday_points[
                matchday
            ] = points or 0

    # --------------------------------------------------------------
    # Anzahl exakter Ergebnisse des aktuellen Nutzers
    # --------------------------------------------------------------

    exact_predictions = (
        current_user_standing.exact_predictions
        if current_user_standing
        else 0
    )

    # --------------------------------------------------------------
    # Persönliche Leistungsentwicklung
    # --------------------------------------------------------------

    evaluated_matchday_points = [
        user_matchday_points.get(
            matchday,
            0,
        )
        for matchday in result_matchdays
    ]

    if evaluated_matchday_points:
        average_matchday_points = round(
            sum(
                evaluated_matchday_points
            )
            / len(
                evaluated_matchday_points
            ),
            1,
        )

    else:
        average_matchday_points = None

    best_matchday = None
    best_matchday_points = None

    if result_matchdays:
        best_matchday = max(
            result_matchdays,
            key=lambda matchday: (
                user_matchday_points.get(
                    matchday,
                    0,
                ),
                matchday,
            ),
        )

        best_matchday_points = (
            user_matchday_points.get(
                best_matchday,
                0,
            )
        )

    # Neuester ausgewerteter Spieltag zuerst.
    recent_matchdays = list(
        reversed(
            result_matchdays[-5:]
        )
    )

    recent_points = [
        user_matchday_points.get(
            matchday,
            0,
        )
        for matchday in recent_matchdays
    ]

    maximum_recent_points = max(
        recent_points,
        default=0,
    )

    performance_rows = []

    for matchday, points in zip(
        recent_matchdays,
        recent_points,
    ):
        if maximum_recent_points > 0:
            bar_percent = round(
                points
                / maximum_recent_points
                * 100
            )

        else:
            bar_percent = 0

        performance_rows.append(
            {
                "matchday": matchday,
                "points": points,
                "bar_percent": bar_percent,
            }
        )

    # --------------------------------------------------------------
    # Kleine Rangliste direkt aus der Datenbank
    #
    # Es werden nur die drei führenden Teilnehmer sowie
    # gegebenenfalls der aktuelle Nutzer geladen.
    # --------------------------------------------------------------

    mini_table_rows = []
    user_position = None

    if standings_started:
        leaderboard_queryset = (
            GroupStanding.objects
            .filter(
                group=group,
            )
            .select_related(
                "user",
                "user__tip_profile",
            )
            .annotate(
                dashboard_sort_name=Lower(
                    Coalesce(
                        NullIf(
                            "user__username",
                            Value(""),
                        ),
                        NullIf(
                            "user__email",
                            Value(""),
                        ),
                        Concat(
                            Value("user-"),
                            Cast(
                                "user_id",
                                output_field=CharField(),
                            ),
                        ),
                        output_field=CharField(),
                    )
                )
            )
            .order_by(
                f"-{ranking_points_field}",
                "dashboard_sort_name",
                "user_id",
            )
        )

        top_standings = list(
            leaderboard_queryset[:3]
        )

        previous_total = None
        current_position = 0

        for index, standing in enumerate(
            top_standings,
            start=1,
        ):
            visible_total = (
                getattr(
                    standing,
                    ranking_points_field,
                )
                or 0
            )

            # Wettbewerbsrang:
            # 1, 1, 3 statt 1, 1, 2.
            if (
                previous_total is None
                or visible_total != previous_total
            ):
                current_position = index
                previous_total = visible_total

            mini_table_rows.append(
                {
                    "user": standing.user,
                    "position": current_position,
                    "total": visible_total,
                    "bonus": (
                        standing.bonus_points or 0
                        if bonus_reveal
                        else 0
                    ),
                    "is_current_user": (
                        standing.user_id
                        == request.user.id
                    ),
                }
            )

        if current_user_standing:
            # Rang = Anzahl der Nutzer mit mehr Punkten + 1.
            # Dadurch bleibt das Wettbewerbssystem erhalten.
            user_position = (
                GroupStanding.objects
                .filter(
                    group=group,
                    **{
                        (
                            f"{ranking_points_field}"
                            "__gt"
                        ): user_total_points,
                    },
                )
                .count()
                + 1
            )

            top_user_ids = {
                row["user"].id
                for row in mini_table_rows
            }

            if (
                request.user.id
                not in top_user_ids
            ):
                mini_table_rows.append(
                    {
                        "user": (
                            current_user_standing.user
                        ),
                        "position": user_position,
                        "total": user_total_points,
                        "bonus": (
                            current_user_standing
                            .bonus_points
                            or 0
                            if bonus_reveal
                            else 0
                        ),
                        "is_current_user": True,
                        "is_extra": True,
                    }
                )

    # --------------------------------------------------------------
    # Letzter ausgewerteter Spieltag
    # --------------------------------------------------------------

    last_result_matchday = (
        result_matchdays[-1]
        if result_matchdays
        else None
    )

    last_matchday_points = None

    if last_result_matchday is not None:
        last_matchday_points = (
            user_matchday_points.get(
                last_result_matchday,
                0,
            )
        )

    # --------------------------------------------------------------
    # Template rendern
    # --------------------------------------------------------------

    return render(
        request,
        "tipping/dashboard.html",
        {
            "group": group,
            "tournament": tournament,

            "current_matchday": (
                current_matchday
            ),
            "current_matchday_state": (
                current_matchday_state
            ),
            "current_matches_count": len(
                current_matches
            ),
            "open_matches_count": len(
                open_matches
            ),
            "has_open_matches": (
                has_open_matches
            ),
            "missing_predictions": (
                missing_predictions
            ),
            "completed_open_predictions": (
                completed_open_predictions
            ),
            "next_deadline": (
                next_deadline
            ),

            "participant_count": (
                participant_count
            ),
            "user_position": (
                user_position
            ),
            "user_total_points": (
                user_total_points
            ),

            "standings_started": (
                standings_started
            ),
            "mini_table_rows": (
                mini_table_rows
            ),

            "last_result_matchday": (
                last_result_matchday
            ),
            "last_matchday_points": (
                last_matchday_points
            ),

            "bonus_reveal": (
                bonus_reveal
            ),
            "bonus_lock_time": (
                bonus_lock_time
            ),

            "performance_rows": (
                performance_rows
            ),
            "average_matchday_points": (
                average_matchday_points
            ),
            "exact_predictions": (
                exact_predictions
            ),
            "best_matchday": (
                best_matchday
            ),
            "best_matchday_points": (
                best_matchday_points
            ),
        },
    )

@login_required
@require_http_methods(["GET", "POST"])
def tippen(request):
    membership = _require_active_membership(
        request
    )

    if not membership:
        return redirect("join_group")

    group = membership.group
    tournament = group.tournament
    now = timezone.now()

    # --------------------------------------------------------------
    # Verfügbare Spieltage
    # --------------------------------------------------------------

    matchdays = list(
        Match.objects
        .filter(
            tournament=tournament,
        )
        .exclude(
            matchday__isnull=True,
        )
        .values_list(
            "matchday",
            flat=True,
        )
        .distinct()
        .order_by(
            "matchday",
        )
    )

    # --------------------------------------------------------------
    # Gewählten Spieltag bestimmen
    # --------------------------------------------------------------

    matchday = _get_selected_matchday(
        request,
        tournament,
        now,
    )

    if matchday is None:
        return render(
            request,
            "tipping/tippen.html",
            {
                "group": group,
                "matchday": None,
                "matchdays": matchdays,
                "rows": [],
                "prev_md": None,
                "next_md": None,
                "now": now,
            },
        )

    def _matches_for_md(md: int):
        return list(
            Match.objects
            .filter(
                tournament=tournament,
                matchday=md,
            )
            .order_by(
                "kickoff",
                "home_team",
            )
        )

    matches = _matches_for_md(
        matchday
    )

    # --------------------------------------------------------------
    # Fallback bei ungültigem Spieltag
    # --------------------------------------------------------------

    if not matches:
        if matchdays:
            matchday = matchdays[0]

            matches = _matches_for_md(
                matchday
            )

        else:
            return render(
                request,
                "tipping/tippen.html",
                {
                    "group": group,
                    "matchday": None,
                    "matchdays": matchdays,
                    "rows": [],
                    "prev_md": None,
                    "next_md": None,
                    "now": now,
                },
            )

    prev_md, next_md = _prev_next_md(
        tournament,
        matchday,
    )

    # --------------------------------------------------------------
    # Eigene vorhandene Tipps
    # --------------------------------------------------------------

    predictions = {
        prediction.match_id: prediction
        for prediction in (
            Prediction.objects
            .filter(
                user=request.user,
                group=group,
                match__in=matches,
            )
        )
    }

    rows = [
        {
            "match": match,
            "pred": predictions.get(
                match.id
            ),
        }
        for match in matches
    ]

    # --------------------------------------------------------------
    # Tipps speichern
    # --------------------------------------------------------------

    if request.method == "POST":
        saved = 0
        skipped_locked = 0
        skipped_invalid = 0

        with transaction.atomic():
            # Mitgliedschaft unmittelbar vor dem Schreiben
            # erneut kontrollieren und während der Transaktion
            # gegen parallele Änderungen sperren.
            membership_exists = (
                GroupMembership.objects
                .select_for_update()
                .filter(
                    pk=membership.pk,
                    user=request.user,
                    group=group,
                )
                .exists()
            )

            if not membership_exists:
                messages.error(
                    request,
                    (
                        "Ya no perteneces "
                        "a este grupo."
                    ),
                )

                request.session.pop(
                    "active_group_id",
                    None,
                )

                return redirect(
                    "join_group"
                )

            # Spiele erneut aus der Datenbank laden.
            # In PostgreSQL werden die Zeilen bis zum Ende
            # der Transaktion gesperrt.
            locked_matches = {
                match.id: match
                for match in (
                    Match.objects
                    .select_for_update()
                    .filter(
                        id__in=[
                            match.id
                            for match in matches
                        ],
                        tournament=tournament,
                        matchday=matchday,
                    )
                )
            }

            for original_match in matches:
                match = locked_matches.get(
                    original_match.id
                )

                if match is None:
                    skipped_invalid += 1
                    continue

                home_key = (
                    f"pred_home_{match.id}"
                )

                away_key = (
                    f"pred_away_{match.id}"
                )

                home_value = (
                    request.POST
                    .get(
                        home_key,
                        "",
                    )
                    .strip()
                )

                away_value = (
                    request.POST
                    .get(
                        away_key,
                        "",
                    )
                    .strip()
                )

                # Leere oder unvollständige Eingaben
                # werden nicht verändert.
                if (
                    home_value == ""
                    or away_value == ""
                ):
                    continue

                # Sehr lange manipulierte Zahlenwerte
                # bereits vor int() verwerfen.
                if (
                    len(home_value) > 3
                    or len(away_value) > 3
                ):
                    skipped_invalid += 1
                    continue

                try:
                    pred_home = int(
                        home_value
                    )

                    pred_away = int(
                        away_value
                    )

                except (
                    TypeError,
                    ValueError,
                ):
                    skipped_invalid += 1
                    continue

                if not (
                    0 <= pred_home <= MAX_GOALS
                    and
                    0 <= pred_away <= MAX_GOALS
                ):
                    skipped_invalid += 1
                    continue

                # Die Frist möglichst unmittelbar vor dem
                # tatsächlichen Schreiben prüfen.
                if (
                    match.has_result
                    or timezone.now()
                    >= match.kickoff
                ):
                    skipped_locked += 1
                    continue

                Prediction.objects.update_or_create(
                    user=request.user,
                    group=group,
                    match=match,
                    defaults={
                        "pred_home": pred_home,
                        "pred_away": pred_away,
                        "points": None,
                        "scored_at": None,
                    },
                )

                saved += 1

        # ----------------------------------------------------------
        # Rückmeldungen
        # ----------------------------------------------------------

        if saved > 0:
            messages.success(
                request,
                (
                    f"Se guardaron correctamente "
                    f"{saved} pronóstico(s)."
                ),
            )

        if skipped_locked > 0:
            messages.warning(
                request,
                (
                    f"{skipped_locked} partido(s) "
                    "ya estaban bloqueados y no "
                    "fueron modificados."
                ),
            )

        if skipped_invalid > 0:
            messages.error(
                request,
                (
                    f"{skipped_invalid} pronóstico(s) "
                    "contenían valores no válidos."
                ),
            )

        if (
            saved == 0
            and skipped_locked == 0
            and skipped_invalid == 0
        ):
            messages.info(
                request,
                (
                    "No se introdujeron nuevos "
                    "pronósticos."
                ),
            )

        return redirect(
            f"{request.path}?md={matchday}"
        )

    # --------------------------------------------------------------
    # Seite anzeigen
    # --------------------------------------------------------------

    return render(
        request,
        "tipping/tippen.html",
        {
            "group": group,
            "matchday": matchday,
            "matchdays": matchdays,
            "rows": rows,
            "prev_md": prev_md,
            "next_md": next_md,
            "now": now,
        },
    )

@login_required
def spieltag(request):
    membership = _require_active_membership(request)

    if not membership:
        return redirect("join_group")

    group = membership.group
    tournament = group.tournament
    now = timezone.now()

    def user_sort_name(user) -> str:
        return (
            user.get_username()
            or user.email
            or f"user-{user.id}"
        ).strip().lower()

    # -------------------------------------------------------------
    # Spieltage und ausgewählter Bereich
    # -------------------------------------------------------------

    matchdays = list(
        Match.objects
        .filter(tournament=tournament)
        .exclude(matchday__isnull=True)
        .values_list("matchday", flat=True)
        .distinct()
        .order_by("matchday")
    )

    tab = request.GET.get("tab", "matches")

    if tab not in {"matches", "bonus"}:
        tab = "matches"

    bonus_lock_time = get_bonus_lock_time(
        tournament
    )

    bonus_reveal = bool(
        bonus_lock_time
        and now >= bonus_lock_time
    )

    # -------------------------------------------------------------
    # Aktive Gruppenmitglieder
    # -------------------------------------------------------------

    memberships = list(
        GroupMembership.objects
        .filter(group=group)
        .select_related(
            "user",
            "user__tip_profile",
        )
        .order_by(
            "user__username",
            "user_id",
        )
    )

    users = [
        item.user
        for item in memberships
    ]

    user_ids = [
        user.id
        for user in users
    ]

    # -------------------------------------------------------------
    # Aktiven Spieltag bestimmen
    # -------------------------------------------------------------

    matchday = _get_selected_matchday(
        request,
        tournament,
        now,
    )

    matches = []
    prev_md = None
    next_md = None

    # Spiele werden nur im normalen Spieltag-Tab benötigt.
    if (
        tab == "matches"
        and matchday is not None
    ):
        matches = list(
            Match.objects
            .filter(
                tournament=tournament,
                matchday=matchday,
            )
            .order_by(
                "kickoff",
                "home_team",
            )
        )

        prev_md, next_md = _prev_next_md(
            tournament,
            matchday,
        )

    match_ids = [
        match.id
        for match in matches
    ]

    locked_match_ids = {
        match.id
        for match in matches
        if (
            match.has_result
            or now >= match.kickoff
        )
    }

    # -------------------------------------------------------------
    # Bonustipps
    #
    # Sie werden nur geladen, wenn der Bonus-Tab geöffnet ist.
    # Vor der Freigabe wird nur der eigene Bonustipp geladen.
    # -------------------------------------------------------------

    bonus_by_user = defaultdict(list)

    bonus_points_map = {
        user_id: 0
        for user_id in user_ids
    }

    my_bonus = []

    if tab == "bonus":
        bonus_queryset = (
            BonusPrediction.objects
            .filter(
                group=group,
                tournament=tournament,
            )
        )

        if bonus_reveal:
            bonus_queryset = (
                bonus_queryset.filter(
                    user_id__in=user_ids,
                )
            )

        else:
            bonus_queryset = (
                bonus_queryset.filter(
                    user=request.user,
                )
            )

        all_bonus = list(
            bonus_queryset
        )

        for bonus_prediction in all_bonus:
            bonus_by_user[
                bonus_prediction.user_id
            ].append(
                bonus_prediction
            )

        my_bonus = bonus_by_user.get(
            request.user.id,
            [],
        )

        if bonus_reveal:
            stored_bonus_rows = (
                GroupStanding.objects
                .filter(
                    group=group,
                    user_id__in=user_ids,
                )
                .values_list(
                    "user_id",
                    "bonus_points",
                )
            )

            for user_id, bonus_points in stored_bonus_rows:
                bonus_points_map[
                    user_id
                ] = bonus_points or 0

    # -------------------------------------------------------------
    # Vorbereitete Punkte des ausgewählten Spieltags
    #
    # Die Spieltagssummen werden direkt aus MatchdayScore
    # gelesen. Die einzelnen Tipps bleiben weiterhin in
    # Prediction und werden erst für die sichtbare Seite geladen.
    # -------------------------------------------------------------

    total_points_by_user = {
        user_id: 0
        for user_id in user_ids
    }

    if (
        tab == "matches"
        and matchday is not None
    ):
        stored_point_rows = (
            MatchdayScore.objects
            .filter(
                group=group,
                user_id__in=user_ids,
                matchday=matchday,
            )
            .values_list(
                "user_id",
                "points",
            )
        )

        for user_id, points in stored_point_rows:
            total_points_by_user[
                user_id
            ] = points or 0

    # -------------------------------------------------------------
    # Globale Sortierung vor der Seiteneinteilung
    # -------------------------------------------------------------

    if tab == "bonus":
        if bonus_reveal:
            sorted_users = sorted(
                users,
                key=lambda user: (
                    -bonus_points_map.get(
                        user.id,
                        0,
                    ),
                    user_sort_name(user),
                    user.id,
                ),
            )

        else:
            # Vor der Freigabe wird der aktuelle Nutzer
            # an erster Stelle angezeigt.
            sorted_users = sorted(
                users,
                key=lambda user: (
                    (
                        0
                        if user.id == request.user.id
                        else 1
                    ),
                    user_sort_name(user),
                    user.id,
                ),
            )

    else:
        # Im normalen Spieltag-Tab wird ausschließlich
        # nach den Punkten dieses Spieltags sortiert.
        sorted_users = sorted(
            users,
            key=lambda user: (
                -total_points_by_user.get(
                    user.id,
                    0,
                ),
                user_sort_name(user),
                user.id,
            ),
        )

    # -------------------------------------------------------------
    # Seiteneinteilung
    # -------------------------------------------------------------

    paginator = Paginator(
        sorted_users,
        GROUP_PAGE_SIZE,
    )

    page_obj = paginator.get_page(
        request.GET.get("page")
    )

    page_users = list(
        page_obj.object_list
    )

    page_user_ids = [
        user.id
        for user in page_users
    ]

    # -------------------------------------------------------------
    # Nur Tipps der aktuell sichtbaren Teilnehmer laden
    #
    # Fremde Tipps werden nur für gesperrte Spiele geladen.
    # Der eigene Tipp bleibt auch vor dem Anstoß sichtbar.
    # -------------------------------------------------------------

    prediction_map = {}

    if (
        tab == "matches"
        and matches
        and page_user_ids
    ):
        page_predictions = (
            Prediction.objects
            .filter(
                group=group,
                user_id__in=page_user_ids,
                match_id__in=match_ids,
            )
            .filter(
                Q(
                    match_id__in=locked_match_ids,
                )
                | Q(
                    user=request.user,
                )
            )
        )

        prediction_map = {
            (
                prediction.user_id,
                prediction.match_id,
            ): prediction
            for prediction in page_predictions
        }

    # -------------------------------------------------------------
    # Bonustabelle der sichtbaren Teilnehmer
    # -------------------------------------------------------------

    bonus_rows = []

    if tab == "bonus":
        for user in page_users:
            predictions = bonus_by_user.get(
                user.id,
                [],
            )

            by_type = {
                prediction.bonus_type: prediction.value
                for prediction in predictions
            }

            row_reveal = (
                bonus_reveal
                or user.id == request.user.id
            )

            if row_reveal:
                visible_picks = {
                    "herbstmeister": by_type.get(
                        "herbstmeister",
                        "",
                    ),
                    "meister": by_type.get(
                        "meister",
                        "",
                    ),
                    "trainer_first": by_type.get(
                        "trainer_first",
                        "",
                    ),
                    "topscorer": by_type.get(
                        "topscorer",
                        "",
                    ),
                    "relegation1": by_type.get(
                        "relegation1",
                        "",
                    ),
                    "relegation2": by_type.get(
                        "relegation2",
                        "",
                    ),
                }

            else:
                visible_picks = {}

            bonus_rows.append(
                {
                    "user": user,
                    "reveal": row_reveal,
                    "picks": visible_picks,
                    "points": (
                        bonus_points_map.get(
                            user.id,
                            0,
                        )
                        if bonus_reveal
                        else None
                    ),
                }
            )

    # -------------------------------------------------------------
    # Tabellenköpfe der normalen Spiele
    # -------------------------------------------------------------

    match_headers = [
        {
            "match": match,
            "result": (
                match.home_score,
                match.away_score,
            )
            if match.has_result
            else None,
        }
        for match in matches
    ]

    # -------------------------------------------------------------
    # Spieltagsmatrix der sichtbaren Teilnehmer
    # -------------------------------------------------------------

    table_rows = []

    if tab == "matches":
        for user in page_users:
            cells = []

            for match in matches:
                reveal = (
                    match.id in locked_match_ids
                )

                can_view_prediction = (
                    reveal
                    or user.id == request.user.id
                )

                prediction = prediction_map.get(
                    (
                        user.id,
                        match.id,
                    )
                )

                # Punkte werden direkt aus Prediction.points gelesen.
                # Vor dem Ergebnis bleibt der Wert None.
                cell_points = (
                    prediction.points
                    if (
                        reveal
                        and match.has_result
                        and prediction is not None
                    )
                    else None
                )

                cells.append(
                    {
                        "reveal": reveal,
                        "can_view_prediction": (
                            can_view_prediction
                        ),
                        "pred": (
                            prediction
                            if can_view_prediction
                            else None
                        ),
                        "points": cell_points,
                    }
                )

            total_points = (
                total_points_by_user.get(
                    user.id,
                    0,
                )
            )

            table_rows.append(
                {
                    "user": user,
                    "cells": cells,
                    "total_points": total_points,
                }
            )

    # -------------------------------------------------------------
    # Template rendern
    # -------------------------------------------------------------

    return render(
        request,
        "tipping/spieltag.html",
        {
            "group": group,
            "tab": tab,
            "matchday": matchday,
            "matchdays": matchdays,
            "matches": match_headers,
            "table_rows": table_rows,
            "prev_md": prev_md,
            "next_md": next_md,
            "now": now,
            "bonus_lock_time": bonus_lock_time,
            "bonus_reveal": bonus_reveal,
            "bonus_rows": bonus_rows,
            "my_bonus": my_bonus,
            "page_obj": page_obj,
        },
    )

@login_required
def tabelle(request):
    membership = _require_active_membership(
        request
    )

    if not membership:
        return redirect("join_group")

    group = membership.group
    tournament = group.tournament
    now = timezone.now()

    def user_sort_name(user) -> str:
        return (
            user.get_username()
            or user.email
            or f"user-{user.id}"
        ).strip().lower()

    # --------------------------------------------------------------
    # Bonusfreigabe
    # --------------------------------------------------------------

    season_start = tournament.season_start

    bonus_lock_time = get_bonus_lock_time(
        tournament
    )

    bonus_reveal = bool(
        bonus_lock_time
        and now >= bonus_lock_time
    )

    # --------------------------------------------------------------
    # Ausgewählte Ansicht
    # --------------------------------------------------------------

    view = request.GET.get(
        "view",
        "mdpoints",
    )

    if view not in {
        "mdpoints",
        "ranks",
        "rankdiff",
    }:
        view = "mdpoints"

    # --------------------------------------------------------------
    # Anzahl der sichtbaren Spieltagsspalten
    # --------------------------------------------------------------

    try:
        count = int(
            request.GET.get(
                "count",
                "8",
            )
        )

    except (
        TypeError,
        ValueError,
    ):
        count = 8

    count = max(
        4,
        min(
            count,
            15,
        ),
    )

    # --------------------------------------------------------------
    # Alle vorhandenen Spieltage
    # --------------------------------------------------------------

    matchdays = list(
        Match.objects
        .filter(
            tournament=tournament,
        )
        .exclude(
            matchday__isnull=True,
        )
        .values_list(
            "matchday",
            flat=True,
        )
        .distinct()
        .order_by(
            "matchday",
        )
    )

    # --------------------------------------------------------------
    # Leerer Zustand ohne Spieltage
    # --------------------------------------------------------------

    if not matchdays:
        return render(
            request,
            "tipping/tabelle.html",
            {
                "group": group,
                "view": view,
                "matchdays": [],
                "shown_matchdays": [],
                "table_rows": [],
                "prev_from": None,
                "next_from": None,
                "from_idx": 0,
                "count": count,
                "me_id": request.user.id,
                "bonus_enabled": True,
                "bonus_reveal": bonus_reveal,
                "bonus_lock_time": bonus_lock_time,
                "season_start": season_start,
                "current_matchday": None,
                "page_obj": None,
            },
        )

    # --------------------------------------------------------------
    # Aktuellen beziehungsweise nächsten Spieltag bestimmen
    # --------------------------------------------------------------

    current_matchday = (
        Match.objects
        .filter(
            tournament=tournament,
            kickoff__gte=now,
        )
        .exclude(
            matchday__isnull=True,
        )
        .order_by(
            "kickoff",
            "matchday",
        )
        .values_list(
            "matchday",
            flat=True,
        )
        .first()
    )

    # Falls kein zukünftiges Spiel existiert,
    # wird der zuletzt begonnene Spieltag verwendet.
    if current_matchday is None:
        current_matchday = (
            Match.objects
            .filter(
                tournament=tournament,
                kickoff__lt=now,
            )
            .exclude(
                matchday__isnull=True,
            )
            .order_by(
                "-kickoff",
                "-matchday",
            )
            .values_list(
                "matchday",
                flat=True,
            )
            .first()
        )

    if current_matchday not in matchdays:
        current_matchday = matchdays[-1]

    # --------------------------------------------------------------
    # Sichtbares Spieltagsfenster bestimmen
    # --------------------------------------------------------------

    current_matchday_index = matchdays.index(
        current_matchday
    )

    default_from_idx = max(
        0,
        current_matchday_index - count + 1,
    )

    from_parameter = request.GET.get(
        "from"
    )

    if from_parameter is None:
        from_idx = default_from_idx

    else:
        try:
            from_idx = int(
                from_parameter
            )

        except (
            TypeError,
            ValueError,
        ):
            from_idx = default_from_idx

    max_from_idx = max(
        0,
        len(matchdays) - count,
    )

    from_idx = max(
        0,
        min(
            from_idx,
            max_from_idx,
        ),
    )

    shown_matchdays = matchdays[
        from_idx:from_idx + count
    ]

    shown_matchday_set = set(
        shown_matchdays
    )

    prev_from = (
        max(
            0,
            from_idx - count,
        )
        if from_idx > 0
        else None
    )

    next_from = (
        min(
            from_idx + count,
            max_from_idx,
        )
        if from_idx < max_from_idx
        else None
    )

    # --------------------------------------------------------------
    # Aktive Gruppenmitglieder
    # --------------------------------------------------------------

    memberships = list(
        GroupMembership.objects
        .filter(
            group=group,
        )
        .select_related(
            "user",
            "user__tip_profile",
        )
        .order_by(
            "user__username",
            "user_id",
        )
    )

    users = [
        item.user
        for item in memberships
    ]

    users_by_id = {
        user.id: user
        for user in users
    }

    user_ids = list(
        users_by_id.keys()
    )

    username_by_id = {
        user.id: user_sort_name(
            user
        )
        for user in users
    }

    # --------------------------------------------------------------
    # Spieltage mit vollständigen Ergebnissen
    # --------------------------------------------------------------

    result_matchdays = set(
        Match.objects
        .filter(
            tournament=tournament,
            home_score__isnull=False,
            away_score__isnull=False,
        )
        .exclude(
            matchday__isnull=True,
        )
        .values_list(
            "matchday",
            flat=True,
        )
        .distinct()
    )

    # --------------------------------------------------------------
    # Vorbereitete Spieltagswerte
    #
    # Punkte, historische Ränge und Rangveränderungen
    # werden direkt aus MatchdayScore gelesen.
    # --------------------------------------------------------------

    points_by_user_md = {
        user_id: {}
        for user_id in user_ids
    }

    rank_by_user_md = {
        user_id: {}
        for user_id in user_ids
    }

    rankdiff_by_user_md = {
        user_id: {}
        for user_id in user_ids
    }

    visible_result_matchdays = sorted(
        shown_matchday_set.intersection(
            result_matchdays
        )
    )

    if (
        user_ids
        and visible_result_matchdays
    ):
        stored_score_rows = (
            MatchdayScore.objects
            .filter(
                group=group,
                user_id__in=user_ids,
                matchday__in=(
                    visible_result_matchdays
                ),
            )
            .values_list(
                "user_id",
                "matchday",
                "points",
                "rank",
                "rank_change",
            )
        )

        for (
            user_id,
            matchday,
            points,
            rank,
            rank_change,
        ) in stored_score_rows:
            points_by_user_md[
                user_id
            ][
                matchday
            ] = points or 0

            rank_by_user_md[
                user_id
            ][
                matchday
            ] = rank

            rankdiff_by_user_md[
                user_id
            ][
                matchday
            ] = rank_change

    # --------------------------------------------------------------
    # Vorbereitete Gesamt- und Bonuspunkte
    #
    # Vor der Bonusfreigabe werden nur match_points
    # angezeigt und für die Sortierung verwendet.
    # --------------------------------------------------------------

    stored_standing_rows = (
        GroupStanding.objects
        .filter(
            group=group,
            user_id__in=user_ids,
        )
        .values_list(
            "user_id",
            "match_points",
            "bonus_points",
            "total_points",
        )
    )

    standing_by_user = {
        user_id: {
            "match_points": (
                match_points or 0
            ),
            "bonus_points": (
                bonus_points or 0
            ),
            "total_points": (
                total_points or 0
            ),
        }
        for (
            user_id,
            match_points,
            bonus_points,
            total_points,
        ) in stored_standing_rows
    }

    total_points_all = {}
    bonus_points_by_user = defaultdict(
        int
    )

    for user_id in user_ids:
        standing = standing_by_user.get(
            user_id
        )

        if standing is None:
            total_points_all[
                user_id
            ] = 0

            continue

        if bonus_reveal:
            total_points_all[
                user_id
            ] = standing[
                "total_points"
            ]

            bonus_points_by_user[
                user_id
            ] = standing[
                "bonus_points"
            ]

        else:
            total_points_all[
                user_id
            ] = standing[
                "match_points"
            ]

    # --------------------------------------------------------------
    # Nutzer global sortieren
    #
    # Bonuspunkte werden nach ihrer Freigabe in der
    # Gesamtplatzierung berücksichtigt.
    # --------------------------------------------------------------

    sorted_user_ids = sorted(
        user_ids,
        key=lambda user_id: (
            -total_points_all.get(
                user_id,
                0,
            ),
            username_by_id[
                user_id
            ],
            user_id,
        ),
    )

    # --------------------------------------------------------------
    # Teilnehmer paginieren
    # --------------------------------------------------------------

    paginator = Paginator(
        sorted_user_ids,
        GROUP_PAGE_SIZE,
    )

    page_obj = paginator.get_page(
        request.GET.get("page")
    )

    page_user_ids = list(
        page_obj.object_list
    )

    # --------------------------------------------------------------
    # Tabellenzeilen nur für die sichtbare Teilnehmerseite
    # --------------------------------------------------------------

    table_rows = []

    for user_id in page_user_ids:
        user = users_by_id[
            user_id
        ]

        if view == "mdpoints":
            cells = [
                (
                    points_by_user_md[
                        user_id
                    ].get(
                        matchday,
                        0,
                    )
                    if matchday
                    in result_matchdays
                    else None
                )
                for matchday in shown_matchdays
            ]

        elif view == "ranks":
            cells = [
                rank_by_user_md[
                    user_id
                ].get(
                    matchday
                )
                for matchday in shown_matchdays
            ]

        else:
            cells = [
                rankdiff_by_user_md[
                    user_id
                ].get(
                    matchday
                )
                for matchday in shown_matchdays
            ]

        table_rows.append(
            {
                "user": user,
                "cells": cells,
                "bonus": (
                    bonus_points_by_user.get(
                        user_id,
                        0,
                    )
                    if bonus_reveal
                    else None
                ),
                "total": (
                    total_points_all.get(
                        user_id,
                        0,
                    )
                ),
            }
        )

    # --------------------------------------------------------------
    # Template rendern
    # --------------------------------------------------------------

    return render(
        request,
        "tipping/tabelle.html",
        {
            "group": group,
            "view": view,
            "matchdays": matchdays,
            "shown_matchdays": shown_matchdays,
            "table_rows": table_rows,
            "prev_from": prev_from,
            "next_from": next_from,
            "from_idx": from_idx,
            "count": count,
            "current_matchday": (
                current_matchday
            ),
            "me_id": request.user.id,
            "bonus_enabled": True,
            "bonus_reveal": bonus_reveal,
            "bonus_lock_time": (
                bonus_lock_time
            ),
            "season_start": season_start,
            "page_obj": page_obj,
        },
    )
    
@login_required
def join_group(request):
    if request.method == "POST":
        code = request.POST.get("code", "").strip().upper()

        group = Group.objects.filter(join_code=code).select_related("tournament").first()
        if not group:
            messages.error(request, "Code nicht gefunden.")
            return render(request, "tipping/join.html", {"code": code})

        membership, _ = GroupMembership.objects.get_or_create(
            user=request.user,
            group=group
        )

        request.session["active_group_id"] = group.id

        messages.success(request, f"Beigetreten ✅ Gruppe: {group.name}")
        return redirect("tippen")

    user_groups = (
        GroupMembership.objects
        .filter(user=request.user)
        .select_related("group__tournament")
        .order_by("group__name")
    )

    return render(request, "tipping/join.html", {
        "user_groups": user_groups,
        "active_group_id": request.session.get("active_group_id"),
    })


@login_required
def user_stats(request, user_id: int):
    """
    Statistik pro User (sichtbar für alle User derselben aktiven Gruppe):
    - Pie: Tipps (Heim/Remis/Gast)
    - Pie: Treffer (Kein Treffer / Tendenz / Tordifferenz / Ergebnis)
    - Top 3: meistgetippte Ergebnisse
    - Bar: Top 10 Teams (meiste Punkte) & Flop 10 Teams (wenigste Punkte)
    - Getippte Ligatabelle aus seinen Tipps (Vergleich zur echten Tabelle)
    """
    membership = _require_active_membership(request)
    if not membership:
        return redirect("join_group")

    group = membership.group
    tournament = group.tournament

    # Ziel-User muss Mitglied der aktiven Gruppe sein
    target_membership = get_object_or_404(
    GroupMembership.objects
    .select_related("user"),
    group=group,
    user_id=user_id,
)

    target_user = target_membership.user

    # Nur Spiele mit Ergebnis (sonst kann man keine Punkte/Tabellen berechnen)
    matches_with_result = Match.objects.filter(
        tournament=tournament,
        home_score__isnull=False,
        away_score__isnull=False,
    )

    preds = (
        Prediction.objects
        .filter(group=group, user=target_user, match__in=matches_with_result)
        .select_related("match")
    )

    tip_counts = Counter({"Heim": 0, "Remis": 0, "Gast": 0})
    hit_counts = Counter({"Kein Treffer": 0, "Tendenz": 0, "Tordifferenz": 0, "Ergebnis": 0})
    scoreline_counts = Counter()
    team_points = defaultdict(int)

    predicted_table = defaultdict(lambda: {
        "played": 0,
        "wins": 0,
        "draws": 0,
        "losses": 0,
        "gf": 0,
        "ga": 0,
        "points": 0,
    })

    def points_from_pred(h: int, a: int):
        if h > a:
            return 3, 0
        if h < a:
            return 0, 3
        return 1, 1

    for p in preds:
        m = p.match

        # leere Tipps ignorieren
        if p.pred_home is None or p.pred_away is None:
            continue

        # A) Heim/Remis/Gast
        if p.pred_home > p.pred_away:
            tip_counts["Heim"] += 1
        elif p.pred_home < p.pred_away:
            tip_counts["Gast"] += 1
        else:
            tip_counts["Remis"] += 1

        # B) Trefferkategorie
        pts = _prediction_points(m, p)

        if pts is None:
            continue
        if pts == 4:
            hit_counts["Ergebnis"] += 1
        elif pts == 3:
            hit_counts["Tordifferenz"] += 1
        elif pts == 2:
            hit_counts["Tendenz"] += 1
        else:
            hit_counts["Kein Treffer"] += 1

        # C) Scorelines
        scoreline_counts[f"{p.pred_home}:{p.pred_away}"] += 1

        # D) Team-Punkte
        team_points[m.home_team] += pts
        team_points[m.away_team] += pts

        # E) Predicted League Table
        home = m.home_team
        away = m.away_team
        ph = int(p.pred_home)
        pa = int(p.pred_away)

        predicted_table[home]["played"] += 1
        predicted_table[away]["played"] += 1

        predicted_table[home]["gf"] += ph
        predicted_table[home]["ga"] += pa
        predicted_table[away]["gf"] += pa
        predicted_table[away]["ga"] += ph

        hp, ap = points_from_pred(ph, pa)
        predicted_table[home]["points"] += hp
        predicted_table[away]["points"] += ap

        if ph > pa:
            predicted_table[home]["wins"] += 1
            predicted_table[away]["losses"] += 1
        elif ph < pa:
            predicted_table[away]["wins"] += 1
            predicted_table[home]["losses"] += 1
        else:
            predicted_table[home]["draws"] += 1
            predicted_table[away]["draws"] += 1

    top_scores = scoreline_counts.most_common(3)

    team_points_items = list(team_points.items())
    top_teams = sorted(team_points_items, key=lambda x: (-x[1], x[0].lower()))[:10]
    bottom_teams = sorted(team_points_items, key=lambda x: (x[1], x[0].lower()))[:10]

    predicted_table_rows = []
    for team, st in predicted_table.items():
        gd = st["gf"] - st["ga"]
        predicted_table_rows.append({
            "team": team,
            "played": st["played"],
            "wins": st["wins"],
            "draws": st["draws"],
            "losses": st["losses"],
            "gf": st["gf"],
            "ga": st["ga"],
            "gd": gd,
            "points": st["points"],
        })

    predicted_table_rows.sort(key=lambda r: (-r["points"], -r["gd"], -r["gf"], r["team"].lower()))
    for i, r in enumerate(predicted_table_rows, start=1):
        r["pos"] = i

    return render(request, "tipping/user_stats.html", {
        "group": group,
        "target_user": target_user,

        "tip_counts": dict(tip_counts),
        "hit_counts": dict(hit_counts),

        "top_scores": top_scores,
        "top_teams": top_teams,
        "bottom_teams": bottom_teams,

        "predicted_table_rows": predicted_table_rows,
        "total_predictions": sum(tip_counts.values()),
    })

@login_required
def create_group(request: HttpRequest):
    if request.method == "POST":
        form = GroupCreateForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    group = form.save(commit=False)
                    group.owner = request.user
                    group.save()

                    GroupMembership.objects.create(
                    user=request.user,
                    group=group,
                    is_creator=True,
    )

                request.session["active_group_id"] = group.id

                # Pro: Code sofort, aber nicht nur "einmalig"
                messages.success(request, f"Gruppe erstellt ✅ Join-Code: {group.join_code}")
                return redirect("tippen")

            except IntegrityError:
                messages.error(request, "Konnte die Gruppe nicht erstellen (Kollision). Bitte erneut versuchen.")
        else:
            messages.error(request, "Bitte prüfe deine Eingaben.")
    else:
        form = GroupCreateForm()

    return render(request, "tipping/create_group.html", {"form": form})

@login_required
def my_groups(request):
    active_membership = _require_active_membership(request)

    active_group_id = (
        active_membership.group_id
        if active_membership
        else None
    )

    memberships = list(
        GroupMembership.objects
        .filter(user=request.user)
        .select_related(
            "group__tournament",
            "group__owner",
        )
        .annotate(
            member_count=Count(
                "group__memberships",
                distinct=True,
            )
        )
        .order_by("group__name")
    )

    group_rows = []

    for membership in memberships:
        current_group = membership.group

        # owner ist die Hauptinformation.
        # is_creator bleibt als Fallback für ältere Datensätze.
        is_owner = (
            current_group.owner_id == request.user.id
            or (
                current_group.owner_id is None
                and membership.is_creator
            )
        )

        transfer_candidates = []

        if is_owner:
            transfer_candidates = list(
                GroupMembership.objects
                .filter(group=current_group)
                .exclude(user=request.user)
                .select_related("user")
                .order_by("user__username")
            )

        group_rows.append({
            "membership": membership,
            "group": current_group,
            "is_owner": is_owner,
            "is_active": (
                current_group.id == active_group_id
            ),
            "member_count": membership.member_count,
            "transfer_candidates": transfer_candidates,
        })

    return render(
        request,
        "tipping/my_groups.html",
        {
            "group": (
                active_membership.group
                if active_membership
                else None
            ),
            "group_rows": group_rows,
            "active_group_id": active_group_id,
        },
    )
    
@login_required
@require_POST
def transfer_group_ownership(
    request,
    group_id,
):
    new_owner_id = (
        request.POST
        .get("new_owner_id", "")
        .strip()
    )

    if not new_owner_id.isdigit():
        messages.error(
            request,
            (
                "Selecciona un nuevo "
                "administrador válido."
            ),
        )
        return redirect("my_groups")

    with transaction.atomic():
        current_group = get_object_or_404(
            Group.objects.select_for_update(),
            id=group_id,
        )

        current_membership = (
            GroupMembership.objects
            .filter(
                group=current_group,
                user=request.user,
            )
            .first()
        )

        is_owner = (
            current_group.owner_id
            == request.user.id
            or (
                current_group.owner_id is None
                and current_membership is not None
                and current_membership.is_creator
            )
        )

        if not is_owner:
            messages.error(
                request,
                (
                    "No tienes permiso para "
                    "administrar este grupo."
                ),
            )
            return redirect("my_groups")

        if int(new_owner_id) == request.user.id:
            messages.error(
                request,
                (
                    "Ya eres el administrador "
                    "de este grupo."
                ),
            )
            return redirect("my_groups")

        new_owner_membership = (
            GroupMembership.objects
            .select_for_update()
            .select_related("user")
            .filter(
                group=current_group,
                user_id=new_owner_id,
            )
            .first()
        )

        if not new_owner_membership:
            messages.error(
                request,
                (
                    "El nuevo administrador debe "
                    "ser miembro del grupo."
                ),
            )
            return redirect("my_groups")

        # Zuerst den eigentlichen Eigentümer ändern.
        current_group.owner = (
            new_owner_membership.user
        )

        current_group.save(
            update_fields=["owner"],
        )

        # Das aktuelle Gruppenobjekt mit dem
        # neuen Eigentümer verwenden.
        new_owner_membership.group = (
            current_group
        )

        GroupMembership.objects.filter(
            group=current_group,
        ).update(
            is_creator=False,
        )

        new_owner_membership.is_creator = True

        new_owner_membership.save(
            update_fields=["is_creator"],
        )

        new_owner_name = (
            new_owner_membership.user.username
            or new_owner_membership.user.email
            or f"Jugador {new_owner_membership.user_id}"
        )

        group_name = current_group.name

    messages.success(
        request,
        (
            f"La administración de «{group_name}» "
            f"fue transferida a {new_owner_name}."
        ),
    )

    return redirect("my_groups")

@login_required
@require_POST
def delete_group(request, group_id):
    confirmation = (
        request.POST
        .get("confirmation", "")
        .strip()
    )

    with transaction.atomic():
        current_group = get_object_or_404(
            Group.objects
            .select_for_update()
            .select_related("owner"),
            id=group_id,
        )

        current_membership = (
            GroupMembership.objects
            .filter(
                group=current_group,
                user=request.user,
            )
            .first()
        )

        is_owner = (
            current_group.owner_id == request.user.id
            or (
                current_group.owner_id is None
                and current_membership is not None
                and current_membership.is_creator
            )
        )

        if not is_owner:
            messages.error(
                request,
                "No tienes permiso para eliminar este grupo.",
            )
            return redirect("my_groups")

        if confirmation != current_group.name:
            messages.error(
                request,
                (
                    "El nombre introducido no coincide con "
                    "el nombre del grupo."
                ),
            )
            return redirect("my_groups")

        group_name = current_group.name

        was_active_group = (
            request.session.get("active_group_id")
            == current_group.id
        )

        # Gruppenspezifische Tipps ausdrücklich löschen.
        Prediction.objects.filter(
            group=current_group,
        ).delete()

        BonusPrediction.objects.filter(
            group=current_group,
        ).delete()

        GroupMembership.objects.filter(
            group=current_group,
        ).delete()

        current_group.delete()

    # Falls die aktive Gruppe gelöscht wurde,
    # eine andere Mitgliedschaft aktivieren.
    if was_active_group:
        next_membership = (
            GroupMembership.objects
            .filter(user=request.user)
            .select_related("group")
            .order_by("id")
            .first()
        )

        if next_membership:
            request.session["active_group_id"] = (
                next_membership.group_id
            )
        else:
            request.session.pop(
                "active_group_id",
                None,
            )

    messages.success(
        request,
        f"El grupo «{group_name}» fue eliminado permanentemente.",
    )

    return redirect("my_groups")

@login_required
@require_POST
def set_active_group(request: HttpRequest):
    group_id = request.POST.get("group_id")

    membership = (
        GroupMembership.objects
        .filter(
            user=request.user,
            group_id=group_id,
        )
        .select_related("group")
        .first()
    )

    if not membership:
        messages.error(
            request,
            "No perteneces a este grupo.",
        )
        return redirect("dashboard")

    request.session["active_group_id"] = (
        membership.group_id
    )

    messages.success(
        request,
        (
            "Grupo activo: "
            f"{membership.group.name}"
        ),
    )

    return redirect("dashboard")

@login_required
@require_POST
def leave_group(request, group_id):
    with transaction.atomic():
        membership = get_object_or_404(
            GroupMembership.objects
            .select_for_update()
            .select_related(
                "group__owner",
            ),
            user=request.user,
            group_id=group_id,
        )

        group = membership.group

        is_owner = (
            group.owner_id == request.user.id
            or (
                group.owner_id is None
                and membership.is_creator
            )
        )

        if is_owner:
            messages.error(
                request,
                (
                    "No puedes abandonar un grupo "
                    "que administras. Primero debes "
                    "transferir la administración "
                    "o eliminar el grupo."
                ),
            )
            return redirect("my_groups")

        was_active_group = (
            request.session.get(
                "active_group_id"
            )
            == group.id
        )

        group_name = group.name

        # Gruppenspezifische persönliche Daten
        # vor der Mitgliedschaft löschen.
        Prediction.objects.filter(
            user=request.user,
            group=group,
        ).delete()

        BonusPrediction.objects.filter(
            user=request.user,
            group=group,
        ).delete()

        membership.delete()

    if was_active_group:
        next_membership = (
            GroupMembership.objects
            .filter(user=request.user)
            .select_related("group")
            .order_by("id")
            .first()
        )

        if next_membership:
            request.session[
                "active_group_id"
            ] = next_membership.group_id

        else:
            request.session.pop(
                "active_group_id",
                None,
            )

    messages.success(
        request,
        (
            f"Has abandonado el grupo "
            f"«{group_name}»."
        ),
    )

    return redirect("my_groups")

@login_required
def delete_account(request):
    """
    Löscht das Benutzerkonto dauerhaft.

    Die Löschung ist nicht möglich, solange der Benutzer
    Eigentümer oder ursprünglicher Ersteller einer Gruppe ist.
    """

    # Regulär zugeordnete eigene Gruppen sowie ältere Gruppen,
    # bei denen owner noch leer ist, der Nutzer aber is_creator ist.
    owned_groups = (
        Group.objects
        .filter(
            Q(owner=request.user)
            | Q(
                owner__isnull=True,
                memberships__user=request.user,
                memberships__is_creator=True,
            )
        )
        .select_related("tournament")
        .distinct()
        .order_by("name")
    )

    account_can_be_deleted = not owned_groups.exists()

    if request.method == "POST":
        # Die Berechtigung serverseitig erneut prüfen.
        if not account_can_be_deleted:
            messages.error(
                request,
                (
                    "No puedes eliminar tu cuenta mientras "
                    "administras uno o varios grupos. "
                    "Primero debes transferir la administración "
                    "o eliminar esos grupos."
                ),
            )

            return redirect("delete_account")

        form = DeleteAccountForm(
            request.POST,
            user=request.user,
        )

        if form.is_valid():
            user = request.user


            with transaction.atomic():
                # Eigene Tipps löschen.
                Prediction.objects.filter(
                    user=user,
                ).delete()

                # Eigene Bonustipps löschen.
                BonusPrediction.objects.filter(
                    user=user,
                ).delete()

                # Mitgliedschaften löschen.
                GroupMembership.objects.filter(
                    user=user,
                ).delete()

                # Das Löschen des Users entfernt durch die
                # CASCADE-Beziehungen auch das UserProfile und
                # die allauth-Kontodaten aus der Datenbank.
                user.delete()



            # Sitzung vollständig beenden.
            logout(request)

            # Die Nachricht erst nach logout erzeugen, damit sie in
            # der neuen anonymen Sitzung erhalten bleibt.
            messages.success(
                request,
                "Tu cuenta fue eliminada permanentemente.",
            )

            return redirect("account_login")

    else:
        form = DeleteAccountForm(
            user=request.user,
        )

    active_membership = _require_active_membership(request)

    return render(
        request,
        "tipping/delete_account.html",
        {
            "group": (
                active_membership.group
                if active_membership
                else None
            ),
            "form": form,
            "owned_groups": owned_groups,
            "account_can_be_deleted": account_can_be_deleted,
        },
    )



@login_required
def bonus_tips(request):
    membership = _require_active_membership(request)

    if not membership:
        return redirect("join_group")

    group = membership.group
    tournament = group.tournament

    bonus_lock_time = get_bonus_lock_time(
        tournament
    )

    # Frühe Prüfung für die normale Seitennavigation.
    if (
        bonus_lock_time
        and timezone.now() >= bonus_lock_time
    ):
        messages.error(
            request,
            (
                "Los pronósticos especiales "
                "ya están cerrados."
            ),
        )

        return redirect(
            f"{reverse('spieltag')}?tab=bonus"
        )

    existing_predictions = (
        BonusPrediction.objects
        .filter(
            user=request.user,
            group=group,
            tournament=tournament,
        )
    )

    initial = {
        prediction.bonus_type: prediction.value
        for prediction in existing_predictions
    }

    if request.method == "POST":
        form = BonusPredictionForm(
            request.POST,
            tournament=tournament,
        )

        if form.is_valid():
            with transaction.atomic():
                # Turnier und erstes Spiel während der
                # abschließenden Fristprüfung sperren.
                locked_tournament = (
                    Tournament.objects
                    .select_for_update()
                    .get(pk=tournament.pk)
                )

                first_match = (
                    Match.objects
                    .select_for_update()
                    .filter(
                        tournament=locked_tournament
                    )
                    .order_by("kickoff")
                    .first()
                )

                current_lock_time = (
                    first_match.kickoff
                    if first_match
                    else locked_tournament.season_start
                )

                # Frist unmittelbar vor dem Schreiben
                # erneut serverseitig kontrollieren.
                if (
                    current_lock_time
                    and timezone.now()
                    >= current_lock_time
                ):
                    messages.error(
                        request,
                        (
                            "Los pronósticos especiales "
                            "ya están cerrados."
                        ),
                    )

                    return redirect(
                        (
                            f"{reverse('spieltag')}"
                            "?tab=bonus"
                        )
                    )

                allowed_bonus_types = {
                    bonus_type
                    for bonus_type, _label
                    in BonusPrediction.BONUS_TYPES
                }

                for bonus_type in allowed_bonus_types:
                    value = form.cleaned_data.get(
                        bonus_type
                    )

                    if value is None:
                        continue

                    BonusPrediction.objects.update_or_create(
                        user=request.user,
                        group=group,
                        tournament=locked_tournament,
                        bonus_type=bonus_type,
                        defaults={
                            "value": value,
                        },
                    )

            messages.success(
                request,
                (
                    "Los pronósticos especiales "
                    "se guardaron correctamente."
                ),
            )

            return redirect("bonus_tips")

    else:
        form = BonusPredictionForm(
            initial=initial,
            tournament=tournament,
        )

    return render(
        request,
        "tipping/bonus.html",
        {
            "group": group,
            "form": form,
            "bonus_lock_time": bonus_lock_time,
        },
    )