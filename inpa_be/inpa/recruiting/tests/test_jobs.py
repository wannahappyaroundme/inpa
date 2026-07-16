"""Recruiting notification, daily reminder, and retention regressions."""
from datetime import datetime, time, timedelta
from unittest.mock import Mock, patch

from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from inpa.accounts.models import Profile, User
from inpa.accounts.team import link_agent_to_manager
from inpa.analysis.models import SeedMarker
from inpa.billing.models import Plan, Subscription
from inpa.notifications.jobs import run_daily_jobs
from inpa.notifications.models import Notification, NotifType
from inpa.recruiting.jobs import (
    cleanup_expired_recruiting_candidates,
    create_recruiting_notification_once,
    produce_recruiting_reminders,
)
from inpa.recruiting.models import (
    RecruitingActivity,
    RecruitingCampaign,
    RecruitingCandidate,
    RecruitingConsentLog,
    RecruitingEvent,
    RecruitingPage,
    SettlementCheck,
)
from inpa.recruiting.services import (
    apply_leader_choice,
    create_candidate_submission,
    stop_candidate_contact,
)


@override_settings(
    RECRUITING_ENABLED=True,
    RECRUITING_RETENTION_DAYS=180,
    RECRUITING_TOMBSTONE_DAYS=30,
)
class RecruitingJobTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.owner = self._user("recruit-jobs-owner@inpa.local", "김리더")
        self.other_owner = self._user("recruit-jobs-other@inpa.local", "박리더")
        self.page = RecruitingPage.objects.create(owner=self.owner, is_published=True)
        self.campaign = RecruitingCampaign.objects.create(
            page=self.page,
            name="개인 소개",
            channel=RecruitingCampaign.Channel.RELATIONSHIP,
        )

    def _user(self, email, name):
        user = User.objects.create_user(email=email, password="inpaPass123!")
        user.is_active = True
        user.save(update_fields=["is_active"])
        Profile.objects.create(
            user=user,
            name=name,
            affiliation="인파GA",
            email_verified_at=timezone.now(),
        )
        return user

    def _candidate(self, **overrides):
        values = {
            "owner": self.owner,
            "campaign": self.campaign,
            "name": "민감한 지원자 이름",
            "phone": "01012345678",
            "career_band": RecruitingCandidate.CareerBand.FIVE_TO_TEN,
            "current_affiliation": "민감한 이전 소속",
            "region": "서울",
            "contact_window": RecruitingCandidate.ContactWindow.EVENING,
            "selection_status": RecruitingCandidate.SelectionStatus.ACTIVE,
            "stage": RecruitingCandidate.Stage.CONTACT,
        }
        values.update(overrides)
        return RecruitingCandidate.objects.create(**values)

    def _payload(self, **overrides):
        import uuid

        values = {
            "name": "민감한 지원자 이름",
            "phone": "010-1234-5678",
            "career_band": RecruitingCandidate.CareerBand.FIVE_TO_TEN,
            "current_affiliation": "민감한 이전 소속",
            "region": "서울",
            "contact_window": RecruitingCandidate.ContactWindow.EVENING,
            "submission_key": uuid.uuid4(),
            "agreed": True,
        }
        values.update(overrides)
        return values

    def _kst(self, day, at=time(9, 0)):
        return timezone.make_aware(datetime.combine(day, at))

    def test_new_application_notifies_owner_without_candidate_pii(self):
        with self.captureOnCommitCallbacks(execute=True):
            result = create_candidate_submission(
                campaign=self.campaign,
                data=self._payload(),
                ip_address="127.0.0.1",
            )

        notice = Notification.objects.get(
            owner=self.owner,
            notif_type=NotifType.RECRUITING_APPLICATION,
        )
        rendered = f"{notice.title} {notice.body} {notice.dedupe_key}"
        self.assertEqual(notice.title, "새 영입 지원이 도착했어요")
        self.assertEqual(
            notice.body,
            "가능한 시간대를 확인하고 첫 연락을 준비해보세요.",
        )
        self.assertEqual(
            notice.dedupe_key,
            f"recruiting:application:{result.candidate.audit_ref}",
        )
        for pii in ("민감한 지원자 이름", "01012345678", "민감한 이전 소속", "서울"):
            self.assertNotIn(pii, rendered)

    def test_application_notification_failure_does_not_rollback_submission_or_log_pii(self):
        with patch(
            "inpa.recruiting.jobs.create_recruiting_notification_once",
            side_effect=RuntimeError("민감한 지원자 이름 01012345678"),
        ), self.assertLogs("inpa.recruiting.services", level="WARNING") as captured:
            with self.captureOnCommitCallbacks(execute=True):
                result = create_candidate_submission(
                    campaign=self.campaign,
                    data=self._payload(),
                )

        self.assertTrue(RecruitingCandidate.objects.filter(pk=result.candidate.pk).exists())
        self.assertFalse(Notification.objects.exists())
        rendered = " ".join(captured.output)
        self.assertIn("application_notification", rendered)
        self.assertIn("RuntimeError", rendered)
        self.assertNotIn("민감한 지원자 이름", rendered)
        self.assertNotIn("01012345678", rendered)

    def test_pending_leader_choice_does_not_notify_either_owner_until_selected(self):
        with self.captureOnCommitCallbacks(execute=True):
            old = create_candidate_submission(
                campaign=self.campaign,
                data=self._payload(),
            ).candidate
        Notification.objects.all().delete()
        other_page = RecruitingPage.objects.create(
            owner=self.other_owner,
            is_published=True,
        )
        other_campaign = RecruitingCampaign.objects.create(
            page=other_page,
            name="개인 소개",
            channel=RecruitingCampaign.Channel.RELATIONSHIP,
        )

        with self.captureOnCommitCallbacks(execute=True):
            pending = create_candidate_submission(
                campaign=other_campaign,
                data=self._payload(prior_manage_token=str(old.manage_token)),
            )
        self.assertEqual(Notification.objects.count(), 0)

        with self.captureOnCommitCallbacks(execute=True):
            apply_leader_choice(token=pending.choice_token, choice="switch_to_new")
        self.assertEqual(
            Notification.objects.filter(
                owner=self.other_owner,
                notif_type=NotifType.RECRUITING_APPLICATION,
            ).count(),
            1,
        )
        self.assertFalse(Notification.objects.filter(owner=self.owner).exists())

    def test_keep_current_does_not_notify_existing_owner_again(self):
        with self.captureOnCommitCallbacks(execute=True):
            old = create_candidate_submission(
                campaign=self.campaign,
                data=self._payload(),
            ).candidate
        Notification.objects.all().delete()
        other_page = RecruitingPage.objects.create(owner=self.other_owner, is_published=True)
        other_campaign = RecruitingCampaign.objects.create(
            page=other_page,
            name="개인 소개",
            channel=RecruitingCampaign.Channel.RELATIONSHIP,
        )
        pending = create_candidate_submission(
            campaign=other_campaign,
            data=self._payload(prior_manage_token=str(old.manage_token)),
        )

        with self.captureOnCommitCallbacks(execute=True):
            apply_leader_choice(token=pending.choice_token, choice="keep_current")

        self.assertFalse(Notification.objects.exists())

    def test_due_follow_up_notification_is_idempotent_per_owner_and_day(self):
        self._candidate(next_action_at=self._kst(self.today, time(23, 59)))
        self._candidate(phone="01099998888", next_action_at=self._kst(self.today, time(12, 0)))

        self.assertEqual(produce_recruiting_reminders(self.today), 1)
        self.assertEqual(produce_recruiting_reminders(self.today), 0)
        notice = Notification.objects.get(notif_type=NotifType.RECRUITING_FOLLOWUP)
        self.assertEqual(
            notice.dedupe_key,
            f"recruiting:followup:{self.owner.pk}:{self.today.isoformat()}",
        )

    def test_settlement_due_notification_is_idempotent_per_check(self):
        candidate = self._candidate(
            stage=RecruitingCandidate.Stage.TEAM_JOIN,
            joined_user=self._user("joined-reminder@inpa.local", "합류 설계사"),
            joined_at=timezone.now(),
            name="팀 합류 설계사",
            phone="",
            current_affiliation="",
            region="",
        )
        check = SettlementCheck.objects.create(
            candidate=candidate,
            week=1,
            due_on=self.today,
        )

        self.assertEqual(produce_recruiting_reminders(self.today), 1)
        self.assertEqual(produce_recruiting_reminders(self.today), 0)
        notice = Notification.objects.get(notif_type=NotifType.RECRUITING_SETTLEMENT)
        self.assertEqual(notice.dedupe_key, f"recruiting:settlement:{check.pk}")

    def test_reopened_active_check_is_due_but_still_only_notified_once(self):
        candidate = self._candidate(
            stage=RecruitingCandidate.Stage.TEAM_JOIN,
            joined_user=self._user("joined-reopen@inpa.local", "합류 설계사"),
            joined_at=timezone.now(),
            name="팀 합류 설계사",
            phone="",
            current_affiliation="",
            region="",
        )
        check = SettlementCheck.objects.create(
            candidate=candidate,
            week=4,
            due_on=self.today,
            state=SettlementCheck.State.ACTIVE,
            completed_at=None,
        )

        self.assertEqual(produce_recruiting_reminders(self.today), 1)
        self.assertEqual(produce_recruiting_reminders(self.today), 0)
        self.assertEqual(
            Notification.objects.filter(dedupe_key=f"recruiting:settlement:{check.pk}").count(),
            1,
        )

    def test_opted_out_candidate_is_never_reminded(self):
        candidate = self._candidate(next_action_at=self._kst(self.today))
        stop_candidate_contact(candidate=candidate)

        self.assertEqual(produce_recruiting_reminders(self.today), 0)

    def test_ended_and_team_join_candidates_are_never_followed_up(self):
        self._candidate(
            stage=RecruitingCandidate.Stage.ENDED,
            next_action_at=self._kst(self.today),
        )
        self._candidate(
            phone="01022223333",
            stage=RecruitingCandidate.Stage.TEAM_JOIN,
            next_action_at=self._kst(self.today),
        )

        self.assertEqual(produce_recruiting_reminders(self.today), 0)

    def test_expired_ended_unjoined_candidate_is_deleted(self):
        candidate = self._candidate(
            stage=RecruitingCandidate.Stage.ENDED,
            ended_at=timezone.now() - timedelta(days=181),
            retention_expires_at=timezone.now() - timedelta(days=1),
        )
        audit_ref = candidate.audit_ref
        RecruitingEvent.objects.create(
            owner=self.owner,
            campaign=self.campaign,
            candidate=candidate,
            event_type=RecruitingEvent.EventType.APPLICATION_SUBMITTED,
            channel=self.campaign.channel,
        )
        RecruitingConsentLog.objects.create(
            candidate=candidate,
            doc_version="recruiting-contact-v1",
        )

        self.assertEqual(cleanup_expired_recruiting_candidates(), 1)
        self.assertFalse(RecruitingCandidate.objects.filter(pk=candidate.pk).exists())
        activity = RecruitingActivity.objects.get(
            candidate_ref=audit_ref,
            event_type=RecruitingActivity.EventType.CANDIDATE_PURGED,
        )
        self.assertIsNone(activity.candidate_id)
        self.assertIsNone(RecruitingEvent.objects.get().candidate_id)
        self.assertFalse(RecruitingConsentLog.objects.exists())

    def test_recent_system_activity_extends_retention_and_prevents_delete(self):
        candidate = self._candidate(
            stage=RecruitingCandidate.Stage.ENDED,
            ended_at=timezone.now() - timedelta(days=181),
            retention_expires_at=timezone.now() - timedelta(days=1),
        )
        recent = RecruitingActivity.objects.create(
            candidate=candidate,
            candidate_ref=candidate.audit_ref,
            event_type=RecruitingActivity.EventType.STAGE_CHANGED,
            from_stage=RecruitingCandidate.Stage.CONTACT,
            to_stage=RecruitingCandidate.Stage.ENDED,
        )

        self.assertEqual(cleanup_expired_recruiting_candidates(), 0)
        candidate.refresh_from_db()
        self.assertGreaterEqual(
            candidate.retention_expires_at,
            recent.created_at + timedelta(days=180) - timedelta(seconds=1),
        )

    def test_recent_last_contact_extends_retention_and_prevents_delete(self):
        recent = timezone.now() - timedelta(days=2)
        candidate = self._candidate(
            stage=RecruitingCandidate.Stage.ENDED,
            ended_at=timezone.now() - timedelta(days=181),
            last_contacted_at=recent,
            retention_expires_at=timezone.now() - timedelta(days=1),
        )

        self.assertEqual(cleanup_expired_recruiting_candidates(), 0)
        candidate.refresh_from_db()
        self.assertGreaterEqual(
            candidate.retention_expires_at,
            recent + timedelta(days=180) - timedelta(seconds=1),
        )

    def test_active_candidate_is_not_deleted_only_because_it_is_old(self):
        candidate = self._candidate(retention_expires_at=timezone.now() - timedelta(days=1))
        RecruitingCandidate.objects.filter(pk=candidate.pk).update(
            created_at=timezone.now() - timedelta(days=400)
        )

        self.assertEqual(cleanup_expired_recruiting_candidates(), 0)
        self.assertTrue(RecruitingCandidate.objects.filter(pk=candidate.pk).exists())

    def test_joined_candidate_keeps_non_pii_history_after_retention(self):
        joined = self._user("retained-joined@inpa.local", "합류 설계사")
        candidate = self._candidate(
            stage=RecruitingCandidate.Stage.TEAM_JOIN,
            joined_user=joined,
            joined_at=timezone.now() - timedelta(days=200),
            retention_expires_at=timezone.now() - timedelta(days=1),
            name="팀 합류 설계사",
            phone="",
            current_affiliation="",
            region="",
        )

        self.assertEqual(cleanup_expired_recruiting_candidates(), 0)
        candidate.refresh_from_db()
        self.assertEqual(candidate.joined_user, joined)
        self.assertEqual(candidate.phone, "")

    def test_expired_opt_out_requires_complete_system_tombstone(self):
        candidate = self._candidate()
        stop_candidate_contact(candidate=candidate)
        RecruitingCandidate.objects.filter(pk=candidate.pk).update(
            retention_expires_at=timezone.now() - timedelta(seconds=1)
        )
        self.assertEqual(cleanup_expired_recruiting_candidates(), 1)

        malformed = self._candidate(
            phone="01077776666",
            name="정리 요청",
            current_affiliation="",
            region="",
            stage=RecruitingCandidate.Stage.ENDED,
            ended_at=timezone.now() - timedelta(days=31),
            contact_opt_out_at=timezone.now() - timedelta(days=31),
            retention_expires_at=timezone.now() - timedelta(seconds=1),
        )
        self.assertEqual(cleanup_expired_recruiting_candidates(), 0)
        self.assertTrue(RecruitingCandidate.objects.filter(pk=malformed.pk).exists())

    def test_feature_off_skips_reminders_but_runner_still_cleans_retention(self):
        candidate = self._candidate(
            stage=RecruitingCandidate.Stage.ENDED,
            ended_at=timezone.now() - timedelta(days=181),
            retention_expires_at=timezone.now() - timedelta(days=1),
        )
        with override_settings(RECRUITING_ENABLED=False):
            result = run_daily_jobs(today=self.today)

        self.assertEqual(result["counts"]["recruiting_reminders"], 0)
        self.assertEqual(result["counts"]["recruiting_retention_deleted"], 1)
        self.assertFalse(RecruitingCandidate.objects.filter(pk=candidate.pk).exists())

    def test_recruiting_job_failure_does_not_stop_other_daily_producers(self):
        sentinel = []

        def other_producer(today):
            sentinel.append(today)
            return 2

        def broken_recruiting(today):
            raise RuntimeError("민감한 지원자 이름 01012345678")

        with patch(
            "inpa.notifications.jobs.PRODUCERS",
            (("recruiting_reminders", broken_recruiting), ("other", other_producer)),
        ), patch("inpa.notifications.jobs.cleanup_expired_leads", return_value=0), patch(
            "inpa.notifications.jobs.cleanup_expired_share_snapshots", return_value=0
        ), patch(
            "inpa.notifications.jobs.cleanup_expired_recruiting_candidates", return_value=0
        ), self.assertLogs("inpa.notifications.jobs", level="WARNING") as captured:
            result = run_daily_jobs(today=self.today)

        self.assertEqual(sentinel, [self.today])
        self.assertEqual(result["counts"]["other"], 2)
        self.assertEqual(result["errors"]["recruiting_reminders"], "RuntimeError")
        rendered = " ".join(captured.output) + repr(result)
        self.assertNotIn("민감한 지원자 이름", rendered)
        self.assertNotIn("01012345678", rendered)
        self.assertFalse(
            RecruitingEvent.objects.filter(
                event_type=RecruitingEvent.EventType.MANAGER_PROMOTED
            ).exists()
        )
        self.assertFalse(SeedMarker.objects.filter(key="daily_jobs").exists())

    def test_manager_promotion_notification_is_on_commit_and_idempotent(self):
        agent = self._user("manager-notice-agent@inpa.local", "후임 설계사")
        with self.captureOnCommitCallbacks(execute=True):
            first = link_agent_to_manager(agent=agent, manager=self.owner)
        with self.captureOnCommitCallbacks(execute=True):
            second = link_agent_to_manager(agent=agent, manager=self.owner)

        self.assertTrue(first.promoted_now)
        self.assertFalse(second.promoted_now)
        notice = Notification.objects.get(notif_type=NotifType.MANAGER_PROMOTED)
        self.assertEqual(notice.title, "관리자 기능이 열렸어요")
        self.assertEqual(notice.dedupe_key, f"manager-promoted:{self.owner.pk}")
        self.assertNotIn("후임 설계사", f"{notice.title} {notice.body}")

    def test_legacy_manager_link_creates_no_manager_promotion_notification(self):
        manager_plan = Plan.objects.create(
            code="manager",
            display_name="Manager",
            price_krw=0,
        )
        Subscription.objects.create(
            user=self.owner,
            plan=manager_plan,
            status="active",
        )
        agent = self._user("legacy-manager-agent@inpa.local", "후임 설계사")

        with self.captureOnCommitCallbacks(execute=True):
            result = link_agent_to_manager(agent=agent, manager=self.owner)

        self.assertFalse(result.promoted_now)
        self.assertFalse(
            Notification.objects.filter(notif_type=NotifType.MANAGER_PROMOTED).exists()
        )

    def test_manager_notification_failure_does_not_rollback_team_link_or_log_pii(self):
        agent = self._user("manager-failure-agent@inpa.local", "민감한 후임 이름")
        with patch(
            "inpa.recruiting.jobs.create_recruiting_notification_once",
            side_effect=RuntimeError("민감한 후임 이름 01055556666"),
        ), self.assertLogs("inpa.accounts.team", level="WARNING") as captured:
            with self.captureOnCommitCallbacks(execute=True):
                result = link_agent_to_manager(agent=agent, manager=self.owner)

        agent.profile.refresh_from_db()
        self.owner.profile.refresh_from_db()
        self.assertTrue(result.promoted_now)
        self.assertEqual(agent.profile.manager_id, self.owner.pk)
        self.assertIsNotNone(self.owner.profile.manager_promoted_at)
        rendered = " ".join(captured.output)
        self.assertIn("manager_promotion_notification", rendered)
        self.assertIn("RuntimeError", rendered)
        self.assertNotIn("민감한 후임 이름", rendered)
        self.assertNotIn("01055556666", rendered)

    def test_dedupe_integrity_race_converges_to_zero(self):
        before_race = Mock()
        before_race.exists.return_value = False
        after_race = Mock()
        after_race.exists.return_value = True
        with patch.object(
            Notification.objects,
            "filter",
            side_effect=[before_race, after_race],
        ), patch.object(
            Notification.objects,
            "create",
            side_effect=IntegrityError,
        ):
            created = create_recruiting_notification_once(
                owner_id=self.owner.pk,
                notif_type=NotifType.RECRUITING_FOLLOWUP,
                title="다음 연락 시간이 되었어요",
                body="영입 현황에서 오늘 이어갈 대화를 확인해보세요.",
                dedupe_key="recruiting:followup:race",
            )

        self.assertEqual(created, 0)

    def test_unread_counts_include_recruiting_bucket_without_exposing_dedupe_key(self):
        client = APIClient()
        client.force_authenticate(self.owner)
        Notification.objects.create(
            owner=self.owner,
            notif_type=NotifType.RECRUITING_APPLICATION,
            title="새 영입 지원이 도착했어요",
            body="가능한 시간대를 확인하고 첫 연락을 준비해보세요.",
            dedupe_key="recruiting:application:test-audit-ref",
        )
        Notification.objects.create(
            owner=self.owner,
            notif_type=NotifType.BIRTHDAY_SOON,
            title="고객 생일 안내",
            body="준비해보세요.",
        )

        response = client.get("/api/v1/notifications/unread-count/")
        listing = client.get("/api/v1/notifications/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["unread_count"], 2)
        self.assertEqual(response.json()["recruiting"], 1)
        self.assertEqual(response.json()["customers"], 1)
        self.assertNotIn("dedupe_key", repr(listing.json()))

    def test_multiple_existing_notifications_can_keep_null_dedupe_keys(self):
        Notification.objects.create(
            owner=self.owner,
            notif_type=NotifType.BOARD_COMMENT,
            title="알림 1",
            body="본문",
        )
        Notification.objects.create(
            owner=self.owner,
            notif_type=NotifType.BOARD_COMMENT,
            title="알림 2",
            body="본문",
        )

        self.assertEqual(Notification.objects.filter(dedupe_key__isnull=True).count(), 2)
