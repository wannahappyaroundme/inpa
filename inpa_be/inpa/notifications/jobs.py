"""일일 배치 잡 — 리마인더 알림 생산자 레지스트리 + 실행기 (spec 2026-07-04, LB #5+#6).

호출 경로 2개(둘 다 이 모듈의 run_daily_jobs 하나로 수렴):
  ① POST /api/v1/jobs/run-daily/  (runner.py — X-JOB-TOKEN, GitHub Actions cron이 호출)
  ② python manage.py run_daily_jobs (수동/Render Shell)

설계 원칙:
  - KST 기준 하루 1회 멱등: 같은 날 재실행 시 중복 알림 0 (재실행 = no-op).
    dedupe 키 = (owner, notif_type, target_date, customer_id, calendar_event_id).
    Notification 의 부분 유니크 제약(owner+type+target_date+customer)이 DB 레벨 2차 방어.
  - 날짜 계산 전부 KST (CLAUDE.md §7 — timezone.localdate/localtime, make_aware=Asia/Seoul).
  - ReminderRule 존중: enabled=False → 그 유저+유형은 생산 0. rule 부재 시 REMINDER_DEFAULTS.
  - 소유자 격리 절대: 모든 후보 행은 owner(또는 customer__owner) 경유로만 귀속.
  - 생산자 간 실패 격리: 하나가 죽어도 나머지는 계속(부분 실패 시 errors 에 기록,
    하트비트 마커는 전부 성공했을 때만 기록 → dead-man 스위치 의미 보존).
  - 단순 쿼리만(120s gunicorn 타임아웃 대비 여유).

알림 카피 레드라인(§6): 쉬운 말·긍정 프레이밍·em-dash 금지·'D-3' 표기는 허용.
"""
import datetime as dt
import logging

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.db.models.functions import Coalesce
from django.utils import timezone

from inpa.analysis.models import SeedMarker
from inpa.booking.models import Meeting
from inpa.customers.models import Customer
from inpa.insurances.models import CustomerInsurance
from inpa.schedule.models import ScheduleItem

from .models import REMINDER_DEFAULTS, Notification, NotifType, ReminderRule

logger = logging.getLogger(__name__)

# dead-man 하트비트 — 성공 시 SeedMarker(key)에 KST 날짜 기록(H-2 Sentry 감시 예정).
HEARTBEAT_KEY = 'daily_jobs'

# ReminderRule.days_before 상한(모델 docstring 0~90) — 후보 스캔 창의 안전 상한.
_MAX_LEAD_DAYS = 90


# ─── 공통 헬퍼 ─────────────────────────────────────────────────────

def _rule_getter(rule_type):
    """owner_id → (enabled, days_before). rule 부재 유저는 REMINDER_DEFAULTS 폴백."""
    default = next(d for d in REMINDER_DEFAULTS if d['rule_type'] == rule_type)
    fallback = (default['enabled'], default['days_before'])
    rules = {
        owner_id: (enabled, days_before)
        for owner_id, enabled, days_before in ReminderRule.objects
        .filter(rule_type=rule_type)
        .values_list('owner_id', 'enabled', 'days_before')
    }
    return lambda owner_id: rules.get(owner_id, fallback)


def _parse_date(raw):
    """레거시 CharField 날짜('YYYY.MM.DD' / 'YYYY-MM-DD') → date | None (관대 파싱)."""
    if not raw:
        return None
    parts = str(raw).strip().replace('.', '-').replace('/', '-').split('-')
    if len(parts) != 3:
        return None
    try:
        return dt.date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (TypeError, ValueError):
        return None


def _next_birthday(birth, today):
    """다음 생일(월-일 매칭, 오늘 포함). 2/29 생은 평년 2/28 처리."""
    for year in (today.year, today.year + 1):
        try:
            cand = birth.replace(year=year)
        except ValueError:  # 2/29 → 평년
            cand = dt.date(year, 2, 28)
        if cand >= today:
            return cand
    return None  # 도달 불가(방어)


def _kst_day_start(day):
    """KST 그 날 00:00 aware datetime (TIME_ZONE=Asia/Seoul 전제 — CLAUDE.md §7)."""
    return timezone.make_aware(dt.datetime.combine(day, dt.time.min))


def _day_label(lead, target):
    if lead <= 0:
        return '오늘'
    if lead == 1:
        return '내일'
    return f'{target.month}월 {target.day}일'


