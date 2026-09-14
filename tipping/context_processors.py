from django.conf import settings

from .group_branding import get_visible_group_branding
from .group_plans import group_has_entitlement
from .models import GroupMembership


def legal_pages_context(request):
    """Steuert Links auf die noch nicht freigegebenen Rechtstexte."""

    return {
        "legal_pages_enabled": (
            settings.LEGAL_PAGES_ENABLED
        ),
    }


def group_plans_context(request):
    """Blendet die unverbindliche Tarifvorschau zentral ein oder aus."""

    return {
        "group_plans_enabled": (
            settings.GROUP_PLANS_ENABLED
        ),
    }


def active_group_context(request):
    if not request.user.is_authenticated:
        return {
            "group": None,
            "membership": None,
            "my_groups": [],
            "group_branding": None,
        }

    memberships = (
        GroupMembership.objects
        .filter(user=request.user)
        .select_related(
            "group__tournament",
            "group__branding",
        )
        .order_by("group__name")
    )

    my_groups = [m.group for m in memberships]

    # Active group aus Session
    active_group_id = request.session.get("active_group_id")

    membership = None
    if active_group_id:
        membership = memberships.filter(group_id=active_group_id).first()

    # Fallback: erste Gruppe setzen
    if membership is None and memberships.exists():
        membership = memberships.first()
        request.session["active_group_id"] = membership.group_id

    group = membership.group if membership else None

    return {
        "group": group,
        "membership": membership,
        "my_groups": my_groups,
        "group_branding": get_visible_group_branding(
            group
        ),
        "advanced_group_stats_available": bool(
            group
            and group_has_entitlement(
                group,
                "advanced_stats",
            )
        ),
    }
