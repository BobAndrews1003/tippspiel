from __future__ import annotations

from collections import Counter, defaultdict

from typing import Optional


from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import HttpRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST


from .forms import GroupCreateForm, BonusPredictionForm
from .models import Group, GroupMembership, Match, Prediction, BonusPrediction

User = get_user_model()


# ---------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------

def _outcome(h: int, a: int) -> int:
    """1=Heimsieg, 0=Remis, -1=Auswärtssieg"""
    return (h > a) - (h < a)


def points_for_prediction(match: Match, pred: Prediction | None) -> int:
    """
    Kicktipp-like:
    4 = exaktes Ergebnis
    3 = richtige Tordifferenz
    2 = richtige Tendenz (S/U/N)
    0 = falsch / keine Daten
    """
    if pred is None:
        return 0
    if match.home_score is None or match.away_score is None:
        return 0
    if pred.pred_home is None or pred.pred_away is None:
        return 0

    # 3 Punkte: exakter Tipp
    if pred.pred_home == match.home_score and pred.pred_away == match.away_score:
        return 4

    # 2 Punkte: richtige Tordifferenz
    if (pred.pred_home - pred.pred_away) == (match.home_score - match.away_score):
        return 3

    # 1 Punkt: richtige Tendenz
    if _outcome(pred.pred_home, pred.pred_away) == _outcome(match.home_score, match.away_score):
        return 2

    return 0


def bonus_points_for_user(tournament, preds: list[BonusPrediction]) -> int:
    """
    +5 Punkte pro richtigem Bonustipp.

    Tournament-Felder:
      autumn_champion, champion, first_coach_sacked, top_scorer, relegated_teams (kommagetrennt)

    BonusPrediction-Typen:
      herbstmeister, meister, trainer_first, topscorer, relegation1, relegation2
    """
    def _norm(s: str) -> str:
        return (s or "").strip().lower()

    real_herbst = _norm(getattr(tournament, "autumn_champion", ""))
    real_meister = _norm(getattr(tournament, "champion", ""))
    real_trainer = _norm(getattr(tournament, "first_coach_sacked", ""))
    real_topscorer = _norm(getattr(tournament, "top_scorer", ""))

    relegated_raw = getattr(tournament, "relegated_teams", "") or ""
    relegated_set = {_norm(x) for x in relegated_raw.split(",") if _norm(x)}

    pts = 0

    # ✅ schützt gegen Doppelwertung bei relegation1/relegation2
    counted_relegations: set[str] = set()

    for bp in preds:
        btype = bp.bonus_type
        val = _norm(bp.value)

        if not val:
            continue

        if btype == "herbstmeister" and real_herbst and val == real_herbst:
            pts += 5

        elif btype == "meister" and real_meister and val == real_meister:
            pts += 5

        elif btype == "trainer_first" and real_trainer and val == real_trainer:
            pts += 5

        elif btype == "topscorer" and real_topscorer and val == real_topscorer:
            pts += 5

        elif btype in {"relegation1", "relegation2"} and relegated_set and val in relegated_set:
            if val not in counted_relegations:
                pts += 5
                counted_relegations.add(val)

    return pts



# ---------------------------------------------------------------------
# Membership / Matchday helpers
# ---------------------------------------------------------------------

