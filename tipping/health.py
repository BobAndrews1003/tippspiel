import logging

from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET


logger = logging.getLogger(__name__)

HEALTH_CACHE_KEY = "healthcheck:probe"
HEALTH_CACHE_VALUE = "ok"


@require_GET
@never_cache
def health_check(request):
    """
    Bestätigt, dass Webprozess, Datenbank und gemeinsamer Cache
    erreichbar sind. Interne Fehlerdetails werden nicht ausgegeben.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()

        cache.set(
            HEALTH_CACHE_KEY,
            HEALTH_CACHE_VALUE,
            timeout=10,
        )

        if (
            cache.get(HEALTH_CACHE_KEY)
            != HEALTH_CACHE_VALUE
        ):
            raise RuntimeError(
                "Der Cache-Healthcheck ist fehlgeschlagen."
            )

    except Exception:
        logger.exception(
            "Healthcheck für Datenbank oder Cache fehlgeschlagen."
        )

        return JsonResponse(
            {
                "status": "unavailable",
            },
            status=503,
        )

    return JsonResponse(
        {
            "status": "ok",
        }
    )
