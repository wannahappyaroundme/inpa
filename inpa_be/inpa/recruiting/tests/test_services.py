import uuid
from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from inpa.accounts.models import Profile, User
from inpa.recruiting.models import (
    RecruitingActivity,
    RecruitingCampaign,
    RecruitingCandidate,
    RecruitingPage,
)
from inpa.recruiting.services import (
    ALLOWED_STAGE_TRANSITIONS,
    RecruitingApplicationLimitReached,
    apply_leader_choice,
    create_candidate_submission,
    stop_candidate_contact,
    transition_candidate,
)


@override_settings(RECRUITING_ENABLED=True)
class RecruitingSubmissionServiceTests(TestCase):
    def setUp(self):
        self.owner = self.make_owner("leader-one@inpa.local", "김리더", "인파 GA")
        self.other_owner = self.make_owner("leader-two@inpa.local", "이리더", "인파금융")
        self.campaign = self.make_campaign(self.owner)
        self.other_campaign = self.make_campaign(self.other_owner)

    def make_owner(self, email, name, affiliation):
        user = User.objects.create_user(email=email, password="inpaPass123!")
        Profile.objects.create(user=user, name=name, affiliation=affiliation)
        return user

    def make_campaign(self, owner):
        page = RecruitingPage.objects.create(owner=owner, is_published=True)
        return RecruitingCampaign.objects.create(
            page=page,
            name="개인 소개",
            channel=RecruitingCampaign.Channel.RELATIONSHIP,
        )

    def payload(self, **overrides):
        values = {
            "name": "홍길동",
            "phone": "010-1234-5678",
            "career_band": RecruitingCandidate.CareerBand.FIVE_TO_TEN,
            "current_affiliation": "기존 GA",
            "region": "서울",
            "contact_window": RecruitingCandidate.ContactWindow.EVENING,
            "submission_key": uuid.uuid4(),
            "agreed": True,
        }
        values.update(overrides)
        return values

    def submit(self, campaign=None, **overrides):
        return create_candidate_submission(
            campaign=campaign or self.campaign,
            data=self.payload(**overrides),
            ip_address="127.0.0.1",
        )

    def test_same_campaign_and_submission_key_is_idempotent(self):
        submission_key = uuid.uuid4()
        first = self.submit(submission_key=submission_key)
        second = self.submit(submission_key=submission_key)

        self.assertEqual(first.candidate.pk, second.candidate.pk)
        self.assertEqual(first.candidate.manage_token, second.candidate.manage_token)
        self.assertEqual(RecruitingCandidate.objects.count(), 1)

    def test_same_owner_phone_with_new_submission_key_is_separate(self):
        first = self.submit()
        second = self.submit()

        self.assertNotEqual(first.candidate.pk, second.candidate.pk)
        self.assertNotEqual(first.candidate.manage_token, second.candidate.manage_token)
        self.assertEqual(first.candidate.owner, second.candidate.owner)

    def test_same_phone_under_another_owner_creates_separate_candidate(self):
        first = self.submit()
        second = self.submit(campaign=self.other_campaign)

        self.assertNotEqual(first.candidate.pk, second.candidate.pk)
        self.assertNotEqual(first.candidate.identity_ref, second.candidate.identity_ref)
        self.assertEqual(second.candidate.owner, self.other_owner)

    def test_phone_match_alone_cannot_change_or_stop_an_existing_application(self):
        first = self.submit().candidate
        second = self.submit(campaign=self.other_campaign).candidate

        stop_candidate_contact(candidate=second)
        first.refresh_from_db()

        self.assertEqual(first.selection_status, RecruitingCandidate.SelectionStatus.ACTIVE)
        self.assertIsNone(first.contact_opt_out_at)
        self.assertEqual(first.name, "홍길동")

    def test_valid_prior_manage_token_offers_keep_or_switch_choice(self):
        old = self.submit().candidate
        result = self.submit(
            campaign=self.other_campaign,
            prior_manage_token=str(old.manage_token),
        )

        self.assertTrue(result.choice_required)
        self.assertIsNotNone(result.choice_token)
        self.assertEqual(result.candidate.selection_status, RecruitingCandidate.SelectionStatus.PENDING)
        self.assertEqual(result.candidate.identity_ref, old.identity_ref)

    def test_keep_choice_closes_only_the_new_pending_application(self):
        old = self.submit().candidate
        pending = self.submit(
            campaign=self.other_campaign,
            prior_manage_token=str(old.manage_token),
        )

        selected = apply_leader_choice(token=pending.choice_token, choice="keep_current")
        old.refresh_from_db()
        pending.candidate.refresh_from_db()

        self.assertEqual(selected.pk, old.pk)
        self.assertEqual(old.selection_status, RecruitingCandidate.SelectionStatus.ACTIVE)
        self.assertEqual(pending.candidate.selection_status, RecruitingCandidate.SelectionStatus.DECLINED)
        self.assertEqual(pending.candidate.stage, RecruitingCandidate.Stage.ENDED)
        self.assertIsNotNone(pending.candidate.retention_expires_at)

    def test_switch_choice_closes_old_and_activates_new_without_revealing_new_leader(self):
        old = self.submit().candidate
        pending = self.submit(
            campaign=self.other_campaign,
            prior_manage_token=str(old.manage_token),
        )

        selected = apply_leader_choice(token=pending.choice_token, choice="switch_to_new")
        old.refresh_from_db()
        pending.candidate.refresh_from_db()

        self.assertEqual(selected.pk, pending.candidate.pk)
        self.assertEqual(old.selection_status, RecruitingCandidate.SelectionStatus.REPLACED)
        self.assertEqual(old.stage, RecruitingCandidate.Stage.ENDED)
        self.assertEqual(old.name, "담당 변경")
        self.assertEqual(old.phone, "")
        self.assertEqual(pending.candidate.selection_status, RecruitingCandidate.SelectionStatus.ACTIVE)
        self.assertEqual(pending.candidate.next_action, RecruitingCandidate.NextAction.CALL)
        self.assertLess(
            pending.candidate.next_action_at,
            timezone.now() + timedelta(hours=24, minutes=1),
        )

    def test_replaced_or_opted_out_candidate_cannot_be_reactivated_by_previous_owner(self):
        candidate = self.submit().candidate
        candidate.selection_status = RecruitingCandidate.SelectionStatus.REPLACED
        candidate.stage = RecruitingCandidate.Stage.ENDED
        candidate.save(update_fields=["selection_status", "stage", "updated_at"])

        with self.assertRaises(ValidationError):
            transition_candidate(
                candidate=candidate,
                actor=self.owner,
                to_stage=RecruitingCandidate.Stage.RECONTACT,
            )

    def test_stage_change_writes_structured_activity(self):
        candidate = self.submit().candidate

        updated = transition_candidate(
            candidate=candidate,
            actor=self.owner,
            to_stage=RecruitingCandidate.Stage.CONTACT,
            next_action=RecruitingCandidate.NextAction.MESSAGE,
            next_action_at=timezone.now() + timedelta(days=1),
        )

        activity = RecruitingActivity.objects.get(candidate=updated)
        self.assertEqual(activity.candidate_ref, candidate.audit_ref)
        self.assertEqual(activity.actor, self.owner)
        self.assertEqual(activity.event_type, RecruitingActivity.EventType.STAGE_CHANGED)
        self.assertEqual(activity.from_stage, RecruitingCandidate.Stage.NEW)
        self.assertEqual(activity.to_stage, RecruitingCandidate.Stage.CONTACT)

    def test_recontact_clears_previous_end_and_retention_timestamps(self):
        candidate = self.submit().candidate
        candidate.stage = RecruitingCandidate.Stage.ENDED
        candidate.ended_at = timezone.now()
        candidate.retention_expires_at = timezone.now() + timedelta(days=30)
        candidate.save(
            update_fields=["stage", "ended_at", "retention_expires_at", "updated_at"]
        )

        updated = transition_candidate(
            candidate=candidate,
            actor=self.owner,
            to_stage=RecruitingCandidate.Stage.RECONTACT,
        )

        self.assertIsNone(updated.ended_at)
        self.assertIsNone(updated.retention_expires_at)

    def test_allowed_stage_transitions_match_the_approved_table(self):
        approved = {
            RecruitingCandidate.Stage.NEW: {
                RecruitingCandidate.Stage.CONTACT,
                RecruitingCandidate.Stage.RECONTACT,
                RecruitingCandidate.Stage.ENDED,
            },
            RecruitingCandidate.Stage.CONTACT: {
                RecruitingCandidate.Stage.CONVERSATION,
                RecruitingCandidate.Stage.RECONTACT,
                RecruitingCandidate.Stage.ENDED,
            },
            RecruitingCandidate.Stage.CONVERSATION: {
                RecruitingCandidate.Stage.PREPARING,
                RecruitingCandidate.Stage.RECONTACT,
                RecruitingCandidate.Stage.ENDED,
            },
            RecruitingCandidate.Stage.PREPARING: {
                RecruitingCandidate.Stage.CONVERSATION,
                RecruitingCandidate.Stage.RECONTACT,
                RecruitingCandidate.Stage.ENDED,
            },
            RecruitingCandidate.Stage.RECONTACT: {
                RecruitingCandidate.Stage.CONTACT,
                RecruitingCandidate.Stage.ENDED,
            },
            RecruitingCandidate.Stage.TEAM_JOIN: {RecruitingCandidate.Stage.ENDED},
            RecruitingCandidate.Stage.ENDED: {RecruitingCandidate.Stage.RECONTACT},
        }
        self.assertEqual(ALLOWED_STAGE_TRANSITIONS, approved)

        for source, allowed_targets in approved.items():
            for target in RecruitingCandidate.Stage.values:
                candidate = RecruitingCandidate.objects.create(
                    owner=self.owner,
                    campaign=self.campaign,
                    name="단계 확인",
                    phone="01012345678",
                    career_band=RecruitingCandidate.CareerBand.ONE_TO_THREE,
                    region="서울",
                    contact_window=RecruitingCandidate.ContactWindow.ANYTIME,
                    stage=source,
                )
                with self.subTest(source=source, target=target):
                    if target in allowed_targets:
                        updated = transition_candidate(
                            candidate=candidate,
                            actor=self.owner,
                            to_stage=target,
                        )
                        self.assertEqual(updated.stage, target)
                    else:
                        with self.assertRaises(ValidationError):
                            transition_candidate(
                                candidate=candidate,
                                actor=self.owner,
                                to_stage=target,
                            )

    def _prefill_daily_candidates(self, count):
        RecruitingCandidate.objects.bulk_create(
            [
                RecruitingCandidate(
                    owner=self.owner,
                    campaign=self.campaign,
                    name=f"지원자 {index}",
                    phone=f"010{index:08d}",
                    career_band=RecruitingCandidate.CareerBand.ONE_TO_THREE,
                    region="서울",
                    contact_window=RecruitingCandidate.ContactWindow.ANYTIME,
                    submission_key=uuid.uuid4(),
                )
                for index in range(count)
            ]
        )

    def test_idempotent_retry_does_not_consume_daily_limit(self):
        self._prefill_daily_candidates(29)
        submission_key = uuid.uuid4()

        first = self.submit(submission_key=submission_key)
        retry = self.submit(submission_key=submission_key)

        self.assertEqual(first.candidate.pk, retry.candidate.pk)
        self.assertEqual(
            RecruitingCandidate.objects.filter(campaign=self.campaign).count(),
            30,
        )

    def test_thirty_first_new_submission_is_rejected_without_row(self):
        self._prefill_daily_candidates(30)
        rejected_key = uuid.uuid4()

        with self.assertRaises(RecruitingApplicationLimitReached):
            self.submit(submission_key=rejected_key)

        self.assertFalse(
            RecruitingCandidate.objects.filter(
                campaign=self.campaign,
                submission_key=rejected_key,
            ).exists()
        )
        self.assertEqual(
            RecruitingCandidate.objects.filter(campaign=self.campaign).count(),
            30,
        )

    def test_new_submission_locks_campaign_before_daily_limit_check(self):
        original = RecruitingCampaign.objects.select_for_update
        with patch(
            "inpa.recruiting.services.RecruitingCampaign.objects.select_for_update",
            wraps=original,
        ) as select_for_update:
            self.submit()

        select_for_update.assert_called_once_with()
