from django import template

from tipping.models import UserProfile


register = template.Library()




@register.filter
def user_initial(user):
    if not user:
        return "?"

    value = (
        user.get_username()
        or getattr(user, "email", "")
        or "?"
    )

    return value.strip()[:1].upper()