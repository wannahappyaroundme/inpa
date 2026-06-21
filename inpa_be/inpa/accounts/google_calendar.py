"""구글 캘린더 — OAuth 코드 플로우 + 이벤트 생성. google libs는 함수 내부 lazy import.

state는 django signing(서명·짧은 TTL)으로 CSRF 방어. callback은 state로만 신원 식별.
이벤트엔 병력·보험·분석 정보를 절대 넣지 않는다(국외이전 최소화).
"""
from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.utils import timezone

_SCOPES = ['https://www.googleapis.com/auth/calendar.events']
_STATE_SALT = 'inpa-gcal-oauth-state'
_TOKEN_URI = 'https://oauth2.googleapis.com/token'


def make_calendar_state(user_pk):
    return signing.dumps(user_pk, salt=_STATE_SALT)


def read_calendar_state(state):
    """유효하면 user pk, 만료/위조면 signing 예외(SignatureExpired/BadSignature)."""
    return signing.loads(state, salt=_STATE_SALT, max_age=settings.GOOGLE_OAUTH_STATE_TTL_SECONDS)


def _client_config():
    return {
        'web': {
            'client_id': settings.GOOGLE_OAUTH_CLIENT_ID,
            'client_secret': settings.GOOGLE_OAUTH_CLIENT_SECRET,
            'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
            'token_uri': _TOKEN_URI,
            'redirect_uris': [settings.GOOGLE_OAUTH_REDIRECT_URI],
        }
    }


def build_flow():
    from google_auth_oauthlib.flow import Flow
    return Flow.from_client_config(
        _client_config(), scopes=_SCOPES, redirect_uri=settings.GOOGLE_OAUTH_REDIRECT_URI)


def build_auth_url(user_pk):
    """연동 동의 URL(offline+consent로 refresh_token 보장) + 서명 state."""
    flow = build_flow()
    auth_url, _ = flow.authorization_url(
        access_type='offline', prompt='consent', include_granted_scopes='false',
        state=make_calendar_state(user_pk))
    return auth_url


def exchange_code(code):
    """code → refresh_token(없으면 None)."""
    flow = build_flow()
    flow.fetch_token(code=code)
    return getattr(flow.credentials, 'refresh_token', None)


def _mask_name(name):
    if not name:
        return '고객'
    if len(name) == 1:
        return name
    return name[0] + '○' * (len(name) - 1)


def insert_meeting_event(profile, meeting, customer_name):
    """미팅을 설계사 구글 캘린더(primary)에 등록 → event id. 병력·보험 정보 미포함."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials(
        None, refresh_token=profile.google_calendar_refresh_token,
        token_uri=_TOKEN_URI,
        client_id=settings.GOOGLE_OAUTH_CLIENT_ID,
        client_secret=settings.GOOGLE_OAUTH_CLIENT_SECRET,
        scopes=_SCOPES)
    service = build('calendar', 'v3', credentials=creds, cache_discovery=False)

    name = _mask_name(customer_name) if profile.google_calendar_mask_name else (customer_name or '고객')
    start = timezone.localtime(meeting.start_at)
    end = start + timedelta(minutes=meeting.duration_min or 30)
    method_label = dict(meeting.METHOD_CHOICES).get(meeting.method, meeting.method)
    body = {
        'summary': f'[인파 상담] {name}님 ({method_label})',
        'description': '인파 미팅 예약입니다. (보험 분석·병력 정보는 포함되지 않습니다.)',
        'start': {'dateTime': start.isoformat(), 'timeZone': settings.TIME_ZONE},
        'end': {'dateTime': end.isoformat(), 'timeZone': settings.TIME_ZONE},
    }
    if meeting.method == meeting.METHOD_IN_PERSON and meeting.location_detail:
        body['location'] = meeting.location_detail
    event = service.events().insert(calendarId='primary', body=body).execute()
    return event.get('id')


def revoke_refresh_token(refresh_token):
    """best-effort 토큰 폐기. 실패 무시."""
    if not refresh_token:
        return
    try:
        import urllib.parse
        import urllib.request
        data = urllib.parse.urlencode({'token': refresh_token}).encode()
        req = urllib.request.Request('https://oauth2.googleapis.com/revoke', data=data)
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass
