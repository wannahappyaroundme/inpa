from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from inpa.accounts.models import Profile, User

from .prepare_insurance_load_fixture import (
    OWNER_COUNT,
    SAFE_REF,
    fixture_emails,
    fixture_run_marker,
    validate_fixture_subset,
    validate_private_root,
    validate_staging_resources,
)


class Command(BaseCommand):
    help = 'Delete only the explicitly marked synthetic insurance load fixture.'

    def add_arguments(self, parser):
        parser.add_argument('--private-root', required=True)
        parser.add_argument('--run-id', required=True)
        parser.add_argument('--expected-host', required=True)

    def handle(self, *args, **options):
        if not settings.INSURANCE_LOAD_TEST_ENABLED:
            raise CommandError('합성 부하 실행 스위치를 먼저 열어 주세요.')
        run_id = options['run_id']
        if not SAFE_REF.fullmatch(run_id):
            raise CommandError('안전한 실행 이름을 입력해 주세요.')
        validate_staging_resources(options['expected_host'])
        users = list(User.objects.filter(email__in=fixture_emails()))
        root = validate_private_root(
            options['private_root'], missing_ok=True)
        if not root.exists():
            if users:
                raise CommandError('합성 계정과 비공개 폴더의 실행이 다릅니다.')
            self.stdout.write('LOAD FIXTURE CLEANED owners=0')
            return
        actual_files = validate_fixture_subset(root, run_id)
        documents_dir = root / 'documents'
        if len(users) not in {0, OWNER_COUNT}:
            raise CommandError('합성 계정 수를 확인해 주세요.')
        for user in users:
            try:
                profile = user.profile
            except Profile.DoesNotExist:
                raise CommandError('합성 계정 표식을 확인해 주세요.') from None
            if (profile.affiliation != fixture_run_marker(run_id)
                    or user.has_usable_password()
                    or user.is_staff or user.is_superuser):
                raise CommandError('합성 계정 표식을 확인해 주세요.')
        with transaction.atomic():
            User.objects.filter(pk__in=[user.pk for user in users]).delete()

        for path in sorted(actual_files, key=lambda item: len(item.parts), reverse=True):
            path.unlink()
        if documents_dir.exists():
            documents_dir.rmdir()
        root.rmdir()
        self.stdout.write(f'LOAD FIXTURE CLEANED owners={len(users)}')
