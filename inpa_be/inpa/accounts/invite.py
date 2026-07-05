"""팀 초대 링크 (#24) — 동의 침해 없는 팀 연결.

흐름: 관리자(인증 설계사 누구나)가 초대 링크 발급 → 신입이 /register?invite=<token>
으로 가입 → 생성되는 Profile 에 manager FK(+ 비어 있으면 affiliation)만 프리셋.

★ PIPA-clean 합의(레드라인): 초대 토큰은 manager_share_level 을 절대 건드리지 않는다
  (기본 none 유지 — 성과 공유 여부는 신입 본인이 설정에서 직접 선택).
★ 무효/만료 토큰이 가입을 막지 않는다 — RegisterSerializer 가 토큰만 무시(+로그).

토큰: signing.dumps(manager pk) — accounts/tokens.py·booking/tokens.py 와 동일한
stateless TimestampSigner 패턴. TTL = settings.TEAM_INVITE_TTL_DAYS (기본 7일).
"""
from django.conf import settings
from django.core import signing
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from inpa.core.permissions import IsEmailVerified

from .models import User

TEAM_INVITE_SALT = 'inpa-team-invite'


def make_invite_token(user):
    return signing.dumps(user.pk, salt=TEAM_INVITE_SALT)


def read_invite_token(token):
    """유효하면 manager user pk 반환, 만료/위조면 signing 예외(SignatureExpired/BadSignature)."""
    max_age = settings.TEAM_INVITE_TTL_DAYS * 86400
    return signing.loads(token, salt=TEAM_INVITE_SALT, max_age=max_age)


def resolve_invite_manager(token):
    """토큰 → 활성 manager User 또는 None (예외를 삼킨다 — 가입 흐름에서 안전하게 재사용)."""
    try:
        pk = read_invite_token(token)
    except signing.BadSignature:  # SignatureExpired 포함(서브클래스)
        return None
    return User.objects.filter(pk=pk, is_active=True).select_related('profile').first()


class TeamInviteLinkView(APIView):
    """POST /api/v1/manager/invite-link/ — 인증 설계사 누구나(자기 팀을 만들 관리자)."""
    permission_classes = [IsAuthenticated, IsEmailVerified]

    def post(self, request):
        token = make_invite_token(request.user)
        base = (getattr(settings, 'FRONTEND_BASE_URL', '') or '').rstrip('/')
        # ttl_days 동봉 — FE 카드 문구가 env(TEAM_INVITE_TTL_DAYS) 변경을 자동 추종
        return Response({'url': f'{base}/register?invite={token}',
                         'ttl_days': settings.TEAM_INVITE_TTL_DAYS})


class TeamInviteInfoView(APIView):
    """GET /api/v1/manager/invite-info/?token= — AllowAny(가입 화면 칩용), throttled.

    유효하면 {manager_name, affiliation}, 무효/만료면 404 — FE 는 칩 없이 일반 가입 진행.
    """
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'invite_info'

    def get(self, request):
        token = (request.query_params.get('token') or '').strip()
        manager = resolve_invite_manager(token) if token else None
        if manager is None:
            return Response({'code': 'INVITE_INVALID', 'detail': '유효하지 않은 초대 링크입니다.'},
                            status=404)
        profile = getattr(manager, 'profile', None)
        name = (profile.name if profile and profile.name else manager.email.split('@')[0])
        return Response({
            'manager_name': name,
            'affiliation': (profile.affiliation if profile else None) or None,
        })
