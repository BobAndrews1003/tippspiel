import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from urllib.parse import (
    parse_qs,
    urlsplit,
)

from django.core.management import call_command
from django.test import (
    SimpleTestCase,
    override_settings,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class MediaStorageCommandTests(SimpleTestCase):
    @override_settings(
        STORAGES={
            "default": {
                "BACKEND": (
                    "django.core.files.storage."
                    "FileSystemStorage"
                ),
            },
        },
    )
    def test_check_command_removes_its_test_file(self):
        with TemporaryDirectory() as media_root:
            with self.settings(MEDIA_ROOT=media_root):
                call_command(
                    "check_media_storage",
                    verbosity=0,
                )

            self.assertEqual(
                list(Path(media_root).rglob("*")),
                [Path(media_root) / "storage-checks"],
            )


class MediaStorageSettingsTests(SimpleTestCase):
    def settings_process(self, **media_environment):
        environment = os.environ.copy()
        environment.update(
            {
                "DEBUG": "1",
                "MEDIA_STORAGE_BACKEND": "s3",
                "MEDIA_S3_BUCKET_NAME": "puntero-media-test",
                "MEDIA_S3_ACCESS_KEY_ID": "test-access-key",
                "MEDIA_S3_SECRET_ACCESS_KEY": "test-secret-key",
                "MEDIA_S3_REGION_NAME": "auto",
                "MEDIA_S3_ENDPOINT_URL": (
                    "https://storage.example.test"
                ),
                "MEDIA_S3_ADDRESSING_STYLE": "virtual",
            }
        )
        environment.update(media_environment)
        code = (
            "import json; "
            "from django.conf import settings; "
            "from django.core.files.storage import default_storage; "
            "print(json.dumps({"
            "'storage': settings.STORAGES['default'], "
            "'origin': settings.MEDIA_STORAGE_ORIGIN, "
            "'images': settings.SECURE_CSP_REPORT_ONLY['img-src'], "
            "'url': default_storage.url('groups/example.png')"
            "}, default=str))"
        )
        return subprocess.run(
            [sys.executable, "-c", code],
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_s3_environment_builds_private_storage_and_csp_origin(self):
        process = self.settings_process()

        self.assertEqual(process.returncode, 0, process.stderr)
        payload = json.loads(process.stdout)
        storage = payload["storage"]
        options = storage["OPTIONS"]

        self.assertEqual(
            storage["BACKEND"],
            "storages.backends.s3.S3Storage",
        )
        self.assertTrue(options["querystring_auth"])
        self.assertFalse(options["file_overwrite"])
        self.assertEqual(options["location"], "media")
        self.assertEqual(
            payload["origin"],
            "https://puntero-media-test.storage.example.test",
        )
        self.assertIn(
            payload["origin"],
            payload["images"],
        )
        signed_url = urlsplit(payload["url"])
        signed_query = parse_qs(signed_url.query)
        self.assertEqual(
            signed_url.netloc,
            "puntero-media-test.storage.example.test",
        )
        self.assertEqual(
            signed_url.path,
            "/media/groups/example.png",
        )
        self.assertEqual(
            signed_query["X-Amz-Expires"],
            ["3600"],
        )
        self.assertIn("X-Amz-Signature", signed_query)

    def test_s3_environment_rejects_missing_secret(self):
        process = self.settings_process(
            MEDIA_S3_SECRET_ACCESS_KEY="",
        )

        self.assertNotEqual(process.returncode, 0)
        self.assertIn(
            "MEDIA_S3_SECRET_ACCESS_KEY",
            process.stderr,
        )
