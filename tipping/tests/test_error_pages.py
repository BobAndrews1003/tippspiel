from django.core.exceptions import BadRequest, PermissionDenied
from django.test import Client, SimpleTestCase, override_settings
from django.urls import path


def test_bad_request(request):
    raise BadRequest("Test bad request")


def test_permission_denied(request):
    raise PermissionDenied("Test forbidden")


def test_server_error(request):
    raise RuntimeError("Test server error")


urlpatterns = [
    path("__error-test__/400/", test_bad_request),
    path("__error-test__/403/", test_permission_denied),
    path("__error-test__/500/", test_server_error),
]


@override_settings(
    DEBUG=False,
    ROOT_URLCONF=__name__,
    ALLOWED_HOSTS=["testserver"],
)
class ErrorPageTests(SimpleTestCase):

    def setUp(self):
        self.client = Client(
            raise_request_exception=False
        )

    def test_400_page(self):
        response = self.client.get(
            "/__error-test__/400/"
        )

        self.assertEqual(
            response.status_code,
            400,
        )

        self.assertContains(
            response,
            "No pudimos procesar esta solicitud.",
            status_code=400,
        )

    def test_403_page(self):
        response = self.client.get(
            "/__error-test__/403/"
        )

        self.assertEqual(
            response.status_code,
            403,
        )

        self.assertContains(
            response,
            "No tienes acceso a esta página.",
            status_code=403,
        )

    def test_404_page(self):
        response = self.client.get(
            "/__error-test__/no-existe/"
        )

        self.assertEqual(
            response.status_code,
            404,
        )

        self.assertContains(
            response,
            "No encontramos esa página.",
            status_code=404,
        )

    def test_500_page(self):
        response = self.client.get(
            "/__error-test__/500/"
        )

        self.assertEqual(
            response.status_code,
            500,
        )

        self.assertContains(
            response,
            "Algo salió mal.",
            status_code=500,
        )