def _get_membership(request):
    """
    Gibt die Membership der aktuell aktiven Gruppe zurück.
    Die aktive Gruppe wird in der Session gespeichert.
    """

    qs = (
        GroupMembership.objects
        .filter(user=request.user)
        .select_related("group__tournament")
        .order_by("id")
    )

    if not qs.exists():
        return None

    active_group_id = request.session.get("active_group_id")

    # Falls Session-Gruppe existiert → prüfen ob gültig
    if active_group_id:
        membership = qs.filter(group_id=active_group_id).first()
        if membership:
            return membership

    # Fallback: erste Gruppe setzen
    membership = qs.first()
    request.session["active_group_id"] = membership.group_id
    return membership

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
def tippen(request):
    # ✅ Einheitlich: aktive Gruppe aus Session holen (oder fallback), sonst redirect
    membership = _require_active_membership(request)
    if not membership:
        return redirect("join_group")

    group = membership.group
    tournament = group.tournament

    now = timezone.now()

    # Spieltag wählen (Default: nächstes zukünftiges Spiel oder ?md=)
    matchday = _get_selected_matchday(request, tournament, now)
    if matchday is None:
        return render(request, "tipping/tippen.html", {
            "group": group,
            "matchday": None,
            "rows": [],
            "prev_md": None,
            "next_md": None,
            "now": now,
        })

    def _matches_for_md(md: int):
        return (
            Match.objects
            .filter(tournament=tournament, matchday=md)
            .order_by("kickoff", "home_team")
        )

    matches = _matches_for_md(matchday)

    # Falls aus irgendeinem Grund md leer ist → nochmal Default bestimmen
    if not matches.exists():
        matchday = _get_selected_matchday(request, tournament, now)
        if matchday is None:
            return render(request, "tipping/tippen.html", {
                "group": group,
                "matchday": None,
                "rows": [],
                "prev_md": None,
                "next_md": None,
                "now": now,
            })
        matches = _matches_for_md(matchday)

    prev_md, next_md = _prev_next_md(tournament, matchday)

    preds = {
        p.match_id: p
        for p in Prediction.objects.filter(user=request.user, group=group, match__in=matches)
    }
    rows = [{"match": m, "pred": preds.get(m.id)} for m in matches]

    if request.method == "POST":
        saved = 0
        skipped_locked = 0
        now = timezone.now()  # Locking immer mit aktuellem "jetzt"

        for m in matches:
            # ab Anstoß sperren
            if m.kickoff <= now:
                skipped_locked += 1
                continue

            hk = f"pred_home_{m.id}"
            ak = f"pred_away_{m.id}"

            home_val = request.POST.get(hk, "").strip()
            away_val = request.POST.get(ak, "").strip()

            if home_val == "" or away_val == "":
                continue

            try:
                ph = int(home_val)
                pa = int(away_val)
                if ph < 0 or pa < 0:
                    continue
            except ValueError:
                continue

            Prediction.objects.update_or_create(
                user=request.user,
                group=group,
                match=m,
                defaults={"pred_home": ph, "pred_away": pa},
            )
            saved += 1

        if saved > 0:
            if skipped_locked > 0:
                messages.success(
                    request,
                    f"Tipps gespeichert ✅ ({saved}) — {skipped_locked} Spiel(e) waren gesperrt."
                )
            else:
                messages.success(request, f"Tipps gespeichert ✅ ({saved})")
        else:
            messages.info(request, "Keine Tipps gespeichert (leere oder ungültige Eingaben).")

        # ✅ Wichtig: im gleichen Spieltag bleiben
        return redirect(f"{request.path}?md={matchday}")

    return render(request, "tipping/tippen.html", {
        "group": group,
        "matchday": matchday,
        "rows": rows,
        "prev_md": prev_md,
        "next_md": next_md,
        "now": now,
    })


