"""운영 백오피스 관리자 계정 생성/갱신 (멱등).

사용:
  python manage.py create_admin --email inpa --password '비밀번호'
  또는 환경변수: ADMIN_EMAIL / ADMIN_PASSWORD (인자 미지정 시 fallback)

인자·환경변수 둘 다 없으면 아무 것도 하지 않고 정상 종료 → Render startCommand 에
안전하게 포함 가능(env 미설정 배포에서 무해). 이미 있으면 비밀번호·플래그만 갱신(멱등).

부여 권한:
  - Profile.is_admin=True  → 운영 백오피스(/admin-login → /admin) 접근.
  - is_staff/is_superuser=True → Django 관리(/admin/) 접근.
  - email_verified_at 채움 → 이메일 인증 게이트 통과.

★ AdminLoginView 는 이메일 형식을 검증하지 않으므로 'inpa' 같은 비이메일 ID 도 허용.
"""
import os

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from inpa.accounts.models import Profile, User


class Command(BaseCommand):
    help = ('운영 백오피스 관리자 계정 생성/갱신 (멱등). '
            '--email/--password 또는 ADMIN_EMAIL/ADMIN_PASSWORD env.')

    def add_arguments(self, parser):
        parser.add_argument('--email', default=None, help='관리자 로그인 ID (미지정 시 ADMIN_EMAIL env)')
        parser.add_argument('--password', default=None, help='비밀번호 (미지정 시 ADMIN_PASSWORD env)')

    @transaction.atomic
    def handle(self, *args, **opts):
        email = (opts.get('email') or os.environ.get('ADMIN_EMAIL') or '').strip().lower()
        password = opts.get('password') or os.environ.get('ADMIN_PASSWORD') or ''

        if not email or not password:
            self.stdout.write(
                'ADMIN_EMAIL/ADMIN_PASSWORD(또는 --email/--password) 미지정 — 건너뜀.')
            return

        try:
            user = User.objects.get(email=email)
            created = False
        except User.DoesNotExist:
            user = User.objects.create_user(email=email, password=password)
            created = True

        user.set_password(password)
        user.is_active = True
        user.is_staff = True
        user.is_superuser = True
        user.save()

        profile, _ = Profile.objects.get_or_create(user=user)
        profile.is_admin = True
        if not profile.email_verified_at:
            profile.email_verified_at = timezone.now()
        profile.save()

        verb = '생성' if created else '갱신'
        self.stdout.write(self.style.SUCCESS(
            f'관리자 {verb}: {email} (is_admin=True, superuser=True) — /admin-login 로 접속.'))
