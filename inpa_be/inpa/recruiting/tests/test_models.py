import importlib
import uuid

from django.apps import apps as django_apps
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.fields.related import RelatedField
from django.test import TestCase
from rest_framework.test import APIClient

from inpa.accounts.models import User
from inpa.recruiting.models import (
    RecruitingActivity,
    RecruitingCampaign,
    RecruitingCandidate,
    RecruitingConsentLog,
    RecruitingCopyTemplate,
    RecruitingEvent,
    RecruitingPage,
    SettlementCheck,
)


class RecruitingModelIsolationTests(TestCase):
    def test_candidate_has_no_customer_relation(self):
        related_models = {
            field.related_model._meta.label_lower
            for field in RecruitingCandidate._meta.get_fields()
            if isinstance(field, RelatedField) and field.related_model
        }
        self.assertNotIn("customers.customer", related_models)


class RecruitingModelTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="recruiting-owner@inpa.local",
            password="inpaPass123!",
        )
        self.page = RecruitingPage.objects.create(owner=self.owner)
        self.campaign = RecruitingCampaign.objects.create(
            page=self.page,
            name="개인 소개",
            channel=RecruitingCampaign.Channel.RELATIONSHIP,
        )

    def create_candidate(self, **overrides):
        values = {
            "owner": self.owner,
            "campaign": self.campaign,
            "name": "지원자",
            "phone": "010-1234-5678",
            "career_band": RecruitingCandidate.CareerBand.ONE_TO_THREE,
            "region": "서울",
            "contact_window": RecruitingCandidate.ContactWindow.ANYTIME,
        }
        values.update(overrides)
        return RecruitingCandidate.objects.create(**values)

    def test_relationship_campaign_is_unique_per_page_while_active(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                RecruitingCampaign.objects.create(
                    page=self.page,
                    name="두 번째 개인 소개",
                    channel=RecruitingCampaign.Channel.RELATIONSHIP,
                )

        RecruitingCampaign.objects.create(
            page=self.page,
            name="중단된 개인 소개",
            channel=RecruitingCampaign.Channel.RELATIONSHIP,
            is_active=False,
        )
        RecruitingCampaign.objects.create(
            page=self.page,
            name="인스타그램",
            channel=RecruitingCampaign.Channel.INSTAGRAM,
        )

    def test_submission_key_is_unique_within_campaign(self):
        submission_key = uuid.uuid4()
        self.create_candidate(submission_key=submission_key)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_candidate(submission_key=submission_key)

        other_campaign = RecruitingCampaign.objects.create(
            page=self.page,
            name="Threads",
            channel=RecruitingCampaign.Channel.THREADS,
        )
        retry_for_another_campaign = self.create_candidate(
            campaign=other_campaign,
            submission_key=submission_key,
        )
        self.assertEqual(retry_for_another_campaign.submission_key, submission_key)

    def test_same_phone_with_new_submission_stays_separate(self):
        first = self.create_candidate()
        second = self.create_candidate()

        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(first.phone, "01012345678")
        self.assertEqual(second.phone, first.phone)
        self.assertNotEqual(first.identity_ref, second.identity_ref)
        self.assertNotEqual(first.manage_token, second.manage_token)

    def test_same_phone_can_belong_to_different_owners_without_cross_scope(self):
        other_owner = User.objects.create_user(
            email="other-recruiting-owner@inpa.local",
            password="inpaPass123!",
        )
        other_page = RecruitingPage.objects.create(owner=other_owner)
        other_campaign = RecruitingCampaign.objects.create(
            page=other_page,
            name="개인 소개",
            channel=RecruitingCampaign.Channel.RELATIONSHIP,
        )
        mine = self.create_candidate()
        theirs = self.create_candidate(owner=other_owner, campaign=other_campaign)

        owner_candidates = RecruitingCandidate.objects.filter(owner=self.owner)
        self.assertEqual(list(owner_candidates), [mine])
        self.assertNotIn(theirs, owner_candidates)
        self.assertNotEqual(mine.identity_ref, theirs.identity_ref)

    def test_account_with_recruiting_data_can_use_existing_withdrawal_flow(self):
        candidate = self.create_candidate()
        audit_ref = candidate.audit_ref
        activity = RecruitingActivity.objects.create(
            candidate=candidate,
            candidate_ref=audit_ref,
            actor=self.owner,
            event_type=RecruitingActivity.EventType.STAGE_CHANGED,
            from_stage=RecruitingCandidate.Stage.NEW,
            to_stage=RecruitingCandidate.Stage.CONTACT,
        )
        client = APIClient()
        client.force_authenticate(user=self.owner)

        response = client.post(
            "/api/v1/auth/withdraw/",
            {"password": "inpaPass123!"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(pk=self.owner.pk).exists())
        activity.refresh_from_db()
        self.assertIsNone(activity.candidate)
        self.assertIsNone(activity.actor)
        self.assertEqual(activity.candidate_ref, audit_ref)

    def test_settlement_week_is_unique_per_candidate(self):
        candidate = self.create_candidate()
        SettlementCheck.objects.create(candidate=candidate, week=1, due_on="2026-07-23")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SettlementCheck.objects.create(
                    candidate=candidate,
                    week=1,
                    due_on="2026-07-30",
                )

    def test_recruiting_event_metadata_allows_only_stable_keys_and_values(self):
        allowed = RecruitingEvent(
            owner=self.owner,
            campaign=self.campaign,
            event_type=RecruitingEvent.EventType.SETTLEMENT_COMPLETED,
            channel=RecruitingCampaign.Channel.RELATIONSHIP,
            metadata={
                "source": RecruitingCampaign.Channel.RELATIONSHIP,
                "week": 13,
                "state": SettlementCheck.State.ACTIVE,
                "previous_stage": RecruitingCandidate.Stage.PREPARING,
            },
        )
        allowed.full_clean()

        for unsafe_metadata in (
            {"name": "홍길동"},
            {"phone": "01012345678"},
            {"source": "홍길동"},
            {"week": "13주"},
            {"source": [RecruitingCampaign.Channel.RELATIONSHIP]},
        ):
            with self.subTest(metadata=unsafe_metadata):
                event = RecruitingEvent(
                    owner=self.owner,
                    event_type=RecruitingEvent.EventType.PAGE_VIEW,
                    metadata=unsafe_metadata,
                )
                with self.assertRaises(ValidationError):
                    event.full_clean()

    def test_pii_models_have_safe_string_representations(self):
        candidate = self.create_candidate(name="홍길동", phone="010-9999-8888")
        consent = RecruitingConsentLog.objects.create(
            candidate=candidate,
            doc_version="2026-07-16-v1",
            ip_address="127.0.0.1",
        )
        activity = RecruitingActivity.objects.create(
            candidate=candidate,
            candidate_ref=candidate.audit_ref,
            actor=self.owner,
            event_type=RecruitingActivity.EventType.STAGE_CHANGED,
        )
        settlement = SettlementCheck.objects.create(
            candidate=candidate,
            week=4,
            due_on="2026-08-13",
        )
        event = RecruitingEvent.objects.create(
            owner=self.owner,
            candidate=candidate,
            event_type=RecruitingEvent.EventType.APPLICATION_SUBMITTED,
        )

        self.assertEqual(str(candidate), f"candidate:{candidate.pk}")
        for instance in (consent, activity, settlement, event):
            rendered = str(instance)
            self.assertNotIn("홍길동", rendered)
            self.assertNotIn("01099998888", rendered)
            self.assertNotIn("127.0.0.1", rendered)

    def test_candidate_deletion_keeps_pseudonymous_activity_audit(self):
        candidate = self.create_candidate()
        audit_ref = candidate.audit_ref
        activity = RecruitingActivity.objects.create(
            candidate=candidate,
            candidate_ref=audit_ref,
            actor=self.owner,
            event_type=RecruitingActivity.EventType.STAGE_CHANGED,
            from_stage=RecruitingCandidate.Stage.NEW,
            to_stage=RecruitingCandidate.Stage.CONTACT,
        )

        candidate.delete()

        activity.refresh_from_db()
        self.assertIsNone(activity.candidate)
        self.assertEqual(activity.candidate_ref, audit_ref)
        self.assertEqual(activity.event_type, RecruitingActivity.EventType.STAGE_CHANGED)
        self.assertEqual(activity.from_stage, RecruitingCandidate.Stage.NEW)
        self.assertEqual(activity.to_stage, RecruitingCandidate.Stage.CONTACT)

    def test_locked_enum_values_match_the_approved_funnel(self):
        self.assertEqual(
            set(RecruitingCandidate.Stage.values),
            {"new", "contact", "conversation", "preparing", "team_join", "recontact", "ended"},
        )
        self.assertEqual(
            set(RecruitingActivity.EventType.values),
            {
                "stage_changed",
                "contact_stopped",
                "leader_changed",
                "team_joined",
                "settlement_completed",
                "settlement_reopened",
                "candidate_purged",
            },
        )
        self.assertEqual(
            set(SettlementCheck.State.values),
            {"active", "support_needed", "stopped"},
        )


class RecruitingCopyTemplateSeedTests(TestCase):
    def test_default_copy_templates_are_seeded(self):
        self.assertEqual(
            set(RecruitingCopyTemplate.objects.values_list("code", flat=True)),
            {
                "headline-long-growth",
                "support-first-week",
                "support-field",
                "support-growth",
                "faq-contract",
                "faq-data",
                "share-known",
            },
        )

    def test_seed_rerun_preserves_operator_edits(self):
        template = RecruitingCopyTemplate.objects.get(code="headline-long-growth")
        template.body = "운영자가 다듬은 문구"
        template.save(update_fields=["body"])
        migration = importlib.import_module(
            "inpa.recruiting.migrations.0002_seed_copy_templates"
        )

        migration.seed_copy_templates(django_apps, None)

        template.refresh_from_db()
        self.assertEqual(template.body, "운영자가 다듬은 문구")
