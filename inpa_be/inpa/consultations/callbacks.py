import uuid
from urllib.parse import urljoin

from django.conf import settings
from django.core import signing
from django.core.exceptions import ImproperlyConfigured


CALLBACK_SALT = 'consultation-clova-callback'


def make_clova_callback_url(run):
    base_url = settings.BACKEND_BASE_URL.rstrip('/') + '/'
    if not base_url.startswith('https://'):
        raise ImproperlyConfigured('BACKEND_BASE_URL must use https')
    token = signing.dumps(
        {
            'run_id': str(run.id),
            'attempt_uuid': str(run.attempt_uuid),
        },
        salt=CALLBACK_SALT,
        compress=True,
    )
    return urljoin(
        base_url,
        f'api/v1/consultations/clova-callback/{token}/',
    )


def read_clova_callback_token(token):
    payload = signing.loads(
        token,
        salt=CALLBACK_SALT,
        max_age=settings.CONSULTATION_CALLBACK_TTL_SECONDS,
    )
    if not isinstance(payload, dict):
        raise signing.BadSignature('INVALID_CALLBACK_PAYLOAD')
    try:
        run_id = uuid.UUID(str(payload['run_id']))
        attempt_uuid = uuid.UUID(str(payload['attempt_uuid']))
    except (KeyError, TypeError, ValueError) as exc:
        raise signing.BadSignature('INVALID_CALLBACK_PAYLOAD') from exc
    return run_id, attempt_uuid
