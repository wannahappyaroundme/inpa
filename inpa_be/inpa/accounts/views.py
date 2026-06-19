"""계정 도메인 API (dev/11 정본) — 이메일/비밀번호 전용 인증.

엔드포인트: register · verify-email · resend-verification · login · logout
· password-reset(+confirm) · password/change · profile · withdraw · onboarding/attest
"""
from django.conf import settings
from django.contrib.auth import authenticate
from django.core import signing
from django.core.cache import cache
from django.core.mail import send_mail
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Profile, User
from .serializers import (
    LoginSerializer, OnboardingAttestSerializer, PasswordChangeSerializer,
    PasswordResetConfirmSerializer, PasswordResetRequestSerializer, ProfileSerializer,
    RegisterSerializer,
)
from .tokens import (
    check_password_reset_token, get_user_from_uid, make_email_verify_token,
    make_password_reset_pair, read_email_verify_token,
)


# ── 이메일 발송 헬퍼 (로컬=콘솔, 운영=Resend SMTP) ────────────────
def _send_verify_email(user):
    token = make_email_verify_token(user)
    url = f'{settings.FRONTEND_BASE_URL}/verify-email?token={token}'
    send_mail('[인파] 이메일 인증을 완료해주세요',
              f'아래 링크로 이메일을 인증해주세요 (24시간 유효):\n{url}',
              settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)


