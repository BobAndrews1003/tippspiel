from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import re
import unicodedata

from django.conf import settings
from django.db import transaction
from django.utils import timezone
import requests

from .models import MAX_GOALS, Match, Tournament


LIGAPRO_SOURCE = "ligapro_official"
MAX_FEED_BYTES = 3 * 1024 * 1024


class LigaProFeedError(RuntimeError):
    """Die LigaPro-Quelle konnte nicht sicher verarbeitet werden."""


@dataclass(frozen=True)
class LigaProFixture:
    external_id: str
    source_round: int
    match_date: date
    kickoff: datetime | None
    home_team: str
    away_team: str
    status: str
    home_score: int | None
    away_score: int | None


@dataclass
class LigaProSyncResult:
    fetched: int = 0
    matched: int = 0
    linked: int = 0
    changed: int = 0
    kickoff_updates: int = 0
    live_updates: int = 0
    final_updates: int = 0
    unmatched: list[str] = field(default_factory=list)
    ambiguous: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    has_live_matches: bool = False

    @property
    def skipped(self) -> int:
        return (
            len(self.unmatched)
            + len(self.ambiguous)
            + len(self.conflicts)
        )


def _normalized_team_name(value: str) -> str:
    decomposed = unicodedata.normalize(
        "NFKD",
        value,
    )
    ascii_value = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    return re.sub(
        r"[^a-z0-9]+",
        " ",
        ascii_value.casefold(),
    ).strip()


TEAM_ALIASES = {
    _normalized_team_name(source): canonical
    for source, canonical in {
        "Orense SC": "Orense",
        "Orense": "Orense",
        "Liga Deportiva Universitaria de Quito": "LDU Quito",
        "LDU Quito": "LDU Quito",
        "Barcelona SC": "Barcelona SC",
        "CD Técnico Universitario": "Técnico Universitario",
        "Técnico Universitario": "Técnico Universitario",
        "SD Aucas": "Aucas",
        "Aucas": "Aucas",
        "Mushuc Runa SC": "Mushuc Runa",
        "Mushuc Runa": "Mushuc Runa",
        "CSD Independiente del Valle": "Independiente del Valle",
        "Independiente del Valle": "Independiente del Valle",
        "Guayaquil City FC": "Guayaquil City",
        "Guayaquil City": "Guayaquil City",
        "Delfín SC": "Delfín",
        "Delfín": "Delfín",
        "CD Cuenca": "Deportivo Cuenca",
        "Deportivo Cuenca": "Deportivo Cuenca",
        "CSD Macará": "Macará",
        "Macará": "Macará",
        "Leones FC": "Leones",
        "Leones": "Leones",
        "Libertad Fútbol Club": "Libertad FC",
        "Libertad FC": "Libertad FC",
        (
            "CD Universidad Católica del Ecuador"
        ): "Universidad Católica del Ecuador",
        (
            "Universidad Católica del Ecuador"
        ): "Universidad Católica del Ecuador",
        "CS Emelec": "Emelec",
        "Emelec": "Emelec",
        "Manta FC": "Manta",
        "Manta": "Manta",
    }.items()
}


STATUS_MAP = {
    "fixture": Match.SourceStatus.SCHEDULED,
    "playing": Match.SourceStatus.LIVE,
    "played": Match.SourceStatus.FINISHED,
    "postponed": Match.SourceStatus.POSTPONED,
    "suspended": Match.SourceStatus.POSTPONED,
    "cancelled": Match.SourceStatus.CANCELLED,
    "canceled": Match.SourceStatus.CANCELLED,
}


