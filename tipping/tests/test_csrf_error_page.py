from django.http import HttpResponse
from django.test import Client, SimpleTestCase, override_settings
from django.urls import path


def protected_post(request):
    return HttpResponse("OK")


urlpatterns = [
    path(
        "__csrf-test__/",
        protected_post,
    ),
]


@override_settings(
    DEBUG=False,
    ROOT_URLCONF=__name__,
    ALLOWED_HOSTS=["testserver"],
    CSRF_FAILURE_VIEW="tipping.error_views.csrf_failure",
)
class CsrfErrorPageTests(SimpleTestCase):

    def test_missing_csrf_token_uses_custom_page(self):
        client = Client(
            enforce_csrf_checks=True
        )

        response = client.post(
            "/__csrf-test__/",
            {"test": "value"},
        )

        self.assertEqual(
            response.status_code,
            403,
        )

        self.assertContains(
            response,
            "No pudimos completar esta acción.",
            status_code=403,
        )

        self.assertContains(
            response,
            "Sesión no válida",
            status_code=403,
        )