@login_required
def spieltag(request):
    membership = _require_active_membership(request)
    if not membership:
        return redirect("join_group")

    group = membership.group
    tournament = group.tournament
    now = timezone.now()

    tab = request.GET.get("tab", "matches")
    if tab not in {"matches", "bonus"}:
        tab = "matches"

    # Bonustipps sind für alle erst sichtbar, wenn season_start gesetzt UND erreicht
    season_start = tournament.season_start
    bonus_reveal = bool(season_start and now >= season_start)

    # --- Spieler in Gruppe ---
    memberships = list(
        GroupMembership.objects
        .filter(group=group)
        .select_related("user")
        .order_by("user__username")
    )
    users = [m.user for m in memberships]

    # --- BONUSTAB ---
    bonus_rows = []
    my_bonus = None

    if tab == "bonus":
        # lade alle Bonustipps der Gruppe
        all_bonus = list(
            BonusPrediction.objects
            .filter(group=group, tournament=tournament, user__in=users)
            .select_related("user")
        )

        # gruppieren: user_id -> list[BonusPrediction]
        bonus_by_user = defaultdict(list)
        for bp in all_bonus:
            bonus_by_user[bp.user_id].append(bp)

        # eigene Bonustipps (für Anzeige vor Lock)
        my_bonus = bonus_by_user.get(request.user.id, [])

        if bonus_reveal:
            for u in users:
                preds = bonus_by_user.get(u.id, [])
                pts = bonus_points_for_user(tournament, preds)
                by_type = {p.bonus_type: p.value for p in preds}

                bonus_rows.append({
                    "user": u,
                    "points": pts,
                    "picks": {
                        "herbstmeister": by_type.get("herbstmeister", ""),
                        "meister": by_type.get("meister", ""),
                        "trainer_first": by_type.get("trainer_first", ""),
                        "topscorer": by_type.get("topscorer", ""),
                        "relegation1": by_type.get("relegation1", ""),
                        "relegation2": by_type.get("relegation2", ""),
                    }
                })

            bonus_rows.sort(key=lambda r: (-r["points"], r["user"].username.lower()))

    # --- MATCHTAB (dein bisheriger Code) ---
    # (Hier bleibt dein bisheriger Matchday/Matrix-Code, nur: total_points += bonus_points wenn reveal)

    matchday = _get_selected_matchday(request, tournament, now)
    if matchday is None:
        return render(request, "tipping/spieltag.html", {
            "group": group,
            "tab": tab,
            "matchday": None,
            "matches": [],
            "table_rows": [],
            "prev_md": None,
            "next_md": None,
            "now": now,
            "season_start": season_start,
            "bonus_reveal": bonus_reveal,
            "bonus_rows": bonus_rows,
            "my_bonus": my_bonus,
        })

    matches = list(
        Match.objects.filter(tournament=tournament, matchday=matchday)
        .order_by("kickoff", "home_team")
    )
    prev_md, next_md = _prev_next_md(tournament, matchday)

    all_preds = (
        Prediction.objects
        .filter(group=group, match__in=matches, user__in=users)
        .select_related("user", "match")
    )
    pred_map = {(p.user_id, p.match_id): p for p in all_preds}

    match_headers = [
        {
            "match": m,
            "result": (m.home_score, m.away_score)
            if (m.home_score is not None and m.away_score is not None)
            else None,
        }
        for m in matches
    ]

    # Bonuspunkte (pro User) nur addieren, wenn reveal
    bonus_points_map = {}
    if bonus_reveal:
        all_bonus = list(
            BonusPrediction.objects
            .filter(group=group, tournament=tournament, user__in=users)
            .select_related("user")
        )
        bonus_by_user = defaultdict(list)
        for bp in all_bonus:
            bonus_by_user[bp.user_id].append(bp)
        for u in users:
            bonus_points_map[u.id] = bonus_points_for_user(tournament, bonus_by_user.get(u.id, []))
    else:
        for u in users:
            bonus_points_map[u.id] = 0

    table_rows = []
    for u in users:
        total_points = 0
        cells = []

        for m in matches:
            reveal = (m.kickoff <= now)
            p = pred_map.get((u.id, m.id))

            cell_points = points_for_prediction(m, p) if reveal else None
            if cell_points is not None:
                total_points += cell_points

            cells.append({"reveal": reveal, "pred": p, "points": cell_points})

        # ✅ Bonuspunkte (nur wenn reveal, sonst 0)
        total_points_with_bonus = total_points + bonus_points_map.get(u.id, 0)

        table_rows.append({
            "user": u,
            "cells": cells,
            "total_points": total_points,
            "bonus_points": bonus_points_map.get(u.id, 0),
            "total_with_bonus": total_points_with_bonus,
        })

    # sortiert nach Total inkl Bonus sobald reveal
    if bonus_reveal:
        table_rows.sort(key=lambda r: (-r["total_with_bonus"], r["user"].username.lower()))
    else:
        table_rows.sort(key=lambda r: (-r["total_points"], r["user"].username.lower()))

    return render(request, "tipping/spieltag.html", {
        "group": group,
        "tab": tab,
        "matchday": matchday,
        "matches": match_headers,
        "table_rows": table_rows,
        "prev_md": prev_md,
        "next_md": next_md,
        "now": now,
        "season_start": season_start,
        "bonus_reveal": bonus_reveal,
        "bonus_rows": bonus_rows,
        "my_bonus": my_bonus,
    })



