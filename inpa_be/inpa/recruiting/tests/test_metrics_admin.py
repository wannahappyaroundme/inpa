"""Task 7: isolated recruiting metrics and de-identified operations contracts."""
import json
from datetime import date, datetime, time, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from inpa.accounts.models import Profile, User
from inpa.billing.models import Plan, Subscription
from inpa.recruiting.jobs import produce_recruiting_reminders
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


KST = ZoneInfo("Asia/Seoul")


def _aware(day, at=time.min):
    return datetime.combine(day, at, tzinfo=KST)


def _json_text(response):
    return json.dumps(response.json(), ensure_ascii=False, default=str)


def _all_keys(value):
    if isinstance(value, dict):
        keys = set(value)
        for item in value.values():
            keys.update(_all_keys(item))
        return keys
    if isinstance(value, list):
        keys = set()
        for item in value:
            keys.update(_all_keys(item))
        return keys
    return set()


@override_settings(
    RECRUITING_ENABLED=True,
    RECRUITING_RETENTION_DAYS=180,
    RECRUITING_TOMBSTONE_DAYS=30,
)
class RecruitingMetricsAdminTests(TestCase):
    def setUp(self):
        self.owner = self._user("metrics-owner@inpa.local", "김리더")
        self.other = self._user("metrics-other@inpa.local", "박리더")
        self.admin_user = self._user("metrics-admin@inpa.local", "운영자", is_admin=True)
        self.member_activity = self._user(
            "member-activity@inpa.local",
            "활동 공유",
            manager=self.owner,
            share_level=Profile.SHARE_ACTIVITY,
        )
        self.member_full = self._user(
            "member-full@inpa.local",
            "전체 공유",
            manager=self.owner,
            share_level=Profile.SHARE_FULL,
        )
        self.member_none = self._user(
            "member-none@inpa.local",
            "공유 안 함",
            manager=self.owner,
            share_level=Profile.SHARE_NONE,
        )
        self.outsider = self._user(
            "outsider@inpa.local",
            "다른 팀원",
            manager=self.other,
            share_level=Profile.SHARE_FULL,
        )
        self.campaigns = {}
        self.client = APIClient()

    def _user(self, email, name, *, is_admin=False, manager=None, share_level="none"):
        user = User.objects.create_user(email=email, password="inpaPass123!")
        user.is_active = True
        user.save(update_fields=["is_active"])
        Profile.objects.create(
            user=user,
            name=name,
            affiliation="인파GA",
            is_admin=is_admin,
            manager=manager,
            manager_share_level=share_level,
            manager_share_opt_in=share_level != Profile.SHARE_NONE,
        )
        return user

    def _campaign(self, owner):
        campaign = self.campaigns.get(owner.pk)
        if campaign is None:
            page = RecruitingPage.objects.create(owner=owner, is_published=True)
            campaign = RecruitingCampaign.objects.create(
                page=page,
                name="개인 소개",
                channel=RecruitingCampaign.Channel.RELATIONSHIP,
            )
            self.campaigns[owner.pk] = campaign
        return campaign

    def _candidate(self, owner=None, **overrides):
        owner = owner or self.owner
        values = {
            "owner": owner,
            "campaign": self._campaign(owner),
            "name": "홍길동",
            "phone": "01012345678",
            "career_band": RecruitingCandidate.CareerBand.ONE_TO_THREE,
            "current_affiliation": "민감한 이전 소속",
            "region": "서울 강남",
            "contact_window": RecruitingCandidate.ContactWindow.ANYTIME,
            "selection_status": RecruitingCandidate.SelectionStatus.ACTIVE,
            "stage": RecruitingCandidate.Stage.NEW,
        }
        values.update(overrides)
        return RecruitingCandidate.objects.create(**values)

    def _get(self, user, path):
        self.client.force_authenticate(user=user)
        return self.client.get(path)

    def _post(self, user, path, data):
        self.client.force_authenticate(user=user)
        return self.client.post(path, data, format="json")

    def test_personal_summary_has_all_stage_zeroes_and_excludes_inactive_selections(self):
        self._candidate(stage=RecruitingCandidate.Stage.CONTACT)
        self._candidate(owner=self.other, stage=RecruitingCandidate.Stage.CONTACT)
        self._candidate(
            stage=RecruitingCandidate.Stage.CONVERSATION,
            selection_status=RecruitingCandidate.SelectionStatus.PENDING,
        )
        self._candidate(
            stage=RecruitingCandidate.Stage.PREPARING,
            selection_status=RecruitingCandidate.SelectionStatus.REPLACED,
        )

        response = self._get(self.owner, "/api/v1/recruiting/summary/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("stage_counts", response.json())
        expected = {stage: 0 for stage in RecruitingCandidate.Stage.values}
        expected[RecruitingCandidate.Stage.CONTACT] = 1
        self.assertEqual(response.json()["stage_counts"], expected)
        self.assertEqual(
            set(response.json()),
            {"stage_counts", "due_today", "overdue", "joined_this_month", "settlement_due"},
        )

    def test_personal_summary_uses_kst_day_and_month_boundaries(self):
        today = date(2026, 8, 1)
        at_kst_midnight = _aware(today)
        yesterday = self._candidate(
            stage=RecruitingCandidate.Stage.CONTACT,
            next_action=RecruitingCandidate.NextAction.CALL,
            next_action_at=at_kst_midnight - timedelta(microseconds=1),
        )
        due = self._candidate(
            stage=RecruitingCandidate.Stage.CONTACT,
            next_action=RecruitingCandidate.NextAction.CALL,
            next_action_at=at_kst_midnight,
        )
        self._candidate(
            stage=RecruitingCandidate.Stage.ENDED,
            next_action=RecruitingCandidate.NextAction.CALL,
            next_action_at=at_kst_midnight,
        )
        self._candidate(
            stage=RecruitingCandidate.Stage.CONTACT,
            next_action=RecruitingCandidate.NextAction.CALL,
            next_action_at=at_kst_midnight,
            contact_opt_out_at=at_kst_midnight,
        )
        joined_agent = self._user("joined-boundary@inpa.local", "경계 합류")
        joined = self._candidate(
            stage=RecruitingCandidate.Stage.TEAM_JOIN,
            joined_user=joined_agent,
            joined_at=at_kst_midnight,
        )
        check = SettlementCheck.objects.create(
            candidate=joined,
            week=1,
            due_on=today,
        )
        self.assertLess(yesterday.next_action_at, due.next_action_at)
        self.assertEqual(check.due_on, today)

        with patch("django.utils.timezone.localdate", return_value=today):
            response = self._get(self.owner, "/api/v1/recruiting/summary/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["overdue"], 1)
        self.assertEqual(response.json()["due_today"], 1)
        self.assertEqual(response.json()["joined_this_month"], 1)
        self.assertEqual(response.json()["settlement_due"], 1)

    def test_owner_only_settlement_list_includes_history_without_candidate_pii(self):
        joined_agent = self._user("settled-agent@inpa.local", "정착 설계사")
        mine = self._candidate(
            stage=RecruitingCandidate.Stage.TEAM_JOIN,
            joined_user=joined_agent,
            joined_at=timezone.now(),
        )
        check = SettlementCheck.objects.create(
            candidate=mine,
            week=4,
            due_on=timezone.localdate(),
            state=SettlementCheck.State.STOPPED,
            blocker=SettlementCheck.Blocker.NONE,
            next_support=SettlementCheck.NextSupport.CLOSE,
            completed_at=timezone.now(),
        )
        other_candidate = self._candidate(owner=self.other)
        SettlementCheck.objects.create(
            candidate=other_candidate,
            week=1,
            due_on=timezone.localdate(),
        )

        response = self._get(self.owner, "/api/v1/recruiting/settlements/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]["id"], check.pk)
        self.assertEqual(response.json()[0]["joined_agent_name"], "정착 설계사")
        self.assertEqual(
            set(response.json()[0]),
            {
                "id",
                "candidate_id",
                "joined_agent_name",
                "week",
                "due_on",
                "state",
                "blocker",
                "next_support",
                "completed_at",
            },
        )
        rendered = _json_text(response)
        self.assertNotIn("01012345678", rendered)
        self.assertNotIn("민감한 이전 소속", rendered)

    def test_team_summary_uses_profile_manager_and_share_level_only(self):
        today = timezone.localdate()
        self._candidate(owner=self.member_activity, stage=RecruitingCandidate.Stage.CONTACT)
        self._candidate(
            owner=self.member_activity,
            stage=RecruitingCandidate.Stage.CONVERSATION,
            selection_status=RecruitingCandidate.SelectionStatus.PENDING,
        )
        full_joined = self._candidate(
            owner=self.member_full,
            stage=RecruitingCandidate.Stage.TEAM_JOIN,
            joined_user=self.member_full,
            joined_at=timezone.now(),
        )
        SettlementCheck.objects.create(
            candidate=full_joined,
            week=1,
            due_on=today,
        )
        self._candidate(owner=self.member_none, stage=RecruitingCandidate.Stage.CONTACT)
        self._candidate(owner=self.outsider, stage=RecruitingCandidate.Stage.CONTACT)

        response = self._get(self.owner, "/api/v1/recruiting/team-summary/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("team_totals", payload)
        self.assertEqual(payload["not_shared_count"], 1)
        self.assertEqual(
            payload["team_totals"],
            {
                "active_recruiting": 1,
                "joined_this_month": 1,
                "settlement_due": 1,
            },
        )
        self.assertEqual(
            {item["user_id"] for item in payload["members"]},
            {self.member_activity.pk, self.member_full.pk},
        )
        activity = next(item for item in payload["members"] if item["user_id"] == self.member_activity.pk)
        full = next(item for item in payload["members"] if item["user_id"] == self.member_full.pk)
        self.assertEqual(activity["active_recruiting"], 1)
        self.assertEqual(full["joined_this_month"], 1)
        self.assertEqual(full["settlement_due"], 1)
        expected_member_keys = {
            "user_id",
            "display_name",
            "active_recruiting",
            "joined_this_month",
            "settlement_due",
        }
        self.assertTrue(all(set(item) == expected_member_keys for item in payload["members"]))
        forbidden = {
            "candidate",
            "candidate_id",
            "name",
            "phone",
            "affiliation",
            "region",
            "campaign",
            "campaign_id",
        }
        self.assertFalse(_all_keys(payload) & forbidden)
        rendered = _json_text(response)
        self.assertNotIn("홍길동", rendered)
        self.assertNotIn("01012345678", rendered)

    def test_team_summary_gate_off_is_open_and_gate_on_reuses_402_contract(self):
        with override_settings(MANAGER_PLAN_GATE_ENABLED=False):
            open_response = self._get(self.owner, "/api/v1/recruiting/team-summary/")
        with override_settings(MANAGER_PLAN_GATE_ENABLED=True):
            gated_response = self._get(self.owner, "/api/v1/recruiting/team-summary/")

        self.assertEqual(open_response.status_code, 200)
        self.assertEqual(gated_response.status_code, 402)
        self.assertEqual(
            gated_response.json(),
            {
                "detail": "Plus를 시작하면 팀 관리 기능을 계속 사용할 수 있어요.",
                "code": "manager_plan_required",
                "plan": "manager",
            },
        )

        plus = Plan.objects.create(
            code="plus",
            display_name="Plus",
            price_krw=19900,
            can_use_team=True,
        )
        Subscription.objects.create(user=self.owner, plan=plus, status="active")
        with override_settings(MANAGER_PLAN_GATE_ENABLED=True):
            entitled = self._get(self.owner, "/api/v1/recruiting/team-summary/")
        self.assertEqual(entitled.status_code, 200)

    @override_settings(RECRUITING_ENABLED=False)
    def test_admin_routes_ignore_rollout_flag_and_non_admin_gets_403(self):
        routes = (
            "/api/v1/admin/recruiting/summary/",
            "/api/v1/admin/recruiting/candidates/",
            "/api/v1/admin/recruiting/templates/",
            "/api/v1/admin/recruiting/promotions/",
            "/api/v1/admin/recruiting/audit/",
        )
        for route in routes:
            with self.subTest(route=route):
                self.assertEqual(self._get(self.admin_user, route).status_code, 200)
                self.assertEqual(self._get(self.owner, route).status_code, 403)

    def test_admin_summary_is_kst_month_scoped_and_uses_active_candidate_selection(self):
        today = date(2026, 8, 1)
        active = self._candidate()
        inactive = self._candidate(selection_status=RecruitingCandidate.SelectionStatus.REPLACED)
        event_specs = (
            (RecruitingEvent.EventType.PAGE_VIEW, None, 2),
            (RecruitingEvent.EventType.APPLICATION_SUBMITTED, active, 1),
            (RecruitingEvent.EventType.APPLICATION_SUBMITTED, inactive, 1),
            (RecruitingEvent.EventType.TEAM_JOIN, active, 1),
            (RecruitingEvent.EventType.SETTLEMENT_COMPLETED, active, 1),
            (RecruitingEvent.EventType.MANAGER_PROMOTED, None, 1),
        )
        for event_type, candidate, count in event_specs:
            for offset in range(count):
                event = RecruitingEvent.objects.create(
                    owner=self.owner,
                    candidate=candidate,
                    event_type=event_type,
                )
                RecruitingEvent.objects.filter(pk=event.pk).update(
                    created_at=_aware(today) + timedelta(seconds=offset)
                )
        prior = RecruitingEvent.objects.create(
            owner=self.owner,
            event_type=RecruitingEvent.EventType.PAGE_VIEW,
        )
        RecruitingEvent.objects.filter(pk=prior.pk).update(
            created_at=_aware(today) - timedelta(microseconds=1)
        )

        with patch("django.utils.timezone.localdate", return_value=today):
            response = self._get(self.admin_user, "/api/v1/admin/recruiting/summary/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "visits": 2,
                "applications": 1,
                "joins": 1,
                "settlements_completed": 1,
                "manager_promotions": 1,
                "recruiting_enabled": True,
                "retention_days": 180,
                "tombstone_days": 30,
            },
        )

    def test_admin_candidate_list_is_exactly_masked_and_contains_no_raw_pii(self):
        candidate = self._candidate(
            name="홍길동",
            phone="010-1234-5678",
            current_affiliation="극비 소속",
            region="극비 지역",
            retention_expires_at=timezone.now() + timedelta(days=30),
        )

        response = self._get(self.admin_user, "/api/v1/admin/recruiting/candidates/")

        self.assertEqual(response.status_code, 200)
        item = next(row for row in response.json()["results"] if row["id"] == candidate.pk)
        self.assertEqual(
            set(item),
            {
                "id",
                "name_masked",
                "phone_masked",
                "stage",
                "created_at",
                "retention_expires_at",
                "contact_opted_out",
            },
        )
        self.assertEqual(item["name_masked"], "홍*동")
        self.assertEqual(item["phone_masked"], "***-****-5678")
        rendered = _json_text(response)
        for raw in ("홍길동", "01012345678", "극비 소속", "극비 지역", self.owner.email):
            self.assertNotIn(raw, rendered)

    def test_admin_phone_mask_reveals_suffix_only_for_valid_length(self):
        from inpa.recruiting.admin_views import _mask_phone

        self.assertEqual(_mask_phone(""), "-")
        self.assertEqual(_mask_phone("   "), "-")
        self.assertEqual(_mask_phone("02-1234-5678"), "***-****-5678")
        self.assertEqual(_mask_phone("010-1234-5678"), "***-****-5678")
        for invalid in ("123", "010123456789", "전화번호 없음"):
            with self.subTest(invalid=invalid):
                self.assertEqual(_mask_phone(invalid), "***-****-****")

    def test_admin_purge_locks_scrubs_and_is_idempotent_without_reminders(self):
        today = timezone.localdate()
        candidate = self._candidate(
            stage=RecruitingCandidate.Stage.CONTACT,
            next_action=RecruitingCandidate.NextAction.CALL,
            next_action_at=_aware(today, time(9, 0)),
        )
        RecruitingConsentLog.objects.create(
            candidate=candidate,
            doc_version="recruiting-contact-v1",
            ip_address="127.0.0.1",
        )
        real_lock = RecruitingCandidate.objects.select_for_update
        with patch(
            "inpa.recruiting.models.RecruitingCandidate.objects.select_for_update",
            wraps=real_lock,
        ) as select_for_update:
            first = self._post(
                self.admin_user,
                f"/api/v1/admin/recruiting/candidates/{candidate.pk}/purge/",
                {"reason": "user_request"},
            )
        second = self._post(
            self.admin_user,
            f"/api/v1/admin/recruiting/candidates/{candidate.pk}/purge/",
            {"reason": "user_request"},
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        select_for_update.assert_called_once_with()
        candidate.refresh_from_db()
        self.assertEqual(candidate.name, "정리 요청")
        self.assertEqual(candidate.phone, "")
        self.assertEqual(candidate.current_affiliation, "")
        self.assertEqual(candidate.region, "")
        self.assertEqual(candidate.next_action, "")
        self.assertIsNone(candidate.next_action_at)
        self.assertIsNotNone(candidate.contact_opt_out_at)
        self.assertFalse(candidate.consents.exists())
        self.assertEqual(
            RecruitingActivity.objects.filter(
                candidate_ref=candidate.audit_ref,
                event_type=RecruitingActivity.EventType.CANDIDATE_PURGED,
            ).count(),
            1,
        )
        self.assertEqual(produce_recruiting_reminders(today), 0)
        audit = RecruitingActivity.objects.get(
            candidate_ref=candidate.audit_ref,
            event_type=RecruitingActivity.EventType.CANDIDATE_PURGED,
        )
        self.assertEqual(audit.actor_id, self.admin_user.pk)
        rendered = f"{audit} {first.content!r} {second.content!r}"
        self.assertNotIn("홍길동", rendered)
        self.assertNotIn("01012345678", rendered)

    def test_admin_purge_refuses_current_or_historical_join_and_strictly_validates_body(self):
        joined = self._candidate(
            stage=RecruitingCandidate.Stage.TEAM_JOIN,
            joined_user=self.member_full,
            joined_at=timezone.now(),
        )
        historical = self._candidate(joined_at=timezone.now() - timedelta(days=90))
        normal = self._candidate()

        for candidate in (joined, historical):
            with self.subTest(candidate=candidate.pk):
                response = self._post(
                    self.admin_user,
                    f"/api/v1/admin/recruiting/candidates/{candidate.pk}/purge/",
                    {"reason": "retention"},
                )
                self.assertEqual(response.status_code, 409)
                candidate.refresh_from_db()
                self.assertEqual(candidate.name, "홍길동")
                self.assertIsNotNone(candidate.joined_at)

        bad_reason = self._post(
            self.admin_user,
            f"/api/v1/admin/recruiting/candidates/{normal.pk}/purge/",
            {"reason": "please delete 홍길동"},
        )
        extra_text = self._post(
            self.admin_user,
            f"/api/v1/admin/recruiting/candidates/{normal.pk}/purge/",
            {"reason": "admin_correction", "note": "01012345678"},
        )
        self.assertEqual(bad_reason.status_code, 400)
        self.assertEqual(extra_text.status_code, 400)
        normal.refresh_from_db()
        self.assertEqual(normal.name, "홍길동")
        self.assertFalse(
            RecruitingActivity.objects.filter(
                candidate_ref=normal.audit_ref,
                event_type=RecruitingActivity.EventType.CANDIDATE_PURGED,
            ).exists()
        )

    def test_admin_templates_have_immutable_code_kind_validation_and_no_delete(self):
        created = self._post(
            self.admin_user,
            "/api/v1/admin/recruiting/templates/",
            {
                "code": "welcome-note",
                "kind": RecruitingCopyTemplate.Kind.SHARE,
                "title": "첫 안내",
                "body": "지원 흐름을 확인해보세요.",
                "is_active": True,
                "sort_order": 10,
            },
        )
        self.assertEqual(created.status_code, 201)
        template_id = created.json()["id"]

        self.client.force_authenticate(user=self.admin_user)
        detail = self.client.get(f"/api/v1/admin/recruiting/templates/{template_id}/")
        updated = self.client.patch(
            f"/api/v1/admin/recruiting/templates/{template_id}/",
            {"title": "바뀐 안내", "is_active": False},
            format="json",
        )
        immutable = self.client.patch(
            f"/api/v1/admin/recruiting/templates/{template_id}/",
            {"code": "changed", "kind": RecruitingCopyTemplate.Kind.FAQ},
            format="json",
        )
        deleted = self.client.delete(f"/api/v1/admin/recruiting/templates/{template_id}/")
        duplicate = self._post(
            self.admin_user,
            "/api/v1/admin/recruiting/templates/",
            {
                "code": "welcome-note",
                "kind": RecruitingCopyTemplate.Kind.SHARE,
                "title": "중복",
                "body": "중복",
                "is_active": True,
                "sort_order": 0,
            },
        )

        self.assertEqual(detail.status_code, 200)
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["title"], "바뀐 안내")
        self.assertEqual(immutable.status_code, 400)
        self.assertEqual(deleted.status_code, 405)
        self.assertEqual(duplicate.status_code, 400)

    def test_admin_promotions_separate_effective_and_original_plan_without_mutation(self):
        free = Plan.objects.create(code="free", display_name="Free", price_krw=0)
        plus = Plan.objects.create(
            code="plus",
            display_name="Plus",
            price_krw=19900,
            can_use_team=True,
        )
        profile = self.owner.profile
        profile.manager_promoted_at = timezone.now()
        profile.save(update_fields=["manager_promoted_at"])
        Subscription.objects.create(
            user=self.owner,
            plan=plus,
            status="expired",
            expires_at=timezone.now() - timedelta(days=1),
        )
        before = Subscription.objects.get(user=self.owner).plan_id

        response = self._get(self.admin_user, "/api/v1/admin/recruiting/promotions/")

        self.assertEqual(response.status_code, 200)
        item = next(row for row in response.json() if row["user_id"] == self.owner.pk)
        self.assertEqual(
            set(item),
            {
                "user_id",
                "display_name",
                "manager_promoted_at",
                "current_team_count",
                "is_manager",
                "effective_plan_code",
                "subscription_plan_code",
            },
        )
        self.assertEqual(item["current_team_count"], 3)
        self.assertTrue(item["is_manager"])
        self.assertEqual(item["effective_plan_code"], free.code)
        self.assertEqual(item["subscription_plan_code"], plus.code)
        self.assertEqual(Subscription.objects.get(user=self.owner).plan_id, before)

    def test_admin_audit_has_only_pseudonymous_fields(self):
        candidate = self._candidate(name="감사 민감 이름", phone="01077778888")
        activity = RecruitingActivity.objects.create(
            candidate=candidate,
            candidate_ref=candidate.audit_ref,
            actor=self.owner,
            event_type=RecruitingActivity.EventType.STAGE_CHANGED,
            from_stage=RecruitingCandidate.Stage.NEW,
            to_stage=RecruitingCandidate.Stage.CONTACT,
        )
        candidate.delete()
        activity.refresh_from_db()
        self.assertIsNone(activity.candidate_id)

        response = self._get(self.admin_user, "/api/v1/admin/recruiting/audit/")

        self.assertEqual(response.status_code, 200)
        item = next(row for row in response.json()["results"] if row["candidate_ref"] == str(activity.candidate_ref))
        self.assertEqual(
            set(item),
            {"candidate_ref", "event_type", "from_stage", "to_stage", "actor_id", "created_at"},
        )
        rendered = _json_text(response)
        for raw in ("감사 민감 이름", "01077778888", self.owner.email, "metadata"):
            self.assertNotIn(raw, rendered)

    def test_recruiting_event_objects_create_cannot_bypass_metadata_validation(self):
        for unsafe in (
            {"name": "홍길동"},
            {"phone": "01012345678"},
            {"source": "홍길동"},
            {"week": "13"},
        ):
            with self.subTest(unsafe=unsafe), self.assertRaises(ValidationError):
                RecruitingEvent.objects.create(
                    owner=self.owner,
                    event_type=RecruitingEvent.EventType.PAGE_VIEW,
                    metadata=unsafe,
                )

        allowed = RecruitingEvent.objects.create(
            owner=self.owner,
            event_type=RecruitingEvent.EventType.SETTLEMENT_COMPLETED,
            metadata={"week": 13, "state": SettlementCheck.State.ACTIVE},
        )
        self.assertEqual(allowed.metadata["week"], 13)

    def test_django_admin_candidate_and_audit_models_are_pii_safe_read_only(self):
        candidate_admin = admin.site._registry[RecruitingCandidate]
        self.assertEqual(
            candidate_admin.list_display,
            ("id", "stage", "campaign", "created_at", "retention_expires_at"),
        )
        self.assertFalse(candidate_admin.search_fields)
        self.assertNotIn("name", candidate_admin.list_filter)
        self.assertNotIn("phone", candidate_admin.list_filter)
        self.assertFalse(candidate_admin.has_add_permission(None))
        self.assertFalse(candidate_admin.has_delete_permission(None))

        for model in (RecruitingConsentLog, RecruitingActivity, RecruitingEvent):
            with self.subTest(model=model.__name__):
                model_admin = admin.site._registry[model]
                self.assertFalse(model_admin.has_add_permission(None))
                self.assertFalse(model_admin.has_change_permission(None))
                self.assertFalse(model_admin.has_delete_permission(None))

    def test_django_admin_detail_fields_use_explicit_safe_allowlists(self):
        request = RequestFactory().get("/admin/recruiting/")
        request.user = self.admin_user
        candidate = self._candidate()
        consent = RecruitingConsentLog.objects.create(
            candidate=candidate,
            doc_version="recruiting-contact-v1",
            ip_address="127.0.0.1",
        )
        activity = RecruitingActivity.objects.create(
            candidate=candidate,
            candidate_ref=candidate.audit_ref,
            actor=self.owner,
            event_type=RecruitingActivity.EventType.STAGE_CHANGED,
        )
        event = RecruitingEvent.objects.create(
            owner=self.owner,
            campaign=candidate.campaign,
            candidate=candidate,
            event_type=RecruitingEvent.EventType.APPLICATION_SUBMITTED,
        )
        settlement = SettlementCheck.objects.create(
            candidate=candidate,
            week=1,
            due_on=timezone.localdate(),
        )
        expected_fields = {
            RecruitingCandidate: (
                "id",
                "campaign",
                "career_band",
                "contact_window",
                "selection_status",
                "stage",
                "next_action",
                "next_action_at",
                "last_contacted_at",
                "joined_at",
                "ended_at",
                "retention_expires_at",
                "contact_opt_out_at",
                "created_at",
                "updated_at",
            ),
            RecruitingConsentLog: (
                "id",
                "scope",
                "doc_version",
                "agreed_at",
                "revoked_at",
            ),
            RecruitingActivity: (
                "id",
                "candidate_ref",
                "event_type",
                "from_stage",
                "to_stage",
                "actor_id",
                "created_at",
            ),
            RecruitingEvent: ("id", "event_type", "channel", "created_at"),
            SettlementCheck: (
                "id",
                "week",
                "due_on",
                "state",
                "blocker",
                "next_support",
                "completed_at",
                "created_at",
                "updated_at",
            ),
        }
        objects = {
            RecruitingCandidate: candidate,
            RecruitingConsentLog: consent,
            RecruitingActivity: activity,
            RecruitingEvent: event,
            SettlementCheck: settlement,
        }

        for model, fields in expected_fields.items():
            with self.subTest(model=model.__name__):
                model_admin = admin.site._registry[model]
                self.assertEqual(tuple(model_admin.get_fields(request, objects[model])), fields)
                self.assertEqual(tuple(model_admin.fields), fields)
                self.assertEqual(tuple(model_admin.readonly_fields), fields)

        candidate_fields = set(
            admin.site._registry[RecruitingCandidate].get_fields(request, candidate)
        )
        self.assertFalse(
            candidate_fields
            & {
                "name",
                "phone",
                "current_affiliation",
                "region",
                "submission_key",
                "audit_ref",
                "identity_ref",
                "manage_token",
                "owner",
                "joined_user",
            }
        )
        self.assertFalse(
            set(admin.site._registry[RecruitingConsentLog].get_fields(request, consent))
            & {"candidate", "ip_address"}
        )
        self.assertFalse(
            set(admin.site._registry[RecruitingActivity].get_fields(request, activity))
            & {"candidate", "actor"}
        )
        self.assertFalse(
            set(admin.site._registry[RecruitingEvent].get_fields(request, event))
            & {"candidate", "owner"}
        )
