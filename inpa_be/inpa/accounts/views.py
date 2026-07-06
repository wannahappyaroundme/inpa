"""계정 도메인 API (dev/11 정본) — 이메일/비밀번호 전용 인증.

엔드포인트: register · verify-email · resend-verification · login · logout
· password-reset(+confirm) · password/change · profile · withdraw · onboarding/attest
"""
import logging

from django.conf import settings
from django.contrib.auth import authenticate
from django.core import signing
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import transaction
from django.http import HttpResponseRedirect
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from inpa.notifications.models import create_reminder_rules_for_user

from .google import (
    GoogleTokenError, google_calendar_enabled, google_login_enabled,
    verify_google_id_token,
)
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


# ── 지점장 연결 헬퍼 (이메일 → User). 본인 지정/없는 이메일은 무시(미연결). ──
def _link_manager(profile, manager_email):
    if not manager_email:
        return
    mgr = User.objects.filter(email=manager_email).first()
    if mgr and mgr != profile.user:
        profile.manager = mgr
        profile.save(update_fields=['manager'])


logger = logging.getLogger(__name__)


# ── 이메일 발송 헬퍼 (로컬=콘솔, 운영=Resend SMTP) ────────────────
def _try_send(sender, user):
    """메일 발송 실패를 가입·요청 흐름과 격리 — 예외를 밖으로 던지지 않는다.

    2026-07-07 프로드 사고: Resend SMTP 실패가 가입 500으로 번짐(유저 생성 후
    발송 단계에서 폭발 → 재시도하면 '이미 가입된 이메일'로 막히는 최악 경로).
    발송 실패는 내용 없이 로깅만 하고 흐름은 계속한다(회복 경로 = 재발송 버튼).
    """
    try:
        sender(user)
        return True
    except Exception:
        logger.exception('메일 발송 실패 (도메인=%s)',
                         user.email.split('@')[-1] if user.email else '?')
        return False


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
    # 공개 엔드포인트 — 전역 TokenAuthentication 비활성화. (브라우저 localStorage 의
    # 헌/무효 토큰이 요청에 실려도 401 로 막히지 않도록. 로그인/가입은 토큰 무관.)
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_email'  # 임의 이메일 대량 가입·발송(스팸/비용/평판) 방어

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        sent = _try_send(_send_verify_email, user)
        msg = ('인증 이메일을 발송했습니다. 메일함을 확인해주세요.' if sent else
               '가입이 완료됐어요. 인증 메일이 곧 도착해요. 오지 않으면 로그인 화면의 '
               "'인증 메일 다시 받기'로 다시 받을 수 있어요.")
        return Response(
            {'message': msg, 'email': user.email, 'email_sent': sent},
            status=status.HTTP_201_CREATED)


class VerifyEmailView(APIView):
    authentication_classes = []
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
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_email'  # 인증메일 폭탄 방어

    def post(self, request):
        email = (request.data.get('email') or '').lower()
        user = User.objects.filter(email__iexact=email, is_active=False).first()
        if user:
            _try_send(_send_verify_email, user)  # 실패해도 200 유지(계정 존재 노출 방지)
        # 계정 존재 노출 방지 — 항상 200
        return Response({'message': '미인증 계정이면 인증 메일을 재발송했습니다.'})


class LoginView(APIView):
    authentication_classes = []   # 공개 로그인 — 헌 토큰 무시 (401 차단 버그 방지)
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


class GoogleLoginView(APIView):
    """구글 소셜 로그인(병행) — POST /api/v1/auth/google/ {id_token}.

    이메일/비밀번호 인증은 그대로 유지. 구글 검증 이메일 기준으로 기존 계정에 링크하거나
    신규 생성(is_active=True, 비번 미설정). 응답 계약은 LoginView와 동일.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        if not google_login_enabled():
            return Response({'code': 'NOT_FOUND'}, status=status.HTTP_404_NOT_FOUND)
        id_token_str = request.data.get('id_token')
        if not id_token_str:
            return Response({'code': 'ID_TOKEN_REQUIRED', 'detail': 'id_token이 필요합니다.'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            claims = verify_google_id_token(id_token_str)
        except GoogleTokenError:
            return Response({'code': 'GOOGLE_TOKEN_INVALID', 'detail': '구글 로그인에 실패했습니다.'},
                            status=status.HTTP_401_UNAUTHORIZED)

        email = claims['email'].lower()
        sub = claims['sub']

        # 1) sub로 이미 링크된 프로필이 있으면 그 사용자(정본).
        profile = Profile.objects.filter(google_sub=sub).select_related('user').first()
        if profile is not None:
            user = profile.user
        else:
            user = User.objects.filter(email__iexact=email).first()
            if user is not None:
                # 기존(이메일/비번) 계정에 링크 — 비번 무손상(병행).
                profile, _ = Profile.objects.get_or_create(user=user)
                if profile.google_sub and profile.google_sub != sub:
                    return Response({'code': 'GOOGLE_ALREADY_LINKED',
                                     'detail': '이미 다른 구글 계정에 연결된 이메일입니다.'},
                                    status=status.HTTP_409_CONFLICT)
                if not profile.google_sub:
                    profile.google_sub = sub
                    profile.save(update_fields=['google_sub'])
            else:
                # 신규 구글 사용자 — 구글이 이메일 검증했으므로 is_active=True, 비번 미설정.
                with transaction.atomic():
                    user = User.objects.create_user(email=email, is_active=True)
                    user.set_unusable_password()
                    user.save(update_fields=['password'])
                    profile = Profile.objects.create(
                        user=user, google_sub=sub,
                        name=(claims.get('given_name') or claims.get('name') or ''),
                        email_verified_at=timezone.now())
                create_reminder_rules_for_user(user)

        # 휴면 자동 복구(로그인 시에만).
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


def _gcal_redirect(result):
    base = (settings.FRONTEND_BASE_URL or '').rstrip('/')
    return HttpResponseRedirect(f'{base}/settings/account?gcal={result}')


class GoogleCalendarConnectView(APIView):
    """구글 캘린더 연동 시작 — GET /api/v1/auth/google/calendar/connect/ → {auth_url}."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not google_calendar_enabled():
            return Response({'code': 'CALENDAR_DISABLED', 'detail': '구글 캘린더 연동이 비활성화되어 있습니다.'},
                            status=status.HTTP_403_FORBIDDEN)
        from .google_calendar import build_auth_url
        return Response({'auth_url': build_auth_url(request.user.pk)})