@login_required
def tabelle(request):
    # ✅ Einheitlich: aktive Gruppe aus Session holen (oder fallback), sonst redirect
    membership = _require_active_membership(request)
    if not membership:
        return redirect("join_group")

    group = membership.group
    tournament = group.tournament

    # ✅ Bonus erst sichtbar/gewertet, wenn season_start erreicht ist
    now = timezone.now()
    season_start = tournament.season_start
    bonus_reveal = bool(season_start and now >= season_start)

    # --- View Tab (mdpoints / ranks / rankdiff) -----------------------------
    view = request.GET.get("view", "mdpoints")
    if view not in {"mdpoints", "ranks", "rankdiff"}:
        view = "mdpoints"

    # --- Spaltenfenster (Pagination über Spieltage) -------------------------
    try:
        from_idx = int(request.GET.get("from", "0"))
    except ValueError:
        from_idx = 0

    try:
        count = int(request.GET.get("count", "8"))
    except ValueError:
        count = 8

    count = max(4, min(count, 15))

    # --- Alle Spieltage im Turnier -----------------------------------------
    matchdays = list(
        Match.objects
        .filter(tournament=tournament)
        .exclude(matchday__isnull=True)
        .values_list("matchday", flat=True)
        .distinct()
        .order_by("matchday")
    )

    if not matchdays:
        return render(request, "tipping/tabelle.html", {
            "group": group,
            "view": view,
            "matchdays": [],
            "shown_matchdays": [],
            "table_rows": [],
            "prev_from": None,
            "next_from": None,
            "count": count,
            "me_id": request.user.id,
            "bonus_enabled": True,
            "bonus_reveal": bonus_reveal,
        })

    # from_idx clamp
    if from_idx < 0:
        from_idx = 0
    if from_idx >= len(matchdays):
        from_idx = max(0, len(matchdays) - count)

    shown_matchdays = matchdays[from_idx:from_idx + count]
    prev_from = from_idx - count if (from_idx - count) >= 0 else None
    next_from = from_idx + count if (from_idx + count) < len(matchdays) else None

    # --- Alle Spieler der Gruppe -------------------------------------------
    memberships = list(
        GroupMembership.objects
        .filter(group=group)
        .select_related("user")
        .order_by("user__username")
    )
    users = [m.user for m in memberships]

    # ----------------------------------------------------------------------
    # Σ = Gesamtpunkte über ALLE Spieltage (nur Matches mit Ergebnis)
    # ----------------------------------------------------------------------
    finished_preds = (
        Prediction.objects
        .filter(
            group=group,
            match__tournament=tournament,
            match__home_score__isnull=False,
            match__away_score__isnull=False,
        )
        .select_related("match", "user")
    )

    total_points_all = {u.id: 0 for u in users}
    for pr in finished_preds:
        total_points_all[pr.user_id] = total_points_all.get(pr.user_id, 0) + points_for_prediction(pr.match, pr)

    # ----------------------------------------------------------------------
    # ✅ BONUS: +5 Punkte pro richtigem Bonustipp (nur wenn Bonus "reveal")
    # ----------------------------------------------------------------------
    bonus_points_by_user = defaultdict(int)

    if bonus_reveal:
        all_bonus = list(
            BonusPrediction.objects
            .filter(group=group, tournament=tournament, user__in=users)
            .select_related("user")
        )

        bonus_by_user = defaultdict(list)
        for bp in all_bonus:
            bonus_by_user[bp.user_id].append(bp)

        for u in users:
            bonus_points_by_user[u.id] = bonus_points_for_user(
                tournament,
                bonus_by_user.get(u.id, [])
            )

        # Bonuspunkte auf Σ draufaddieren
        for u in users:
            total_points_all[u.id] = total_points_all.get(u.id, 0) + bonus_points_by_user.get(u.id, 0)

    # ----------------------------------------------------------------------
    # Spalten-Fenster: md_points / ranks / rankdiff nur für shown_matchdays
    # ----------------------------------------------------------------------
    matches = list(
        Match.objects
        .filter(tournament=tournament, matchday__in=shown_matchdays)
        .order_by("matchday", "kickoff", "home_team")
    )

    matches_by_md = {md: [] for md in shown_matchdays}
    for m in matches:
        matches_by_md[m.matchday].append(m)

    match_ids = [m.id for m in matches]

    all_preds = list(
        Prediction.objects
        .filter(group=group, match_id__in=match_ids, user__in=users)
        .select_related("user", "match")
    )
    pred_map = {(p.user_id, p.match_id): p for p in all_preds}

    # md_points[user_id][md] = int oder None (wenn an dem Spieltag noch keine Ergebnisse existieren)
    md_points = {u.id: {md: None for md in shown_matchdays} for u in users}

    for u in users:
        for md in shown_matchdays:
            md_matches = matches_by_md.get(md, [])
            if not md_matches:
                md_points[u.id][md] = None
                continue

            scored_any = False
            total = 0

            for m in md_matches:
                if m.home_score is None or m.away_score is None:
                    continue
                scored_any = True
                p = pred_map.get((u.id, m.id))
                total += points_for_prediction(m, p)

            md_points[u.id][md] = total if scored_any else None

    # --- Ränge pro Spieltag -------------------------------------------------
    rank_by_md = {md: {} for md in shown_matchdays}

    for md in shown_matchdays:
        any_results = any(
            (m.home_score is not None and m.away_score is not None)
            for m in matches_by_md.get(md, [])
        )
        if not any_results:
            for u in users:
                rank_by_md[md][u.id] = None
            continue

        sortable = []
        for u in users:
            pts = md_points[u.id][md]
            pts = pts if pts is not None else 0
            sortable.append((pts, u.username.lower(), u.id))

        sortable.sort(key=lambda x: (-x[0], x[1]))

        rank = 0
        last_pts = None
        for idx, (pts, _name, uid) in enumerate(sortable, start=1):
            if last_pts is None or pts != last_pts:
                rank = idx
                last_pts = pts
            rank_by_md[md][uid] = rank

    # --- Platzierungsdifferenz (vs vorherige Spalte im Fenster) -------------
    rankdiff_by_md = {md: {} for md in shown_matchdays}

    for i, md in enumerate(shown_matchdays):
        prev_md_local = shown_matchdays[i - 1] if i > 0 else None

        for u in users:
            cur = rank_by_md[md].get(u.id)

            if prev_md_local is None:
                rankdiff_by_md[md][u.id] = None
                continue

            prev = rank_by_md[prev_md_local].get(u.id)

            if cur is None or prev is None:
                rankdiff_by_md[md][u.id] = None
            else:
                # positiv = verbessert (z.B. von 5 auf 3 -> +2)
                rankdiff_by_md[md][u.id] = prev - cur

    # --- Template Rows ------------------------------------------------------
    table_rows = []
    for u in users:
        if view == "mdpoints":
            cells = [md_points[u.id][md] for md in shown_matchdays]
        elif view == "ranks":
            cells = [rank_by_md[md][u.id] for md in shown_matchdays]
        else:  # rankdiff
            cells = [rankdiff_by_md[md][u.id] for md in shown_matchdays]

        table_rows.append({
            "user": u,
            "cells": cells,
            "bonus": bonus_points_by_user.get(u.id, 0) if bonus_reveal else None,  # optional im Template
            "total": total_points_all.get(u.id, 0),  # enthält Bonus nur wenn reveal
        })

    # Sortierung wie Kicktipp: Σ absteigend, dann Username
    table_rows.sort(key=lambda r: (-r["total"], r["user"].username.lower()))

    return render(request, "tipping/tabelle.html", {
        "group": group,
        "view": view,
        "matchdays": matchdays,
        "shown_matchdays": shown_matchdays,
        "table_rows": table_rows,
        "prev_from": prev_from,
        "next_from": next_from,
        "count": count,
        "me_id": request.user.id,
        "bonus_enabled": True,
        "bonus_reveal": bonus_reveal,
        "season_start": season_start,
    })
    
    
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
    target_user = get_object_or_404(
        User,
        id=user_id,
        groupmembership__group=group,
    )

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
        pts = points_for_prediction(m, p)
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
                    group = form.save()

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
@require_POST
def set_active_group(request: HttpRequest):
    group_id = request.POST.get("group_id")

    membership = (
        GroupMembership.objects
        .filter(user=request.user, group_id=group_id)
        .select_related("group")
        .first()
    )

    if not membership:
        messages.error(request, "Du bist nicht Mitglied dieser Gruppe.")
        return redirect(request.META.get("HTTP_REFERER", "tippen"))

    request.session["active_group_id"] = membership.group_id
    messages.success(request, f"Aktive Gruppe: {membership.group.name}")
    return redirect(request.META.get("HTTP_REFERER", "tippen"))