def _create_once(*, owner_id, notif_type, title, body, target_date,
                 customer_id=None, meeting=None, calendar_event_id=None):
    """당일 멱등 생성 — 이미 같은 키의 알림이 있으면 0, 새로 만들면 1.

    1차: (owner, type, target_date, customer_id, calendar_event_id[, meeting]) 존재 검사
         — meeting 이 주어지면 키에 포함해, 고객 없는(SET_NULL) 서로 다른 미팅 2건이
         같은 날이라는 이유로 두 번째가 억제되지 않게 한다.
    2차: DB 부분 유니크 제약(owner+type+target_date+customer, 둘 다 not null 조건)
         레이스/키 겹침은 IntegrityError 로 잡아 0 처리(같은 고객·같은 날 1건으로 수렴).
    """
    key = dict(
        owner_id=owner_id, notif_type=notif_type, target_date=target_date,
        customer_id=customer_id, calendar_event_id=calendar_event_id,
    )
    if meeting is not None:
        key['meeting'] = meeting
    exists = Notification.objects.filter(**key).exists()
    if exists:
        return 0
    try:
        with transaction.atomic():
            Notification.objects.create(
                owner_id=owner_id, notif_type=notif_type, title=title, body=body,
                target_date=target_date, customer_id=customer_id, meeting=meeting,
                calendar_event_id=calendar_event_id,
            )
    except IntegrityError:
        return 0
    return 1


# ─── 생산자 5종 (spec §4) ─────────────────────────────────────────

def produce_birthday_soon(today):
    """진행중(active) 고객의 생일이 리드일수 내면 설계사에게 알림."""
    get_rule = _rule_getter(NotifType.BIRTHDAY_SOON)
    created = 0
    rows = (Customer.objects
            .filter(status=Customer.STATUS_ACTIVE)
            .exclude(birth_day='')
            .exclude(birth_day__isnull=True)
            .values_list('id', 'owner_id', 'name', 'birth_day'))
    for cid, owner_id, name, birth_raw in rows.iterator():
        enabled, lead = get_rule(owner_id)
        if not enabled:
            continue
        birth = _parse_date(birth_raw)
        if birth is None:
            continue
        bday = _next_birthday(birth, today)
        if bday is None:
            continue
        dday = (bday - today).days
        if dday > lead:
            continue
        when = '오늘' if dday == 0 else f'D-{dday}'
        created += _create_once(
            owner_id=owner_id, notif_type=NotifType.BIRTHDAY_SOON,
            title='고객 생일 안내',
            body=f'{name}님 생일이 {bday.month}월 {bday.day}일({when})이에요. 축하 인사를 준비해 보세요.',
            target_date=bday, customer_id=cid,
        )
    return created


def produce_expiry_soon(today):
    """보유(portfolio_type=1)·미해지 계약의 만기일이 리드일수 내면 알림.

    만기 필드 = CustomerInsurance.expiry_date (churn/보험카드가 쓰는 실제 필드,
    CharField 'YYYY.MM.DD'/'YYYY-MM-DD' 혼재 → 관대 파싱).
    """
    get_rule = _rule_getter(NotifType.EXPIRY_SOON)
    created = 0
    qs = (CustomerInsurance.objects
          .filter(portfolio_type=1, is_cancelled=False)
          .exclude(expiry_date__isnull=True)
          .exclude(expiry_date='')
          .select_related('customer')
          .only('id', 'name', 'expiry_date',
                'customer__id', 'customer__owner_id', 'customer__name'))
    for ci in qs.iterator():
        cust = ci.customer
        enabled, lead = get_rule(cust.owner_id)
        if not enabled:
            continue
        exp = _parse_date(ci.expiry_date)
        if exp is None:
            continue
        dday = (exp - today).days
        if dday < 0 or dday > lead:
            continue
        when = '오늘' if dday == 0 else f'D-{dday}'
        product = ci.name or '보험 계약'
        created += _create_once(
            owner_id=cust.owner_id, notif_type=NotifType.EXPIRY_SOON,
            title='만기 예정 계약 안내',
            body=f'{cust.name}님의 {product} 만기일이 {exp.month}월 {exp.day}일({when})이에요. '
                 f'갱신 상담을 준비해 보세요.',
            target_date=exp, customer_id=cust.id,
        )
    return created


