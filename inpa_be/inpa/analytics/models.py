"""북극성 계측 — NorthStarEvent (dev/13 정본, dev/06 §5.1 analytics 앱).

★ Day1 동결 = 사후복원 불가 자산. 북극성은 곱셈형(발송 × 열람 × 귀속)이라
  한 항이라도 사후에 계측을 붙이면 그 이전 데이터가 영구 공백이 된다(dev/13 §0).
  특히 share_view(열람)·referral(귀속)은 "그 순간" 기록하지 않으면 영원히 사라진다.
  → 그래서 이 모델을 지금 적재 시작하는 것이 핵심이다.

설계 원칙 — 단일 테이블 append-only 로그(dev/13 §2.2):
  6종을 별 테이블로 쪼개면 깔때기 조인이 다중 조인이 되고 사후 이벤트 추가 시
  마이그레이션이 여러 벌이 된다. event_type(문자열 안정값) + payload(JSON 확장 슬롯)으로
  단일 테이블을 만들어 깔때기를 단일 GROUP BY로 집계 가능하게 한다.

가시성(dev/02 §0): 관리자 전용 집계 + 본인(sender) 자기 이벤트.
  viewer_fp 는 비식별 지문(개인정보 아님) — share_view 중복제거 키.

★ event_type 은 SmallInt 재배치(dev/13 §2.2 경고) 대신 **문자열 안정값**으로 고정한다.
  컬럼 의미 변경·값 재정의는 귀속 영구 파손 → 기존 값은 절대 바꾸지 않고, 신규는 추가만 한다.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q


class NorthStarEvent(models.Model):
    """북극성 단일 append-only 이벤트 로그.

    필드(dev/13 §2.2 컬럼 동결):
      event_type  깔때기 단계(문자열 안정값 — 재정의 금지)
      customer    대상 고객 FK(null — ocr/analysis 등 고객 무관 이벤트 허용), SET_NULL
      sender      발신 설계사(owner) FK(null — 비인증 공유뷰 열람자), SET_NULL(탈퇴해도 보존)
      share_token 공유 토큰(null — create→view 매칭 키)
      ref_code    귀속 코드(null — referral 집계)
      viewer_fp   비식별 지문(null — share_view/referral 중복제거 키)
      channel     발생 채널(web/clipboard/device 등 — clipboard_copy 자동발송 사칭 금지)
      payload     확장 슬롯(JSON — 사후 추가는 여기로만, 기존 컬럼 불변)
      created_at  적재 시각(UTC 저장, KST 표기)
    """

    # ── event_type 안정값 (★재정의 금지 — 신규는 추가만) ───────────────
    OCR_UPLOAD = 'ocr_upload'                # ① 증권 detect 성공 (깔때기 입구)
    ANALYSIS_VIEW = 'analysis_view'          # ② 분석/히트맵 조회 (미끼 지표)
    SHARE_CREATED = 'share_created'          # ③ 공유링크 발급 (발송 — 곱셈 1항)
    CLIPBOARD_COPY = 'clipboard_copy'        # ④ 공유뷰 복사 클릭 (발송 프록시·보조)
    SHARE_VIEW = 'share_view'                # ⑤ 공유뷰 200 (열람 — 곱셈 2항·신뢰 KPI)
    REFERRAL_ATTRIBUTED = 'referral_attributed'  # ⑥ ?ref= 보유 view→신규 가입 (귀속 — 곱셈 3항)
    # ⑦ 공유뷰 '연락 요청 남기기'(콜백) — 설계사 알림 트리거(LB#8).
    #    ⚠️ EVENT_TYPE_CHOICES에 넣지 않음 — choices 변경은 AlterField 마이그레이션을
    #    만드는데 이번 라운드는 마이그레이션 0 고정. choices는 표시용일 뿐 저장은 자유
    #    (create()는 choices 검증을 하지 않음). 다음 스키마 라운드에서 choices에 흡수.
    CALLBACK_REQUEST = 'callback_request'
    # ⑧ 공유뷰(/s) '바로 상담 예약' CTA 클릭 — 분석→예약 전환 계측(FE가 이미 전송).
    CTA_CLICK = 'cta_click'

    EVENT_TYPE_CHOICES = (
        (OCR_UPLOAD, '증권 OCR 업로드'),
        (ANALYSIS_VIEW, '분석 조회'),
        (SHARE_CREATED, '공유링크 발급'),
        (CLIPBOARD_COPY, '클립보드 복사'),
        (SHARE_VIEW, '공유뷰 열람'),
        (REFERRAL_ATTRIBUTED, '인바운드 귀속'),
        (CTA_CLICK, '예약 CTA 클릭'),
    )

    event_type = models.CharField('이벤트 종류', max_length=40, choices=EVENT_TYPE_CHOICES)

    customer = models.ForeignKey(
        'customers.Customer', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='northstar_events', verbose_name='대상 고객')
    # 발신 설계사 — 탈퇴해도 이벤트 보존(SET_NULL). 비인증 공유뷰 열람자는 null.
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='northstar_events', verbose_name='발신 설계사')

    share_token = models.UUIDField('공유 토큰', null=True, blank=True)
    ref_code = models.CharField('귀속 코드', max_length=20, null=True, blank=True)
    viewer_fp = models.CharField('열람자 지문(비식별)', max_length=64, null=True, blank=True)
    channel = models.CharField('채널', max_length=20, default='', blank=True)
    payload = models.JSONField('확장 페이로드', default=dict, blank=True)

    created_at = models.DateTimeField('적재 시각', auto_now_add=True)

    class Meta:
        db_table = 'northstar_event'
        verbose_name = '북극성 이벤트'
        verbose_name_plural = '북극성 이벤트'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['event_type', 'created_at']),    # 깔때기 시계열
            models.Index(fields=['share_token']),                  # create→view 매칭
            models.Index(fields=['ref_code', 'event_type']),       # 귀속 집계
            models.Index(fields=['sender', 'created_at']),         # 설계사별 KPI
        ]

    def __str__(self):
        return f'{self.event_type}@{self.created_at:%Y-%m-%d %H:%M}'


class ShareSnapshot(models.Model):
    """공유(/s) 스냅샷 — 공유 링크 발급 시점의 화면을 그대로 기록 (✦ 2026-07-08, 프리런치 #27).

    `payload`는 발급 순간의 분석 화면을 표준트리 FK 없이 복제한 불변 본문이다.
    이후 표준 담보 트리·정규화 사전이 바뀌어도 본문은 그대로 남는다. 회수·만료·첫 열람
    같은 링크 수명 주기 필드만 별도로 갱신한다.

    `customer`는 CASCADE(ConsentLog의 SET_NULL과 다름): 스냅샷은 비정규화 PII(마스킹된
    이름·생년·담보명·금액)를 그대로 들고 있으므로, 고객이 삭제되면 함께 파기돼야
    "증권 원본 미보관" PIPA 자산이 유지된다.

    파기 경로 2개(+FK 1개):
      ① 보유기간(SHARE_SNAPSHOT_RETENTION_DAYS, 기본 180일) 경과 → daily job
         (notifications/jobs.py::cleanup_expired_share_snapshots).
      ② 고객 본인 개인정보(personal_info) 동의 철회 → 즉시 전량 삭제
         (customers/public_consent.py::_apply_revocations).
      ③ 고객 삭제 → CASCADE로 자동 파기.
    """
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='share_snapshots', verbose_name='설계사')
    customer = models.ForeignKey(
        'customers.Customer', on_delete=models.CASCADE,
        related_name='share_snapshots', verbose_name='대상 고객')

    share_token = models.UUIDField('캡처 시점 공유 토큰', null=True, blank=True)
    payload_version = models.CharField(
        '공유 본문 버전', max_length=40, default='v1-legacy-actions')
    payload = models.JSONField('공유뷰 페이로드(그때 그 화면, 값 복제)', default=dict, blank=True)

    # 캡처 시점 동의/사전 버전 스탬프(감사용) — 값 복제, 이후 실제 상태 변화와 무관.
    consent_overseas = models.BooleanField('캡처 시점 국외이전 동의', default=False)
    consent_doc_version = models.CharField(
        '캡처 시점 동의문 버전', max_length=40, default='', blank=True)
    consent_scopes = models.JSONField('캡처 시점 유효 동의 범위', default=list, blank=True)
    dict_version = models.CharField(
        '캡처 시점 정규화 사전 버전', max_length=40, default='', blank=True)
    insurance_count = models.SmallIntegerField('캡처 시점 보유 보험 수', default=0)

    captured_at = models.DateTimeField('캡처 시각', auto_now_add=True, db_index=True)
    link_expires_at = models.DateTimeField(
        '공개 링크 만료일', null=True, blank=True, db_index=True)
    revoked_at = models.DateTimeField('공개 링크 회수 시각', null=True, blank=True)
    revoked_reason = models.CharField(
        '공개 링크 회수 사유', max_length=40, default='', blank=True)
    first_viewed_at = models.DateTimeField('첫 열람 시각', null=True, blank=True)
    retention_expires_at = models.DateTimeField('자동 삭제 예정일', db_index=True)

    class Meta:
        db_table = 'share_snapshot'
        verbose_name = '공유 기록'
        verbose_name_plural = '공유 기록'
        ordering = ['-captured_at']
        indexes = [
            models.Index(fields=['owner', 'customer']),
            models.Index(fields=['retention_expires_at']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['share_token'],
                condition=Q(share_token__isnull=False),
                name='uniq_share_snapshot_nonnull_token'),
        ]

    def __str__(self):
        return f'share-snapshot#{self.pk}@{self.captured_at:%Y-%m-%d %H:%M}'
