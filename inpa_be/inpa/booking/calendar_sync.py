"""구글 캘린더 정리 — 취소·거절된 미팅의 외부 일정 삭제와 재시도.

배경: 인파에서 예약을 취소·거절해도 구글 캘린더 일정이 그대로 남으면, 고객이 이미 취소된
시간에 찾아오는 실사고가 난다. 앱 DB가 최종 진실이므로 상태 전환은 항상 성공시키되,
외부 삭제는 별도로 완결시킨다.

규약(spec 2026-07-21 §9.2):
  - 외부 삭제 실패가 사용자의 취소 요청을 실패시키지 않는다(격리).
  - 실패는 조용히 사라지지 않는다 → Meeting.calendar_cleanup_pending=True 로 남기고
    일일 작업(notifications.jobs.run_daily_jobs)이 다시 시도한다.
  - google_event_id 는 삭제가 확인된 뒤에만 비운다(미확인 상태에서 지우면 추적 불가).
  - 로그에는 예외 타입과 미팅 id만 남긴다(고객명·이메일·이벤트 본문 금지).
"""
import logging

from inpa.core.internal_accounts import is_showcase_user

from .models import Meeting

logger = logging.getLogger(__name__)

# 한 번의 일일 작업에서 재시도할 최대 건수(장애 누적 시에도 배치 시간이 폭주하지 않게).
CLEANUP_BATCH_LIMIT = 200


def _linked_profile(owner):
    """구글 캘린더 삭제를 실제로 호출할 수 있는 프로필. 연동이 없으면 None."""
    from inpa.accounts.google import google_calendar_enabled
    if not google_calendar_enabled():
        return None
    profile = getattr(owner, 'profile', None)
    if profile is None or not profile.google_calendar_refresh_token:
        return None
    return profile


def _set_pending(meeting, pending):
    Meeting.objects.filter(pk=meeting.pk).update(calendar_cleanup_pending=pending)
    meeting.calendar_cleanup_pending = pending


def _mark_cleaned(meeting):
    Meeting.objects.filter(pk=meeting.pk).update(
        google_event_id=None, calendar_cleanup_pending=False)
    meeting.google_event_id = None
    meeting.calendar_cleanup_pending = False


def remove_meeting_event(meeting):
    """미팅에 연결된 구글 캘린더 일정을 지운다 → True=정리 완료(지울 것이 없는 경우 포함).

    False 를 반환하면 그 미팅은 calendar_cleanup_pending 으로 표시돼 일일 작업이 다시 시도한다.
    이 함수는 예외를 밖으로 던지지 않는다(호출부의 취소·거절 응답을 절대 실패시키지 않기 위해).
    """
    if not meeting.google_event_id:
        if meeting.calendar_cleanup_pending:
            _set_pending(meeting, False)
        return True
    # 내부 쇼케이스 계정은 애초에 외부 캘린더에 쓰지 않는다(등록 경로와 동일 기준).
    # 지울 외부 일정이 없으므로 재시도 표시만 내려 매일 다시 집히지 않게 한다(이벤트 id는 기록으로 보존).
    if is_showcase_user(meeting.owner):
        if meeting.calendar_cleanup_pending:
            _set_pending(meeting, False)
        return True
    try:
        profile = _linked_profile(meeting.owner)
        if profile is None:
            # 연동이 끊긴 상태 → 지금은 지울 수 없다. 표시만 남겨두면 다시 연결됐을 때 정리된다.
            _set_pending(meeting, True)
            return False
        from inpa.accounts.google_calendar import delete_meeting_event
        delete_meeting_event(profile, meeting.google_event_id)
    except Exception as exc:  # noqa: BLE001 — 외부 API 실패 격리(취소 자체는 이미 성공)
        logger.warning(
            'calendar cleanup failed meeting=%s exception=%s',
            meeting.pk, type(exc).__name__)
        try:
            _set_pending(meeting, True)
        except Exception as mark_exc:  # noqa: BLE001 — 표시 실패도 요청을 깨뜨리지 않는다
            logger.warning(
                'calendar cleanup mark failed meeting=%s exception=%s',
                meeting.pk, type(mark_exc).__name__)
        return False
    _mark_cleaned(meeting)
    return True


def retry_pending_calendar_cleanup(limit=CLEANUP_BATCH_LIMIT):
    """일일 작업 — 미처리로 남은 캘린더 삭제를 다시 시도 → 이번에 정리된 건수.

    재실행 멱등: 정리된 건은 표시가 꺼지므로 다음 실행에서 다시 잡히지 않는다.
    연동이 끊긴 설계사의 건은 지금 지울 수 없으므로 아예 대상에서 빼고 표시만 남겨둔다
    (한 번에 처리할 수 있는 건수가 정해져 있어, 처리 불가 건이 앞자리를 계속 차지하면
    뒤의 처리 가능한 건이 밀린다).
    """
    from inpa.accounts.google import google_calendar_enabled
    if not google_calendar_enabled():
        return 0
    pending = list(
        Meeting.objects
        .filter(calendar_cleanup_pending=True)
        .exclude(owner__profile__google_calendar_refresh_token__isnull=True)
        .exclude(owner__profile__google_calendar_refresh_token='')
        .select_related('owner__profile')
        .order_by('pk')[:limit]
    )
    cleaned = 0
    for meeting in pending:
        if remove_meeting_event(meeting):
            cleaned += 1
    return cleaned