def produce_consult_reminder(today):
    """리드일수 뒤(기본 1일 = 내일, KST) 확정 미팅 + 고객미팅 분류 일정 알림."""
    get_rule = _rule_getter(NotifType.CONSULT_REMINDER)
    created = 0
    scan_min = _kst_day_start(today)
    scan_max = _kst_day_start(today + dt.timedelta(days=_MAX_LEAD_DAYS + 1))

    # ① 확정(confirmed) 미팅 — booking.Meeting (start_at=UTC 저장 → localtime 으로 KST 날짜 판정)
    meetings = (Meeting.objects
                .filter(status=Meeting.STATUS_CONFIRMED,
                        start_at__gte=scan_min, start_at__lt=scan_max)
                .select_related('customer'))
    for m in meetings.iterator():
        enabled, lead = get_rule(m.owner_id)
        if not enabled:
            continue
        target = today + dt.timedelta(days=lead)
        local = timezone.localtime(m.start_at)
        if local.date() != target:
            continue
        who = f'{m.customer.name}님과 ' if m.customer else ''
        created += _create_once(
            owner_id=m.owner_id, notif_type=NotifType.CONSULT_REMINDER,
            title='상담 일정 안내',
            body=f'{_day_label(lead, target)} {local:%H:%M}에 {who}{m.get_method_display()} '
                 f'상담이 있어요. 미리 준비해 보세요.',
            target_date=target, customer_id=m.customer_id, meeting=m,
        )

    # ② 고객미팅(category=meeting) 일정 — schedule.ScheduleItem(kind=event)
    items = (ScheduleItem.objects
             .filter(kind=ScheduleItem.KIND_EVENT, category=ScheduleItem.CAT_MEETING,
                     start_at__gte=scan_min, start_at__lt=scan_max)
             .select_related('customer'))
    for it in items.iterator():
        enabled, lead = get_rule(it.owner_id)
        if not enabled:
            continue
        target = today + dt.timedelta(days=lead)
        local = timezone.localtime(it.start_at)
        if local.date() != target:
            continue
        who = f'{it.customer.name}님과 ' if it.customer else ''
        at = '' if it.all_day else f' {local:%H:%M}에'
        created += _create_once(
            owner_id=it.owner_id, notif_type=NotifType.CONSULT_REMINDER,
            title='상담 일정 안내',
            body=f"{_day_label(lead, target)}{at} {who}'{it.title}' 일정이 있어요. 미리 준비해 보세요.",
            target_date=target, customer_id=it.customer_id, calendar_event_id=it.id,
        )
    return created


def produce_task_due(today):
    """마감 임박(리드일수 내)·미완료 할 일 알림.

    ReminderRule.days_before(기본 1)를 리드로 존중 — 설정 화면('할 일 마감일 전 알림')이
    사용자에게 약속하는 동작과 일치. dedupe target_date=마감일 → 할 일당 1회
    (리드창 안에서 매일 재실행돼도 중복 없음). 시각 없는 todo 는 KST 정오 저장 규약이라
    당일 창에 포함.
    """
    get_rule = _rule_getter(NotifType.TASK_DUE)
    created = 0
    scan_min = _kst_day_start(today)
    scan_max = _kst_day_start(today + dt.timedelta(days=_MAX_LEAD_DAYS + 1))
    items = (ScheduleItem.objects
             .filter(kind=ScheduleItem.KIND_TODO, is_done=False,
                     start_at__gte=scan_min, start_at__lt=scan_max)
             .select_related('customer'))
    for it in items.iterator():
        enabled, lead = get_rule(it.owner_id)
        if not enabled:
            continue
        due = timezone.localtime(it.start_at).date()
        d_left = (due - today).days
        if d_left > max(lead or 0, 0):
            continue
        who = f'{it.customer.name}님 관련 ' if it.customer else ''
        when = '오늘 마감인' if d_left <= 0 else f'{due.month}월 {due.day}일(D-{d_left}) 마감인'
        created += _create_once(
            owner_id=it.owner_id, notif_type=NotifType.TASK_DUE,
            title='오늘 할 일 안내' if d_left <= 0 else '할 일 마감 안내',
            body=f"{when} {who}할 일이 있어요: '{it.title}'. 잊지 말고 마무리해 보세요.",
            target_date=due, customer_id=it.customer_id, calendar_event_id=it.id,
        )
    return created


