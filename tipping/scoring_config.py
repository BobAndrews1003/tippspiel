from __future__ import annotations

from dataclasses import dataclass


MAX_SCORING_POINTS = 20


@dataclass(frozen=True)
class ScoringValues:
    exact_points: int
    goal_difference_points: int
    tendency_points: int
    incorrect_points: int


STANDARD_SCORING_VALUES = ScoringValues(
    exact_points=4,
    goal_difference_points=3,
    tendency_points=2,
    incorrect_points=0,
)


SCORING_PRESETS = {
    "puntero": (
        "Puntero",
        STANDARD_SCORING_VALUES,
    ),
    "classic": (
        "Clásico",
        ScoringValues(
            exact_points=3,
            goal_difference_points=2,
            tendency_points=1,
            incorrect_points=0,
        ),
    ),
    "exact_focus": (
        "El exacto cuenta más",
        ScoringValues(
            exact_points=5,
            goal_difference_points=3,
            tendency_points=1,
            incorrect_points=0,
        ),
    ),
}


def identify_scoring_preset(
    values: ScoringValues,
) -> str:
    for code, (_label, preset_values) in SCORING_PRESETS.items():
        if values == preset_values:
            return code

    return "custom"
