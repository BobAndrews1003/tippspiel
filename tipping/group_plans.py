from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.conf import settings
from django.utils import timezone


if TYPE_CHECKING:
    from .models import Group


@dataclass(frozen=True)
class GroupPlanDefinition:
    code: str
    name: str
    price: str
    billing_note: str
    description: str
    member_limit: int | None
    included_features: tuple[str, ...]
    planned_features: tuple[str, ...] = ()
    entitlement_keys: frozenset[str] = frozenset()
    highlighted: bool = False

    @property
    def member_limit_label(self) -> str:
        if self.member_limit is None:
            return "Participantes ilimitados"

        return f"Hasta {self.member_limit} participantes"


def get_group_plan_catalog() -> tuple[GroupPlanDefinition, ...]:
    """Zentrale, in UI und Berechtigungsprüfung verwendete Tarife."""

    free_limit = settings.GROUP_PLAN_FREE_MEMBER_LIMIT
    plus_limit = settings.GROUP_PLAN_PLUS_MEMBER_LIMIT

    return (
        GroupPlanDefinition(
            code="free",
            name="Free",
            price="$0",
            billing_note="para siempre",
            description=(
                "Para grupos pequeños que quieren jugar juntos "
                "sin publicidad."
            ),
            member_limit=free_limit,
            included_features=(
                "Pronósticos, bonus y clasificaciones",
                "Grupo privado mediante código de invitación",
                f"Hasta {free_limit} participantes",
            ),
        ),
        GroupPlanDefinition(
            code="plus",
            name="Plus",
            price=(
                f"${settings.GROUP_PLAN_PLUS_PRICE_USD}"
            ),
            billing_note="por grupo y año",
            description=(
                "Para grupos grandes que quieren más control y "
                "análisis."
            ),
            member_limit=plus_limit,
            included_features=(
                "Todo lo incluido en Free",
                f"Hasta {plus_limit} participantes",
                "Coadministradores para la gestión diaria",
                "Evolución, comparaciones e informe del grupo",
            ),
            planned_features=(
                "Exportación CSV de resultados y clasificaciones",
                "Reglas de puntuación configurables",
            ),
            entitlement_keys=frozenset(
                {
                    "co_admins",
                    "advanced_stats",
                }
            ),
            highlighted=True,
        ),
        GroupPlanDefinition(
            code="club",
            name="Club",
            price=(
                f"Desde ${settings.GROUP_PLAN_CLUB_PRICE_USD}"
            ),
            billing_note="por torneo",
            description=(
                "Para clubes, empresas y comunidades con una "
                "competición propia."
            ),
            member_limit=None,
            included_features=(
                "Todo lo incluido en Plus",
                "Participantes ilimitados",
            ),
            planned_features=(
                "Imagen de marca del organizador",
                "Espacios propios para patrocinadores",
                "Soporte prioritario",
            ),
            entitlement_keys=frozenset(
                {
                    "co_admins",
                    "advanced_stats",
                }
            ),
        ),
    )


def effective_plan_code(group: Group) -> str:
    """Liefert Free, sobald ein zeitlich begrenzter Plan abgelaufen ist."""

    plan_code = group.plan
    valid_codes = {
        plan.code
        for plan in get_group_plan_catalog()
    }

    if plan_code not in valid_codes:
        return "free"

    if (
        plan_code != "free"
        and group.plan_expires_at is not None
        and group.plan_expires_at <= timezone.now()
    ):
        return "free"

    return plan_code


def get_group_plan(group: Group) -> GroupPlanDefinition:
    plan_code = effective_plan_code(group)

    return next(
        plan
        for plan in get_group_plan_catalog()
        if plan.code == plan_code
    )


def group_member_limit(group: Group) -> int | None:
    """Kein Limit, solange die gesonderte Durchsetzung aus ist."""

    if not settings.GROUP_PLAN_LIMITS_ENABLED:
        return None

    return get_group_plan(group).member_limit


def group_has_entitlement(
    group: Group,
    entitlement: str,
) -> bool:
    return entitlement in get_group_plan(group).entitlement_keys
