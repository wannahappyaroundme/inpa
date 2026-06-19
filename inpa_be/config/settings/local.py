"""로컬 개발 설정 — SQLite, DEBUG, 콘솔 이메일."""
from .base import *  # noqa: F401,F403

DEBUG = True
ALLOWED_HOSTS = ['*']

# DATABASES는 base의 SQLite 기본값을 그대로 사용.