class GoogleCalendarCallbackView(APIView):
    """구글 OAuth 콜백(브라우저 리다이렉트) — 신원은 서명 state로만. AllowAny."""
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        if not google_calendar_enabled():
            return Response({'code': 'NOT_FOUND'}, status=status.HTTP_404_NOT_FOUND)
        from .google_calendar import exchange_code, read_calendar_state
        if request.query_params.get('error'):
            return _gcal_redirect('denied')
        code = request.query_params.get('code')
        state = request.query_params.get('state') or ''
        try:
            user_pk = read_calendar_state(state)
        except (signing.BadSignature, signing.SignatureExpired):
            return _gcal_redirect('error')
        if not code:
            return _gcal_redirect('error')
        user = User.objects.filter(pk=user_pk).first()
        if user is None:
            return _gcal_redirect('error')
        try:
            refresh_token = exchange_code(code)
            if not refresh_token:
                return _gcal_redirect('error')
            profile, _ = Profile.objects.get_or_create(user=user)
            profile.google_calendar_refresh_token = refresh_token
            profile.google_calendar_connected_at = timezone.now()
            profile.save(update_fields=['google_calendar_refresh_token', 'google_calendar_connected_at'])
        except Exception:
            return _gcal_redirect('error')
        return _gcal_redirect('connected')


class GoogleCalendarDisconnectView(APIView):
    """구글 캘린더 연동 해제 — POST /api/v1/auth/google/calendar/disconnect/."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from .google_calendar import revoke_refresh_token
        profile, _ = Profile.objects.get_or_create(user=request.user)
        revoke_refresh_token(profile.google_calendar_refresh_token)
        profile.google_calendar_refresh_token = None
        profile.google_calendar_connected_at = None
        profile.save(update_fields=['google_calendar_refresh_token', 'google_calendar_connected_at'])
        return Response({'disconnected': True})


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        return Response({'message': '로그아웃되었습니다.'})


class PasswordResetView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_email'  # 비번재설정 메일 폭탄 방어

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = User.objects.filter(email__iexact=serializer.validated_data['email']).first()
        if user:
            _try_send(_send_reset_email, user)  # 실패해도 200 유지(계정 존재 노출 방지)
        return Response({'message': '가입된 이메일이면 재설정 링크를 보냈습니다.'})


class PasswordResetConfirmView(APIView):
    authentication_classes = []
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
        return Response(ProfileSerializer(profile, context={'request': request}).data)

    def patch(self, request):
        # request.data 는 JSON·멀티파트(프로필 사진 업로드) 모두 DRF 기본 파서가 처리.
        profile, _ = Profile.objects.get_or_create(user=request.user)
        serializer = ProfileSerializer(profile, data=request.data, partial=True,
                                       context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        # 지점장 연결(이메일→User). 본인 지정 금지. 없는 이메일은 조용히 무시(미연결).
        _link_manager(profile, request.data.get('manager_email'))
        return Response(ProfileSerializer(profile, context={'request': request}).data)


class WithdrawView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if user.has_usable_password():
            # 이메일/비번 가입자 — 비밀번호 확인
            if not user.check_password(request.data.get('password', '')):
                return Response({'code': 'INVALID_PASSWORD', 'detail': '비밀번호 확인이 필요합니다.'},
                                status=status.HTTP_400_BAD_REQUEST)
        else:
            # 구글 전용 가입자(비번 없음) — 가입 이메일 입력으로 본인 확인(개인정보 삭제권 보장)
            confirm = (request.data.get('confirm') or '').strip().lower()
            if confirm != user.email.lower():
                return Response({'code': 'CONFIRM_REQUIRED',
                                 'detail': '확인을 위해 가입 이메일을 정확히 입력해 주세요.'},
                                status=status.HTTP_400_BAD_REQUEST)
        # 즉시 삭제 (CASCADE로 Profile·고객 데이터 연쇄 삭제). 유예기간 soft-delete은 openGap.
        user.delete()
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
        if data.get('affiliation_type'):
            profile.affiliation_type = data['affiliation_type']
        if 'career_years' in data:
            profile.career_years = data['career_years']
        profile.license_self_declared = data.get('license_self_declared', profile.license_self_declared)
        profile.onboarding_completed_at = timezone.now()
        profile.save()
        _link_manager(profile, data.get('manager_email'))
        return Response(ProfileSerializer(profile).data)