def _canonical_team_name(value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LigaProFeedError(
            "Ein Spiel enthält keinen gültigen Mannschaftsnamen."
        )

    normalized = _normalized_team_name(value)

    try:
        return TEAM_ALIASES[normalized]

    except KeyError as exc:
        raise LigaProFeedError(
            f"Unbekannte LigaPro-Mannschaft: {value!r}."
        ) from exc


def _score(value) -> int | None:
    if value is None or value in {
        "",
        "-",
        "–",
        "—",
    }:
        return None

    if isinstance(value, bool):
        raise LigaProFeedError(
            "Ein Spielstand enthält einen ungültigen Wahrheitswert."
        )

    try:
        parsed = int(value)

    except (TypeError, ValueError) as exc:
        raise LigaProFeedError(
            f"Ungültiger Spielstand: {value!r}."
        ) from exc

    if not 0 <= parsed <= MAX_GOALS:
        raise LigaProFeedError(
            f"Spielstand außerhalb des erlaubten Bereichs: {parsed}."
        )

    return parsed


def _parse_date(value) -> date:
    if not isinstance(value, str):
        raise LigaProFeedError(
            "Ein Spiel enthält kein gültiges Datum."
        )

    cleaned = value.strip().removesuffix("Z")

    try:
        return datetime.strptime(
            cleaned[:10],
            "%Y-%m-%d",
        ).date()

    except ValueError as exc:
        raise LigaProFeedError(
            f"Ungültiges Spieldatum: {value!r}."
        ) from exc


def _parse_kickoff(
    match_date: date,
    value,
) -> datetime | None:
    if value is None or value == "":
        return None

    if not isinstance(value, str):
        raise LigaProFeedError(
            f"Ungültige Anstoßzeit: {value!r}."
        )

    cleaned = value.strip().removesuffix("Z")

    try:
        parsed_time = datetime.strptime(
            cleaned,
            "%H:%M:%S",
        ).time()

    except ValueError as exc:
        raise LigaProFeedError(
            f"Ungültige Anstoßzeit: {value!r}."
        ) from exc

    naive = datetime.combine(
        match_date,
        parsed_time,
    )
    return timezone.make_aware(
        naive,
        timezone.get_current_timezone(),
    )


def parse_ligapro_payload(
    payload,
    *,
    minimum_fixtures: int,
    maximum_fixtures: int,
) -> list[LigaProFixture]:
    if not isinstance(payload, dict):
        raise LigaProFeedError(
            "Die LigaPro-Antwort ist kein JSON-Objekt."
        )

    rounds = payload.get("result")

    if not isinstance(rounds, list):
        raise LigaProFeedError(
            "Die LigaPro-Antwort enthält keine Spielliste."
        )

    fixtures = []
    external_ids = set()

    for round_row in rounds:
        if not isinstance(round_row, dict):
            raise LigaProFeedError(
                "Die LigaPro-Antwort enthält eine ungültige Runde."
            )

        try:
            source_round = int(
                round_row.get("fechaSemana")
            )

        except (TypeError, ValueError) as exc:
            raise LigaProFeedError(
                "Eine LigaPro-Runde hat keine gültige Nummer."
            ) from exc

        matches = round_row.get("partidos")

        if not isinstance(matches, list):
            raise LigaProFeedError(
                "Eine LigaPro-Runde enthält keine gültigen Spiele."
            )

        for row in matches:
            if not isinstance(row, dict):
                raise LigaProFeedError(
                    "Die LigaPro-Antwort enthält ein ungültiges Spiel."
                )

            external_id = str(
                row.get("idPartido") or ""
            ).strip()

            if not external_id:
                raise LigaProFeedError(
                    "Ein LigaPro-Spiel hat keine stabile ID."
                )

            if external_id in external_ids:
                raise LigaProFeedError(
                    f"Doppelte LigaPro-Spiel-ID: {external_id}."
                )

            external_ids.add(external_id)

            raw_status = str(
                row.get("estadoComet") or ""
            ).strip().casefold()
            status = STATUS_MAP.get(
                raw_status,
                Match.SourceStatus.UNKNOWN,
            )

            local = row.get("clubLocal") or {}
            visitor = row.get("clubVisitante") or {}

            if not isinstance(local, dict) or not isinstance(visitor, dict):
                raise LigaProFeedError(
                    f"Spiel {external_id} enthält ungültige Mannschaften."
                )

            match_date = _parse_date(
                row.get("fechaPartido")
            )
            home_score = _score(
                local.get("scoreLocal")
            )
            away_score = _score(
                visitor.get("scoreVisitante")
            )

            if (home_score is None) != (away_score is None):
                raise LigaProFeedError(
                    f"Spiel {external_id} enthält nur einen Spielstand."
                )

            if (
                status == Match.SourceStatus.FINISHED
                and home_score is None
            ):
                raise LigaProFeedError(
                    f"Beendetes Spiel {external_id} hat kein Ergebnis."
                )

            fixtures.append(
                LigaProFixture(
                    external_id=external_id,
                    source_round=source_round,
                    match_date=match_date,
                    kickoff=_parse_kickoff(
                        match_date,
                        row.get("horaPartido"),
                    ),
                    home_team=_canonical_team_name(
                        local.get("razonSocialLocal")
                    ),
                    away_team=_canonical_team_name(
                        visitor.get("razonSocialVisitante")
                    ),
                    status=status,
                    home_score=home_score,
                    away_score=away_score,
                )
            )

    if not minimum_fixtures <= len(fixtures) <= maximum_fixtures:
        raise LigaProFeedError(
            "Die LigaPro-Antwort enthält unerwartet "
            f"{len(fixtures)} Spiele; erwartet werden "
            f"{minimum_fixtures} bis {maximum_fixtures}."
        )

    return fixtures


def fetch_ligapro_fixtures() -> list[LigaProFixture]:
    try:
        response = requests.get(
            settings.LIGAPRO_SYNC_URL,
            headers={
                "Accept": "application/json",
                "User-Agent": settings.LIGAPRO_SYNC_USER_AGENT,
            },
            timeout=settings.LIGAPRO_SYNC_TIMEOUT_SECONDS,
        )
        response.raise_for_status()

    except requests.RequestException as exc:
        raise LigaProFeedError(
            f"LigaPro-Daten konnten nicht geladen werden: {exc}."
        ) from exc

    if len(response.content) > MAX_FEED_BYTES:
        raise LigaProFeedError(
            "Die LigaPro-Antwort ist unerwartet groß."
        )

    try:
        payload = response.json()

    except ValueError as exc:
        raise LigaProFeedError(
            "Die LigaPro-Antwort enthält kein gültiges JSON."
        ) from exc

    return parse_ligapro_payload(
        payload,
        minimum_fixtures=(
            settings.LIGAPRO_SYNC_MIN_FIXTURES
        ),
        maximum_fixtures=(
            settings.LIGAPRO_SYNC_MAX_FIXTURES
        ),
    )


def _local_match_date(match: Match) -> date:
    return timezone.localtime(
        match.kickoff
    ).date()


def _candidate_matches(
    fixture: LigaProFixture,
    matches: list[Match],
) -> list[Match]:
    candidates = [
        match
        for match in matches
        if (
            not match.external_source
            and match.home_team == fixture.home_team
            and match.away_team == fixture.away_team
            and (
                match.matchday == fixture.source_round
                or match.stage_round == fixture.source_round
            )
        )
    ]

    if len(candidates) <= 1:
        return candidates

    distances = {
        match.id: abs(
            (_local_match_date(match) - fixture.match_date).days
        )
        for match in candidates
    }
    shortest_distance = min(distances.values())
    return [
        match
        for match in candidates
        if distances[match.id] == shortest_distance
    ]


def _fixture_label(fixture: LigaProFixture) -> str:
    return (
        f"{fixture.external_id}: {fixture.home_team} – "
        f"{fixture.away_team} ({fixture.match_date.isoformat()})"
    )


def _apply_fixture_to_match(
    match: Match,
    fixture: LigaProFixture,
) -> tuple[list[str], bool, bool, bool]:
    update_fields = []
    kickoff_changed = False
    live_changed = False
    final_changed = False

    def set_value(field_name: str, value) -> None:
        nonlocal kickoff_changed, live_changed, final_changed

        if getattr(match, field_name) == value:
            return

        setattr(match, field_name, value)
        update_fields.append(field_name)

        if field_name == "kickoff":
            kickoff_changed = True

        if field_name in {
            "live_home_score",
            "live_away_score",
        }:
            live_changed = True

        if field_name in {
            "home_score",
            "away_score",
        }:
            final_changed = True

    set_value("external_source", LIGAPRO_SOURCE)
    set_value("external_id", fixture.external_id)

    if fixture.kickoff is not None:
        set_value("kickoff", fixture.kickoff)

    # Ein bereits bestätigtes Endergebnis wird nicht durch einen
    # vorübergehend zurückgestuften Quellstatus entwertet.
    effective_status = fixture.status

    if (
        match.has_result
        and fixture.status != Match.SourceStatus.FINISHED
    ):
        effective_status = Match.SourceStatus.FINISHED

    set_value("source_status", effective_status)

    if fixture.status == Match.SourceStatus.LIVE:
        if (
            fixture.home_score is not None
            and fixture.away_score is not None
        ):
            set_value(
                "live_home_score",
                fixture.home_score,
            )
            set_value(
                "live_away_score",
                fixture.away_score,
            )

    elif fixture.status == Match.SourceStatus.FINISHED:
        set_value("live_home_score", None)
        set_value("live_away_score", None)
        set_value("home_score", fixture.home_score)
        set_value("away_score", fixture.away_score)

    else:
        set_value("live_home_score", None)
        set_value("live_away_score", None)

    return (
        update_fields,
        kickoff_changed,
        live_changed,
        final_changed,
    )


def sync_ligapro_matches(
    *,
    apply: bool,
    fixtures: list[LigaProFixture] | None = None,
) -> LigaProSyncResult:
    if fixtures is None:
        fixtures = fetch_ligapro_fixtures()

    result = LigaProSyncResult(
        fetched=len(fixtures),
        has_live_matches=any(
            fixture.status == Match.SourceStatus.LIVE
            for fixture in fixtures
        ),
    )

    try:
        tournament = Tournament.objects.get(
            name=settings.LIGAPRO_SYNC_TOURNAMENT,
        )

    except Tournament.DoesNotExist as exc:
        raise LigaProFeedError(
            "Das konfigurierte LigaPro-Turnier existiert nicht: "
            f"{settings.LIGAPRO_SYNC_TOURNAMENT!r}."
        ) from exc

    matches = list(
        Match.objects
        .filter(tournament=tournament)
        .select_related("stage")
        .order_by("id")
    )
    linked_by_external_id = {
        match.external_id: match
        for match in matches
        if match.external_source == LIGAPRO_SOURCE
    }
    used_match_ids = set()
    synced_match_ids = []
    sync_time = timezone.now()

    with transaction.atomic():
        for fixture in fixtures:
            label = _fixture_label(fixture)
            match = linked_by_external_id.get(
                fixture.external_id
            )
            newly_linked = False

            if match is not None:
                if (
                    match.home_team != fixture.home_team
                    or match.away_team != fixture.away_team
                ):
                    result.conflicts.append(
                        f"{label}: Mannschaften weichen von der "
                        "bereits verknüpften Partie ab."
                    )
                    continue

            else:
                candidates = _candidate_matches(
                    fixture,
                    matches,
                )

                if not candidates:
                    result.unmatched.append(label)
                    continue

                if len(candidates) > 1:
                    result.ambiguous.append(label)
                    continue

                match = candidates[0]
                newly_linked = True

            if match.id in used_match_ids:
                result.conflicts.append(
                    f"{label}: lokale Partie wurde mehrfach zugeordnet."
                )
                continue

            used_match_ids.add(match.id)
            result.matched += 1

            (
                update_fields,
                kickoff_changed,
                live_changed,
                final_changed,
            ) = _apply_fixture_to_match(
                match,
                fixture,
            )

            if newly_linked:
                result.linked += 1

            if kickoff_changed:
                result.kickoff_updates += 1

            if live_changed:
                result.live_updates += 1

            if final_changed:
                result.final_updates += 1

            if update_fields:
                result.changed += 1

                if apply:
                    match.save(
                        update_fields=update_fields,
                    )

            if apply:
                synced_match_ids.append(match.id)

        if apply and synced_match_ids:
            Match.objects.filter(
                id__in=synced_match_ids,
            ).update(
                source_synced_at=sync_time,
            )

        # Ein produktiver Lauf ist atomar: Sobald auch nur eine
        # Partie nicht sicher zugeordnet werden kann, wird keine der
        # vorherigen Änderungen übernommen. So entsteht kein
        # unbemerkter Mischstand aus alter und neuer Quelle.
        if not apply or result.skipped:
            transaction.set_rollback(True)

    return result


def next_ligapro_sync_delay() -> int:
    live_seconds = settings.LIGAPRO_SYNC_LIVE_SECONDS
    idle_seconds = settings.LIGAPRO_SYNC_IDLE_SECONDS
    now = timezone.now()

    matches = Match.objects.filter(
        tournament__name=settings.LIGAPRO_SYNC_TOURNAMENT,
    )

    if matches.filter(
        source_status=Match.SourceStatus.LIVE,
    ).exists():
        return live_seconds

    window_start = now - timedelta(
        minutes=settings.LIGAPRO_SYNC_WINDOW_AFTER_MINUTES,
    )
    window_end = now + timedelta(
        minutes=settings.LIGAPRO_SYNC_WINDOW_BEFORE_MINUTES,
    )

    if matches.filter(
        home_score__isnull=True,
        away_score__isnull=True,
        kickoff__gte=window_start,
        kickoff__lte=window_end,
    ).exists():
        return live_seconds

    next_kickoff = (
        matches
        .filter(
            home_score__isnull=True,
            away_score__isnull=True,
            kickoff__gt=window_end,
        )
        .order_by("kickoff")
        .values_list("kickoff", flat=True)
        .first()
    )

    if next_kickoff is None:
        return idle_seconds

    seconds_until_window = int(
        (
            next_kickoff
            - now
            - timedelta(
                minutes=(
                    settings.LIGAPRO_SYNC_WINDOW_BEFORE_MINUTES
                ),
            )
        ).total_seconds()
    )
    return max(
        live_seconds,
        min(
            idle_seconds,
            seconds_until_window,
        ),
    )