def produce_share_unread(today):
    """보낸 지 24시간(days_before=0 특별 해석)이 지나도록 열람되지 않은 공유 링크 알림.

    근거 필드(전부 Customer 실필드): share_sent_at(발송 시각, CustomerShareCreateView 기록)
    / user_view_at(고객 열람 시각, ShareAnalysisView 기록) / share_expires_at(만료).
    만료된 링크는 제외(더 열 수 없는 링크 재안내 방지). dedupe target_date=발송일(KST)
    → 같은 발송 건은 평생 1회만 알림(재발송 rotate 시 share_sent_at 갱신 → 새 알림 가능).
    """
    get_rule = _rule_getter(NotifType.SHARE_UNREAD)
    created = 0
    # 기준 시각 = 실행일(today)의 명목 실행 시각 08:00 KST — 다른 생산자처럼 today 에
    # 결정적으로 따른다(재실행·리플레이·테스트에서 벽시계 비의존).
    now = _kst_day_start(today) + dt.timedelta(hours=8)
    qs = (Customer.objects
          .filter(share_sent_at__isnull=False)
          .filter(Q(user_view_at__isnull=True) | Q(user_view_at__lt=F('share_sent_at')))
          .filter(Q(share_expires_at__isnull=True) | Q(share_expires_at__gt=now))
          .values_list('id', 'owner_id', 'name', 'share_sent_at'))
    for cid, owner_id, name, sent_at in qs.iterator():
        enabled, days = get_rule(owner_id)
        if not enabled:
            continue
        threshold = dt.timedelta(days=days or 1)  # 0 = 24h 특별 해석(모델 docstring)
        if now - sent_at < threshold:
            continue
        created += _create_once(
            owner_id=owner_id, notif_type=NotifType.SHARE_UNREAD,
            title='공유 링크 열람 안내',
            body=f'{name}님께 보낸 보장 분석 링크가 아직 열리지 않았어요. 한 번 더 안내해 보세요.',
            target_date=timezone.localtime(sent_at).date(), customer_id=cid,
        )
    return created


# ─── 정리 단계 — 인바운드 리드 보유기간 자동 파기 (spec 2026-07-04 Part1 §5) ──

def cleanup_expired_leads(today):
    """상담으로 이어지지 않은 인바운드 리드를 보유기간(LEAD_RETENTION_DAYS, 기본 180일)
    경과 시 하드 삭제(파기)하고 설계사에게 요약 알림 1건을 남긴다.

    대상(전부 AND — 하나라도 어긋나면 보존):
      - lead_source ∈ {셀프진단(self_diagnosis), 소개카드(introduction)} 인바운드만.
        설계사가 직접 등록한 고객(lead_source null/direct/명함/행사)은 절대 대상 아님.
      - ★ lead_created_at 이 있어야 함(실제 인바운드 유입의 구조적 판별자).
        lead_created_at 은 셀프진단(/d)·소개카드(/p) 유입 경로에서만 기록되고
        수기/일괄 등록은 절대 기록하지 않는다 — lead_source='introduction'(소개)은
        설계사가 등록 모달에서 직접 고를 수 있는 유입경로라, source 만으로 거르면
        직접 등록 고객이 오삭제된다(2026-07-04 리뷰 blocker).
      - 활동 앵커(last_contacted_at 있으면 그것, 없으면 created_at)가 보유기간 초과.
      - sales_stage='db'(미전환) AND 보유 보험 0 AND 접촉기록(ContactLog) 0 AND 미팅 0.
      - ★ 보유기간 내 새 ConsentLog 0 — /d·/p 재신청은 기존 고객을 재사용하며
        새 ConsentLog 만 남기므로(전화번호 dedupe), 신선한 동의 = 활동으로 간주해
        재신청 당일 밤 파기되는 역설(새 동의 직후 파기)을 막는다(2026-07-04 리뷰 major).
    ConsentLog는 SET_NULL이라 동의 감사 로그는 잔존(기존 문서화된 설계 그대로).
    LEAD_RETENTION_DAYS ≤ 0 이면 스킵(안전 스위치). 재실행 멱등(대상 0 → 알림 0).
    """
    days = int(getattr(settings, 'LEAD_RETENTION_DAYS', 180) or 0)
    if days <= 0:
        return 0
    cutoff = _kst_day_start(today - dt.timedelta(days=days))
    qs = (Customer.objects
          .filter(lead_source__in=[Customer.LEAD_SELF_DIAGNOSIS,
                                   Customer.LEAD_INTRODUCTION],
                  sales_stage=Customer.STAGE_DB,
                  lead_created_at__isnull=False)
          .annotate(_activity_anchor=Coalesce('last_contacted_at', 'created_at'))
          .filter(_activity_anchor__lt=cutoff)
          .filter(customer_insurance_list__isnull=True,
                  contact_logs__isnull=True,
                  meetings__isnull=True)
          .exclude(consent_logs__agreed_at__gte=cutoff))
    rows = list(qs.values_list('id', 'owner_id'))
    if not rows:
        return 0
    ids = [cid for cid, _ in rows]
    per_owner = {}
    for _, owner_id in rows:
        per_owner[owner_id] = per_owner.get(owner_id, 0) + 1
    Customer.objects.filter(id__in=ids).delete()
    for owner_id, n in per_owner.items():
        _create_once(
            owner_id=owner_id, notif_type=NotifType.SELF_DIAGNOSIS_LEAD,
            title='잠재고객 정보 자동 정리',
            body=f'오래 연락이 닿지 않은 잠재고객 {n}명의 개인정보를 정리했어요. '
                 f'개인정보 보호를 위한 자동 정리예요.',
            target_date=today,
        )
    return len(ids)


