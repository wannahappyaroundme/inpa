"""인증·계정 모델 — 이메일/비밀번호 전용 (dev/02 §2, dev/11 정본).

User = Django 인증 코어(이메일 로그인). 인증상태·약관동의·위촉·휴면은 Profile로 분리
(Django User 비대화 방지, foliio 패턴 일치).
"""
import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models

from .managers import UserManager


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField('이메일', unique=True)  # 로그인 식별자
    is_active = models.BooleanField(default=False)     # 이메일 인증 완료 시 True
    is_staff = models.BooleanField(default=False)      # Django admin 접근
    date_joined = models.DateTimeField('가입 시각', auto_now_add=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        db_table = 'accounts_user'

    def __str__(self):
        return self.email


def _gen_ref_code():
    """북극성 귀속용 추천 코드 (Day1 발급. 정식 발급 로직은 Sprint0)."""
    return uuid.uuid4().hex[:10].upper()


class Profile(models.Model):
    AGENT_LIFE, AGENT_NONLIFE, AGENT_BOTH = 1, 2, 3
    AGENT_TYPE_CHOICES = [
        (AGENT_LIFE, '생명'), (AGENT_NONLIFE, '손해'), (AGENT_BOTH, '교차'),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name='profile')

    # ── 인증 (이메일/비밀번호 전용) ─────────────────────────
    email_verified_at = models.DateTimeField(null=True, blank=True)   # User.is_active와 1:1
    last_password_changed = models.DateTimeField(null=True, blank=True)

    # ── 약관 동의 (가입 폼 통합 수집) ───────────────────────
    tos_agreed_at = models.DateTimeField(null=True, blank=True)       # 서비스 이용약관 (필수)
    tos_doc_version = models.CharField(max_length=30, default='')
    pp_agreed_at = models.DateTimeField(null=True, blank=True)        # 개인정보처리방침 (필수)
    pp_doc_version = models.CharField(max_length=30, default='')
    marketing_agreed_at = models.DateTimeField(null=True, blank=True)  # 마케팅 (선택)
    marketing_revoked_at = models.DateTimeField(null=True, blank=True)

    # ── 위촉 자기신고 · 온보딩 ──────────────────────────────
    affiliation = models.CharField(max_length=100, null=True, blank=True)
    agent_type = models.SmallIntegerField(null=True, blank=True, choices=AGENT_TYPE_CHOICES)
    license_self_declared = models.BooleanField(default=False)
    license_no = models.CharField(max_length=50, null=True, blank=True)
    career_years = models.IntegerField(null=True, blank=True)
    onboarding_completed_at = models.DateTimeField(null=True, blank=True)

    # ── 계정 상태 (휴면) ────────────────────────────────────
    is_admin = models.BooleanField(default=False)     # 관리자 bypass 게이트
    is_dormant = models.BooleanField(default=False)   # 미들웨어 차단 금지 — 로그인 시 자동복구
    dormant_at = models.DateTimeField(null=True, blank=True)
    dormancy_warning_sent_at = models.DateTimeField(null=True, blank=True)
    will_delete_at = models.DateTimeField(null=True, blank=True)

    # ── 북극성 귀속 ────────────────────────────────────────
    ref_code = models.CharField(max_length=20, unique=True, null=True, blank=True)

    class Meta:
        db_table = 'accounts_profile'

    def save(self, *args, **kwargs):
        if not self.ref_code:
            self.ref_code = _gen_ref_code()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'Profile<{self.user.email}>'
