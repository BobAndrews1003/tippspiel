from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .models import (
    Match,
    Tournament,
    TournamentStage,
)


@dataclass(frozen=True)
class StageDefinition:
    code: str
    name: str
    sort_order: int
    round_count: int


DEFAULT_STAGE_DEFINITIONS = (
    StageDefinition(
        code=TournamentStage.Code.REGULAR,
        name="Fase regular",
        sort_order=1,
        round_count=30,
    ),
    StageDefinition(
        code=TournamentStage.Code.HEXAGONAL_FINAL,
        name="Hexagonal final",
        sort_order=2,
        round_count=10,
    ),
    StageDefinition(
        code=TournamentStage.Code.CUADRANGULAR,
        name="Cuadrangular",
        sort_order=3,
        round_count=6,
    ),
    StageDefinition(
        code=TournamentStage.Code.HEXAGONAL_DESCENT,
        name="Hexagonal de descenso",
        sort_order=4,
        round_count=10,
    ),
)


@dataclass(frozen=True)
class MatchdayMetadata:
    number: int
    label: str
    is_final: bool
    stage_round: int | None
    stage_names: tuple[str, ...]


def ensure_default_stages(
    tournament: Tournament,
) -> None:
    """Legt fehlende Standardphasen an, ohne Anpassungen zu überschreiben."""

    existing_codes = set(
        TournamentStage.objects
        .filter(tournament=tournament)
        .values_list("code", flat=True)
    )

    TournamentStage.objects.bulk_create(
        [
            TournamentStage(
                tournament=tournament,
                code=definition.code,
                name=definition.name,
                sort_order=definition.sort_order,
                round_count=definition.round_count,
            )
            for definition in DEFAULT_STAGE_DEFINITIONS
            if definition.code not in existing_codes
        ],
        ignore_conflicts=True,
    )


def stage_label_for_match(match: Match) -> str:
    stage = getattr(match, "stage", None)

    if (
        stage is None
        or stage.code == TournamentStage.Code.REGULAR
    ):
        return ""

    return stage.name


def matchday_label_for_match(match: Match) -> str:
    if stage_label_for_match(match):
        visible_round = match.stage_round or match.matchday

        if visible_round is not None:
            return f"Finales · Fecha {visible_round}"

        return "Finales"

    if match.matchday is not None:
        return f"Fecha {match.matchday}"

    return "Fecha"


def build_matchday_metadata(
    tournament: Tournament,
    matchdays: Iterable[int],
) -> dict[int, MatchdayMetadata]:
    """Erzeugt zentrale Anzeigenamen für reguläre und finale Spieltage."""

    ordered_matchdays = list(dict.fromkeys(matchdays))

    if not ordered_matchdays:
        return {}

    stage_rows = (
        Match.objects
        .filter(
            tournament=tournament,
            matchday__in=ordered_matchdays,
        )
        .values(
            "matchday",
            "stage__code",
            "stage__name",
            "stage__sort_order",
            "stage_round",
        )
        .order_by(
            "matchday",
            "stage__sort_order",
            "stage_id",
        )
    )

    rows_by_matchday: dict[int, list[dict]] = {
        matchday: []
        for matchday in ordered_matchdays
    }

    for row in stage_rows:
        rows_by_matchday[row["matchday"]].append(row)

    result = {}

    for matchday in ordered_matchdays:
        rows = rows_by_matchday[matchday]
        final_rows = [
            row
            for row in rows
            if (
                row["stage__code"]
                and row["stage__code"]
                != TournamentStage.Code.REGULAR
            )
        ]

        if not final_rows:
            result[matchday] = MatchdayMetadata(
                number=matchday,
                label=f"Fecha {matchday}",
                is_final=False,
                stage_round=None,
                stage_names=(),
            )
            continue

        stage_rounds = {
            row["stage_round"]
            for row in final_rows
            if row["stage_round"] is not None
        }
        stage_round = (
            next(iter(stage_rounds))
            if len(stage_rounds) == 1
            else None
        )
        visible_round = stage_round or matchday
        stage_names = tuple(
            dict.fromkeys(
                row["stage__name"]
                for row in final_rows
                if row["stage__name"]
            )
        )

        result[matchday] = MatchdayMetadata(
            number=matchday,
            label=f"Finales · Fecha {visible_round}",
            is_final=True,
            stage_round=stage_round,
            stage_names=stage_names,
        )

    return result
