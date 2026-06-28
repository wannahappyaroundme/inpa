"""admin_console 모델 — 신규 모델 최소화 (dev/19 §2.2).

admin_console 앱은 기존 모델 위에 관리 API를 얹는다.
Notice/Faq/Inquiry/InquiryReply/Report/PromotionOrder/PromotionOrderStatusLog 등은
inpa.boards, inpa.promotion 앱에 이미 정의됨 — 이 앱에서는 import만.
NormalizationDict/UnmatchedLog는 inpa.analysis 앱에 정의됨.
ConsentLog는 inpa.customers 앱에 정의됨.

★ 이 앱이 직접 소유하는 신규 모델:
  - PolicyVersion: 약관 버전 이력 (운영 관리 전용, 도메인 앱에 속하지 않음).
"""

from django.db import models


class PolicyVersion(models.Model):
    """약관 버전 이력 (관리자 전용).

    ConsentLog.doc_version(CharField)의 버전 레이블이 실제 존재하는지 확인하는
    단방향 레퍼런스 역할. CASCADE 연결은 하지 않는다 — 동의 로그 감사 무결성 보호.
    """

    POLICY_TYPE_TOS = "tos"
    POLICY_TYPE_PP = "pp"
    POLICY_TYPE_OVERSEAS = "overseas"
    POLICY_TYPE_CHOICES = [
        (POLICY_TYPE_TOS, "이용약관"),
        (POLICY_TYPE_PP, "개인정보처리방침"),
        (POLICY_TYPE_OVERSEAS, "국외이전 동의"),
    ]

    policy_type = models.CharField(
        max_length=20,
        choices=POLICY_TYPE_CHOICES,
        db_index=True,
    )
    version = models.CharField(max_length=50, help_text="예: 2026-06-20 / v2.1")
    effective_at = models.DateTimeField(help_text="시행일시 (UTC)")
    requires_reconsent = models.BooleanField(
        default=False,
        help_text="True 시 기존 동의자에게 재동의 요청 필요 여부 표시 (FE 인지용, 실제 플로우는 별도 구현)",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "admin_console"
        ordering = ["-effective_at", "-created_at"]
        verbose_name = "약관 버전"
        verbose_name_plural = "약관 버전 목록"

    def __str__(self):
        return f"[{self.policy_type}] {self.version} ({self.effective_at.date()})"
