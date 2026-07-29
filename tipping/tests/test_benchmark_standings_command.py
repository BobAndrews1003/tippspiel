from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from tipping.models import (
    Group,
    GroupStanding,
    Match,
    MatchdayScore,
    Prediction,
    Tournament,
)


class BenchmarkStandingsCommandTests(
    TestCase
):
    def test_command_rolls_back_all_test_data(
        self,
    ):
        User = get_user_model()

        counts_before = {
            "users": User.objects.count(),
            "tournaments": (
                Tournament.objects.count()
            ),
            "groups": Group.objects.count(),
            "matches": Match.objects.count(),
            "predictions": (
                Prediction.objects.count()
            ),
            "scores": (
                MatchdayScore.objects.count()
            ),
            "standings": (
                GroupStanding.objects.count()
            ),
        }

        output = StringIO()

        call_command(
            "benchmark_standings",
            users=3,
            groups=2,
            matchdays=2,
            stdout=output,
        )

        counts_after = {
            "users": User.objects.count(),
            "tournaments": (
                Tournament.objects.count()
            ),
            "groups": Group.objects.count(),
            "matches": Match.objects.count(),
            "predictions": (
                Prediction.objects.count()
            ),
            "scores": (
                MatchdayScore.objects.count()
            ),
            "standings": (
                GroupStanding.objects.count()
            ),
        }

        self.assertEqual(
            counts_after,
            counts_before,
        )

        command_output = output.getvalue()

        self.assertIn(
            "Vollständiger Rebuild",
            command_output,
        )

        self.assertIn(
            "Inkrementelle Ergebnisänderung",
            command_output,
        )

        self.assertIn(
            "Alle Testdaten wurden zurückgerollt",
            command_output,
        )