@login_required
def bonus_tips(request):
    membership = _require_active_membership(request)
    if not membership:
        return redirect("join_group")

    group = membership.group
    tournament = group.tournament

    # ✅ Locking nur, wenn season_start gesetzt ist
    season_start = tournament.season_start
    if season_start and timezone.now() >= season_start:
        messages.error(request, "Bonustipps sind gesperrt.")
        return redirect("tippen")

    # ✅ existierende Bonustipps laden und als initial setzen
    existing = BonusPrediction.objects.filter(
        user=request.user,
        group=group,
        tournament=tournament
    )

    initial = {bp.bonus_type: bp.value for bp in existing}

    if request.method == "POST":
        form = BonusPredictionForm(
            request.POST,
            tournament=tournament   # ✅ WICHTIG
        )

        if form.is_valid():
            for field, value in form.cleaned_data.items():
                BonusPrediction.objects.update_or_create(
                    user=request.user,
                    group=group,
                    tournament=tournament,
                    bonus_type=field,
                    defaults={"value": value},
                )

            messages.success(request, "Bonustipps gespeichert.")
            return redirect("bonus_tips")

    else:
        form = BonusPredictionForm(
            initial=initial,
            tournament=tournament   # ✅ WICHTIG
        )

    return render(request, "tipping/bonus.html", {
        "group": group,
        "form": form,
        "season_start": season_start,
    })