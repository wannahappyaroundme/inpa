"""계정 도메인 시리얼라이저 (dev/11 정본)."""
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone
from rest_framework import serializers

from .models import Profile, User


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    password_confirm = serializers.CharField(write_only=True)
    tos_agreed = serializers.BooleanField()
    pp_agreed = serializers.BooleanField()
    marketing_agreed = serializers.BooleanField(required=False, default=False)
    affiliation = serializers.CharField(required=False, allow_blank=True)
    agent_type = serializers.IntegerField(required=False, allow_null=True)

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError('이미 가입된 이메일입니다.')
        return value.lower()

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
        Profile.objects.create(
            user=user,
            tos_agreed_at=now, tos_doc_version='v1',
            pp_agreed_at=now, pp_doc_version='v1',
            marketing_agreed_at=now if data.get('marketing_agreed') else None,
            affiliation=(data.get('affiliation') or None),
            agent_type=data.get('agent_type'),
        )
        return user


class ProfileSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source='user.email', read_only=True)
    managed_agents_count = serializers.SerializerMethodField()
    manager_email = serializers.SerializerMethodField()

    class Meta:
        model = Profile
        fields = ('email', 'name', 'affiliation', 'agent_type', 'affiliation_type',
                  'cohort_opt_in', 'manager_share_opt_in', 'manager_email', 'managed_agents_count',
                  'license_self_declared', 'license_no', 'career_years',
                  'booking_msg_template', 'booking_location', 'booking_default_duration',
                  'onboarding_completed_at', 'marketing_agreed_at', 'ref_code',
                  'email_verified_at', 'is_admin', 'is_dormant')
        read_only_fields = ('email', 'onboarding_completed_at', 'ref_code', 'email_verified_at',
                            'is_admin', 'is_dormant', 'manager_email', 'managed_agents_count')

    def get_managed_agents_count(self, obj):
        # 이 사용자(매니저)에게 배정된 소속 설계사 수(메뉴 노출 게이트용 — 동의 여부 무관 총원).
        return obj.user.managed_agents.count()

    def get_manager_email(self, obj):
        return obj.manager.email if obj.manager_id else None


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
