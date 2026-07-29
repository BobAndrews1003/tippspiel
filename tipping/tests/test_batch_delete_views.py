from datetime import timedelta
from unittest.mock import call, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from tipping.models import (
    BonusPrediction,
    Group,
    GroupMembership,
    Match,
    Prediction,
    Tournament,
)


class BatchDeleteViewTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.owner = User.objects.create_user(
            username="batch-delete-owner",
            password="owner-password-123",
        )

        self.member = User.objects.create_user(
            username="batch-delete-member",
            password="member-password-123",
        )

        self.tournament = Tournament.objects.create(
            name="Batch-Delete-Turnier",
            champion="Equipo A",
        )

        self.group = Group.objects.create(
            tournament=self.tournament,
            name="Batch-Delete-Gruppe",
            owner=self.owner,
        )

        GroupMembership.objects.create(
            user=self.owner,
            group=self.group,
            is_creator=True,
        )

        GroupMembership.objects.create(
            user=self.member,
            group=self.group,
            is_creator=False,
        )

        self.match = Match.objects.create(
            tournament=self.tournament,
            home_team="Equipo A",
            away_team="Equipo B",
            kickoff=(
                timezone.now()
                - timedelta(days=1)
            ),
            matchday=1,
        )

        # Ergebnis ohne Match-Signal setzen.
        Match.objects.filter(
            pk=self.match.pk,
        ).update(
            home_score=2,
            away_score=1,
        )

        Prediction.objects.create(
            user=self.member,
            group=self.group,
            match=self.match,
            pred_home=2,
            pred_away=1,
            points=4,
        )

        BonusPrediction.objects.create(
            user=self.member,
            group=self.group,
            bonus_type="meister",
            value="Equipo A",
        )

    def test_leave_group_uses_one_membership_rebuild(
        self,
    ):
        self.client.force_login(
            self.member
        )

        with (
            patch(
                "tipping.prediction_signals."
                "process_prediction_delete"
            ) as prediction_delete,
            patch(
                "tipping.bonus_signals."
                "rebuild_bonus_for_group_id"
            ) as bonus_rebuild,
            patch(
                "tipping.membership_signals."
                "rebuild_group_after_membership_change"
            ) as membership_rebuild,
        ):
            with self.captureOnCommitCallbacks(
                execute=True,
            ):
                response = self.client.post(
                    reverse(
                        "leave_group",
                        args=[
                            self.group.id,
                        ],
                    )
                )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertFalse(
            GroupMembership.objects.filter(
                user=self.member,
                group=self.group,
            ).exists()
        )

        self.assertFalse(
            Prediction.objects.filter(
                user=self.member,
                group=self.group,
            ).exists()
        )

        self.assertFalse(
            BonusPrediction.objects.filter(
                user=self.member,
                group=self.group,
            ).exists()
        )

        prediction_delete.assert_not_called()
        bonus_rebuild.assert_not_called()

        membership_rebuild.assert_called_once_with(
            group_id=self.group.id,
        )

    def test_delete_group_skips_all_read_model_rebuilds(
        self,
    ):
        self.client.force_login(
            self.owner
        )

        with (
            patch(
                "tipping.prediction_signals."
                "process_prediction_delete"
            ) as prediction_delete,
            patch(
                "tipping.bonus_signals."
                "rebuild_bonus_for_group_id"
            ) as bonus_rebuild,
            patch(
                "tipping.membership_signals."
                "rebuild_group_after_membership_change"
            ) as membership_rebuild,
        ):
            with self.captureOnCommitCallbacks(
                execute=True,
            ):
                response = self.client.post(
                    reverse(
                        "delete_group",
                        args=[
                            self.group.id,
                        ],
                    ),
                    {
                        "confirmation": (
                            self.group.name
                        ),
                    },
                )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertFalse(
            Group.objects.filter(
                pk=self.group.id,
            ).exists()
        )

        prediction_delete.assert_not_called()
        bonus_rebuild.assert_not_called()
        membership_rebuild.assert_not_called()

    def test_delete_account_rebuilds_each_group_once(
        self,
    ):
        User = get_user_model()

        second_owner = User.objects.create_user(
            username="batch-second-owner",
            password="second-owner-password-123",
        )

        second_group = Group.objects.create(
            tournament=self.tournament,
            name="Zweite Batch-Gruppe",
            owner=second_owner,
        )

        GroupMembership.objects.create(
            user=second_owner,
            group=second_group,
            is_creator=True,
        )

        GroupMembership.objects.create(
            user=self.member,
            group=second_group,
            is_creator=False,
        )

        member_id = self.member.id

        self.client.force_login(
            self.member
        )

        with (
            patch(
                "tipping.prediction_signals."
                "process_prediction_delete"
            ) as prediction_delete,
            patch(
                "tipping.bonus_signals."
                "rebuild_bonus_for_group_id"
            ) as bonus_rebuild,
            patch(
                "tipping.membership_signals."
                "rebuild_group_after_membership_change"
            ) as membership_signal_rebuild,
            patch(
                "tipping.views."
                "rebuild_group_after_membership_change"
            ) as consolidated_rebuild,
        ):
            with self.captureOnCommitCallbacks(
                execute=True,
            ):
                response = self.client.post(
                    reverse(
                        "delete_account"
                    ),
                    {
                        "password": (
                            "member-password-123"
                        ),
                        "confirmation": (
                            "ELIMINAR"
                        ),
                    },
                )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertFalse(
            User.objects.filter(
                pk=member_id,
            ).exists()
        )

        self.assertTrue(
            Group.objects.filter(
                pk=self.group.id,
            ).exists()
        )

        self.assertTrue(
            Group.objects.filter(
                pk=second_group.id,
            ).exists()
        )

        prediction_delete.assert_not_called()
        bonus_rebuild.assert_not_called()
        membership_signal_rebuild.assert_not_called()

        self.assertEqual(
            consolidated_rebuild.call_count,
            2,
        )

        consolidated_rebuild.assert_has_calls(
            [
                call(
                    group_id=self.group.id,
                ),
                call(
                    group_id=second_group.id,
                ),
            ],
            any_order=False,
        )

    def test_bonus_tips_rejects_put(
        self,
    ):
        self.client.force_login(
            self.member
        )

        response = self.client.put(
            reverse(
                "bonus_tips"
            )
        )

        self.assertEqual(
            response.status_code,
            405,
        )

    def test_delete_account_rejects_put(
        self,
    ):
        self.client.force_login(
            self.member
        )

        response = self.client.put(
            reverse(
                "delete_account"
            )
        )

        self.assertEqual(
            response.status_code,
            405,
        )
