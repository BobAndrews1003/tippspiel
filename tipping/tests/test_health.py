from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse


class HealthCheckTests(TestCase):
    def test_healthcheck_reports_healthy_dependencies(self):
        response = self.client.get(
            reverse("health_check")
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": "ok",
            },
        )
        self.assertIn(
            "no-store",
            response.headers["Cache-Control"],
        )

    @patch(
        "tipping.health.cache.get",
        return_value=None,
    )
    def test_healthcheck_hides_dependency_errors(
        self,
        mocked_cache_get,
    ):
        with self.assertLogs(
            "tipping.health",
            level="ERROR",
        ):
            response = self.client.get(
                reverse("health_check")
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {
                "status": "unavailable",
            },
        )
        mocked_cache_get.assert_called_once()

    def test_healthcheck_rejects_post(self):
        response = self.client.post(
            reverse("health_check")
        )

        self.assertEqual(response.status_code, 405)
