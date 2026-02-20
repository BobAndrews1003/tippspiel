from .models import GroupMembership

def active_group_context(request):
    if not request.user.is_authenticated:
        return {
            "group": None,
            "membership": None,
            "my_groups": [],
        }

    memberships = (
        GroupMembership.objects
        .filter(user=request.user)
        .select_related("group__tournament")
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
    }