def _send_reset_email(user):
    uid, token = make_password_reset_pair(user)
    url = f'{settings.FRONTEND_BASE_URL}/reset-password?uid={uid}&token={token}'
    send_mail('[인파] 비밀번호 재설정',
              f'아래 링크로 비밀번호를 재설정해주세요 (1시간 유효):\n{url}',
              settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        _send_verify_email(user)
        return Response(
            {'message': '인증 이메일을 발송했습니다. 메일함을 확인해주세요.', 'email': user.email},
            status=status.HTTP_201_CREATED)


class VerifyEmailView(APIView):
    permission_classes = [AllowAny]

    def _verify(self, token):
        try:
            pk = read_email_verify_token(token)
        except signing.SignatureExpired:
            return Response({'code': 'TOKEN_EXPIRED', 'detail': '인증 링크가 만료되었습니다.'},
                            status=status.HTTP_400_BAD_REQUEST)
        except signing.BadSignature:
            return Response({'code': 'TOKEN_INVALID', 'detail': '유효하지 않은 인증 링크입니다.'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response({'code': 'TOKEN_INVALID', 'detail': '사용자를 찾을 수 없습니다.'},
                            status=status.HTTP_400_BAD_REQUEST)
        if not user.is_active:
            user.is_active = True
            user.save(update_fields=['is_active'])
            Profile.objects.filter(user=user).update(email_verified_at=timezone.now())
        return Response({'message': '이메일 인증이 완료되었습니다. 로그인해주세요.'})

    def get(self, request):
        return self._verify(request.query_params.get('token', ''))

    def post(self, request):
        return self._verify(request.data.get('token', ''))


class ResendVerificationView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = (request.data.get('email') or '').lower()
        user = User.objects.filter(email__iexact=email, is_active=False).first()
        if user:
            _send_verify_email(user)
        # 계정 존재 노출 방지 — 항상 200
        return Response({'message': '미인증 계정이면 인증 메일을 재발송했습니다.'})


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email'].lower()
        password = serializer.validated_data['password']

        lock_key = f'login-fail:{email}'
        if cache.get(lock_key, 0) >= settings.LOGIN_MAX_ATTEMPTS:
            return Response(
                {'code': 'ACCOUNT_LOCKED', 'detail': '로그인 시도가 많아 잠겼습니다. 10분 후 다시 시도하세요.'},
                status=status.HTTP_423_LOCKED)

        user = authenticate(request, username=email, password=password)
        if user is None:
            # 미인증(is_active=False) 사용자는 authenticate가 None → 별도 식별
            candidate = User.objects.filter(email__iexact=email).first()
            if candidate and not candidate.is_active and candidate.check_password(password):
                return Response(
                    {'code': 'EMAIL_NOT_VERIFIED', 'detail': '이메일 인증을 먼저 완료해주세요.'},
                    status=status.HTTP_403_FORBIDDEN)
            fails = cache.get(lock_key, 0) + 1
            cache.set(lock_key, fails, settings.LOGIN_LOCKOUT_SECONDS)
            return Response(
                {'code': 'INVALID_CREDENTIALS', 'detail': '이메일 또는 비밀번호가 올바르지 않습니다.',
                 'attempts_left': max(0, settings.LOGIN_MAX_ATTEMPTS - fails)},
                status=status.HTTP_400_BAD_REQUEST)

        cache.delete(lock_key)
        # 휴면 자동 복구 (미들웨어 차단 금지 — 로그인 시에만)
        profile, _ = Profile.objects.get_or_create(user=user)
        if profile.is_dormant:
            profile.is_dormant = False
            profile.dormant_at = None
            profile.save(update_fields=['is_dormant', 'dormant_at'])

        token, _ = Token.objects.get_or_create(user=user)
        return Response({
            'token': token.key,
            'email': user.email,
            'onboarding_completed': profile.onboarding_completed_at is not None,
        })


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        return Response({'message': '로그아웃되었습니다.'})


class PasswordResetView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = User.objects.filter(email__iexact=serializer.validated_data['email']).first()
        if user:
            _send_reset_email(user)
        return Response({'message': '가입된 이메일이면 재설정 링크를 보냈습니다.'})


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = get_user_from_uid(User, serializer.validated_data['uid'])
        if user is None or not check_password_reset_token(user, serializer.validated_data['token']):
            return Response({'code': 'TOKEN_INVALID', 'detail': '유효하지 않거나 만료된 링크입니다.'},
                            status=status.HTTP_400_BAD_REQUEST)
        user.set_password(serializer.validated_data['new_password'])
        user.save(update_fields=['password'])
        Profile.objects.filter(user=user).update(last_password_changed=timezone.now())
        Token.objects.filter(user=user).delete()  # 기존 세션 무효화
        return Response({'message': '비밀번호가 재설정되었습니다. 다시 로그인해주세요.'})


class PasswordChangeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user
        if not user.check_password(serializer.validated_data['old_password']):
            return Response({'code': 'INVALID_PASSWORD', 'detail': '현재 비밀번호가 올바르지 않습니다.'},
                            status=status.HTTP_400_BAD_REQUEST)
        user.set_password(serializer.validated_data['new_password'])
        user.save(update_fields=['password'])
        Profile.objects.filter(user=user).update(last_password_changed=timezone.now())
        Token.objects.filter(user=user).delete()
        new_token = Token.objects.create(user=user)
        return Response({'message': '비밀번호가 변경되었습니다.', 'token': new_token.key})


class ProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile, _ = Profile.objects.get_or_create(user=request.user)
        return Response(ProfileSerializer(profile).data)

    def patch(self, request):
        profile, _ = Profile.objects.get_or_create(user=request.user)
        serializer = ProfileSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class WithdrawView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        password = request.data.get('password', '')
        if not request.user.check_password(password):
            return Response({'code': 'INVALID_PASSWORD', 'detail': '비밀번호 확인이 필요합니다.'},
                            status=status.HTTP_400_BAD_REQUEST)
        # 즉시 삭제 (CASCADE로 Profile·고객 데이터 연쇄 삭제). 유예기간 soft-delete은 openGap.
        request.user.delete()
        return Response({'message': '탈퇴가 완료되었습니다.'})


class OnboardingAttestView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = OnboardingAttestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile, _ = Profile.objects.get_or_create(user=request.user)
        data = serializer.validated_data
        if 'affiliation' in data:
            profile.affiliation = data['affiliation'] or None
        if 'agent_type' in data:
            profile.agent_type = data['agent_type']
        if 'career_years' in data:
            profile.career_years = data['career_years']
        profile.license_self_declared = data.get('license_self_declared', profile.license_self_declared)
        profile.onboarding_completed_at = timezone.now()
        profile.save()
        return Response(ProfileSerializer(profile).data)
