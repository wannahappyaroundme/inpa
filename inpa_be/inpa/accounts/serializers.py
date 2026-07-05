"""계정 도메인 시리얼라이저 (dev/11 정본)."""
import logging

from django.contrib.auth.password_validation import validate_password
from django.utils import timezone
from rest_framework import serializers

from .models import Profile, User

logger = logging.getLogger(__name__)


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    password_confirm = serializers.CharField(write_only=True)
    tos_agreed = serializers.BooleanField()
    pp_agreed = serializers.BooleanField()
    marketing_agreed = serializers.BooleanField(required=False, default=False)
    affiliation = serializers.CharField(required=False, allow_blank=True)
    title = serializers.CharField(required=False, allow_blank=True)
    license_no = serializers.CharField(required=False, allow_blank=True)
    agent_type = serializers.IntegerField(required=False, allow_null=True)
    # 팀 초대 토큰(#24, 선택) — 무효/만료여도 가입은 성공(토큰만 무시). 검증에서 절대 실패시키지 않는다.
    invite_token = serializers.CharField(required=False, allow_blank=True)

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError('이미 가입된 이메일입니다.')
        return value.lower()

    def validate_license_no(self, value):
        # 설계사(모집인) 번호 — 선택 입력. 넣으면 숫자 14자리만 허용.
        v = (value or '').strip()
        if v and (not v.isdigit() or len(v) != 14):
            raise serializers.ValidationError('설계사 번호는 숫자 14자리로 입력해 주세요.')
        return v

    def validate(self, data):
        if data['password'] != data['password_confirm']:
            raise serializers.ValidationError({'password_confirm': '비밀번호가 일치하지 않습니다.'})
        if not data.get('tos_agreed'):
            raise serializers.ValidationError({'tos_agreed': '이용약관 동의는 필수입니다.'})
        if not data.get('pp_agreed'):
            raise serializers.ValidationError({'pp_agreed': '개인정보처리방침 동의는 필수입니다.'})
        validate_password(data['password'])
        return data

    def create(self, data):
        user = User.objects.create_user(email=data['email'], password=data['password'])
        now = timezone.now()
        affiliation = data.get('affiliation') or None
        # ── 팀 초대 토큰(#24) — manager FK + (비어 있으면) affiliation 프리셋만.
        # ★ PIPA-clean 레드라인: manager_share_level 은 절대 프리셋하지 않는다(기본 none 유지,
        #   성과 공유 여부는 신입 본인이 설정에서 직접 선택).
        # ★ 무효/만료 토큰은 무시(+로그)하고 가입은 그대로 성공 — 초대가 만료됐다고 가입을 막지 않는다.
        manager = None
        invite_token = (data.get('invite_token') or '').strip()
        if invite_token:
            from .invite import resolve_invite_manager
            manager = resolve_invite_manager(invite_token)
            if manager is None:
                logger.warning('가입 초대 토큰 무효/만료 → 무시하고 일반 가입 진행 (email=%s)',
                               data['email'])
            elif not affiliation:
                manager_profile = getattr(manager, 'profile', None)
                if manager_profile and manager_profile.affiliation:
                    affiliation = manager_profile.affiliation
        Profile.objects.create(
            user=user,
            tos_agreed_at=now, tos_doc_version='v1',
            pp_agreed_at=now, pp_doc_version='v1',
            marketing_agreed_at=now if data.get('marketing_agreed') else None,
            affiliation=affiliation,
            agent_type=data.get('agent_type'),
            title=(data.get('title') or ''),
            license_no=(data.get('license_no') or None),
            manager=manager,
        )
        return user


class ProfileSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source='user.email', read_only=True)
    managed_agents_count = serializers.SerializerMethodField()
    manager_email = serializers.SerializerMethodField()
    google_calendar_connected = serializers.SerializerMethodField()
    has_usable_password = serializers.SerializerMethodField()

    class Meta:
        model = Profile
        # ★ google_sub / google_calendar_refresh_token 은 절대 노출 금지(여기에 넣지 않는다).
        fields = ('email', 'name', 'affiliation', 'agent_type', 'affiliation_type',
                  'cohort_opt_in', 'manager_share_opt_in', 'manager_share_level',
                  'manager_email', 'managed_agents_count',
                  'license_self_declared', 'license_no', 'career_years',
                  'booking_msg_template', 'booking_location', 'booking_default_duration',
                  'booking_buffer_min', 'title', 'intro_text', 'profile_image',
                  'google_calendar_connected', 'google_calendar_mask_name',
                  'onboarding_completed_at', 'marketing_agreed_at', 'ref_code',
                  'email_verified_at', 'is_admin', 'is_dormant', 'has_usable_password')
        read_only_fields = ('email', 'onboarding_completed_at', 'ref_code', 'email_verified_at',
                            'is_admin', 'is_dormant', 'manager_email', 'managed_agents_count',
                            'google_calendar_connected', 'has_usable_password')

    def update(self, instance, validated_data):
        # 공유 단계(manager_share_level) 저장 시 레거시 bool(opt_in)을 동기화 — none이 아니면 True.
        lvl = validated_data.get('manager_share_level')
        if lvl is not None:
            validated_data['manager_share_opt_in'] = (lvl != Profile.SHARE_NONE)
        return super().update(instance, validated_data)

    def get_has_usable_password(self, obj):
        # 비번 변경/탈퇴 UI 분기 — 구글 전용 가입자는 False(unusable_password).
        return obj.user.has_usable_password()

    def get_managed_agents_count(self, obj):
        # 이 사용자(매니저)에게 배정된 소속 설계사 수(메뉴 노출 게이트용 — 동의 여부 무관 총원).
        return obj.user.managed_agents.count()

    def get_manager_email(self, obj):
        return obj.manager.email if obj.manager_id else None

    def get_google_calendar_connected(self, obj):
        return bool(obj.google_calendar_refresh_token)


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True, min_length=8)

    def validate_new_password(self, value):
        validate_password(value)
        return value


class PasswordChangeSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)

    def validate_new_password(self, value):
        validate_password(value)
        return value


class OnboardingAttestSerializer(serializers.Serializer):
    affiliation = serializers.CharField(required=False, allow_blank=True)
    agent_type = serializers.IntegerField(required=False, allow_null=True)
    affiliation_type = serializers.IntegerField(required=False, allow_null=True)  # 1=전속 2=GA
    manager_email = serializers.EmailField(required=False, allow_blank=True)
    license_self_declared = serializers.BooleanField(required=False, default=False)
    career_years = serializers.IntegerField(required=False, allow_null=True)