# ─── 정리 단계 — 공유(/s) 스냅샷 보유기간 자동 파기 (spec 2026-07-08, 프리런치 #27) ──

def cleanup_expired_share_snapshots(now):
    """공유(/s) 스냅샷 보유기간(SHARE_SNAPSHOT_RETENTION_DAYS, 기본 180일) 경과분 하드 삭제.

    retention_expires_at 은 캡처 시점(aware datetime)에 이미 +N일로 계산돼 저장되므로
    비교는 aware datetime끼리 그대로 한다(KST 날짜 변환 불필요 — 저장 자체가 절대시각,
    CLAUDE.md §7 "이번 달" 류의 날짜-버킷 함정과 무관). 재실행 멱등(대상 0 → 삭제 0).
    """
    from inpa.analytics.models import ShareSnapshot
    # 안전 스위치: 0 이하면 파기 전면 중단(§97 소송 보전 등). cleanup_expired_leads 와 동일.
    days = int(getattr(settings, 'SHARE_SNAPSHOT_RETENTION_DAYS', 180) or 0)
    if days <= 0:
        return 0
    deleted, _ = ShareSnapshot.objects.filter(retention_expires_at__lte=now).delete()
    return deleted


# ─── 레지스트리 + 실행기 ──────────────────────────────────────────

PRODUCERS = (
    (NotifType.BIRTHDAY_SOON.value, produce_birthday_soon),
    (NotifType.EXPIRY_SOON.value, produce_expiry_soon),
    (NotifType.CONSULT_REMINDER.value, produce_consult_reminder),
    (NotifType.TASK_DUE.value, produce_task_due),
    (NotifType.SHARE_UNREAD.value, produce_share_unread),
)


def run_daily_jobs(today=None):
    """생산자 전부 실행 → {date, counts, errors, total_created}.

    생산자 간 실패 격리(하나가 죽어도 나머지 계속). 전부 성공했을 때만
    SeedMarker(key='daily_jobs') 하트비트 기록(dead-man 스위치 의미 보존).
    """
    today = today or timezone.localdate()
    counts = {}
    errors = {}
    for name, producer in PRODUCERS:
        try:
            counts[name] = producer(today)
        except Exception as exc:  # noqa: BLE001 — 생산자 간 격리(부분 실패 허용)
            logger.exception('daily job producer failed: %s', name)
            counts[name] = 0
            errors[name] = f'{type(exc).__name__}: {exc}'
    total_created = sum(counts.values())  # 알림 생산 수(정리 단계 삭제 수와 분리)
    # 정리 단계 — 알림 생산자와 별개(인바운드 리드 보유기간 파기). 실패 격리 동일.
    try:
        counts['lead_retention_deleted'] = cleanup_expired_leads(today)
    except Exception as exc:  # noqa: BLE001
        logger.exception('daily cleanup failed: lead_retention')
        counts['lead_retention_deleted'] = 0
        errors['lead_retention'] = f'{type(exc).__name__}: {exc}'
    # 정리 단계 — 공유(/s) 스냅샷 보유기간 파기(spec 2026-07-08). 실패 격리 동일.
    try:
        counts['share_snapshot_retention_deleted'] = cleanup_expired_share_snapshots(timezone.now())
    except Exception as exc:  # noqa: BLE001
        logger.exception('daily cleanup failed: share_snapshot_retention')
        counts['share_snapshot_retention_deleted'] = 0
        errors['share_snapshot_retention'] = f'{type(exc).__name__}: {exc}'
    if not errors:
        SeedMarker.objects.update_or_create(
            key=HEARTBEAT_KEY, defaults={'version': today.isoformat()})
    return {
        'date': today.isoformat(),
        'counts': counts,
        'errors': errors,
        'total_created': total_created,
    }
