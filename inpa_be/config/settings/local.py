"""로컬 개발 설정 — SQLite, DEBUG, 콘솔 이메일."""
from .base import *  # noqa: F401,F403

DEBUG = True
ALLOWED_HOSTS = ['*']

# DATABASES는 base의 SQLite 기본값을 그대로 사용.

# 로컬은 Redis 없이 작업 함수를 검증한다. API의 202 응답 계약은 enqueue mock으로 별도 검증한다.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
